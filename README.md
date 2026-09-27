<div align="center">

<p><code>ANIME PILGRIMAGE NAVIGATOR · 聖地巡礼</code></p>

# AnimeWay · 二次元圣地巡礼智能体

### 穿过次元壁，抵达故事发生的地方。

**从一句喜欢的作品，到一条真实可走的巡礼路线。**<br>
Turn anime memories into a journey you can actually take.<br>
物語の景色を、ほんとうの旅へ。

<br>

<img src="assets/images/animeway-hero.webp" width="100%" alt="AnimeWay 二次元圣地巡礼主视觉">

<br><br>

![Python 3.10–3.13](https://img.shields.io/badge/Python-3.10--3.13-68E1FD?style=flat-square&labelColor=111630)
![Streamlit](https://img.shields.io/badge/Streamlit-App-FF70A6?style=flat-square&labelColor=111630)
![Local search](https://img.shields.io/badge/Local_Search-No_AI_Key-69F0AE?style=flat-square&labelColor=111630)
![Code License](https://img.shields.io/badge/Code_License-MIT-9B7BFF?style=flat-square&labelColor=111630)

</div>


AnimeWay 将作品检索、可信地点资料、Qwen 行程理解和高德路线查询接成一条使用路径：从一句旅行想法生成可核查的东京巡礼路书，再保存为个人 Trip，并在旅行后留下记录。

**当前版本：v0.10 开发版。** 全库搜索可用；手册与个人 Trip 聚焦东京的《孤独摇滚！》TV 第一期和《你的名字。》2016 年剧场版。日本实时公交／铁路、真实用户任务和现场试走尚未完成验收，行程以可编辑草案提供。

[快速开始](#快速开始) · [界面演示](#界面演示) · [功能与使用流程](#功能与使用流程) · [配置](#配置) · [保存与分享](#保存与分享) · [部署与维护](docs/operations.md)

## 快速开始

需要 **Python 3.10–3.13**。在项目根目录运行，推荐使用 [uv](https://docs.astral.sh/uv/) 和仓库中的锁文件：

```bash
git clone https://github.com/lanerchenbuna/AnimeWay.git
cd AnimeWay
uv sync --frozen
uv run streamlit run app.py
```

打开 **http://localhost:8501**。首页「智能巡礼」可以搜索作品和地点，也可以输入旅行想法生成路书。要启用 AI 规划，在左侧填写 DashScope / Qwen Key；高德 Web 服务 Key 用于查询在线路线。东京的高德在线路线还要求该 Key 开通海外 Web 服务权限；不可用时应用会显式标注离线估算。

第一次使用可以按以下顺序操作：

1. 在侧栏输入 DashScope / Qwen Key 和高德 Web 服务 Key；Key 留在本机浏览器会话，不要发到聊天里。
2. 在「智能巡礼」输入自然语言，例如“帮我规划东京《孤独摇滚！》一日轻松巡礼路书”。
3. 检查地点来源、访问状态和可展示的场景图，并区分高德在线路线与离线估算。
4. 保存草案为个人 Trip，在「手册与 Trip」继续编辑时间、必去点、起终点和停留安排。
5. 出发前下载清单；当天主动记录到访或跳过，旅行后整理照片与短文。

也可以使用 pip；该方式按版本范围安装，不保证与锁文件完全相同：

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell 使用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 界面演示

下面的动图记录了**无需 Key** 的真实本地流程：打开智能巡礼、搜索作品、切换到地点列表、查看地点详情。AI 路书需要你自己的 Qwen Key；东京在线路线还需要已开通海外权限的高德 Key。

<img src="docs/media/animeway-flow.gif" width="100%" alt="AnimeWay 智能巡礼、作品搜索、地点列表与详情操作演示">

| 智能巡礼首页 | 作品搜索结果 |
|---|---|
| ![智能巡礼首页，展示服务状态和示例需求](docs/media/agent-home.webp) | ![搜索孤独摇滚后的候选作品](docs/media/work-search.webp) |

| 地点列表 | 地点详情 |
|---|---|
| ![地图探索的地点列表与来源入口](docs/media/place-list.webp) | ![地点详情、访问状态和 Trip 入口](docs/media/place-detail.webp) |

<p align="center"><img src="docs/media/mobile-home.webp" width="270" alt="手机宽度的智能巡礼首页"><br><small>手机首屏；侧栏可按需展开填写 Key。</small></p>

作品封面由 Bangumi 实时提供，权利属于各自权利人；截图用于说明界面。东京精选中尚无完整逐图署名和展示权限的场景只提供来源链接，避免显示破图或将来源不明的图片打包进仓库。

## 功能与使用流程

| 阶段 | 当前能力 |
|---|---|
| 智能路书 | Qwen 从东京试点的可信地点候选中理解作品／日期／节奏并安排日程；本地再按片区和近邻距离优化站点顺序 |
| 发现 | 按作品、城市、地点或主题搜索；东京精选内容支持作品／目的地入口和地图／列表选择 |
| 选择手册 | 查看场景依据、访问说明、来源、核心／可选站点；保存个人副本并删除可选站 |
| 筹备 Trip | 东京同一目的地 1—3 日需求卡，最多两份候选草案，时间、体力与访问条件检查 |
| 局部修改 | 增删、替换、排序、修改停留与锁定；恢复最近 20 个规划版本，检查并发修改冲突 |
| 当天使用 | 查看站点、当地名称与外部导航；记录到访、跳过、临时关闭、迟到或提前结束 |
| 旅行记录 | 私密足迹、短文、本人照片与场景配对；可从 Trip 显式导入已确认到访 |
| 分享 | 预览后发布独立路线副本，可撤下；他人可复制为自己的 Trip |
| 再次发现 | 关注作品／目的地，查看相关内容更新，依据收藏与确认到访获得候选，标记不感兴趣 |
| 内容维护 | 提交地点纠错；新增地点采用邀请制，维护者本地审核、发布或撤回事实变更 |

### 手册、个人 Trip 与临时背包

- **手册副本**保留选择的站点与编辑建议，适合短线参考。模板更新不会覆盖个人取舍；删除可选站后，连接改为待核查。
- **个人 Trip**增加日期、每天可用时间、起终点、必去／不感兴趣、交通偏好、步行预算、用餐、休息和余量。时间按 `Asia/Tokyo` 处理，天数包含抵达日；仅输入住宿名称不会自动定位。
- **临时背包**保留在「圣地观测／冒险之书」，最多 12 个点，可生成原有路线预览，也可显式转存长期愿望清单。

当天记录与规划历史独立：跳过不算到访；撤销规划不会撤销已发生的现场记录；局部编辑保留已执行部分。

### 原有全库搜索

在「智能巡礼」中可以尝试：

```text
孤独摇滚圣地
京都有什么动画圣地
咖啡店巡礼
推荐几部适合夏天巡礼的动画
```

SQLite／FTS 检索无需模型；缺乏相关证据时返回空结果。AI 推荐、问答和自然语言路书需要 DashScope Key。日本高德路线需启用海外权限；不可用时仍可使用本地地点候选和清楚标注的离线估算。

## 数据与交通范围

| 数据层 | 当前规模 | 使用边界 |
|---|---|---|
| 全库索引 | 7,966 部作品元数据；906 部有点位；23,173 条作品点位记录 | 并非全库去重后的现实地点数，也非全部核验通过 |
| 东京精选 | 2 部作品、70 个归并地点、76 个场景关联、3 条短手册 | 大部分是基础发现记录；四谷短线完成限定范围桌面资料核查，其余两条仍为原型 |

精选内容独立于上游索引，按稳定地点 ID 归并多个场景，并为旧搜索接入已知地点修正。来源、访问状态和未知信息随内容记录保留。结构与维护原则见 [东京内容说明](knowledge_base/pilot/README.md)。

个人 Trip 的步行时间采用**直线距离 × 1.35、按 65 米／分钟估算**，不是真实街道路由；超过短途范围保留未知。公交／铁路尚未通过试点核验时不推测班次与票价、不改用驾车。未知费用不按零元处理，估算不能保证赶上预约、关门时间或末班车。

AI 不得生成或改写坐标、交通分钟、费用、开放时间和到访事实。原有高德路线预览与新 Trip 的能力范围不同，服务配置见 [部署与维护](docs/operations.md)。

## 配置

应用读取进程环境变量；不会自动加载 `.env` 文件。Key 也可以在侧栏输入，仅用于当前会话；请勿提交 Key、私人数据库或个人备份。

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `ANIMEWAY_DATA_DIR` | 私人数据使用项目下 `.animeway` | 私人数据库的持久目录；显式设置时也用于默认路线缓存与反馈文件 |
| `ANIMEWAY_PUBLIC_URL` | 未设置 | 站点根地址，用于生成绝对分享链接；例如 `https://animeway.example.com` |
| `DASHSCOPE_API_KEY` | 未设置 | Qwen Agent、需求理解与图文路书；也可在侧栏输入 |
| `DASHSCOPE_COMPATIBLE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DashScope OpenAI 兼容入口；按 API Key 所属地域配置对应 URL |
| `ANIMEWAY_QWEN_MODEL` | `qwen-turbo` | Qwen 模型 ID |
| `AMAP_API_KEY` | 未设置 | 高德 Web 服务路线与地点解析；也可在侧栏输入 |
| `AMAP_OVERSEAS_API_BASE` | `https://sg-restapi.opnavi.com` | 日本海外步行／驾车路线服务域名；Key 必须获批海外权限 |
| `ANIMEWAY_INDEX_DB` | `knowledge_base/animeway.sqlite3` | 兼容旧全库检索索引路径 |
| `ANIMEWAY_SNAPSHOT_DIR` | 未设置 | 已校验的 JSON／SQLite 成对快照；显式设置时优先于 INDEX_DB |
| `ANIMEWAY_ROUTE_CACHE_PATH` | 显式数据目录或系统临时目录下的路线缓存 | 可单独指定旧路线缓存路径 |
| `ANIMEWAY_CONTRIBUTION_QUEUE_LIMIT` | `20` | 新地点投稿积压门槛；`0` 暂停接收新增地点 |

Agent 路书调用按日本自然日限制为每个浏览器身份最多 3 次、应用实例最多 20 次。费用由 DashScope 实际结算；AnimeWay 的调用次数限制不是消费金额上限。需要自定义内部预算时可设置：

| 环境变量 | 默认值 | 单位 |
|---|---:|---|
| `ANIMEWAY_TRIP_AI_DAILY_CALLS` | `20` | 全局每天调用次数 |
| `ANIMEWAY_TRIP_AI_BROWSER_CALLS` | `3` | 每匿名身份每天调用次数 |
| `ANIMEWAY_TRIP_AI_DAILY_MICROCNY` | `0` | 可选：内部每天预留金额，百万分之一人民币元 |
| `ANIMEWAY_TRIP_AI_CALL_MICROCNY` | `0` | 可选：内部每次预留金额，同上 |

AI Key 与调用次数上限即可启用；内部金额预算保持 0 表示不在应用内预留金额。失败请求也占用调用次数。模型请求内容、成本配置和公开部署注意事项见 [部署与维护](docs/operations.md)。

## 保存与分享

私人数据默认写入 `.animeway/private.sqlite3`。身份凭据保存在同一浏览器，服务端只存摘要；数据读写按匿名身份隔离。服务重启后恢复需要持久磁盘，清除浏览器数据或更换浏览器则需要用户自己的备份。

| 备份入口 | 包含内容 | 大小上限 |
|---|---|---:|
| 备份与反馈 | 愿望清单、手册副本、个人 Trip、规划历史、当天事件 | 5 MiB |
| 我的巡礼记录 → 记录备份 | 足迹、短文、压缩照片、场景配对、关注与不感兴趣 | 16 MiB |

恢复会创建独立副本，不提供跨设备自动同步。记录恢复后照片默认私密，解除旧 Trip 关联；备份不包含身份凭据、服务 Key、后台队列或公开分享权限。下载的文字清单可离线阅读，应用本身、外部导航与地图仍需网络。

照片支持 JPEG／PNG／WebP，原文件最多 8 MiB、2000 万像素；上传后重新编码并去除 EXIF／GPS。照片默认私密，只有声明有权分享并在具体预览中选中的图片才进入公开副本。

公开副本默认排除住宿、具体出行日期和私人笔记；自由输入的标题、短文和照片画面仍由发布者检查。撤下分享、删除关联 Trip、修改或删除引用照片后，新请求无法继续取得相应分享；已被他人保存的副本、截图和文件无法远程收回。

新增记录／分享／再次发现统计需明确同意，撤回会删除相应新统计。**该开关目前不覆盖旧手册的浏览、收藏和采用事件。** 详细存储范围、升级回退和审核命令见 [部署与维护](docs/operations.md)。

## 项目结构

```text
app.py                         Streamlit 应用入口
components/                    手册、Trip、记录、旧搜索和页面状态
core/                          检索、规划、持久化、AI、分享与审核规则
assets/                        样式、首页素材、地图与浏览器身份组件
docs/media/                    与当前界面一致的使用截图及动图
data_factory/                  数据抓取、规范化和 SQLite 索引构建
knowledge_base/                全库索引与东京精选内容
scripts/                       内容纠错与投稿审核命令
docs/operations.md             部署、备份、AI 配额和内容维护
```

## 仓库检查

仓库保留应用源码、运行所需的公开数据、依赖锁文件及维护文档。阶段验收材料、旧研究笔记和自动化测试已从当前工作树移除。合并代码前可运行以下静态检查与离线快照构建；它们只验证基本构建，不代替功能回归或真实使用验收。

```bash
uv sync --frozen --group dev
uv run ruff check .
uv run mypy
uv run python -m compileall -q app.py assets components core data_factory scripts utils
uv run python -m data_factory.release --root /tmp/animeway-public-snapshots --offline
```

公开地图索引使用候选校验与成对快照发布；可靠刷新、来源 ID 审阅、环境变量和回退命令见 [公开地图快照运维](docs/operations.md#公开地图快照刷新与回退)。默认「地图探索」显示东京精选；配置 `ANIMEWAY_SNAPSHOT_DIR` 后按视野浏览全库。支持拖动／缩放、键盘和文字列表、作品场景分页及愿望清单；`ANIMEWAY_MAP_ENABLED=0` 可隐藏地图入口。

## 当前限制

- **旅行能力**：自然语言 Agent 目前只规划东京试点 1—3 日路书；不支持任意跨城规划、内置导航、离线地图或预订。所有路线结果出发前仍需复核。
- **跨设备与恢复**：浏览器匿名身份不是账号；备份恢复是独立副本，未下载备份时不能仅凭行程 ID 找回清除的身份。
- **旧手册导航**：保存时坐标仍留作历史参考；当前坐标、关闭或撤下状态会在详情、导出和导航中重新解析，无法确认的地点停止到访导航。出发前仍应核对现场规则。
- **付费服务**：旧 AI 入口尚未统一限额，不能把新 Trip 的预算当成全站预算。公开部署可先保持服务端 Key 未配置。
- **语言**：旧搜索与手册框架支持中文／英文／日文；新 Trip、记录及精选编辑说明仍以中文和当地名称为主。

## English / 日本語

**English.** AnimeWay combines local anime-location search with a Qwen routebook agent, AMap route legs, private Tokyo trip drafts, travel journals and revocable route sharing. Browsing and local drafts work without keys; Qwen routebooks require a DashScope key, and live Tokyo routes require AMap overseas-service authorization. Data persists in the same browser identity when server storage is retained; JSON backups transfer independent copies. Field walks and real-user validation are not yet verified. New editors and editorial content are primarily Chinese.

**日本語。** AnimeWay は、アニメの舞台検索、東京の巡礼手帳、1〜3 日の個人旅程案、非公開の旅行記録、取り消し可能なルート共有を提供します。基本機能に AI キーは不要です。同じブラウザーとサーバーの永続ストレージで保存を続け、JSON バックアップで別ブラウザーに独立したコピーを復元できます。日本の公共交通、現地試歩、実ユーザー検証は未完了で、新しい編集画面と解説は主に中国語です。

## 数据来源与 License

项目代码采用 [MIT License](LICENSE)。仓库同时含有运行用公开数据；作品、点位、图片、地图与在线服务分别受原来源条款约束，不因代码开源而自动适用 MIT。将仓库改为公开可见或复用其数据前，维护者仍需逐项核对再发布范围与署名。

全库数据来源包括 [Bangumi](https://bgm.tv/) 与 [Anitabi](https://anitabi.cn/)；来源登记见 [原始数据说明](knowledge_base/raw/README.md)。Anitabi 的[开放 API 文档](https://navi.anitabi.cn/docs/api/)要求遵循 CC BY-NC-SA 4.0，并建议展示场景截图时同时标注 `origin` 文字与 `originURL` 链接；截图还可能有各自权利。东京精选场景未取得逐图展示依据时只提供原始来源跳转，不嵌入或打包未知权利素材；旧全库发现入口沿用上游封面与图片引用，相关权利需分别确认。地图底图显示 OpenStreetMap 署名并遵守其 [瓦片政策](https://operations.osmfoundation.org/policies/tiles/)，不提供瓦片预取或离线下载。

地点、开放规则、交通与费用可能变化。出发前请查看官方信息，尊重居民、店铺规则和拍摄礼仪。

## 公开部署前

地图地点可新建东京 1—3 日 Trip 或追加现有日程，收藏可直达安排入口；确认到访后可进入私密记录。备份恢复会先预览缺失地点和冲突，分享复制会检查当前草案。维护及故障回退步骤见 [部署与维护](docs/operations.md)。

真实 iOS／Android、素材权利、真实用户任务和东京现场试走尚无验收材料，因此当前版本仍是试点草案，不标 `release_ready`。地图故障时可关闭 `ANIMEWAY_MAP_ENABLED` 并使用其余入口；瓦片不可用时可用文字列表。
