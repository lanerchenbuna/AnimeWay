# AnimeWay | 二次元圣地巡礼智能助手

AnimeWay 是一个面向动画圣地巡礼的 Streamlit 应用。它把 Bangumi 作品元数据、Anitabi 地理点位、DashScope/Qwen Agent、高德地图路线能力组合在一起，帮助用户从自然语言查询一路走到地点收藏、路线预览和 AI 路书生成。

当前版本重点优化了数据可靠性、检索质量、Agent 边界、路线规划和 UI 结构，让项目更适合持续迭代和 vibe coding。

## 核心能力

### 1. 统一 Agent 入口

`AnimeRagAgent.run()` 是 UI、CLI 和测试共用的入口。Agent 内部被拆成独立服务：

- `core/intent.py`：意图分类、LLM JSON 解析、schema fallback。
- `core/search.py`：作品搜索、点位搜索、地点/主题查询分流。
- `core/guide.py`：RAG 回答和推荐列表生成。
- `core/planner.py`：SEARCH / GUIDE / RECOMMEND / CHAT 编排。

这样 LLM 只负责理解和表达，确定性检索与状态流转由代码处理。

### 2. 可靠数据管线

数据层从运行时临时 join 改为可复现的标准索引：

- `data_factory/crawler.py` 支持增量爬取、断点续传和状态文件。
- `knowledge_base/raw/crawl_state.json` 记录成功、404、失败和重试次数。
- 点位 ID 使用稳定 SHA1，不再依赖 Python `hash()`。
- `data_factory/build_kb.py` 生成标准化 `knowledge_base/index.json`。
- `data_factory/schema.py` 使用 Pydantic 校验数据结构。

当前索引统计：

- 作品：7966
- 有圣地数据的作品：906
- 有效点位：23248
- 缺城市字段点位：1164
- 缺图片点位：2356

### 3. 本地 BM25 检索

`core/retrieval.py` 提供两个明确入口：

- `search_anime(query)`：作品搜索。
- `search_spots(query)`：点位、城市、主题、场景搜索。

支持的查询示例：

- `少女歌剧`：优先返回有 96 个圣地的 TV 版。
- `孤独摇滚圣地`：返回下北泽相关点位。
- `京都有什么动画圣地`：返回京都点位，避免误把“東京都”当成京都。
- `咖啡店巡礼`：返回 cafe / 咖啡 / 喫茶相关点位。

可选本地缓存目录：

```bash
export ANIMEWAY_RETRIEVAL_CACHE_DIR="knowledge_base/vector_cache"
```

### 4. 路线规划与冒险之书

`core/route_planner.py` 负责路线规划：

- 没有 Amap Key 时也能生成离线预览路线。
- 有 Amap Key 时优先获取真实公交路线，失败后 fallback 到步行、驾车、离线直线距离。
- 地理编码和路线结果会缓存，减少 API 调用。
- TSP 只按直线距离排序，跨城市时会给出提醒。
- UI 会先展示结构化路线摘要，再调用 LLM 生成路书文案。

### 5. 组件化 UI

`app.py` 已降为装配层，实际界面拆到：

- `components/sidebar.py`：密钥输入和背包概览。
- `components/discover.py`：发现页、Agent 对话、候选作品、点位列表。
- `components/plan.py`：路线摘要、地图、相册、路书。
- `components/state.py`：session state、反馈、背包操作。
- `components/ui.py`：HTML 卡片和状态组件。

HTML 卡片会对外部数据做转义，降低 `unsafe_allow_html=True` 风险。

## 使用方式

### 1. 安装依赖

```bash
git clone https://github.com/lanerchenbuna/AnimeWay.git
cd AnimeWay
pip install -r requirements.txt
```

建议使用 Python 3.10+。

### 2. 配置服务 Key

可以在应用侧边栏输入：

- DashScope Key：用于意图分类、推荐和路书生成。
- 高德地图 Key：用于出发地解析和真实路线规划。

也可以通过环境变量设置 DashScope：

```bash
export DASHSCOPE_API_KEY="sk-your-api-key"
```

### 3. 构建知识库索引

仓库已包含可用数据。更新 raw 数据后，重新构建索引：

```bash
python data_factory/build_kb.py
```

增量同步 Anitabi 点位：

```bash
python data_factory/crawler.py
python data_factory/build_kb.py
```

### 4. 启动应用

```bash
streamlit run app.py
```

默认访问：

```text
http://localhost:8501
```

## 应用流程

### 圣地观测

在发现页输入自然语言：

- `孤独摇滚圣地`
- `京都有什么动画圣地`
- `咖啡店巡礼`
- `推荐几部适合夏天巡礼的动画`

系统会根据意图返回作品候选、点位结果或 Agent 回答。选择作品后可以展开该作品的所有点位，并加入巡礼背包。

### 冒险之书

在计划页管理背包地点：

1. 可选输入出发地。
2. 选择是否启用 TSP 排序。
3. 生成路线预览。
4. 查看结构化摘要、分段明细、地图和相册。
5. 配置 DashScope Key 后生成 AI 路书。

没有 Amap Key 时仍可生成离线预览路线。

## 项目结构

```text
app.py                         # Streamlit 装配入口
components/
  discover.py                  # 发现页
  plan.py                      # 计划页
  sidebar.py                   # 侧边栏
  state.py                     # session state 和 UI 动作
  ui.py                        # HTML/UI helper
core/
  agent.py                     # Agent 装配入口
  intent.py                    # 意图服务
  search.py                    # 搜索服务
  guide.py                     # 回答/推荐服务
  planner.py                   # Agent 编排
  retrieval.py                 # 本地 BM25 检索
  route_planner.py             # 路线规划
data_factory/
  crawler.py                   # Anitabi 增量爬虫
  build_kb.py                  # 知识库索引构建
  schema.py                    # Pydantic schema
knowledge_base/
  index.json                   # 标准化知识库索引
  raw/                         # 原始数据和爬取状态
utils/
  amap.py                      # 高德地图 API
  ali_ai.py                    # DashScope 路书/推荐辅助
tests/                         # 回归测试
```

## 验证

运行测试：

```bash
python -m pytest -q
```

当前覆盖：

- Phase 2 检索验收。
- Phase 3 Agent 统一入口。
- Phase 4 路线规划。
- UI HTML 转义安全。

## License

MIT
