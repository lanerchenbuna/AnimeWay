import requests
import json

url = "https://api.anitabi.cn/bangumi/recommend"
print(" Fetching recommend...")
try:
    res = requests.get(url, headers={'User-Agent': 'AnimePilgrimage/1.0'}).json()
    if isinstance(res, list) and len(res) > 0:
        print("Root is LIST. First item keys:")
        print(res[0].keys())
        print("First item sample:")
        print(res[0])
    elif isinstance(res, dict):
        print("Root is DICT. Keys:")
        print(res.keys())
except Exception as e:
    print(e)
