# AI漫剧Agent · 后端技术文档

## 项目概述

AI漫剧Agent 是一套"全流程自动化+轻量化人工干预"的漫剧生产系统。后端基于 **Python FastAPI + LangGraph** 构建，负责脚本解析、分镜生成、图像生成、配音合成、视频渲染等核心 AI 流水线。

**核心定位**：输入脚本 → Agent 智能拆解 → 全链路自动生成 → 成片输出

---

## 技术栈

| 组件 | 选型 | 版本 | 用途 |
|------|------|------|------|
| Web 框架 | FastAPI | 0.115.0 | REST API + WebSocket |
| Agent 框架 | LangGraph | 0.2.0 | 状态图驱动的 AI 流水线编排 |
| LLM | OpenAI API (兼容) | 1.50.0 | 脚本解析、分镜决策、剧情校验 |
| 向量数据库 | ChromaDB | 0.5.0 | RAG 剧本/小说文档检索 |
| 文本嵌入 | sentence-transformers | 3.0.0 | all-MiniLM-L6-v2 模型 |
| TTS | Edge-TTS | 6.1.0 | 免费中文语音合成 |
| 视频渲染 | FFmpeg (ffmpeg-python) | 0.2.0 | 视频合成、转场、字幕 |
| 图像生成 | Stability AI API | - | 云端图像生成 (可切换本地 SD) |
| ORM | SQLAlchemy | 2.0.0 | 数据库模型 |
| 数据库 | SQLite | - | Demo 阶段零运维 |

---

## 目录结构

```
server/
├── main.py                    # FastAPI 入口，注册路由/中间件/WebSocket
├── config.py                  # Pydantic Settings 配置管理
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板
│
├── agent/                     # LangGraph Agent 核心
│   ├── state.py               # AgentState 状态定义 (TypedDict)
│   ├── graph.py               # 状态图构建与编译
│   ├── nodes/                 # 图节点实现
│   │   ├── script_parser.py   # 脚本解析 (LLM)
│   │   ├── storyboard_gen.py  # 分镜生成 (LLM)
│   │   ├── image_gen.py       # 图像生成 (Stability AI)
│   │   ├── voice_gen.py       # 配音生成 (Edge-TTS)
│   │   ├── video_compose.py   # 视频合成 (FFmpeg)
│   │   └── quality_check.py   # 质量校验
│   └── edges/
│       └── conditions.py      # 条件路由逻辑
│
├── services/                  # 外部服务封装
│   ├── llm_service.py         # OpenAI 兼容 LLM 调用
│   ├── image_service.py       # 图像生成 (角色卡片注入)
│   ├── tts_service.py         # Edge-TTS 语音合成
│   ├── ffmpeg_service.py      # FFmpeg 视频渲染
│   └── storage_service.py     # 文件存储管理
│
├── memory/                    # 三层记忆系统
│   ├── project_memory.py      # 项目级记忆 (JSON 文件)
│   ├── user_memory.py         # 用户偏好记忆 (JSON)
│   └── memory_manager.py      # 统一管理器
│
├── rag/                       # RAG 检索系统
│   └── rag_service.py         # ChromaDB 文档导入与检索
│
├── api/                       # API 路由
│   ├── websocket.py           # WebSocket 连接管理
│   └── routes/
│       ├── project.py         # 项目 CRUD
│       ├── script.py          # 脚本解析 (触发 Agent 流水线)
│       ├── shot.py            # 镜头管理
│       ├── render.py          # 渲染导出
│       └── chat.py            # 自然语言交互
│
├── models/                    # SQLAlchemy 数据模型
│   ├── base.py                # Base 声明
│   ├── project.py             # 项目模型
│   ├── shot.py                # 镜头模型
│   └── character.py           # 角色模型
│
├── db/                        # 数据库
│   └── database.py            # SQLite 连接与初始化
│
├── prompts/                   # 提示词模板
│   └── styles/                # 风格参数模板
│       ├── anime.json         # 日系动漫
│       ├── chinese.json       # 国漫古风
│       ├── chibi.json         # Q版可爱
│       └── realistic.json     # 写实风格
│
└── data/                      # 运行时数据 (gitignore)
    ├── chromadb/              # ChromaDB 持久化
    ├── checkpoints/           # LangGraph 检查点
    └── comic_agent.db         # SQLite 数据库文件
```

