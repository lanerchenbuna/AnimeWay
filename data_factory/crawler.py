import json
import os
import time
import requests
from data_factory.normalization import normalize_spot, stable_spot_id, extract_lat_lon  # noqa: F401
from datetime import datetime
from typing import Any, List, Dict, Tuple

# Configuration
BANGUMI_FILE = "knowledge_base/raw/bangumi_knowledge.json"
OUTPUT_FILE = "knowledge_base/raw/anitabi_crawl.json"
STATE_FILE = "knowledge_base/raw/crawl_state.json"
# 🛠️ Fix: Use /points/detail endpoint for full data (lite is capped at 10)
ANITABI_BASE_URL = "https://api.anitabi.cn/bangumi/{}/points/detail"
ANITABI_LITE_URL = "https://api.anitabi.cn/bangumi/{}/lite"
DELAY_SECONDS = 2.0  # Be polite to the API; bursts are what trigger its Cloudflare 403
HEADERS = {'User-Agent': 'AnimePilgrimage/1.0'}
MAX_HTTP_ATTEMPTS = 3
MAX_BLOCKED_ATTEMPTS = 5
MAX_STATE_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
# Anitabi sits behind Cloudflare, which answers a request burst with HTTP 403 and then
# clears. Observed 2026-09-27: the same URL returned 403 and, 92 seconds later with the
# same client, a normal 200 JSON response. A 403 is a throttle to wait out, not a
# permanent denial, so it is retried after a long cooldown. This stays inside upstream
# limits: TLS verification is never disabled, no challenge is solved and no browser
# fingerprint is forged.
BLOCKED_STATUS_CODES = {403}
BLOCKED_COOLDOWN_SECONDS = 60.0
MAX_BLOCKED_COOLDOWN_SECONDS = 600.0


def request_options() -> dict[str, Any]:
    """Keep network settings explicit without weakening TLS verification."""
    options: dict[str, Any] = {"timeout": (5, 20)}
    proxy = os.getenv("ANIMEWAY_ANITABI_PROXY")
    if proxy:
        options["proxies"] = {"http": proxy, "https": proxy}
    return options


def failure_reason(exc: requests.RequestException) -> str:
    """Avoid persisting request URLs or proxy credentials in candidate reports."""
    return type(exc).__name__


def response_reason(response: requests.Response) -> str:
    return f"HTTP {response.status_code}"


def blocked_cooldown() -> float:
    """Cooldown between blocked attempts; ANIMEWAY_ANITABI_COOLDOWN overrides it."""
    raw = os.getenv("ANIMEWAY_ANITABI_COOLDOWN")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return BLOCKED_COOLDOWN_SECONDS
        if 0 <= value <= MAX_BLOCKED_COOLDOWN_SECONDS:
            return value
    return BLOCKED_COOLDOWN_SECONDS


def retry_after_seconds(response, default: float) -> float:
    """Honour an upstream Retry-After header, capped; never trusts it blindly."""
    raw = response.headers.get("Retry-After") if getattr(response, "headers", None) else None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < 0 or value > MAX_BLOCKED_COOLDOWN_SECONDS:
        return default
    return max(value, default)

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

def normalize_crawled_point(point: Dict, anime_id: int, title: str, anime_city: str = "") -> Dict | None:
    raw = dict(point)
    raw["city"] = point.get("city") or anime_city
    raw["tags"] = point.get("tags") or [title]
    spot = normalize_spot(raw, anime_id)
    if spot is None:
        return None
    result = spot.model_dump(mode="json", exclude_none=True)
    result.update(anime_id=int(anime_id), geo=[spot.lat, spot.lon])
    return result

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
    """Fetch one URL politely; TLS verification stays on and no body is logged.

    Retryable statuses (429/5xx) back off briefly. A Cloudflare 403 gets a longer
    allowance and an escalating cooldown, so a burst-limited refresh slows down and
    eventually gives up instead of hammering or silently dropping the work.
    """
    last_error = ""
    response = None
    cooldown = blocked_cooldown()
    plain, blocked = 0, 0
    while True:
        try:
            response = requests.get(url, headers=HEADERS, **request_options())
            if response.status_code == 200:
                return response, ""
            last_error = response_reason(response)
            if response.status_code not in RETRYABLE_STATUS_CODES | BLOCKED_STATUS_CODES:
                return response, last_error
        except requests.RequestException as exc:
            response = None
            last_error = failure_reason(exc)
        if response is not None and response.status_code in BLOCKED_STATUS_CODES:
            blocked += 1
            if blocked >= MAX_BLOCKED_ATTEMPTS:
                return response, last_error
            time.sleep(retry_after_seconds(response, cooldown))
            cooldown = min(cooldown * 2, MAX_BLOCKED_COOLDOWN_SECONDS)
        else:
            plain += 1
            if plain >= MAX_HTTP_ATTEMPTS:
                return response, last_error
            time.sleep(DELAY_SECONDS * (2 ** (plain - 1)))

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
    """Refreshes use candidate bundles; bootstrap only initializes legacy state."""
    if not bootstrap_state_only:
        from data_factory.sync import main as sync_main
        return sync_main()
    subjects = load_bangumi_ids(BANGUMI_FILE)
    subjects.extend(load_bangumi_ids("knowledge_base/raw/manual_seeds.json"))
    points, _ = load_existing_points(OUTPUT_FILE)
    counts: Dict[int, int] = {}
    for point in points:
        anime_id = int(point["anime_id"])
        counts[anime_id] = counts.get(anime_id, 0) + 1
    state = load_json_file(STATE_FILE, {})
    for subject in subjects:
        try:
            anime_id = int(subject.get("subject") or subject.get("id"))
        except (ValueError, TypeError):
            continue
        if str(anime_id) not in state:
            title = subject.get("中文名") or subject.get("原名") or subject.get("name_cn") or "Unknown"
            update_state(state, anime_id, "success" if anime_id in counts else "pending", title, counts.get(anime_id, 0))
    save_json_file(STATE_FILE, state)
    print(f"State bootstrap complete: {len(state)} works; no network requests.")

if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--bootstrap-state-only"]:
        main(bootstrap_state_only=True)
    else:
        from data_factory.sync import main as sync_main
        sync_main()
