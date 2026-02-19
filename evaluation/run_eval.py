import json
import os
import time
import pandas as pd
from core.agent import AnimeRagAgent

# Configuration
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 

def load_data(filepath):
    if not os.path.exists(filepath):
        # Create dummy data if not exists for demo purpose
        print(f"⚠️ {filepath} not found. Creating dummy evaluation data.")
        return [
            {"query": "Where is the staircase from Your Name?", "expected_keywords": ["suga", "shrine", "stairs"]},
            {"query": "I want to visit a cafe from Lycoris Recoil.", "expected_keywords": ["cafe", "lyco"]},
            {"query": "Show me spots for Attack on Titan.", "expected_keywords": ["hita", "dam", "wall"]}
        ]
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def calculate_overlap_score(response_text, expected_keywords):
    """
    Simple metric: Keyword Recall.
    Checks how many expected keywords appear in the response.
    """
    if not expected_keywords: return 1.0 # No keywords expected
    
    response_lower = response_text.lower()
    hit_count = sum(1 for k in expected_keywords if k.lower() in response_lower)
    return hit_count / len(expected_keywords)

def run_evaluation():
    if not DASHSCOPE_API_KEY:
        print("⚠️  DASHSCOPE_API_KEY is not set. Evaluation will skip actual API calls or fail.")
    
    # 1. Setup
    agent = AnimeRagAgent()
    eval_data = load_data("evaluation/eval_dataset.json")
    
    header = ["Query", "Expected Keywords", "Agent Response", "Overlap Score", "Latency (s)"]
    results = []
    
    print(f"🚀 Starting Evaluation on {len(eval_data)} items...")
    
    # 2. Run Loop
    for item in eval_data:
        query = item.get("query")
        expected = item.get("expected_keywords", [])
        
        start_time = time.time()
        try:
            # We assume agent.generate_response returns a string
            if DASHSCOPE_API_KEY:
                response = agent.generate_response(query, DASHSCOPE_API_KEY)
            else:
                response = "Skipped (No API Key)"
                
        except Exception as e:
            response = f"Error: {e}"
        latency = round(time.time() - start_time, 2)
        
        score = calculate_overlap_score(response, expected)
        
        results.append([query, str(expected), response[:100]+"...", score, latency])
        print(f"   Query: {query[:30]}... | Score: {score:.2f} | Time: {latency}s")

    # 3. Report
    df = pd.DataFrame(results, columns=header)
    
    avg_score = df["Overlap Score"].mean()
    avg_latency = df["Latency (s)"].mean()
    
    print("\n" + "="*40)
    print("📊 Evaluation Report")
    print("="*40)
    print(f"Total Samples: {len(df)}")
    print(f"Average Keyword Recall: {avg_score:.2%}")
    print(f"Average Latency: {avg_latency:.2f}s")
    print("="*40)
    
    # Save Report
    df.to_csv("evaluation/evaluation_report.csv", index=False)
    print("✅ Report saved to evaluation/evaluation_report.csv")

if __name__ == "__main__":
    run_evaluation()
