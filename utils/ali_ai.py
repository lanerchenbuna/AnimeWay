import dashscope
from dashscope import Generation
import json
import random

def get_image_embedding(image_path):
    return None

def generate_tour_guide_text(points, routes_data):
    """
    Generate a tour guide narrative using Qwen-Turbo.
    Handles both Walking and Transit data.
    """
    if not dashscope.api_key:
        return "请先在左侧输入 Ali DashScope Key 以启用 AI 导游功能。"

    # Construction prompt
    prompt = "你是二次元圣地巡礼导游。请为用户生成硬核巡礼路书。\n\n"
    prompt += "### 巡礼地点：\n"
    for i, p in enumerate(points):
        city = p.get('_city', '')
        prompt += f"{i+1}. {p.get('cn') or p.get('name')} (所在: {city}, 出自: {p.get('_anime_name')})\n"
    
    prompt += "\n### 路线数据 (Google Maps / Amap)：\n"
    for i, r in enumerate(routes_data):
        link_str = f"从第 {i+1} 站 -> 第 {i+2} 站"
        if r:
            rstype = r.get('type', 'walking')
            if rstype == 'transit': mode = "公共交通"
            elif rstype == 'driving': mode = "打车/驾车"
            elif rstype == 'walking': mode = "步行"
            else: mode = "直线移动"
            
            prompt += f"{link_str} ({mode}):\n"
            prompt += f"   - 总耗时: {r['duration_min']}分钟, 距离: {r['distance_m']}米\n"
            
            if r.get('type') == 'transit':
                # Transit specific info
                prompt += f"   - 换乘方案: {' -> '.join(r['steps'])}\n"
            else:
                # Walking info
                prompt += f"   - 关键路口: {', '.join(r['steps'][:5])}...\n"
        else:
            prompt += f"{link_str}: (暂无路线数据，建议打车或步行)\n"
            
    prompt += "\n### 核心要求（重要）：\n"
    prompt += "1. **输出极度详细的出行规划表**：\n"
    prompt += "   - 表格列必须包含：【时间点】、【地点】、【详细交通方案/耗时】、【硬核圣地解说】。\n"
    prompt += "   - **交通方案必须具体**：如果是公交/地铁，必须写出**线路名称**（如：乘坐 [京都市营巴士 205路] 或 [JR山手线]）。不要只写“坐公交”。\n"
    prompt += "   - **换乘细节**：如果有换乘，请在表格中注明（如：四条站换乘 -> 乌丸线）。\n"
    prompt += "2. **解说要求“硬核中二”**：\n"
    prompt += "   - 必须指出该地点在动画中出现的**具体集数**或**名场景**（如：第5集 12:30 处，主角跑过的坂道）。\n"
    prompt += "   - 语气要热血、感人，像一个资深阿宅在带路。\n"
    prompt += "3. **格式示例**：\n"
    prompt += "   | 时间 | 站点 | 交通方案 (此行必须包含线路名) | 圣地巡礼指南 (集数/场景) |\n"
    prompt += "   |---|---|---|---|\n"
    prompt += "   | 09:00 | xx车站 | 乘坐 [JR中央线] 往东京方向 (15min) | 出发！目标是星之所在！ |\n"
    prompt += "   | 09:30 | 下北泽 | 步行 5min 至 Live House | 《孤独摇滚》第8集波奇酱飞奔的街道... |\n"
    prompt += "4. 使用 Markdown 格式。不要输出 ```markdown 标记。\n"

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response = Generation.call(model="qwen-turbo", messages=messages)
        if response.status_code == 200:
            return response.output.text
        else:
            return f"AI 生成失败: {response.message}"
    except Exception as e:
        return f"AI 调用错误: {e}"

