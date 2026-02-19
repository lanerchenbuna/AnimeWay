import re
import json
from typing import List, Dict

class HybridRetriever:
    def __init__(self, knowledge_base: List[Dict]):
        self.knowledge_base = knowledge_base

    def retrieve_keyword(self, query: str, k: int = 10) -> List[Dict]:
        """
        Standard BM25-like Keyword Match against Anime Items.
        """
        query_terms = set(re.findall(r'\w+', query.lower()))
        scores = []
        
        for item in self.knowledge_base:
            score = 0
            meta = item.get('meta', {})
            titles = meta.get('titles', {})
            rag_text = item.get('rag_content', '').lower()
            
            # 1. Title Match (High Priority)
            # Use robust normalization to handle special chars like ☆
            def normalize(s):
                return re.sub(r'[^\w\u4e00-\u9fa5]', '', str(s).lower())

            cn_title = normalize(titles.get('cn', ''))
            jp_title = normalize(titles.get('jp', ''))
            
            # Normalize query terms too? 
            # Actually, query_terms are already re.findall(r'\w+').
            # But "少女歌剧" -> \w+ is ok.
            # "少女☆歌剧" -> "少女", "歌剧".
            # If query is "少女歌剧", terms=["少女歌剧"]. 
            # cn_title (normalized) = "少女歌剧". MATCH!
            
            if any(t in cn_title for t in query_terms): score += 5
            if any(t in jp_title for t in query_terms): score += 4
            
            # 2. Content Match (Medium)
            # rag_content includes tags, synopsis, and spot names
            for term in query_terms:
                if term in rag_text:
                    score += 1
            
            if score > 0:
                scores.append((score, item))
        
        scores.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scores[:k]]

    def retrieve_vector_simulated(self, query: str, k: int = 10) -> List[Dict]:
        """
        Simulated Vector Search (Semantic Search).
        Soft matches on tags/synonyms against the aggregated 'rag_content'.
        """
        synonyms = {
            "pray": ["shrine", "temple", "神家", "寺"],
            "eat": ["cafe", "restaurant", "food", "料理", "餐厅"],
            "school": ["highschool", "classroom", "学校", "高校"],
            "music": ["guitar", "band", "轻音", "吉他"],
            "time": ["travel", "future", "past", "时间"],
        }
        
        query_lower = query.lower()
        expanded_keywords = []
        for key, vals in synonyms.items():
             # Two-way match: if query has key, or query has val
            if key in query_lower:
                expanded_keywords.extend(vals)
            for val in vals:
                if val in query_lower:
                    expanded_keywords.append(key)
        
        expanded_keywords.extend(re.findall(r'\w+', query_lower))

        scores = []
        for item in self.knowledge_base:
            score = 0
            rag_text = item.get('rag_content', '').lower()
            
            for kw in expanded_keywords:
                if kw in rag_text:
                    score += 0.5 
            
            if score > 0:
                scores.append((score + 0.1, item))
        
        scores.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scores[:k]]

    def rank_fusion(self, list_a: List[Dict], list_b: List[Dict], k: int = 60) -> List[Dict]:
        """
        Reciprocal Rank Fusion (RRF).
        """
        rrf_map = {}
        
        def process_list(lst):
            for rank, item in enumerate(lst):
                # Use anime_id as unique key
                key = item.get('anime_id')
                if not key: continue
                
                if key not in rrf_map:
                    rrf_map[key] = {"item": item, "score": 0}
                
                rrf_map[key]["score"] += 1 / (k + rank + 1)

        process_list(list_a)
        process_list(list_b)
        
        sorted_items = sorted(rrf_map.values(), key=lambda x: x['score'], reverse=True)
        return [x['item'] for x in sorted_items]

    def retrieve_knowledge(self, query: str, k: int = 5) -> List[Dict]:
        """
        Main Retrieval Entrypoint.
        Returns relevant `AnimeItem` objects.
        """
        kw_results = self.retrieve_keyword(query, k=k*2)
        vec_results = self.retrieve_vector_simulated(query, k=k*2)
        final_results = self.rank_fusion(kw_results, vec_results)
        return final_results[:k]

    def get_anime_candidates(self, query: str) -> List[Dict]:
        """
        For UI Auto-complete / Search.
        Returns simplified anime dicts.
        """
        query_lower = query.lower()
        candidates = []
        
        for item in self.knowledge_base:
            meta = item.get('meta', {})
            titles = meta.get('titles', {})
            cn = titles.get('cn', '')
            jp = titles.get('jp', '')
            
        # Normalize Query
        def normalize(s):
            return re.sub(r'[^\w\u4e00-\u9fa5]', '', str(s).lower())
            
        q_norm = normalize(query)
        
        # Generic Suffix Stripping for ALL search queries
        # This handles cases like "Looking for [Anime]'s holy land"
        common_suffixes = ['的圣地', '圣地', '巡礼', '取景地', '在哪里', '在哪', '原型', '位置']
        q_clean = q_norm
        for suffix in common_suffixes:
            q_clean = q_clean.replace(suffix, '')
        q_clean = q_clean.strip()
        
        candidates = []
        
        for item in self.knowledge_base:
            match = False
            meta = item.get('meta', {})
            titles = meta.get('titles', {})
            cn = titles.get('cn', '')
            jp = titles.get('jp', '')
            
            cn_norm = normalize(cn)
            jp_norm = normalize(jp)
            
            # Check Title (Exact or Fuzzy Substring)
            # 1. Query in Title (Standard)
            # 2. Cleaned Query in Title (Handling suffixes)
            if (q_norm in cn_norm) or (q_norm in jp_norm):
                match = True
            elif q_clean and len(q_clean) > 1 and ((q_clean in cn_norm) or (q_clean in jp_norm)):
                # Ensure cleaned query isn't empty or too short (avoid matching "的")
                match = True
                                    
            # Check Tags (if title match failed)
            if not match:
                for tag in meta.get('tags', []):
                    # Check both raw and clean against tag
                    tag_norm = normalize(tag)
                    if (q_norm in tag_norm) or (q_clean and len(q_clean) > 1 and q_clean in tag_norm):
                        match = True
                        break
            
            if match:
                candidates.append({
                    'id': item['anime_id'],
                    'cn': cn,
                    'jp': jp,
                    'image': meta.get('cover'),
                    'summary': f"{len(item.get('spots', []))} 圣地 | {meta.get('score', 'N/A')} 分"
                })
                
        return candidates[:20] # Limit results
    
    # Backward compatibility helper if needed, but better to update caller
    def retrieve_spots(self, query: str, k: int=5):
        return self.retrieve_knowledge(query, k)

    def get_spots_by_anime_id(self, anime_id: int) -> List[Dict]:
        """
        Retrieve all spots for a specific anime ID.
        Locates the AnimeItem and returns its text-based spots list
        (converting Spot Pydantic models to dicts if needed, though they are dicts in JSON).
        """
        for item in self.knowledge_base:
            if int(item.get('anime_id')) == int(anime_id):
                return item.get('spots', [])
        return []
