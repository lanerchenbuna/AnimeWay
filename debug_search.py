
import requests
from urllib.parse import quote

def do_search(q):
    print(f"\n--- Searching: {q} ---")
    url = f"https://api.bgm.tv/search/subject/{quote(q)}?type=2&responseGroup=medium"
    headers = {'User-Agent': 'AnimePilgrimage/1.0'}
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if 'list' in data and data['list']:
            print(f"Found {len(data['list'])} results.")
            for i, item in enumerate(data['list']):
                print(f"#{i+1}: {item.get('name_cn')} / {item.get('name')} (ID: {item['id']})")
                if item['id'] == 214265:
                    print("!!! FOUND MAIN SERIES (ID 214265) !!!")
        else:
            print("No results found.")
    except Exception as e:
        print(f"Error: {e}")

do_search("少女歌剧")
do_search("少女☆歌剧")
