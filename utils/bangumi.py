import requests
from urllib.parse import quote
from utils import ali_ai

def search_candidates(query, use_llm=True):
    """
    Search Bangumi and return a list of candidate dicts.
    Returns: [{ 'id': int, 'cn': str, 'jp': str, ... }, ...]
    """
    clean_name = query.strip()
    if not clean_name: return []

    candidates_map = {} # Use dict to deduplicate by ID

    def do_search(q):
        url = f"https://api.bgm.tv/search/subject/{quote(q)}?type=2&responseGroup=medium"
        headers = {'User-Agent': 'AnimePilgrimage/1.0'}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            res.raise_for_status()
            data = res.json()
            if 'list' in data and data['list']:
                return data['list']
        except Exception as e:
            print(f"Search Error: {e}")
        return []

    # 1. Raw Search
    raw_list = do_search(clean_name)
    for item in raw_list:
        candidates_map[item['id']] = item
        
    # 2. LLM Correction (Run if LLM enabled, even if Raw found results)
    # Rationale: Raw search "少女歌剧" finds movies/spinoffs but misses the main TV series.
    # LLM corrects to "少女☆歌剧" which finds the main series.
    # We should merge both.
    if use_llm:
        corrected = ali_ai.correct_anime_name(clean_name)
        if corrected and corrected != clean_name:
            print(f"LLM Expanded Search: {clean_name} -> {corrected}")
            corrected_list = do_search(corrected)
            for item in corrected_list:
                # Add if not exist, or maybe update if better match? 
                # Keep simple: Add missing.
                if item['id'] not in candidates_map:
                    candidates_map[item['id']] = item
    
    # Format Output
    results = []
    # Convert map back to list, prioritize by some metric?
    # Bangumi returns relevance sorted. We should perhaps keep Raw top match, then Corrected?
    # Or just list all unique items.
    
    # Ideally, we want ID 214265 (TV) to be near top.
    # Let's just create the list from values.
    
    combined_items = list(candidates_map.values())
    
    # Optional: Sort by popularity (ranking)?
    # Bangumi API 'rank' field implies popularity. Smaller is better.
    # If rank is missing (0 or null), treat as low priority.
    def get_rank(i):
        # Bangumi sometimes puts rank in 'cat' or 'rank' or 'rating.rank'
        # Medium response: item['rank'] exists if type=2?
        # Let's check a sample or just rely on API sort order order.
        return i.get('rank') or 999999
        
    combined_items.sort(key=get_rank)
    
    for item in combined_items:
        results.append({
            'id': item['id'],
            'cn': item.get('name_cn') or item.get('name'), 
            'jp': item.get('name'),
            'image': item.get('images', {}).get('common'),
            'summary': item.get('summary', '')[:50] + '...'
        })
    
    return results

def get_bangumi_id_robust(anime_name):
    c = search_candidates(anime_name, use_llm=True)
    if c:
        return c[0]['id'], c[0]['cn']
    return None, None
