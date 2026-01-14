import requests
import json

url = "https://api.anitabi.cn/bangumi/recommend"
try:
    res = requests.get(url, headers={'User-Agent': 'AnimePilgrimage/1.0'}, timeout=10)
    print(f"Status: {res.status_code}")
    print(f"Raw: {res.text[:500]}")
    data = res.json()
    print(f"Type: {type(data)}")
    if isinstance(data, list):
        print(f"Count: {len(data)}")
        if len(data) > 0:
            print("First Item Keys:", data[0].keys())
except Exception as e:
    print(f"Error: {e}")
