import sys
import os
sys.path.append(os.getcwd())

from core.agent import AnimeRagAgent
import os

def test_chat():
    print("🤖 Init Agent...")
    try:
        agent = AnimeRagAgent()
    except Exception as e:
        print(f"❌ Init failed: {e}")
        return

    # Use env var or placeholder. The user issue might be related to the key passed from UI.
    # We will try with a dummy key if not in env, to see if it crashes before API call
    query = "少女歌剧"
    print(f"🗣️ Query: {query}")
    
    # 1. Test Retrieval Speed/Crash
    print("... Testing Retrieval Logic (GUIDE Intent Path) ...")
    import time
    start = time.time()
    candidates = agent.retriever.get_anime_candidates(query)
    end = time.time()
    
    print(f"✅ Retrieval finished in {end - start:.4f}s")
    print(f"Found {len(candidates)} candidates.")
    if candidates:
        print(f"Top match: {candidates[0]['cn']}")
    
    # 2. Test Context Formatting
    if candidates:
        # Simulate what agent does
        best_match_id = candidates[0]['id']
        context_results = [item for item in agent.knowledge_base if item['anime_id'] == best_match_id]
        
        # Format
        simplified_ctx = []
        for item in context_results[:3]:
            meta = item.get('meta', {})
            spots = item.get('spots', [])
            s_ctx = {
                "anime": meta.get('titles', {}).get('cn'),
                "intro": (meta.get('description', '') or "")[:200],
                "score": float(meta.get('score', 0) or 0),
                "key_spots": [str(s.get('name')) for s in spots[:10]],
                "total_spots": len(spots)
            }
            simplified_ctx.append(s_ctx)
        
        import json
        dumped = json.dumps(simplified_ctx, ensure_ascii=False)
        print("✅ Context formatting successful.")
        print(f"Context dump length: {len(dumped)}")

if __name__ == "__main__":
    test_chat()
