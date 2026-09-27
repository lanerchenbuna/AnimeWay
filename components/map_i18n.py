"""UI text for map discovery, work/scene browsing and accessible fallback."""

from components.i18n import current_locale

MESSAGES = {
    "access_unknown": ("待核查", "Unverified", "未確認"),
    "access_open": ("可访问", "Open", "訪問可"),
    "access_public_exterior": ("可从公共区域观看外观", "Public exterior view", "公共エリアから外観を見学可"),
    "access_restricted": ("受限", "Restricted", "制限あり"),
    "access_closed": ("已关闭", "Closed", "閉鎖"),
    "access_forbidden": ("禁止访问", "Access forbidden", "立入禁止"),
    "access_prohibited": ("禁止进入", "Entry prohibited", "立入禁止"),
    "access_no_entry": ("不可进入", "No entry", "立入不可"),
    "title": ("地图探索", "Explore the map", "地図で探す"),
    "search": ("搜索番剧、地点或城市", "Search works, places or cities", "作品・場所・都市を検索"),
    "search_go": ("搜索", "Search", "検索"),
    "map": ("地图", "Map", "地図"),
    "list": ("文字列表", "Text list", "一覧"),
    "place_count": ("{count} 个地点 · 可切换地图与文字列表", "{count} places · switch between map and list", "{count} か所 · 地図と一覧を切り替え"),
    "back": ("返回上一页", "Back", "戻る"),
    "pilot": (
        "当前显示东京精选资料",
        "Showing the curated Tokyo catalog",
        "東京の編集済みデータを表示中",
    ),
    "all": (
        "当前可探索全库资料；基础收录不代表访问条件已核验",
        "Full catalog; basic records have unverified access conditions",
        "全データを探索できます。基本情報は通行確認済みではありません",
    ),
    "fallback": (
        "全库快照暂不可用或已回退，仍可浏览当前有效资料。",
        "The snapshot is unavailable or rolled back. Available content remains browsable.",
        "スナップショットを利用できないか、前の版に戻りました。有効な情報は閲覧できます。",
    ),
    "filter": ("筛选地点", "Filter places", "場所を絞り込む"),
    "work": ("作品", "Work", "作品"),
    "region": ("片区", "Area", "エリア"),
    "city": (
        "原始城市标签（精确匹配）",
        "Source city label (exact match)",
        "出典の都市名（完全一致）",
    ),
    "any": ("全部", "All", "すべて"),
    "unknown": ("未标注／待核查", "Unspecified / unverified", "未記載・未確認"),
    "level": ("内容级别", "Content level", "情報レベル"),
    "basic": ("基础记录", "Basic record", "基本情報"),
    "selection": ("精选地点", "Curated place", "編集済みの場所"),
    "route": ("路线资料", "Route content", "ルート資料"),
    "access": ("访问状态", "Access status", "訪問条件"),
    "fit": ("定位当前筛选结果", "Fit filtered results", "絞り込み結果を表示"),
    "empty": (
        "没有匹配地点，请调整筛选或地图范围。",
        "No places matched. Change filters or map bounds.",
        "該当する場所がありません。条件や地図範囲を変更してください。",
    ),
    "choose": (
        "选择地点（支持键盘）",
        "Choose a place (keyboard accessible)",
        "場所を選択（キーボード対応）",
    ),
    "open": ("查看地点与场景", "Place and scene details", "場所と場面の詳細"),
    "save": ("加入想去清单", "Save to wishlist", "行きたい場所に保存"),
    "remove": ("从想去清单移除", "Remove from wishlist", "行きたい場所から削除"),
    "saved": ("已保存", "Saved", "保存済み"),
    "save_error": (
        "暂时无法保存，请检查身份或稍后重试。",
        "Could not save. Check your profile or try again.",
        "保存できません。識別情報を確認して再試行してください。",
    ),
    "withdrawn": (
        "该地点已撤下，保留资料用于解释历史记录。",
        "This place is withdrawn; retained for historical context.",
        "この場所は掲載停止です。履歴の説明用に保持しています。",
    ),
    "source": ("来源", "Source", "出典"),
    "source_version": ("来源版本", "Source revision", "出典の版"),
    "source_time": ("核查时间", "Review date", "確認日"),
    "navigate": ("外部地图查看坐标", "Open coordinates in external map", "外部地図で座標を見る"),
    "coordinate_help": (
        "坐标是地点参考位置，不保证是入口或拍摄机位。",
        "Coordinates locate the place; they do not verify an entrance or camera position.",
        "座標は場所の参考位置です。入口や撮影位置を保証しません。",
    ),
    "scenes": ("关联场景", "Related scenes", "関連シーン"),
    "episode": ("话数", "Episode", "話数"),
    "unknown_episode": ("未标注话数", "Episode unspecified", "話数未記載"),
    "timecode": ("时间码", "Timecode", "タイムコード"),
    "spoilers": (
        "展开场景说明（可能包含剧透）",
        "Show scene notes (may contain spoilers)",
        "場面の説明を表示（ネタバレあり）",
    ),
    "image": ("场景截图", "Scene image", "シーン画像"),
    "no_image": (
        "此场景暂时没有可用图片，文字和来源仍可查看。",
        "No image is available for this scene. Text and source links remain available.",
        "このシーンの画像はありません。説明と出典は確認できます。",
    ),
    "work_map": ("在地图查看本作地点", "Show this work on the map", "作品の場所を地図で見る"),
    "prev": ("上一页", "Previous", "前へ"),
    "next": ("下一页", "Next", "次へ"),
    "tiles": (
        "加载底图（OpenStreetMap）",
        "Load basemap (OpenStreetMap)",
        "背景地図を読み込む（OpenStreetMap）",
    ),
    "tile_error": (
        "底图暂不可用，点位和文字列表仍可使用。",
        "Basemap unavailable; points and text list still work.",
        "背景地図を利用できません。点と一覧は利用できます。",
    ),
    "no_tiles": (
        "底图已关闭，仍可拖动、缩放和选点。",
        "Basemap off; pan, zoom and select points still work.",
        "背景地図はオフです。移動・拡大・選択は利用できます。",
    ),
    "help": (
        "拖动或双指缩放；键盘方向键移动，+/− 缩放。",
        "Drag or pinch; arrow keys pan and +/− zoom.",
        "ドラッグ・ピンチ操作、矢印キーで移動、+/−で拡大縮小。",
    ),
    "cluster": ("个地点，点击放大", "places; zoom in", "か所・拡大"),
    "cluster_hint": (
        "地点较多，请放大地图或收窄筛选。",
        "Zoom in or narrow filters to see individual places.",
        "拡大するか条件を絞って個別の場所を表示してください。",
    ),
    "legend": (
        "紫：基础 · 蓝：精选／路线 · 灰：受限／关闭 · 金圈：选中 · 绿边：已收藏",
        "Purple: basic · Blue: curated · Gray: restricted/closed · Gold: selected · Green: saved",
        "紫：基本・青：編集済み・灰：制限／閉鎖・金：選択・緑：保存",
    ),
    "raw_city": (
        "地区为来源标签，未视为核验过的行政归属。",
        "Area text is a source label, not verified geography.",
        "地域名は出典のラベルで、行政区分の確認済み情報ではありません。",
    ),
    "missing": (
        "记录不存在或当前已不可用。",
        "The record is missing or unavailable.",
        "記録が存在しないか利用できません。",
    ),
}


def mtext(key):
    return MESSAGES[key][{"zh_CN": 0, "en_US": 1, "ja_JP": 2}.get(current_locale(), 0)]


def access_text(status):
    """Keep an unfamiliar source status readable and fail closed elsewhere."""
    key = "access_" + status if isinstance(status, str) else "access_unknown"
    return mtext(key if key in MESSAGES else "access_unknown")
