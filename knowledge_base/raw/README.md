# 如何导入自定义数据

请将您准备好的 JSON 文件放置于此目录，并命名为 `anitabi_crawl.json` (或者修改 `data_factory/build_kb.py` 中的路径)。

## 推荐数据格式 (Expected Schema)

知识库构建管道预期的数据格式如下：

```json
[
  {
    "anime_id": 32281,              // 必须: Bangumi ID 或自定义 ID
    "name": "须贺神社前阶梯",         // 必须: 圣地名称
    "geo": [35.6853, 139.7245],     // 必须: [纬度, 经度]
    "city": "东京都",                // 可选: 城市
    "tags": ["神社", "名场面"],      // 可选: 标签列表
    "source_url": "https://...",     // 可选: 场景资料来源
    "episode": "12",                 // 可选: 集数
    "scene": "阶梯相遇场景",          // 可选: 场景说明
    "verified_at": "2026-07-24"      // 可选: 核验日期
  },
  {
    "anime_id": ...
  }
]
```

## 导入步骤

1. 放入 JSON 文件：`knowledge_base/raw/anitabi_crawl.json`
2. 运行知识库构建管道：
   ```bash
   python -m data_factory.build_kb
   ```
3. 系统会自动清洗、校验并生成紧凑的 `knowledge_base/index.json` 与
   SQLite/FTS 运行时索引 `knowledge_base/animeway.sqlite3`。
