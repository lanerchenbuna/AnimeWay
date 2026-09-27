# 部署与维护

本文描述当前应用的运行配置、私人数据、备份、付费服务与本地维护命令。请从项目根目录执行命令；示例路径和域名需要替换为实际部署值。

## 服务与持久目录

先用无 Key 配置验证基础流程。以下示例仅绑定本机，私人文件写入指定目录：

```bash
export ANIMEWAY_DATA_DIR=/absolute/path/to/animeway-data
uv sync --frozen
uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --server.maxUploadSize 16 --browser.gatherUsageStats false
```

数据目录必须可写并在服务重启、容器重建后保留。公开服务需要部署方配置可达地址、TLS 和 Streamlit WebSocket 转发；设置 `ANIMEWAY_PUBLIC_URL` 为实际站点根 URL 后，页面才会生成绝对分享链接。不要将私人目录配置为静态资源目录。

| 数据 | 默认位置／范围 |
|---|---|
| 私人身份、愿望、手册、Trip、记录、照片、分享、额度与审核 | `ANIMEWAY_DATA_DIR/private.sqlite3`；未设置目录时使用项目 `.animeway` |
| SQLite WAL／共享内存 | 数据库旁的 `-wal`、`-shm` 文件，由 SQLite 管理 |
| 原有路线缓存 | `ANIMEWAY_ROUTE_CACHE_PATH`，或显式数据目录下 `route_cache.sqlite3`；未设置时使用系统临时目录的 `animeway` 子目录 |
| 用户主动提交的旧 AI 反馈 | 显式数据目录或系统临时目录的 `animeway` 子目录，JSONL 文件 |
| 全库检索 | 优先 `ANIMEWAY_SNAPSHOT_DIR` 成对快照；兼容 `ANIMEWAY_INDEX_DB`，运行时只读，优先级见末节 |
| 东京基础内容 | `knowledge_base/pilot/tokyo.json`；审核后的覆盖变更保存在私人数据库中 |

应用目前以 SQLite 持久目录为基础；不要为多个实例各放一份私人库，再承诺统一身份、分享状态或全局额度。当前仓库不提供多实例同步方案。

## 身份、备份与升级

匿名身份是保存在浏览器本地的随机凭据；服务端保存摘要。知道行程 ID 或地点 ID 不足以访问他人数据。清除浏览器存储后，需要用户事先下载的备份；站点 URL、浏览器隔离模式和存储权限变化也可能影响身份恢复。

用户备份有两种，不能互相替代：

| 入口 | 格式与内容 | 恢复行为 |
|---|---|---|
| 备份与反馈 | JSON v2，最大 5 MiB；愿望、手册、个人 Trip、最近 20 个规划历史、当天记录；兼容旧 v1 | 创建独立副本，保留个人取舍；同内容重复导入不重复新增 |
| 我的巡礼记录 → 记录备份 | JSON v1，最大 16 MiB；足迹、短文、压缩照片、偏好与删除来源标记 | 创建新 ID，解除旧 Trip 关联，照片恢复为私密，不继承统计同意 |

两者均不含身份凭据、服务 Key、后台队列和公开分享权限；没有跨设备编辑同步。导出的旅行日期、住宿信息与照片仍是用户私人内容，应由用户自行保管。

**服务端备份需要完整数据库。** 用户 JSON 无法恢复原身份、审核覆盖变更或公开分享。升级前使用 SQLite 一致备份，或停服并确认事务完成后保存完整数据库状态；不要在运行时只复制主文件而忽略 WAL。

有 SQLite 命令行工具时，可向一个全新的备份路径执行在线备份，例如：

```bash
sqlite3 /absolute/path/to/animeway-data/private.sqlite3 ".backup '/absolute/path/to/backups/private-before-upgrade.sqlite3'"
sqlite3 /absolute/path/to/backups/private-before-upgrade.sqlite3 'PRAGMA integrity_check;'
```

目标目录须事先存在；每次使用独立备份文件名。`integrity_check` 返回 `ok` 只证明数据库结构检查通过，还应在隔离目录验证行程、照片、身份和分享状态。部署方需自行配置自动备份、访问权限及保留周期，应用未内置备份调度。

