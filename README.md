# ⛩️ AnimeWay (圣地巡礼助手)

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AnimeWay** 是一款基于大语言模型（LLM）的二次元圣地巡礼规划助手。它打破了次元壁，利用 AI 技术为您寻找动画中的现实取景地，并生成硬核的巡礼路书。

**[English Readme](#english-readme)**

---

## ✨ 核心功能 (Features)

1.  **🤖 智能观测者 (Agentic Interface)**
    *   不再需要复杂的表单，直接像聊天一样告诉 Agent 你的愿望。
    *   支持模糊推荐（“推荐几部治愈番”）、精准搜索（“莉可丽丝的圣地”）和闲聊。
    *   **🎲 推荐重随**：不满意？一键 Reroll，直到找到命中注定的番剧。

2.  **🗺️ 全球 3D 巡礼地图**
    *   集成 **PyDeck** 高性能 3D 地图引擎。
    *   无论是东京的街头还是伦敦的桥梁，都能无死角展示巡礼路线和点位。
    *   支持路径可视化与交互式信息查看。

3.  **📖 冒险之书 (Adventure Book)**
    *   **硬核路书**：AI 生成包含具体公交线路、换乘方案的详细指南。
    *   **巡礼相册**：自动抓取并展示圣地巡礼的实景/动画对比图（Visual Album）。
    *   **情怀加持**：每一站都附带动画集数与场景描述，让旅途充满感动。

## 🛠️ 技术栈 (Tech Stack)

*   **框架**: [Streamlit](https://streamlit.io/)
*   **大脑 (LLM)**: 阿里云 DashScope (通义千问 Qwen-Turbo / VL)
*   **数据源**: 
    *   [Anitabi](https://anitabi.cn) (圣地数据)
    *   [Bangumi](https://bangumi.tv) (番组元数据)
*   **地图服务**: 
    *   [AMap (高德地图)](https://lbs.amap.com) (路径规划 API)
    *   [PyDeck](https://pydeck.gl) (3D 可视化)

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保 Python >= 3.9。

```bash
git clone https://github.com/your-username/animeway.git
cd animeway

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. 启动应用
```bash
streamlit run app.py
```

### 3. 配置密钥
应用启动后，在左侧边栏输入您的 API Key：
*   **DashScope Key**: 用于 AI 意图识别与路书生成。
*   **GaoDe Key (Map)**: 用于地理编码与路径规划服务。

---

<a name="english-readme"></a>
## 🌏 English Overview

**AnimeWay** is an AI-powered travel planner dedicated to "Anime Pilgrimage" (Seichijunrei). It helps anime fans discover real-world locations of their favorite anime scenes and generates detailed travel itineraries.

### Key Features
*   **Agentic Chat**: Just ask "Find locations for Your Name" or "Recommend me a sci-fi anime".
*   **Global 3D Map**: Interactive 3D visualization of your pilgrimage route using PyDeck.
*   **Visual Itinerary**: Automatically fetches location photos and generates detailed transit guides with anime context.

### Setup
1.  Install dependencies: `pip install -r requirements.txt`
2.  Run app: `streamlit run app.py`
3.  Enter your **DashScope API Key** and **AMap API Key** in the sidebar.

## 📄 License
MIT License. See [LICENSE](LICENSE) for details.

*Breaking the Dimensional Wall...*
