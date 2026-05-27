---
name: AI漫剧Agent
description: 桌面端 AI 漫剧创作工作台
colors:
  sage-green: "#6f9180"
  deep-pine: "#5f7f6f"
  warm-amber: "#b89266"
  cool-gray: "#7f8e9f"
  paper-white: "#ffffff"
  soft-paper: "#fdfefe"
  ink: "#27313a"
  smoke: "#647385"
  mist: "#8a98a9"
  pale: "#a0acbb"
  hairline: "#d7e1ec"
  hairline-soft: "#e5edf5"
  glass-surface: "rgba(255, 255, 255, 0.72)"
  glass-strong: "rgba(255, 255, 255, 0.84)"
typography:
  heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
  meta:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "12px"
  md: "16px"
  lg: "20px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
components:
  button-primary:
    backgroundColor: "linear-gradient(180deg, #749686, #618171)"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "34px"
    padding: "0 16px"
  button-primary-hover:
    backgroundColor: "linear-gradient(180deg, #7ea08f, #6d8d7c)"
    textColor: "#ffffff"
  button-default:
    backgroundColor: "rgba(252, 254, 255, 0.85)"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: "34px"
    padding: "0 16px"
  chip:
    backgroundColor: "rgba(252, 254, 255, 0.88)"
    textColor: "{colors.smoke}"
    rounded: "999px"
    padding: "6px 10px"
  chip-active:
    backgroundColor: "rgba(111, 145, 128, 0.14)"
    textColor: "{colors.deep-pine}"
    rounded: "999px"
  input:
    backgroundColor: "rgba(253, 255, 255, 0.92)"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "30px"
---

# Design System: AI漫剧Agent

## 1. Overview

**Creative North Star: "清晰的静默"**

Linear 式的极简克制与温柔的白噪基底相遇——像一本摊开的速写本，干净但不冰冷，安静但不沉闷。每个像素的任务是退后一步，让创作者的注意力落在内容上，而非界面上。

这个体系拒绝大声喧哗。控件融入背景，hover 时才浮现；间距用节奏感的留白替代硬边框；毛玻璃底色在桌面窗口四周建立一层环境纵深，工作区以纯白画布从中切出。这不是装饰，是空间分层：玻璃层承接环境，白纸承接创作。

从 Linear 借用命令感和极简决策密度，从 Notion 借用亲和留白，但刻意避开两者的两端极端：不做 Linear 的深色高冷，也不做 Notion 的文档膨胀感。

**Key Characteristics:**
- 单主色驱动：灰绿（sage-green）作为唯一强调色，覆盖率 ≤10%
- 控件融入背景：hover 显现，静态隐退
- 毛玻璃作为空间模型，非装饰效果
- 白色工作区与玻璃外围形成「画布浮在玻璃上」的纵深关系
- 系统字体栈，零图标字体依赖

**明确拒绝：** 游戏化炫技界面、过饱和渐变、霓虹描边、装饰性动画、深灰工业软件调性。

## 2. Colors

灰绿调中性色体系，自然不冰冷。绿是鼠尾草的灰绿（sage-green），橙是琥珀的光晕（warm-amber），灰是石板的冷灰（cool-gray）。

