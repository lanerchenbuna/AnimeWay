import json
import traceback
from typing import List, Dict, Any
import dashscope
from dashscope import Generation
from core.retrieval import HybridRetriever
from core.prompts import (
    SYSTEM_PERSONA, 
    INTENT_PROMPT_TEMPLATE, 
    RAG_RESPONSE_TEMPLATE
)

class AnimeRagAgent:
    def __init__(self, kb_data: List[Dict] = None, retriever: HybridRetriever = None):
        if kb_data:
             self.knowledge_base = kb_data
        else:
             self.knowledge_base = self._load_kb()
             
        if retriever:
            self.retriever = retriever
        else:
            self.retriever = HybridRetriever(self.knowledge_base)
        
    def _load_kb(self) -> List[Dict]:
        """
        Loads Raw Data and performs In-Memory ETL.
        Decouples Runtime from the offline ETL pipeline.
        """
        import os
        
        # Paths
        bangumi_path = "knowledge_base/raw/bangumi_knowledge.json"
        manual_path = "knowledge_base/raw/manual_seeds.json"
        anitabi_path = "knowledge_base/raw/anitabi_crawl.json"
        
        kb_list = []
        
        # 1. Load Metadata (Bangumi + Manual)
        raw_meta = []
        if os.path.exists(manual_path):
            with open(manual_path, 'r', encoding='utf-8') as f:
                raw_meta.extend(json.load(f))
        if os.path.exists(bangumi_path):
            with open(bangumi_path, 'r', encoding='utf-8') as f:
                raw_meta.extend(json.load(f))
                
        # 2. Load Spots
        spots_map = {}
        if os.path.exists(anitabi_path):
            with open(anitabi_path, 'r', encoding='utf-8') as f:
                raw_spots = json.load(f)
                # Group by anime_id
                for s in raw_spots:
                    aid = s.get('anime_id')
                    if aid:
                         # 🛠️ Fix: Inject Synthetic ID if missing (Critical for UI)
                         if 'id' not in s:
                             # Simple hash from name + geo to ensure stability
                             unique_str = f"{s.get('name')}_{s.get('geo')}"
                             s['id'] = str(hash(unique_str)) 
                         
                         # 🛠️ Fix: Flatten 'geo' list to 'lat', 'lon' for UI and Map
                         if 'geo' in s and isinstance(s['geo'], list) and len(s['geo']) == 2:
                             s['lat'] = float(s['geo'][0])
                             s['lon'] = float(s['geo'][1])
                         
                         if aid not in spots_map: spots_map[aid] = []
                         spots_map[aid].append(s)
        
        # 3. Join & Transform
        print(f"⚡ [Runtime] Indexing {len(raw_meta)} anime items...")
        for item in raw_meta:
            try:
                # Normalize ID
                aid = item.get('subject') or item.get('id')
                if not aid: continue
                aid = int(aid)
                
                # Fetch Spots
                spots = spots_map.get(aid, [])
                
                # Build Meta Dict (Schema compliant with HybridRetriever)
                titles = {
                    'cn': item.get('中文名') or item.get('name_cn') or "",
                    'jp': item.get('原名') or item.get('name_jp') or "",
                }
                if not titles['cn'] and titles['jp']: titles['cn'] = titles['jp']
                
                # Build RAG Content (Mocking ETL logic)
                # We need a simple string for keyword search
                tags = item.get('tags', [])
                if isinstance(tags, str): tags = [tags]
                
                rag_content = f"{titles['cn']} {titles['jp']} {' '.join(tags)}".lower()
                
                kb_item = {
                    "anime_id": aid,
                    "meta": {
                        "titles": titles,
                        "score": item.get('score') or item.get('rating'),
                        "tags": tags,
                        "description": item.get('description') or item.get('简介') or "",
                        "cover": item.get('cover') or item.get('image') or item.get('封面')
                    },
                    "spots": spots,
                    "rag_content": rag_content
                }
                kb_list.append(kb_item)
            except Exception:
                continue
                
        print(f"✅ [Runtime] Loaded {len(kb_list)} items with {len(spots_map)} spot groups.")
        # Debug: Check Steins;Gate count
        sg_spots = spots_map.get(10380, [])
        print(f"🔎 [Debug] ID 10380 (Steins;Gate) has {len(sg_spots)} spots.")
        return kb_list

    def _call_llm(self, prompt: str, history: List = None) -> str:
        """Helper to call DashScope safely"""
        try:
            messages = [{'role': 'user', 'content': prompt}]
            if history:
                messages = history + messages
            
            resp = Generation.call(model="qwen-turbo", messages=messages)
            if resp.status_code == 200:
                return resp.output.text
            else:
                return f"⚠️ API Error: {resp.code} - {resp.message}"
        except Exception as e:
            return f"⚠️ Network Error: {e}"

    def analyze_intent(self, query: str, history: List[Dict] = None) -> Dict[str, Any]:
        """
        Step 1: Understand what the user wants.
        """
        # Format history for prompt context
        history_context = ""
        if history:
            history_context = "\nConversation History:\n"
            for msg in history[-3:]: # context window of last 3 turns
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                history_context += f"{role}: {content}\n"
        
        prompt = INTENT_PROMPT_TEMPLATE.replace("{user_query}", f"{history_context}\nCurrent Query: {query}")
        resp = self._call_llm(prompt)
        
        # Parse JSON
        try:
            # Clean potential markdown wrapping
            if "```" in resp: 
                resp = resp.split("```")[1].replace("json", "").strip()
            
            intent_data = json.loads(resp)
            return intent_data
        except:
            # Fallback
            return {"intent": "CHAT", "keywords": query, "reasoning": "Failed to parse intent"}

    def generate_response(self, user_query: str, api_key: str, history: List[Dict] = None) -> Dict[str, Any]:
        """
        Main Agent Entrypoint.
        """
        # Sanitize API Key (Remove non-ascii and whitespace)
        if api_key:
            api_key = api_key.strip()
            # Remove potential Chinese characters or invisible spaces often pasted by accident
            try:
                api_key.encode('ascii')
            except UnicodeEncodeError:
                # Naive cleaning: keep only alphanumeric and standard punctuation
                import re
                api_key = re.sub(r'[^\x00-\x7F]+', '', api_key)
        
        dashscope.api_key = api_key
        
        # 1. Intent Analysis with History
        intent_data = self.analyze_intent(user_query, history)
        intent_type = intent_data.get("intent", "CHAT")
        keywords = intent_data.get("keywords", user_query)
        anime_target = intent_data.get("anime_name")
        thought = f"Detected Intent: {intent_type} | Focus: {keywords}"
        
        context_results = []
        
        # 2. Tool Execution / Retrieval
        if intent_type == "SEARCH":
            # Search for Anime Context (which contains spots)
            # Prioritize extracted anime name if available (cleaner), otherwise use keywords
            search_term = anime_target if anime_target else keywords
            
            # Step 1: Specific Anime Candidates Check
            # (Matches user logic: First find anime, then get its context)
            candidates = self.retriever.get_anime_candidates(search_term)
            if candidates:
                 # Found specific anime match (e.g. "少女歌剧" -> "剧场版 少女☆歌剧...")
                 best_id = candidates[0]['id']
                 # Retrieve knowledge by ID
                 context_results = [item for item in self.knowledge_base if item['anime_id'] == best_id]
                 thought += f" -> Identified Anime: '{candidates[0]['cn']}' (ID: {best_id})."
            else:
                 # Standard content retrieval
                 context_results = self.retriever.retrieve_knowledge(search_term)
                 thought += f" -> Search Term: '{search_term}' -> Found {len(context_results)} relevant anime contexts."
            
        elif intent_type == "GUIDE":
            # Search for an anime first
            search_term = anime_target if anime_target else keywords
            candidates = self.retriever.get_anime_candidates(search_term)
            
            if candidates:
                best_match_id = candidates[0]['id']
                # Retrieve the full AnimeItem from KB
                context_results = [item for item in self.knowledge_base if item['anime_id'] == best_match_id]
                thought += f" -> Identified '{candidates[0]['cn']}' (ID: {best_match_id})."
            else:
                context_results = self.retriever.retrieve_knowledge(keywords)
                thought += " -> Anime not found, performing broad search."
        
        # 3. Response Generation
        # Prepare context string
        if context_results:
            # Format AnimeItem specifically for RAG to save tokens
            simplified_ctx = []
            for item in context_results[:3]: # Limit to top 3 matching animes
                meta = item.get('meta', {})
                spots = item.get('spots', [])
                
                # Create a concise summary
                s_ctx = {
                    "anime": meta.get('titles', {}).get('cn'),
                    "intro": (meta.get('description', '') or "")[:200], # Trucate intro
                    "score": float(meta.get('score', 0) or 0), # Ensure float
                    "key_spots": [str(s.get('name')) for s in spots[:10]], # Ensure strings
                    "total_spots": len(spots)
                }
                simplified_ctx.append(s_ctx)
                
            try:
                ctx_str = json.dumps(simplified_ctx, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"JSON Dump Error: {e}")
                ctx_str = "Context Serialization Error"
        else:
            ctx_str = "No specific data found in Knowledge Base."

        final_prompt = RAG_RESPONSE_TEMPLATE.format(
            system_persona=SYSTEM_PERSONA,
            context_str=ctx_str,
            user_query=user_query
        )
        
        final_answer = self._call_llm(final_prompt)
        
        return {
            "response": final_answer,
            "thought": thought,
            "context": context_results,
            "meta": intent_data
        }

if __name__ == "__main__":
    # Test
    agent = AnimeRagAgent()
    # You would need to set env var for API key to run this test
    print("Agent Initialized.")