私人库当前 `PRAGMA user_version=2`，记录模块使用 `journal_schema=1`。初始化和已支持的升级在事务中执行；未知版本或损坏库报错，不自动重建。回退应用时同时使用兼容的升级前数据库备份，保留升级后文件，不能假设旧程序支持新数据。

## 照片、分享与统计

每个身份最多 500 条足迹、50 张照片，同时受 16 MiB 记录备份容量限制。照片输入限 JPEG／PNG／WebP、8 MiB、2000 万像素；方向纠正后压缩为最长边 1600 像素以内、最多 600,000 字节的 JPEG，去除 EXIF／GPS，不保存原文件名。数据库按 owner 隔离图片，页面不创建可转发的私人图片静态地址。

分享使用独立随机 ID。发布前会重新检查 Trip 版本、选中图片内容与授权，公开字段使用白名单。默认排除具体旅行日期、住宿和私人笔记；标题、短文和画面可能含用户主动输入的信息，发布者需要检查预览。

改变照片使用范围、替换／删除照片、撤销关联到访，会撤下引用这些照片的分享。删除 Trip 会撤下关联路线分享，独立足迹仍保留。撤下阻止后续请求，不会清除别人已经保存的内容。SQLite 逻辑删除也不等于擦除历史页或外部备份，部署方需要说明并执行实际保留周期。

新增记录／分享／再次发现统计经用户同意后才写入，撤回时删除该身份的新统计。旧手册浏览、收藏、采用等 `events` 不受此开关控制；旧 AI 点赞／点踩也有独立反馈文件，不应将此开关描述为关闭全部数据记录。匿名浏览器数不是实际人数，开始行程不表示完成或到访。

## AI 配额与发送内容

自然语言路书、个人 Trip 需求整理与局部修改共用 `core/trip_ai.py` 的配额账本，通过 `core/qwen.py` 调用 DashScope OpenAI 兼容接口，默认模型为 `qwen-turbo`。API Key 默认按北京地域兼容入口发送；地域 Key 不匹配时需用 `DASHSCOPE_COMPATIBLE_BASE_URL` 指向 Key 所属地域的完整 `/compatible-mode/v1` Base URL。仅配置 `DASHSCOPE_API_KEY` 和调用次数上限即可启用：

| 环境变量 | 默认值 | 含义 |
|---|---:|---|
| `ANIMEWAY_TRIP_AI_DAILY_CALLS` | 20 | 数据库内全部身份每天调用上限 |
| `ANIMEWAY_TRIP_AI_BROWSER_CALLS` | 3 | 单身份每天调用上限 |
| `ANIMEWAY_TRIP_AI_DAILY_MICROCNY` | 0 | 可选：每天可预留总金额 |
| `ANIMEWAY_TRIP_AI_CALL_MICROCNY` | 0 | 可选：每次调用预留金额 |

金额单位为百万分之一人民币元，`100000` 表示 ¥0.10，不代表模型价格。维护者应按实际模型、地区与计费方式设置保守单次预留，并配置供应商侧消费控制；账本是预留值，不是已核实账单。

计数按日本自然日，调用前在同一事务内预留全局与个人额度。金额预算两项均为 0 时仅限制次数；这不是消费金额上限。失败、超时或后续语义校验不通过仍占用额度，不自动重试。输入最多 2,000 字，上下文最多 24,000 字节，输出最多 1,200 token，连接／读取超时为 5／20 秒。

- 东京路书发送用户主动输入的描述、日本今天日期、试点作品和可选地点白名单；用户自己写入的个人信息会随请求发送。模型只返回选点与日程结构，代码会二次校验作品关联、访问状态、日期和地点 ID。
- 需求整理发送用户主动输入的文本、日期上下文和有限作品信息；文本中用户自己写入的个人信息会随请求发送。
- Trip 修改发送有限的站点、日期／时间、候选名称、已处理状态和当前指令，不发送完整历史、匿名凭据或住宿坐标。
- 记录整理只重排程序生成的已确认短句；再次发现只选择有效候选。不发送照片或私人笔记。
- AI 提案经过字段、对象、锁定和已执行内容检查，确认后才能写入；AI 不能发布分享、生成到访或改写交通事实。