### Primary
- **鼠尾草绿** (#6f9180)：主按钮、选中态、进度条填充、活跃链接。唯一强调色，覆盖率严格 ≤10%。
- **深松绿** (#5f7f6f)：主按钮 hover、深色文字强调、focus ring 外圈。

### Secondary
- **暖琥珀** (#b89266)：收藏星标、警告提示。低频使用，提供第二维度的语义信号。

### Neutral
- **石板灰** (#7f8e9f)：进度条底色、禁用态辅助色。
- **白纸** (#ffffff)：工作区主背景、弹窗底色。
- **柔纸** (#fdfefe)：次级面板底色，比纯白多一层温度。
- **墨色** (#27313a)：主文字。接近黑但不死黑，保持可读性。
- **烟色** (#647385)：次级文字、导航标签。
- **雾色** (#8a98a9)：三级文字、placeholder、次要元数据。
- **淡色** (#a0acbb)：四级文字、极度退后的辅助信息。
- **发丝线** (#d7e1ec)：标准边框。
- **柔丝线** (#e5edf5)：次级边框、微分隔。
- **玻璃面** (rgba(255,255,255,0.72))：app-shell 毛玻璃背景。
- **厚玻璃** (rgba(255,255,255,0.84))：毛玻璃上的控件底色。

### Named Rules
**The One Voice Rule.** 鼠尾草绿是唯一的彩色强调。任何新颜色加入前，先问：这个状态能不能用灰绿或灰度表达？不需要第三个语义色。

**The Glass Foundation Rule.** 毛玻璃不是装饰。它是 app-shell 的空间基底，建立窗口与环境之间的纵深关系。内部控件不使用毛玻璃，工作区用纯白画布从中切出。

## 3. Typography

**Font Family:** `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif`

**Character:** 系统原生字体，零加载开销。PingFang SC 中文端正，SF Pro 英文利落，天然匹配 macOS / Windows 桌面环境。无衬线单一族，层级靠 weight 与 size 区分。

### Hierarchy
- **Heading** (600, 13px, 1.5)：侧栏品牌名、面板标题、项目名称。与 body 同号但 weight 拉开。
- **Body** (400, 13px, 1.5)：剧本内容、标签、表单字段。基准字号。
- **Label** (500, 12px, 1.4)：按钮文字、表单项标签、chip 文字。
- **Meta** (400, 11px, 1.4)：时间戳、辅助元数据、脚注信息。

### Named Rules
**The No-Type-Trick Rule.** 不靠字号差异建立层级。标题和正文同号时用 weight（600 vs 400）区分；需要信息密度时用两号（11px / 13px），不引入第三号。

## 4. Elevation

**The Flat-By-Default Rule.** 界面是扁平的。玻璃基底提供唯一的环境纵深——app-shell 的 backdrop-filter 模糊了桌面背景，模拟画布浮于玻璃上的空间关系。在此之上的所有面板（工作区、侧栏、弹窗）一律用 1px 细线边框分隔，不叠加阴影。hover 态用颜色变化和轻微位移表达反馈，不用投影。

### Shadow Vocabulary
- **柔影** (`0 1px 2px rgba(31, 37, 45, 0.06)`)：仅用于 Ant Design message 提示和 ReactFlow 小控件。极轻，几乎不可见。不得用于面板、卡片或导航。

## 5. Components

### Buttons
**融入背景的触感。** 静态时按钮是界面的一部分而非突出元素；hover 时提供明确的颜色反馈和 2px 微位移。

- **Shape:** 圆角 16px（`--radius`），高 34px。
- **Primary:** 灰绿渐变 (`linear-gradient(180deg, #749686, #618171)`)，白字，无阴影。仅出现于「开始解析」和主操作路径。
- **Primary Hover:** 浅化渐变 (`#7ea08f → #6d8d7c`)，保持同色系温感。
- **Default:** 微白底色 (`rgba(252,254,255,0.85)`)，发丝线边框，墨色文字。用于「导入」「导出」等辅助操作。
- **Default Hover:** 边框色加深至 `rgba(95,127,111,0.42)`，文字色自动跟随深绿。

### Chips
**轻量胶囊，状态锚点。** 运行模式切换用。

- **Style:** 胶囊形（border-radius: 999px），1px 发丝线边框，微白底色，烟色文字（12px）。
- **Active:** 灰绿背景 (`rgba(111,145,128,0.14)`) + 深松绿文字 + 深绿边框。选中态不喧哗，低饱和度保持呼吸感。

### Cards / Containers
**没有卡片。** 面板就是面板——统一 20px 圆角、1px 柔丝线边框、白纸背景。工作区是一个大面板，侧栏是透明继承，底栏是无边框条状。禁止嵌套卡片。

### Inputs / Fields
**融入画布的输入区。** 静态时边界低调（发丝线边框），内容区微白底。聚焦时边框切换为鼠尾草绿，附加外圈柔和光晕 (`box-shadow: 0 0 0 2px rgba(111,145,128,0.15)`)。

- **Style:** 16px 圆角，高 30px，12px 字体。
- **Placeholder:** `--pale` (#a0acbb)，不喧宾夺主。

### Navigation
**线性侧栏，无边框。** 左侧栏用透明背景继承 app-shell 玻璃，操作项和项目列表以行内按钮排列。选中态用微白高亮 (`rgba(255,255,255,0.4)`)，hover 态更轻 (`rgba(255,255,255,0.28)`)。折叠态窄至 56px，仅保留图标。

### Sidebar Panels
**右侧信息栏，白纸画板。** 展开时与工作区无缝衔接（gap: 0，共享白纸背景），共同形成一个整体的白色面板。折叠时收窄至 24px，仅显示展开/折叠按钮，不保留任何内容导轨或图标。

## 6. Do's and Don'ts

### Do:
- **Do** 用灰绿作为唯一彩色强调——按钮、选中态、进度条。不超过界面面积的 10%。
- **Do** 用毛玻璃（blur 22px + 72% 白透明）作为 app-shell 基底，工作区以纯白画布从中切出。
- **Do** 用 weight（600 v 400）区分同级字号的标题与正文。
- **Do** 用 1px 细线（hairline: #d7e1ec）和留白替代投影来表达层级关系。
- **Do** 控件在 hover 时浮现反馈，静态时融入背景。
- **Do** 侧栏操作项和项目列表从顶部紧密堆叠，不均匀撑满纵轴空间。

### Don't:
- **Don't** 使用游戏化炫技——拒绝过饱和渐变、霓虹描边、装饰性粒子、无意义动画（PRODUCT.md 反参考）。
- **Don't** 引入第二种彩色强调色。暖琥珀仅用于星标和极低频警告，不扩展至新场景。
- **Don't** 在面板或卡片上使用投影。唯一允许的阴影是 `0 1px 2px rgba(31,37,45,0.06)`，且仅用于 message 提示。
- **Don't** 嵌套卡片。面板即面板。
- **Don't** 用 `border-left` 或 `border-right` 大于 1px 作为彩色侧边条纹装饰。
- **Don't** 用 gradient text（`background-clip: text`）制造文字渐变。
- **Don't** 使用 Premiere / DaVinci 式的深灰工业调性——AI漫剧Agent 是创作伙伴，不是剪辑台。
