import dashscope
from dashscope import Generation
import json

def parse_intent(user_input):
    """
    Analyze user input to determine intent:
    - SEARCH: User wants to find a specific anime.
    - RECOMMEND: User wants suggestions based on a mood/genre/city.
    - CHAT: General conversation (handled as a helpful guide).
    
    Returns: {
        'type': 'SEARCH' | 'RECOMMEND' | 'CHAT',
        'query': str (extracted keywords or refined query),
        'context': str (optional context like 'sad', 'kyoto')
    }
    """
    if not dashscope.api_key:
        # Fallback simplistic logic if no key
        if any(k in user_input for k in ['推荐', '想看', '介绍', '有什么']):
            return {'type': 'RECOMMEND', 'query': user_input}
        return {'type': 'SEARCH', 'query': user_input}

    prompt = (
        f"用户输入: \"{user_input}\"\n"
        f"请判断用户意图并提取关键信息。\n"
        f"分类标准:\n"
        f"1. SEARCH: 用户明确提到了番剧名字，想找这部番的圣地 (如: '找一下孤独摇滚', 'Lycoris where').\n"
        f"2. RECOMMEND: 用户没有具体目标，想要推荐 (如: '推荐几部治愈的', '京都附近有什么番', '想看机甲类').\n"
        f"3. CHAT: 闲聊或无关话题.\n\n"
        f"请输出 JSON 格式: {{'type': 'SEARCH'|'RECOMMEND'|'CHAT', 'query': '提取的核心搜索词或推荐关键词'}}.\n"
        f"只输出JSON，不要Markdown。"
    )

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response = Generation.call(model="qwen-turbo", messages=messages)
        if response.status_code == 200:
            txt = response.output.text.strip()
            if txt.startswith("```"): txt = txt.split("\n", 1)[1].rsplit("\n", 1)[0]
            if txt.startswith("json"): txt = txt[4:]
            
            data = json.loads(txt)
            return data
    except Exception as e:
        print(f"Agent Intent Error: {e}")
    
    # Default fallback
    return {'type': 'SEARCH', 'query': user_input}
