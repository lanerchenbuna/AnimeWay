# 公开索引的原始输入

本目录保存应用离线构建公开索引所需的输入：

| 文件 | 用途 |
|---|---|
| `bangumi_knowledge.json` | 作品元数据快照 |
| `anitabi_crawl.json` | 已保存的作品点位记录，包含坐标、图片链接和城市 |
| `crawl_state.json` | 各作品抓取状态，供后续显式刷新使用 |

仓库根目录的 `knowledge_base/index.json` 和 `knowledge_base/animeway.sqlite3` 是运行用旧版索引。构建新的成对快照时，从项目根目录运行：

```bash
uv run python -m data_factory.release --root /tmp/animeway-public-snapshots --offline
```

该命令使用保存的输入，不会联网，也不表示内容已经更新。在线刷新先生成候选、人工核对，再发布；流程见 [部署与维护](../../docs/operations.md#公开地图快照刷新与回退)。请勿直接覆盖旧版 JSON 或 SQLite 文件。

作品元数据来源包括 [Bangumi](https://bgm.tv/)；点位来源包括 [Anitabi](https://anitabi.cn/)。[Anitabi 开放 API 文档](https://navi.anitabi.cn/docs/api/)要求遵循 CC BY-NC-SA 4.0，并要求场景截图保留 `origin` 文字与 `originURL` 链接。当前保存的旧版点位输入没有这两个字段，因此不能仅凭本目录数据确认每张截图的再发布权利。代码 MIT 许可不覆盖第三方数据与图片；公开复用这些文件前须单独核对来源条款、署名与素材权利。
