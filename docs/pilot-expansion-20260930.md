# 东京精选扩展审查记录（2026-09-30）

本批从仓库内 `animeway.sqlite3` 的 2026-07-24 来源快照选取点位，并逐点比对现实设施的运营方、区政府或铁路公司页面。`tokyo.json` 保留每条上游作品 ID、点位 ID、原名、原坐标及来源链接。官方页面仅支持**地点名称、地理归属或设施存在**；动画画面对照、具体机位、当天开放和步行连接都未据此认定已核验。

| 新增作品 | 东京框内候选来源记录 | 本批来源记录 | 本批涉及现实地点 | 代表性官方参照 |
|---|---:|---:|---:|---|
| 《虹咲学园校园偶像同好会》 | 235 | 6 | 6 | [台场海滨公园](https://www.tptc.co.jp/park/01_02/point)、[象征性步道公园](https://www.tptc.co.jp/park/01_04/point)、[水之广场公园](https://www.tptc.co.jp/park/02_04) |
| 《江户前精灵》 | 195 | 7 | 3 | [中央区佃小桥资料](https://www.city.chuo.lg.jp/a0037/shisetsu/genre/sonota/sonota00060.html)、[月岛地区规划资料](https://www.city.chuo.lg.jp/documents/5126/tukishima.pdf)、[波除神社](https://www.namiyoke.or.jp/index.php) |
| 《MyGO!!!!!》 | 125 | 5 | 4 | [丰岛区东池袋中央公园](https://www.city.toshima.lg.jp/340/shisetsu/koen/022.html)、[池袋站](https://www.jreast.co.jp/estation/station/info.aspx?StationCD=108) |
| 《咒术回战 第二季》 | 90 | 2 | 2 | [涩谷区站前广场名称](https://www.city.shibuya.tokyo.jp/kankyo/doro-kasen/doro-jorei/kudo_tushomei.html)、[道路拍摄说明](https://www.city.shibuya.tokyo.jp/kankyo/doro-kasen/doro-shinsei/senyo.html) |
| 《无头骑士异闻录》 | 85 | 4 | 4，其中 1 个与《MyGO!!!!!》共址 | [丰岛区池袋西口公园](https://www.city.toshima.lg.jp/340/miryoku/shiru/koen/nishiguchi.html)、[东池袋中央公园](https://www.city.toshima.lg.jp/340/shisetsu/koen/022.html) |
| 《Love Live! Superstar!!》 | 81 | 3 | 3 | [代代木公园设施](https://www.tokyo-park.or.jp/park/yoyogi/facility/index.html)、[原宿站](https://www.jreast.co.jp/estation/station/info.aspx?StationCd=1256) |

六部作品合计 811 条东京坐标框内候选记录，本批仅选 27 条来源记录，形成 **21 个新增现实地点**；一处东池袋中央公园同时关联《MyGO!!!!!》两条和《无头骑士异闻录》一条记录，所以逐作品“涉及地点”相加为 22，不是全局新增地点数。原有两部作品未改写，东京精选总量变为 **8 部作品、91 个地点、103 条场景关联、7 条手册**。

佃小桥的五条《江户前精灵》TV 来源记录归为一处桥，没有把同坐标的漫画卷数记录混入 TV 版本。原宿站来源名写“东口”，但 [JR 官方站页](https://www.jreast.co.jp/estation/station/info.aspx?StationCd=1256)使用表参道口、竹下口等名称，因此地点只表述为“原宿站东侧公共街面”。涩谷两处站前广场没有规划进新手册，仍可手动选点；施工、人流及拍摄活动规则需要当天再查。

新增的台场、佃月岛、池袋与原宿四条手册均标为 `prototype`。所有新地点 `access.status=unknown`，所有新场景 `match_status=community_reported`，新手册的 `content_ready`、`field_verified`、`user_validated` 均为 `false`。停留时间只是编辑建议，连接距离和耗时为未知。没有新增下载或展示上游截图的权限；场景图片仍只保留来源作品页，不打包素材。即使现有 Trip 规则允许这些地点手动加入，也不能据此称为已现场验收的推荐路线。

剩余 784 条候选记录仍在离线审查池，不会自动变成 Trip 地点。下一轮优先核查同片区重复点、商户与私有空间、道路施工和准确机位，再决定是否补入。复算统计：

```bash
python -m scripts.audit_data_scope --write-inventory
```

候选池与准入规则见[数据范围](data-scope.md)；上游数据和素材条款见[原始数据说明](../knowledge_base/raw/README.md)。