---

## Agent 流水线架构

基于 LangGraph 状态图，6 个核心节点 + 2 个干预节点：

```
START
  │
  ▼
parse_script ──▶ generate_storyboard ──▶ generate_images
   (LLM)              (LLM)              (Stability AI)
                                              │
                                              ▼
                                         quality_check
                                              │
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                                  pass    regenerate  human_review
                                   │      _shot         │
                                   ▼         │          ▼
                                  END         ▼      compose_video
                                         quality_check    │
                                              ◀───────────┘
                                              │
                                              ▼
                                    generate_voice ──▶ compose_video ──▶ END
                                      (Edge-TTS)         (FFmpeg)
```

### AgentState 核心字段

```python
class AgentState(TypedDict):
    project_id: str
    user_input: str
    input_type: Literal["text", "file", "ip"]
    
    # 脚本解析结果
    characters: list[CharacterCard]     # 角色卡片列表
    script_scenes: list[dict]           # 结构化场景
    logic_issues: list[dict]            # 逻辑问题
    
    # 分镜
    shots: Annotated[list[Shot], add]   # 镜头列表 (reducer: 追加)
    
    # 风格
    style: str                          # anime/chinese/chibi/realistic
    style_params: StyleParams
    
    # 渲染参数
    output_format: Literal["9:16", "16:9", "1:1"]
    resolution: str
    platform: Literal["douyin", "kuaishou", "bilibili", "custom"]
    
    # 流程控制
    needs_human_review: bool
    rag_context: list[str]              # RAG 检索结果
```

---

## 核心模块说明

### 1. 角色一致性保障 (Character Card)

每次图像生成时，从角色卡片强制注入以下参数：

- `base_prompt`: 角色基础英文描述 (发型/发色/瞳色/身材)
- `key_features`: 关键视觉特征列表
- `emotion_variants`: 6 种情绪对应的 prompt 片段 (neutral/happy/shy/sad/angry/surprised)
- `negative_prompt`: 排除不符合特征的描述
- `seed`: 固定随机种子，保证生成一致性

### 2. 记忆系统 (三层架构)

| 层级 | 载体 | 生命周期 | 用途 |
|------|------|---------|------|
| 工作记忆 | LangGraph State | 单次流水线 | 节点间数据传递 |
| 项目记忆 | JSON 文件 | 项目生命周期 | 角色卡片、风格参数、剧情上下文 |
| 用户记忆 | JSON 文件 | 永久 | 用户偏好、常用修正模式 |

### 3. RAG 系统

- **向量库**: ChromaDB (本地持久化)
- **嵌入模型**: all-MiniLM-L6-v2 (sentence-transformers)
- **分块策略**: 剧本按场景切分，小说按滑动窗口 (3段重叠1段)
- **chunk 类型**: scene / dialogue / narrative
- **检索支持**: 按 chunk_type 过滤，按角色名查询相关上下文

### 4. FFmpeg 视频渲染

- **Ken Burns 动效**: 全景缓慢推进、特写轻微抖动、中景静止
- **字幕**: drawtext 滤镜，白色描边，底部居中
- **拼接**: concat demuxer
- **音频混流**: 配音音轨与视频合并
- **输出**: libx264 + aac，支持 720p/1080p/4K

---

## API 接口

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/project` | 创建项目 |
| GET | `/api/project/{id}` | 获取项目详情 |
| PUT | `/api/project/{id}` | 更新项目 |
| GET | `/api/project` | 项目列表 |
| POST | `/api/script/parse` | 提交脚本，触发 Agent 流水线 |
| POST | `/api/script/upload` | 上传脚本文件 |
| GET | `/api/shot/{project_id}/shots` | 获取项目镜头列表 |
| PUT | `/api/shot/{shot_id}` | 更新镜头 |
| POST | `/api/shot/{shot_id}/regenerate` | 重新生成单个镜头 |
| POST | `/api/shot/batch-regenerate` | 批量重生成 |
| POST | `/api/render` | 触发渲染 |
| GET | `/api/render/{project_id}/status` | 渲染进度 |
| POST | `/api/chat` | 自然语言交互 |

### WebSocket

```
ws://localhost:8000/ws/{project_id}
```

**服务端推送事件：**

```json
{"type": "progress", "step": "parse_script", "progress": 20, "message": "..."}
{"type": "complete", "project_id": "...", "shots": [...], "video_path": "..."}
{"type": "shot_update", "shot_id": "...", "status": "done", "image_url": "..."}
{"type": "render_complete", "video_url": "...", "duration": 30}
{"type": "error", "message": "..."}
```

**客户端消息：**

```json
"ping"  → 服务端回复 {"type": "pong"}
```

---

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
# LLM (必填)
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o
# OPENAI_BASE_URL=          # 兼容接口地址

# 图像生成 (必填)
STABILITY_API_KEY=sk-xxx

# TTS (可选，默认 Edge-TTS 免费)
TTS_PROVIDER=edge
TTS_DEFAULT_VOICE=zh-CN-XiaoyiNeural
```