Qwen 自然语言路书入口使用 `ANIMEWAY_TRIP_AI_DAILY_CALLS` 与 `ANIMEWAY_TRIP_AI_BROWSER_CALLS` 计数。其它旧版搜索、问答和建议仍走兼容入口，公开部署应在边缘代理配置调用限额和消费提醒。`AMAP_API_KEY` 用于真实路线段；东京坐标走高德海外路线域名，Key 需由高德开通海外 Web 服务权限。海外公交是否返回路线取决于高德当前服务范围；无结果时应用显式回退为直线估算并标注，不能当作导航。

## 内容纠错与审核

管理脚本只供有数据库访问权的维护者本地执行，不应暴露为无鉴权网页接口。

旧地点纠错队列：

```bash
uv run python scripts/review_corrections.py --db /path/to/private.sqlite3 list --status pending
uv run python scripts/review_corrections.py --db /path/to/private.sqlite3 stats
uv run python scripts/review_corrections.py --db /path/to/private.sqlite3 set CORRECTION_ID --status needs_info --note '请补充公开来源'
```

该流程只更新反馈状态，不直接修改公共事实。需要改动内容时，通过新投稿审核流程处理，并在说明中关联原问题编号。

新投稿与邀请：

```bash
uv run python scripts/review_community.py --db /path/to/private.sqlite3 queue
uv run python scripts/review_community.py --db /path/to/private.sqlite3 stats
uv run python scripts/review_community.py --db /path/to/private.sqlite3 invite --reviewer '实际维护者'
uv run python scripts/review_community.py --db /path/to/private.sqlite3 review CONTRIBUTION_ID --status needs_info --reviewer '实际维护者' --minutes 5 --note '请补充公开来源和观察日期'
uv run python scripts/review_community.py --db /path/to/private.sqlite3 review CONTRIBUTION_ID --status accepted --reviewer '实际维护者' --minutes 12 --note '审核后的公开变更说明' --patch /path/to/reviewed-patch.json
uv run python scripts/review_community.py --db /path/to/private.sqlite3 withdraw EDIT_ID --reviewer '实际维护者' --note '撤回原因'
```

邀请码默认单次兑换、14 天有效；只交给受邀者，不写入公开文档。已有地点纠错不要求邀请，新增地点需要有效邀请。默认待处理门槛 20，可设置 `ANIMEWAY_CONTRIBUTION_QUEUE_LIMIT=0` 暂停新增；单身份待处理硬上限 10，全队列 200。

patch 必须由维护者核验后构造，不自动采纳用户 proposal。可更新名称、坐标、片区、作品关联、来源、访问说明、入口、机位及撤下状态，具体字段校验见 [contributions.py](../core/contributions.py)。采纳会保留前后版本并产生通知；撤回按同一对象最新变更逆序执行。说明可能展示给投稿者和关注用户，勿包含私人信息。

活动仅由维护者用 `activity --file /path/to/reviewed-activity.json --reviewer '实际维护者' --minutes 10` 登记，需自行确认官方来源、起止日期和核查日期。URL 格式有效不代表事实已自动核验。界面按旅行日期与资料新鲜度筛选，不承诺库存、预约或实时营业。

## 常见问题

| 现象 | 排查方式 |
|---|---|
| 重启后找不到清单 | 检查持久目录是否变化、磁盘是否被重建、是否换浏览器或站点地址；不要删除原库 |
| 私人库读取失败 | 保留原文件和 WAL，检查目录权限、磁盘与版本兼容；不要通过重建空库掩盖错误 |
| AI 按钮不可用 | 检查 Key、四项配额和当日使用量；额度不足不影响人工编辑 |
| 分享只有相对链接 | 配置实际 `ANIMEWAY_PUBLIC_URL`，或打开相对链接后复制浏览器地址 |
| 备份超限 | 先导出备份再整理不需要的记录／照片；两个备份入口各自受限 |
| 旧手册坐标与详情不同 | 已保存手册可能保留旧坐标；出发前查看当前地点详情并重新核对导航 |

## 公开地图快照、刷新与回退

