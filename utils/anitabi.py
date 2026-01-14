import requests

def get_points(subject_id):
    """
    Fetch pilgrimage points for a specific Bangumi Subject ID from Anitabi.
    """
    url = f"https://api.anitabi.cn/bangumi/{subject_id}/points/detail?haveImage=true"
    headers = {'User-Agent': 'AnimePilgrimage/1.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"Anitabi API Error: {e}")
        return []

def get_subject_lite(subject_id):
    """
    Fetch lite info for a subject to get metadata like 'city'.
    """
    url = f"https://api.anitabi.cn/bangumi/{subject_id}/lite"
    headers = {'User-Agent': 'AnimePilgrimage/1.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"Anitabi Lite API Error: {e}")
        return {}

def get_recommendations():
    """
    Fetch a list of recommended/popular anime from Anitabi.
    Returns: List of dicts { 'id': int, 'cn': str, ... }
    """
    candidates = []
    
    # Try Live API 
    urls = [
        "https://api.anitabi.cn/bangumi/recommend",
        "https://api.anitabi.cn/bangumi/list"
    ]
    headers = {'User-Agent': 'AnimePilgrimage/1.0'}
    
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    candidates = data
                    break 
        except Exception as e:
            print(f"API Fetch Error {url}: {e}")
            
    return candidates
