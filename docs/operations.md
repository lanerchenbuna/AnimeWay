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
| 全库检索 | `ANIMEWAY_INDEX_DB`，默认 `knowledge_base/animeway.sqlite3`，运行时只读 |
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

新 Trip、短句整理和再次发现共用 `core/trip_ai.py` 的请求入口，当前模型为 `qwen-plus`。仅有 `DASHSCOPE_API_KEY` 不会启用这些功能，还需要下面四项为正整数：

| 环境变量 | 默认值 | 含义 |
|---|---:|---|
| `ANIMEWAY_TRIP_AI_DAILY_CALLS` | 0 | 数据库内全部身份每天调用上限 |
| `ANIMEWAY_TRIP_AI_BROWSER_CALLS` | 3 | 单身份每天调用上限 |
| `ANIMEWAY_TRIP_AI_DAILY_MICROCNY` | 0 | 每天可预留总金额 |
| `ANIMEWAY_TRIP_AI_CALL_MICROCNY` | 0 | 每次调用预留金额 |

金额单位为百万分之一人民币元，`100000` 表示 ¥0.10，不代表模型价格。维护者应按实际模型、地区与计费方式设置保守单次预留，并配置供应商侧消费控制；账本是预留值，不是已核实账单。

计数按日本自然日，调用前在同一事务内预留全局与个人额度。失败、超时或后续语义校验不通过仍占用额度，不自动重试。输入最多 2,000 字，上下文最多 24,000 字节，输出最多 1,200 token，连接／读取超时为 5／20 秒。

- 需求整理发送用户主动输入的文本、日期上下文和有限作品信息；文本中用户自己写入的个人信息会随请求发送。
- Trip 修改发送有限的站点、日期／时间、候选名称、已处理状态和当前指令，不发送完整历史、匿名凭据或住宿坐标。
- 记录整理只重排程序生成的已确认短句；再次发现只选择有效候选。不发送照片或私人笔记。
- AI 提案经过字段、对象、锁定和已执行内容检查，确认后才能写入；AI 不能发布分享、生成到访或改写交通事实。

**旧搜索、问答、路线建议未接入上述额度。** 侧栏 Key 或服务端 `DASHSCOPE_API_KEY` 仍可触发旧接口；公开部署保持服务端 Key 未配置，或在启用前另行补齐这些入口的限额。新 Trip 没有真实日本交通供应商调用，配置 `AMAP_API_KEY` 只影响原有路线预览。

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

## 浏览器检查

自动化脚本是可复用工具，输出写到临时目录。请使用无 Key、独立数据库和本机地址，勿连接真实用户数据。终端一：

```bash
ANIMEWAY_DATA_DIR=/tmp/animeway-browser-check AMAP_API_KEY='' DASHSCOPE_API_KEY='' uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8754 --server.headless true --server.maxUploadSize 16 --browser.gatherUsageStats false
```

终端二安装可选浏览器依赖并运行：

```bash
uv run --with playwright python -m playwright install chromium
uv run --with playwright python scripts/verify_pilot_browser.py --url http://127.0.0.1:8754 --output-dir /tmp/animeway-check-handbook
uv run --with playwright python scripts/verify_trip_browser.py --url http://127.0.0.1:8754 --output-dir /tmp/animeway-check-trip
uv run --with playwright python scripts/verify_journal_browser.py --url http://127.0.0.1:8754 --output-dir /tmp/animeway-check-journal
```

已有 Chromium 可加 `--executable /path/to/chromium`。脚本用临时浏览器档案和合成数据验证保存、重开、隔离、恢复与分享撤下，并阻断外部 HTTP。移动端检查为 Chromium 尺寸模拟，不代表真实 iOS／Android、GPS、地图服务或现场通行已通过。

## 常见问题

| 现象 | 排查方式 |
|---|---|
| 重启后找不到清单 | 检查持久目录是否变化、磁盘是否被重建、是否换浏览器或站点地址；不要删除原库 |
| 私人库读取失败 | 保留原文件和 WAL，检查目录权限、磁盘与版本兼容；不要通过重建空库掩盖错误 |
| AI 按钮不可用 | 检查 Key、四项配额和当日使用量；额度不足不影响人工编辑 |
| 分享只有相对链接 | 配置实际 `ANIMEWAY_PUBLIC_URL`，或打开相对链接后复制浏览器地址 |
| 备份超限 | 先导出备份再整理不需要的记录／照片；两个备份入口各自受限 |
| 旧手册坐标与详情不同 | 已保存手册可能保留旧坐标；出发前查看当前地点详情并重新核对导航 |