def correct_anime_name(user_input):
    """
    Use LLM to correct/normalize anime names.
    Now optimized to return the Official Full Name (with logic to ensure Bangumi Hit).
    """
    if not dashscope.api_key:
        return user_input 

    prompt = (
        f"用户想在 Bangumi 上搜索动画 \"{user_input}\"。\n"
        f"为了确保搜索命中，请分析该动画的 **官方中文全名** 或 **官方日文原名**。\n"
        f"如果该动画有常用的搜索命中率更高的名字（例如带符号的 '少女☆歌剧'，或者 'Love Live!'），请务必返回那个最精确的名字。\n"
        f"只输出名字，不要输出其他内容。\n"
        f"最佳搜索词:"
    )

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response = Generation.call(model="qwen-turbo", messages=messages)
        if response.status_code == 200:
            corrected = response.output.text.strip()
            # Clean generic punctuation if AI gets chatty
            if "是" in corrected and len(corrected) > 10: 
                 pass 
            else:
                 return corrected
        return user_input
    except Exception as e:
        print(f"LLM Correction Error: {e}")
        return user_input

def recommend_anime_list(count=6, context_query=""):
    """
    Ask LLM to recommend a diverse list of high-quality pilgrimage anime.
    """
    if not dashscope.api_key:
        return ["你的名字。", "孤独摇滚!", "灌篮高手", "铃芽之旅", "轻音少女"]

    base_prompt = f"请推荐 {count} 部适合去日本实地巡礼（圣地巡礼）的高质量动画。"
    
    if context_query:
        # Inject user context
        base_prompt = f"用户想要关于“{context_query}”的{count}部圣地巡礼动画推荐。"
    
    prompt = (
        f"{base_prompt}\n"
        f"要求：\n"
        f"1. 必须是真实的、有明确取景地的动画。\n"
        f"2. 尽量覆盖不同风格（如京阿尼系列、新海诚系列、硬核写实系）。\n"
        f"3. 每次回答请尽量随机，不要每次都一样。\n"
        f"4. 只输出动画的官方中文名称，用JSON列表格式。\n"
        f"5. 不要包含任何Markdown标记或解释。\n\n"
        f"示例格式: [\"动画A\", \"动画B\"]"
    )

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response = Generation.call(model="qwen-turbo", messages=messages, temperature=0.9)
        if response.status_code == 200:
            txt = response.output.text.strip()
            if txt.startswith("```"): txt = txt.split("\n", 1)[1].rsplit("\n", 1)[0]
            if txt.startswith("json"): txt = txt[4:]
            try:
                anime_list = json.loads(txt)
                if isinstance(anime_list, list):
                    return anime_list
            except:
                lines = txt.replace('[','').replace(']','').replace('"','').split(',')
                return [l.strip() for l in lines if l.strip()]
    except Exception as e:
        print(f"LLM Rec Error: {e}")
    
    return ["您的名字。", "孤独摇滚!", "千与千寻"]

def recommend_anime_by_city(city_name):
    """
    Ask LLM for anime associated with a specific city.
    """
    if not dashscope.api_key:
        return []

    prompt = (
        f"请列出 5 部取景地主要在 **{city_name}** 或其周边的著名动画。\n"
        f"要求：\n"
        f"1. 必须是真实的、有该城市明确巡礼价值的动画。\n"
        f"2. 只输出动画的官方中文名称，用JSON列表格式。\n"
        f"3. 不要废话，不要Markdown。\n"
        f"示例: [\"动画A\", \"动画B\"]"
    )

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response = Generation.call(model="qwen-turbo", messages=messages)
        if response.status_code == 200:
            txt = response.output.text.strip()
            if txt.startswith("```"): txt = txt.split("\n", 1)[1].rsplit("\n", 1)[0]
            if txt.startswith("json"): txt = txt[4:]
            try:
                anime_list = json.loads(txt)
                if isinstance(anime_list, list):
                    return anime_list
            except:
                lines = txt.replace('[','').replace(']','').replace('"','').split(',')
                return [l.strip() for l in lines if l.strip()]
    except Exception as e:
        print(f"LLM City Rec Error: {e}")
    
    return []