公开数据发布流程的运行环境为支持 `fcntl.flock` 的 POSIX（当前验证为 macOS，CI 为 Linux）。`knowledge_base/releases/` 是生成物，已加入 Git 忽略；部署时应使用独立、持久、仅维护进程可写的公开快照目录，与私人目录分开。

### 首次构建与运行

以下示例在临时目录验证，不更新仓库自带的 v2 JSON／SQLite：

```bash
uv run python -m data_factory.release --root /tmp/animeway-public-snapshots --offline
export ANIMEWAY_SNAPSHOT_DIR=/tmp/animeway-public-snapshots
uv run streamlit run app.py
```

`--offline` 首次使用保存的原始快照；后续重建使用该发布目录当前版本的原始数据和状态，保留已发布的刷新结果。它不代表获取了新内容。`python -m data_factory.build_kb` 的写入入口也已改走成对发布，默认目录 `knowledge_base/releases/`；建议维护时使用显式 `--root` 的 release 命令。

检索运行时优先级：显式 `ANIMEWAY_SNAPSHOT_DIR` → 显式 `ANIMEWAY_INDEX_DB` → 检测到的 `knowledge_base/releases/current.json` → 仓库旧 SQLite／JSON。快照模式下不会混用旧 JSON 与新 SQLite；两份候选均校验失败时显式报错。地图查询使用 `MapQueryService.from_snapshot()`；旧 v2 SQLite 没有空间表，需要先生成新快照。地图 UI 已接入，未配置全库快照时显示明确标注的东京精选。应用壳在显式快照不可用时也可显示东京精选降级提示；这不代表原快照有效，也不混用旧散文件冒充全库。

### 刷新、审阅、发布

```bash
uv run python -m data_factory.crawler --snapshot-root /tmp/animeway-public-snapshots --refresh --subject 328609 --candidate /tmp/animeway-sync-candidate.json
uv run python -m data_factory.release --root /tmp/animeway-public-snapshots --bundle /tmp/animeway-sync-candidate.json
```

`--subject` 可重复。没有 `--refresh` 时只尝试未完成、尚未达到三轮状态重试上限的作品；显式刷新可以重新检查 success/no_spots/not_found 和已达上限的作品。HTTP 请求本身最多尝试三次，429/5xx/网络错误退避。上游 lite 只作元数据／总数核对，点位必须取 detail。

候选 JSON 同时包含 raw、state、report。输出路径已存在则拒绝，重新尝试请换新文件名；失败候选留作审阅记录，不影响当前发布快照。维护者可以通过 `refresh_subjects(..., state=上次候选状态)` 保留失败尝试计数；CLI 默认以当前已发布状态为起点，每个失败候选的尝试记录独立保存。部分成功、未知删除、源 ID 改变、无效点位、详情数量不符或数量下降超过 20% 均阻止整批发布。

查看候选 report.works 的 added/modified/deleted/migrations/unresolved_deleted/legacy_conflicts。确有来源证据时，创建审阅文件，重新抓取候选：

```json
{
  "schema_version": 1,
  "reviewed_by": "实际审阅者",
  "reason": "对应的来源核对记录或工单",
  "migrations": [{"work_id": "328609", "old_id": "旧源ID", "new_id": "新源ID"}],
  "deletions": [],
  "allow_large_drop_work_ids": []
}
```

```bash
uv run python -m data_factory.crawler --snapshot-root /tmp/animeway-public-snapshots --refresh --subject 328609 --review /path/to/review.json --candidate /tmp/animeway-reviewed-candidate.json
```

迁移必须同作品、一对一、旧 ID 确实被移除且新 ID 确实新增；名称相同和坐标接近不是对应证据。批准删除用 `deletions: [{"work_id":"...","point_id":"..."}]`；超过 20% 的下降还要列入 `allow_large_drop_work_ids`。已删除地点仍有撤下记录供旧引用解析，默认查询不推荐。发布器拒绝基线已变化的旧候选，必须针对新的当前版本重新生成。

### 成对发布与回退

每个不可变版本目录有 `index.json`、`animeway.sqlite3`、`catalog.json`、`raw.json`、`state.json`、`sync-report.json`、`manifest.json`。manifest 绑定 schema、来源、计数、内容校验和及六个数据文件的 SHA256。单写入锁 → 候选构建 → 完整性／外键校验 → 文件与目录 fsync → 原子切换 current.json；SQLite 完成而 JSON 失败时不会切换版本。

