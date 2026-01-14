
import requests
import json

def probe_points(subject_id):
    url = f"https://api.anitabi.cn/bangumi/{subject_id}/points/detail?haveImage=true"
    print(f"Fetching {url}...")
    try:
        res = requests.get(url)
        data = res.json()
        if data:
            print("Sample Point Keys:", data[0].keys())
            print("Sample Point Data:", json.dumps(data[0], ensure_ascii=False))
        else:
            print("No points found.")
    except Exception as e:
        print(f"Error: {e}")

# Test with "Sound! Euphonium" (ID 115908) which is strongly associated with Uji, Kyoto.
probe_points(115908)
