import requests
import json

urls = [
    "https://api.anitabi.cn/bangumi/recommend",
    "https://api.anitabi.cn/bangumi/list",
    "https://api.anitabi.cn/subject/hot"
]

headers = {'User-Agent': 'AnimePilgrimage/1.0'}

for url in urls:
    print(f"\n--- Testing {url} ---")
    try:
        res = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {res.status_code}")
        try:
            data = res.json()
            print("Type:", type(data))
            if isinstance(data, list):
                print(f"List Len: {len(data)}")
                if len(data) > 0: print(f"Sample[0]: {data[0]}")
            elif isinstance(data, dict):
                print("Dict Keys:", data.keys())
                # maybe standard wrapper? code/msg/data?
                if 'data' in data:
                    print("Has 'data' key.")
                    print("Data Type:", type(data['data']))
        except:
             print("Raw Text (First 200 chars):", res.text[:200])
    except Exception as e:
        print(f"Error: {e}")