```bash
uv run python -m data_factory.release --root /tmp/animeway-public-snapshots --rollback
```

current.json 保存当前和上一版本。回退前校验目标版本；当前版本校验失败时，新读取者会整对选择上一有效版本，`resolve_snapshot()` 返回 fallback_reasons。读服务实例固定其打开时的版本，发布后需重建服务实例／清理应用相应缓存以采用新版本；不要在一个请求内分别解析 JSON 和 SQLite 的当前版本。

中断可能留下 `.staging-*` 或未被指针引用的版本，运行时不会读取。目前没有自动清理器；清理时须确认版本不被 current.json 引用，并确保已固定旧版本的读进程退出。不要直接修改已发布文件，不要删除仍在使用的版本。快照目录不包含用户照片、身份或私人数据库。

## 地图页面与运行边界

- 「地图探索」是第四标签；默认无需在线 API／AI Key。未配置全库快照时使用东京精选临时公共索引；配置有效 `ANIMEWAY_SNAPSHOT_DIR` 后显示全库范围说明，从东京视野开始浏览。
- 地图单次最多发送 500 点或聚合，作品页 24 场景／页，聚合文字入口 20 个／页。底图关闭或失败不会阻止文字浏览和收藏。
- `ANIMEWAY_MAP_ENABLED=0` 并重启：恢复原三个入口；不清空任何私人资料。默认值为 `1`。
- 地图实例每轮读取有效快照版本；旧检索资源按发布指针内容和配置缓存，指针切换时重建当前会话的检索 agent。只修复已发布文件、未改变指针的非正常操作应重启服务；正常发布应始终使用不可变版本流程。
- OSM 仅浏览器请求当前视野瓦片、遵循 HTTP 缓存并发送 Referer；不要预取、批量下载瓦片或制作整城离线包。

### 在线 Anitabi 刷新

在线内容刷新是维护者显式操作，不能由应用启动或定时任务自动触发。上游 API 曾出现限流和详情缺少坐标字段；可用性及响应结构须以实际候选报告为准。缺少坐标的记录只能保留已核验的本地坐标，不按名称或距离猜测补点；无法匹配的来源 ID、删除和数量异常均阻止直接发布。

```bash
uv run python -m data_factory.sync --refresh --subject 265 --subject 328609 --candidate /tmp/candidate.json
```

