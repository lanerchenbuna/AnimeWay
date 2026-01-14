import requests

endpoints = [
    "https://api.anitabi.cn/home/recommend",
    "https://api.anitabi.cn/bangumi/list",
    "https://api.anitabi.cn/bangumi/recommend",
    "https://api.anitabi.cn/subject/hot",
    "https://api.anitabi.cn/bangumi/updated",
    "https://api.anitabi.cn/timeline"
]

headers = {'User-Agent': 'AnimePilgrimage/1.0'}

for url in endpoints:
    try:
        print(f"Testing {url}...")
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            print(f"✅ SUCCESS: {url}")
            # Print structure summary
            if isinstance(data, list):
                print(f"Type: List, Len: {len(data)}")
                if len(data) > 0: print(f"Sample: {data[0]}")
            elif isinstance(data, dict):
                print(f"Type: Dict, Keys: {list(data.keys())}")
        else:
            print(f"❌ {res.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")
