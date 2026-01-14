CITY_ANIME_MAP = {
    "京都": ["吹响！上低音号", "轻音少女", "有顶天家族", "玉子市场"],
    "宇治": ["吹响！上低音号"],
    "镰仓": ["灌篮高手", "TARI TARI", "青春猪头少年不会梦到兔女郎学姐", "孤独摇滚!"],
    "藤泽": ["青春猪头少年不会梦到兔女郎学姐", "TARI TARI"],
    "江之岛": ["孤独摇滚!", "TARI TARI", "青春猪头少年不会梦到兔女郎学姐", "乒乓"],
    "东京": ["你的名字。", "天气之子", "秒速5厘米", "Love Live!", "孤独摇滚!", "莉可丽丝"],
    "新宿": ["你的名字。", "言叶之庭"],
    "下北沢": ["孤独摇滚!"],
    "秋叶原": ["命运石之门", "Love Live!"],
    "沼津": ["Love Live! Sunshine!!"],
    "横滨": ["文豪野犬", "滨虎"],
    "箱根": ["新世纪福音战士"],
    "埼玉": ["未闻花名", "幸运星", "更衣人偶坠入爱河"],
    "秩父": ["未闻花名", "心灵想要大声呼喊"],
    "饭能": ["向山进发"], 
    "大垣": ["声之形"],
    "高山": ["冰菓"],
    "飞驒": ["你的名字。"],
    "佐贺": ["佐贺偶像是传奇"],
    "格里普斯": ["机动战士Z高达"], # Joke
    "长崎": ["色づく世界の明日から"],
    "冲绳": ["白沙的水族馆"],
    "北海道": ["黄金神威", "只有我不在的街道"],
    "函馆": ["Love Live! Sunshine!!"],
    "鸟取": ["Free!"],
    "岩美": ["Free!"]
}

def get_popular_anime_by_city(city_name):
    """
    Return list of anime for a given city (fuzzy match).
    """
    results = set()
    for k, v in CITY_ANIME_MAP.items():
        if k in city_name or city_name in k:
            for anime in v:
                results.add(anime)
    return list(results)
