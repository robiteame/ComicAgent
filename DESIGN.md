# Design System

## Scene Sentence
一个自媒体创作者在周末下午的窗边桌前，阳光透过百叶窗洒在笔记本上，用自然语言描述一个校园甜宠故事，看着 AI 逐帧生成漫剧分镜，像翻阅一本正在绘制的漫画手稿。

## Theme
Light. 阳光、空气感、透明层次。

## Color Strategy
Committed. 蓝色作为品牌识别色，白色为主调，毛玻璃构建空间层次。

## Colors (OKLCH)
- Brand Primary: oklch(0.55 0.15 250) - 天际蓝，自然不刺眼
- Brand Hover: oklch(0.50 0.17 250) - 深一点的蓝
- Brand Light: oklch(0.92 0.04 250) - 极淡蓝，用于选中背景
- Surface: oklch(0.985 0.003 250) - 近乎白，带极微蓝调
- Surface Alt: oklch(0.96 0.008 250) - 淡蓝灰，面板底色
- Glass: rgba(255, 255, 255, 0.72) + backdrop-blur(20px) - 毛玻璃
- Glass Border: rgba(255, 255, 255, 0.5) - 毛玻璃边框
- Text Primary: oklch(0.20 0.015 250) - 深蓝黑
- Text Secondary: oklch(0.50 0.02 250) - 中灰蓝
- Text Tertiary: oklch(0.65 0.02 250) - 浅灰
- Border: oklch(0.90 0.015 250) - 淡蓝灰线
- Accent Green: oklch(0.65 0.15 150) - 成功
- Accent Amber: oklch(0.75 0.15 80) - 进行中
- Accent Red: oklch(0.55 0.18 25) - 错误/危险

## Typography
- Font: "Noto Sans SC", -apple-system, "Segoe UI", system-ui, sans-serif
- Display: 28px / 700 / -0.02em
- Heading: 20px / 600 / -0.01em
- Body: 14px / 400 / 0
- Caption: 12px / 400 / 0.01em
- Mono: "JetBrains Mono", "Fira Code", monospace, 13px

## Spacing
Base: 4px. Scale: 4, 8, 12, 16, 24, 32, 48, 64

## Elevation
Glassmorphism 层次体系:
- Level 0: 纯白底 (surface)
- Level 1: 毛玻璃面板 (glass + blur 12px)
- Level 2: 毛玻璃浮层 (glass + blur 20px, slight shadow)
- Level 3: 毛玻璃弹出 (glass + blur 24px, shadow)

## Motion
- 200ms ease-out 大多数过渡
- 300ms ease-out-quart 页面切换
- 不动画布局属性

## Components
- Sidebar: 毛玻璃，图标优先，极窄
- Cards: 毛玻璃背景，无实线边框
- Buttons: 实色 primary，ghost secondary
- Inputs: 底线或极细边框，毛玻璃聚焦态
- Tags/Badges: 半透明蓝底
