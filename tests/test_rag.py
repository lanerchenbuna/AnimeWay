import sys
import os
import json
# Add project root to path
sys.path.append(os.getcwd())

from core.agent import AnimeRagAgent

def test_retrieval():
    print("🤖 Initializing Agent...")
    try:
        agent = AnimeRagAgent()
    except Exception as e:
        print(f"❌ Failed to init agent: {e}")
        return

    query = "轻音少女"
    print(f"\n🔍 Testing Search: '{query}'")
    
    # 1. Test Retrieval Direct
    results = agent.retriever.retrieve_knowledge(query)
    if results:
        print(f"✅ Retrieved {len(results)} items.")
        top = results[0]
        print(f"   Name: {top['meta']['titles']['cn']}")
        print(f"   Spots: {len(top['spots'])}")
        print(f"   Rag Content Preview: {top['rag_content'][:100]}...")
    else:
        print("❌ Retrieval returned empty.")

    # 2. Test Candidates (for UI)
    print(f"\nmagnifying glass Testing UI Candidates: '{query}'")
    candidates = agent.retriever.get_anime_candidates(query)
    if candidates:
        print(f"✅ Found {len(candidates)} candidates.")
        print(f"   Top: {candidates[0]}")
    else:
        print("❌ No candidates found.")

if __name__ == "__main__":
    test_retrieval()