---

## 启动方式

```bash
cd server

# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 4. 启动服务
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后：
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health
- 输出文件: http://localhost:8000/output/{path}

---

## 数据库模型

### Project

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| title | str | 项目名称 |
| genre | str | 类型 (甜宠/悬疑/古风/都市) |
| style | str | 风格 (anime/chinese/chibi/realistic) |
| status | str | draft/generating/completed/error |
| input_text | str | 原始输入 |
| output_format | str | 9:16 / 16:9 / 1:1 |
| resolution | str | 720p / 1080p / 4k |
| platform | str | douyin / kuaishou / bilibili / custom |

### Shot

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| project_id | FK | 所属项目 |
| sequence | int | 顺序号 |
| shot_type | str | wide/medium/close-up/extreme_close |
| scene_description | str | 场景描述 (英文，用于 AI 绘画) |
| dialogue | str | 台词 |
| camera_angle | str | 正面/侧面/俯视/仰视 |
| duration | float | 时长 (秒) |
| emotion | str | 情绪 |
| image_path | str | 生成图片路径 |
| audio_path | str | 配音文件路径 |
| status | str | pending/generating/done/failed/needs_review |
| version | int | 版本号 (重生成时递增) |

### Character

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| project_id | FK | 所属项目 |
| name | str | 角色名 |
| visual_prompt | str | 英文 AI 绘画 prompt |
| negative_prompt | str | 排除描述 |
| emotion_variants | JSON | 情绪 → prompt 片段映射 |
| key_features | JSON | 关键视觉特征列表 |
| seed | str | 固定随机种子 |

---

## 风格模板

`prompts/styles/` 目录下 4 套预置风格：

| 文件 | 风格 | prompt_prefix 特征 |
|------|------|--------------------|
| anime.json | 日系动漫 | cel shading, vibrant colors, clean lineart |
| chinese.json | 国漫古风 | ink wash painting, traditional chinese aesthetic |
| chibi.json | Q版可爱 | chibi, kawaii, big head small body |
| realistic.json | 写实风格 | semi-realistic, detailed shading, cinematic lighting |

每套风格包含：prompt_prefix、negative_prefix、color_palette、camera_preferences、character_style

---

## 依赖说明

### 系统依赖

- **Python** >= 3.11
- **FFmpeg** (需要在 PATH 中)
  - Windows: 从 https://ffmpeg.org/download.html 下载，添加到系统 PATH
  - 验证: `ffmpeg -version`

### Python 依赖

核心依赖分 5 类：

1. **Web 框架**: fastapi, uvicorn, pydantic, pydantic-settings
2. **AI/Agent**: langgraph, langchain, langchain-openai, openai
3. **向量检索**: chromadb, sentence-transformers
4. **媒体处理**: ffmpeg-python, Pillow, edge-tts
5. **工具库**: httpx, aiohttp, aiofiles, python-docx, python-multipart

---

## 开发注意事项

1. **sys.path**: `main.py` 开头会将 server 目录加入 sys.path，确保模块导入正确
2. **异步执行**: Agent 流水线通过 `asyncio.create_task()` 异步执行，不阻塞 API 响应
3. **WebSocket 进度**: 流水线执行过程中通过 `ws_manager` 向项目的所有连接推送进度
4. **文件路径**: 输出文件通过 `/output/` 静态路由对外提供访问
5. **角色一致性**: 图像生成时必须注入角色卡片 (Character Card)，不可省略 key_features
6. **FFmpeg 中文字幕**: Windows 需指定 `font=Microsoft YaHei`，Linux 需安装中文字体