保持 TLS 验证，不破解挑战、不伪造浏览器指纹；`ANIMEWAY_ANITABI_PROXY` 仅用于已有授权的 HTTP(S) 代理，凭据不得进入仓库。候选仍需人工核对来源、署名、数量变化与图片权限，再按成对快照流程发布。上游字段及使用要求见 [Anitabi 开放 API 文档](https://navi.anitabi.cn/docs/api/)。

## Trip、记录与恢复

- 运行前 `uv sync --frozen`，使用锁定依赖；原生受控标签需要最低 1.60。修改业务模块后重启服务，避免热重载混用旧模块。
- 无私人 schema 迁移；原 Trip／记录／照片继续存储在 `ANIMEWAY_DATA_DIR`。不要用公开索引目录替代私人目录，也不要重建用户库。
- 备份操作：上传 →「预览恢复内容与地点冲突」→ 阅读缺失／更新／收藏冲突 → 勾选确认 → 恢复。文件或事实变化需重新预览；容量、身份、重复导入在最终事务中再次校验。恢复照片默认 private，公开链接不恢复。
- 分享读取每次检查当前访问事实，关闭／撤下／缺失时不可用；私人历史保留。存储层直接调用未传 catalog 时也检查配置的公开快照，无法解析即停止分享读取。人工编辑不得覆盖系统撤下。
- `ANIMEWAY_MAP_ENABLED=0` 只隐藏地图入口，不删除私人数据；手册和记录仍可用。地点投影与恢复预览仍生效。需要应用回退时先保留私人备份，公共版本按前述成对快照流程回退；无需私人数据库降级。

## 发布候选、故障处置与维护

当前尚无真实手机、素材权利、真实用户任务和东京现场试走的验收材料，不能标记为 `release_ready`。公开发布前，维护者需保存可复核的设备、权利、用户与现场记录，并逐项确认适用范围。

### 候选发布前

1. 固定应用提交、锁文件、东京精选版本和要发布的 `manifest.json`／`current.json`。应用和公开索引 schema 应成对兼容；`ANIMEWAY_SNAPSHOT_DIR` 指向持久、仅维护进程可写的公开目录，`ANIMEWAY_DATA_DIR` 指向**另一**持久私人目录。
2. 在隔离实例完成源码静态检查、离线公开快照构建、应用启动及主要入口的人工浏览器检查，保存实际执行记录。随后在真实目标设备上验证地图／文字列表、愿望、Trip、记录、备份恢复和分享撤下。当前仓库不附带阶段验收脚本与历史报告，不能据此声称已完成真机验收。
3. 在实际部署的私人库上做 SQLite **一致备份**，保留访问控制和恢复点；用隔离副本验证身份、愿望、Trip、记录、照片及分享撤下状态。用户导出的两种 JSON 备份不代替服务器备份。当前私人 schema 未迁移，应用回退仍须确认所选应用版本与当前库版本兼容。
4. 对部署候选人工复核来源、署名、访问说明、核查日期、图片权利及候选报告中列出的源身份冲突键。没有许可的原作截图只提供来源链接，不在地图或分享中嵌入。线上刷新或发布新内容须重新走候选审阅，不能凭离线重建日期声称资料更新。

### 发布及回退顺序

先在试点实例打开地图入口，核对公开快照 `resolve_snapshot()` 的有效版本、作品／地点／场景数量、地图与文字列表、愿望、Trip、记录及权限；然后才逐步扩大访问。保留上个**应用版本、锁文件、公开快照目录版本和私人库一致备份**，并记录操作人、时间、版本与验证结果。新版本下发现来源错配、读写失败或明显延迟时，先停止扩大访问。

- **地图组件或瓦片故障：** 设置 `ANIMEWAY_MAP_ENABLED=0` 后重启，验证原三个入口、私人清单和记录仍可用。若只是瓦片不可用，地图页本身的文字列表、地点来源和外部导航仍应可走；不要因此清空私人目录。
- **公开索引故障：** 在确认目标旧版本与应用兼容后，对同一 `ANIMEWAY_SNAPSHOT_DIR` 执行 `uv run python -m data_factory.release --root /absolute/path/to/public-snapshots --rollback`；用 `resolve_snapshot()` 复核整对 JSON／SQLite 与 manifest，再重启应用或使读服务重建。回退只切换公开指针，不删除新版本或私人数据。若无有效前版，保持地图关闭并保留错误现场。
- **应用或私人库故障：** 停止写入，保存当前库及 WAL／日志，选兼容应用版本。只有确认需要恢复数据库时，才从升级前的一致备份恢复到**新的隔离目录**并验证身份、Trip、照片和分享撤下，再按部署方流程切换；不要直接把旧主文件覆盖正在使用的库。当前没有自动生产恢复流程；演练结果不代表生产恢复已执行。

### 运行观察和例行维护

当前应用没有集中式生产指标管道。试点维护者应在发布记录中按固定时间窗记录：地图视野查询 P95、聚合／超限请求比例、空结果与缺失地点数、公开快照 fallback 原因、来源／图片加载错误、收藏与 Trip 写入错误；同时注明样本数、设备、快照版本和采集方法。隔离样本不能称为真实流量 SLA。不得在日志中写匿名身份 token、私人照片或完整行程；行为统计仍须遵循用户同意边界。没有日志或外部监测来源的项目记为“未观测”，不能填零。

每次内容刷新先看候选报告中的失败、数量下降、ID 迁移／删除、身份冲突及素材策略，再发布不可变成对快照。每次应用改动至少重跑 CI 检查及与改动相关的实际浏览器流程；定期检查 SQLite 一致备份可读、磁盘余量、公开快照 manifest 与回退版本，不自动删除仍被读进程引用的旧版本。线上 Anitabi 的历史诊断边界见上节；没有明确维护计划时，不要自行批量刷新在线内容。
