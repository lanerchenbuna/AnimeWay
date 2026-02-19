import json
import os
import time
import requests
from typing import List, Dict

# Configuration
BANGUMI_FILE = "knowledge_base/raw/bangumi_knowledge.json"
OUTPUT_FILE = "knowledge_base/raw/anitabi_crawl.json"
# 🛠️ Fix: Use /points/detail endpoint for full data (lite is capped at 10)
ANITABI_BASE_URL = "https://api.anitabi.cn/bangumi/{}/points/detail"
DELAY_SECONDS = 0.5  # Be polite to the API

def load_bangumi_ids(filepath: str) -> List[Dict]:
    """Loads anime metadata from the user-provided JSON."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return []
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"✅ Loaded {len(data)} subjects from {filepath}")
    return data

def fetch_anitabi_points(subject_id: str) -> List[Dict]:
    """Fetches pilgrimage points for a given subject ID."""
    url = ANITABI_BASE_URL.format(subject_id)
    headers = {'User-Agent': 'AnimePilgrimage/1.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return [] # No spots for this anime
        else:
            print(f"   ⚠️ API Error {response.status_code} for ID {subject_id}")
            return []
    except Exception as e:
        print(f"   ⚠️ Connection Error for ID {subject_id}: {e}")
        return [] 
        
def main():
    print("🚀 [Sync] Starting Anitabi Sync Job...")
    
    # 1. Load Data
    subjects = load_bangumi_ids(BANGUMI_FILE)
    manual_subjects = load_bangumi_ids("knowledge_base/raw/manual_seeds.json")
    if manual_subjects:
        print(f"✅ Loaded {len(manual_subjects)} manual seeds.")
        subjects.extend(manual_subjects)
        
    if not subjects:
        return

    # 2. Filter / Prioritize (Optional)
    print("📊 Sorting subjects by popularity (votes)...")
    subjects.sort(key=lambda x: int(x.get("votes", 0)) if str(x.get("votes", 0)).isdigit() else 0, reverse=True)
    
    top_subjects = subjects 
         
    print(f"🎯 Targeting ALL {len(top_subjects)} animes for crawl.")

    crawled_points = []
    
    for i, sub in enumerate(top_subjects):
        sid = sub.get("subject") or sub.get("id")
        title = sub.get("中文名") or sub.get("原名") or sub.get("name_cn") or "Unknown"
        
        print(f"[{i+1}/{len(top_subjects)}] Checking: {title} (ID: {sid})...", end="", flush=True)
        
        # API returns a List[Dict] for /points/detail
        data = fetch_anitabi_points(sid)
        
        # Check if we got valid data (List of spots)
        if isinstance(data, list) and data:
            points = data
            city = "" 
            
            print(f" ✅ Found {len(points)} spots (Full).")
            for p in points:
                crawled_points.append({
                    "anime_id": int(sid),
                    "name": p.get("name") or p.get("cn"), 
                    "geo": p.get("geo"),
                    "image": p.get("image"),
                    "city": p.get("city") or "", 
                    "tags": [title]
                })
        else:
             print(" ⚪", end="")
            
        time.sleep(DELAY_SECONDS)
        
        # Incremental Save every 50 items
        if (i + 1) % 50 == 0:
            print(f"\n💾 [Checkpoint] Saving {len(crawled_points)} spots so far...")
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(crawled_points, f, indent=2, ensure_ascii=False)

    # 3. Final Save
    print(f"\n💾 Saving FINAL {len(crawled_points)} retrieved spots to {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(crawled_points, f, indent=2, ensure_ascii=False)
        
    print("🎉 Sync Complete!")

if __name__ == "__main__":
    main()
