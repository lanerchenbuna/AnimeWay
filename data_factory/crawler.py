import argparse
import json
import os
import time
import requests
import hashlib
from datetime import datetime
from typing import Any, List, Dict, Tuple

# Configuration
BANGUMI_FILE = "knowledge_base/raw/bangumi_knowledge.json"
OUTPUT_FILE = "knowledge_base/raw/anitabi_crawl.json"
STATE_FILE = "knowledge_base/raw/crawl_state.json"
# 🛠️ Fix: Use /points/detail endpoint for full data (lite is capped at 10)
ANITABI_BASE_URL = "https://api.anitabi.cn/bangumi/{}/points/detail"
ANITABI_LITE_URL = "https://api.anitabi.cn/bangumi/{}/lite"
DELAY_SECONDS = 0.5  # Be polite to the API
HEADERS = {'User-Agent': 'AnimePilgrimage/1.0'}
MAX_HTTP_ATTEMPTS = 3
MAX_STATE_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

def load_bangumi_ids(filepath: str) -> List[Dict]:
    """Loads anime metadata from the user-provided JSON."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return []
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"✅ Loaded {len(data)} subjects from {filepath}")
    return data

def load_json_file(filepath: str, default: Any):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ Failed to load {filepath}: {e}")
        return default

def save_json_file(filepath: str, data: Any) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = f"{filepath}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, filepath)

def stable_spot_id(anime_id: int, name: str, lat: float, lon: float) -> str:
    source = f"{anime_id}:{name}:{lat:.6f}:{lon:.6f}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()

def extract_lat_lon(point: Dict) -> Tuple[float | None, float | None]:
    geo = point.get("geo")
    if isinstance(geo, list) and len(geo) == 2:
        try:
            return float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            return None, None
    try:
        return float(point.get("lat")), float(point.get("lon"))
    except (TypeError, ValueError):
        return None, None

def normalize_crawled_point(point: Dict, anime_id: int, title: str, anime_city: str = "") -> Dict | None:
    name = str(point.get("name") or point.get("cn") or "").strip()
    lat, lon = extract_lat_lon(point)
    if not name or lat is None or lon is None:
        return None

    return {
        "id": str(point.get("id") or stable_spot_id(anime_id, name, lat, lon)),
        "anime_id": int(anime_id),
        "name": name,
        "geo": [lat, lon],
        "lat": lat,
        "lon": lon,
        "image": point.get("image") or point.get("img"),
        "city": point.get("city") or anime_city,
        "description": point.get("description") or point.get("content"),
        "tags": point.get("tags") or [title],
        "source_url": point.get("source_url"),
        "episode": point.get("episode"),
        "scene": point.get("scene"),
        "verified_at": point.get("verified_at"),
    }

def load_existing_points(filepath: str) -> Tuple[List[Dict], set[int]]:
    raw_points = load_json_file(filepath, [])
    points = []
    completed_ids = set()
    for point in raw_points:
        try:
            anime_id = int(point.get("anime_id"))
        except (TypeError, ValueError):
            continue

        normalized = normalize_crawled_point(
            point=point,
            anime_id=anime_id,
            title=(point.get("tags") or ["Unknown"])[0] if isinstance(point.get("tags"), list) else "Unknown",
            anime_city=point.get("city") or "",
        )
        if normalized:
            points.append(normalized)
            completed_ids.add(anime_id)

    return points, completed_ids

def update_state(state: Dict, subject_id: int, status: str, title: str, point_count: int = 0, error: str = "") -> None:
    key = str(subject_id)
    previous = state.get(key, {})
    retries = int(previous.get("retries", 0))
    if status == "failed":
        retries += 1

    state[key] = {
        "anime_id": subject_id,
        "title": title,
        "status": status,
        "point_count": point_count,
        "retries": retries,
        "error": error,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

def request_with_backoff(url: str):
    last_error = ""
    for attempt in range(MAX_HTTP_ATTEMPTS):
        try:
            response = requests.get(url, headers=HEADERS, timeout=5)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response, ""
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            response = None
            last_error = type(exc).__name__
        if attempt < MAX_HTTP_ATTEMPTS - 1:
            time.sleep(DELAY_SECONDS * (2 ** attempt))
    return response, last_error

def fetch_anitabi_lite_city(subject_id: str) -> str:
    """Fetches the main city for the anime from the lite endpoint."""
    url = ANITABI_LITE_URL.format(subject_id)
    
    try:
        response, _ = request_with_backoff(url)
        if response is None:
            return ""
        if response.status_code == 200:
            data = response.json()
            return data.get("city") or ""
        return ""
    except Exception:
        return ""

def fetch_anitabi_points(subject_id: str) -> Tuple[str, List[Dict], str]:
    """Fetches pilgrimage points for a given subject ID."""
    url = ANITABI_BASE_URL.format(subject_id)
    
    try:
        response, request_error = request_with_backoff(url)
        if response is None:
            return "failed", [], request_error or "Network error"
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return "success", data, ""
            return "failed", [], "Unexpected response shape"
        elif response.status_code == 404:
            return "not_found", [], "404"
        else:
            error = f"API Error {response.status_code}"
            print(f"   ⚠️ {error} for ID {subject_id}")
            return "failed", [], error
    except Exception as e:
        print(f"   ⚠️ Connection Error for ID {subject_id}: {e}")
        return "failed", [], str(e)
        
def main(bootstrap_state_only: bool = False):
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

    crawled_points, completed_from_points = load_existing_points(OUTPUT_FILE)
    state = load_json_file(STATE_FILE, {})
    title_by_id = {}
    for sub in top_subjects:
        sid = sub.get("subject") or sub.get("id")
        if not sid:
            continue
        try:
            title_by_id[int(sid)] = sub.get("中文名") or sub.get("原名") or sub.get("name_cn") or "Unknown"
        except (TypeError, ValueError):
            continue

    existing_counts: Dict[int, int] = {}
    for point in crawled_points:
        anime_id = int(point["anime_id"])
        existing_counts[anime_id] = existing_counts.get(anime_id, 0) + 1
    for anime_id, point_count in existing_counts.items():
        if str(anime_id) not in state:
            update_state(
                state,
                anime_id,
                "success",
                title_by_id.get(anime_id, "Existing crawl data"),
                point_count=point_count,
            )

    pending_added = 0
    for anime_id, title in title_by_id.items():
        if str(anime_id) not in state:
            update_state(state, anime_id, "pending", title, point_count=0)
            pending_added += 1
    if pending_added:
        save_json_file(STATE_FILE, state)
        print(f"🧾 Added {pending_added} pending anime IDs to the crawl state.")
    if bootstrap_state_only:
        print(f"✅ State bootstrap complete: {len(state)} tracked anime IDs.")
        return

    completed_from_state = {
        int(k)
        for k, v in state.items()
        if str(v.get("status")) in {"success", "no_spots", "not_found"} and str(k).isdigit()
    }
    completed_ids = completed_from_points | completed_from_state
    print(f"♻️ Loaded {len(crawled_points)} existing points; {len(completed_ids)} anime IDs already completed.")
    
    for i, sub in enumerate(top_subjects):
        sid = sub.get("subject") or sub.get("id")
        title = sub.get("中文名") or sub.get("原名") or sub.get("name_cn") or "Unknown"
        if not sid:
            continue
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            print(f"[{i+1}/{len(top_subjects)}] Skipping invalid subject ID: {sid}")
            continue

        if sid_int in completed_ids:
            print(f"[{i+1}/{len(top_subjects)}] Skipping completed: {title} (ID: {sid_int})")
            continue
        previous_state = state.get(str(sid_int), {})
        if previous_state.get("status") == "failed" and int(previous_state.get("retries", 0)) >= MAX_STATE_RETRIES:
            print(
                f"[{i+1}/{len(top_subjects)}] Skipping retry limit: "
                f"{title} (ID: {sid_int}, retries: {previous_state.get('retries')})"
            )
            continue
        
        print(f"[{i+1}/{len(top_subjects)}] Checking: {title} (ID: {sid_int})...", end="", flush=True)
        
        # API returns a List[Dict] for /points/detail
        status, data, error = fetch_anitabi_points(str(sid_int))
        
        # Check if we got valid data (List of spots)
        if status == "success" and data:
            points = data
            anime_city = fetch_anitabi_lite_city(str(sid_int)) 
            
            print(f" ✅ Found {len(points)} spots (Full). City: {anime_city}")
            added_count = 0
            for p in points:
                normalized = normalize_crawled_point(p, sid_int, title, anime_city)
                if normalized:
                    crawled_points.append(normalized)
                    added_count += 1
            update_state(state, sid_int, "success", title, point_count=added_count)
            completed_ids.add(sid_int)
        elif status == "success":
            print(" ⚪ No spots")
            update_state(state, sid_int, "no_spots", title, point_count=0)
            completed_ids.add(sid_int)
        elif status == "not_found":
            print(" ⚪ 404")
            update_state(state, sid_int, "not_found", title, point_count=0, error=error)
            completed_ids.add(sid_int)
        else:
            print(" ❌ Failed")
            update_state(state, sid_int, "failed", title, point_count=0, error=error)
            
        time.sleep(DELAY_SECONDS)
        
        # Incremental Save every 50 items
        if (i + 1) % 25 == 0:
            print(f"\n💾 [Checkpoint] Saving {len(crawled_points)} spots so far...")
            save_json_file(OUTPUT_FILE, crawled_points)
            save_json_file(STATE_FILE, state)

    # 3. Final Save
    print(f"\n💾 Saving FINAL {len(crawled_points)} retrieved spots to {OUTPUT_FILE}...")
    save_json_file(OUTPUT_FILE, crawled_points)
    save_json_file(STATE_FILE, state)
        
    print("🎉 Sync Complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incrementally sync Anitabi pilgrimage points.")
    parser.add_argument(
        "--bootstrap-state-only",
        action="store_true",
        help="Record pending/success states without making network requests.",
    )
    args = parser.parse_args()
    main(bootstrap_state_only=args.bootstrap_state_only)
