import json
import platform
import resource
import statistics
import time


NEGATIVE_QUERIES = [
    "量子香蕉飞船",
    "火星章鱼地铁",
    "蓝色土豆宇宙港",
    "机械榴莲温泉",
    "银河萝卜小学",
    "透明企鹅车站",
    "反物质拉面神社",
    "月球海底咖啡馆",
    "赛博西瓜寺",
    "紫色引力面包店",
    "平行宇宙白菜塔",
    "超导章鱼电影院",
    "木星豆腐研究所",
    "时间旅行菠萝港",
    "纳米鳄鱼音乐厅",
    "黑洞草莓图书馆",
    "星际韭菜体育馆",
    "光速海豹杂货店",
    "磁悬浮柚子神殿",
    "暗物质寿司学校",
    "量子河马美术馆",
    "虫洞茄子便利店",
    "太阳风企鹅公园",
    "火星芒果警察局",
    "宇宙乌冬实验室",
    "中微子熊猫商场",
    "引力波橙子码头",
    "反物质猫咪医院",
    "超新星萝卜旅馆",
    "平行时空西瓜广场",
    "等离子章鱼邮局",
    "夸克土豆银行",
    "暗能量海豚车库",
    "光子白菜水族馆",
    "量子纠缠柠檬城堡",
    "曲率引擎熊猫茶室",
    "星门芒果理发店",
    "月球韭菜事务所",
    "火星豆浆游乐园",
    "银河榴莲消防站",
]

SPOT_QUERIES = [
    "京都有什么动画圣地",
    "横滨有什么动画圣地",
    "咖啡店巡礼",
    "孤独摇滚圣地",
    "东京有什么动画圣地",
    "学校巡礼",
    "神社巡礼",
    "下北泽圣地",
]

THRESHOLDS = {
    "startup_seconds": 2.0,
    "rss_mb": 300.0,
    "spot_p95_ms": 100.0,
    "false_positive_rate": 0.05,
}


def _rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return value / 1024 / 1024
    return value / 1024


def run_benchmark(iterations: int = 30):
    startup_begin = time.perf_counter()
    from core.agent import AnimeRagAgent

    agent = AnimeRagAgent()
    startup_seconds = time.perf_counter() - startup_begin

    false_hits = [
        query
        for query in NEGATIVE_QUERIES
        if agent.retriever.search_anime(query, 3)
        or agent.retriever.search_spots(query, 3)
    ]

    latencies = []
    for _ in range(iterations):
        for query in SPOT_QUERIES:
            begin = time.perf_counter()
            agent.retriever.search_spots(query, 20)
            latencies.append((time.perf_counter() - begin) * 1000)

    result = {
        "startup_seconds": round(startup_seconds, 3),
        "rss_mb": round(_rss_mb(), 1),
        "spot_p50_ms": round(statistics.median(latencies), 2),
        "spot_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
        "negative_query_count": len(NEGATIVE_QUERIES),
        "false_hits": false_hits,
        "false_positive_rate": round(len(false_hits) / len(NEGATIVE_QUERIES), 4),
    }
    failures = {
        metric: {"actual": result[metric], "threshold": threshold}
        for metric, threshold in THRESHOLDS.items()
        if result[metric] >= threshold
    }
    return result, failures


if __name__ == "__main__":
    result, failures = run_benchmark()
    print(json.dumps({"result": result, "failures": failures}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if failures else 0)
