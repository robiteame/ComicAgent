# 全链路测试说明

本项目默认后端端口为 `8011`，前端开发端口为 `5173`。之所以不用 `8010`，是因为本机可能已有旧服务占用该端口，容易让前端连到旧接口。

## 启动

```bash
cd server
python main.py
```

另开一个终端：

```bash
cd client
pnpm dev
```

`pnpm dev` 会显式监听 `127.0.0.1:5173`，与 Electron 加载地址保持一致。

桌面端启动：

```bash
cd client
pnpm run electron:dev
```

## 自动冒烟测试

在后端服务已启动后执行：

```bash
cd server
python scripts/full_flow_smoke.py
```

成功时应看到：

```text
PROJECT ...
SCRIPT ... chars
STORYBOARD ... shots
EDIT ok
CONFIRM ok
VIDEO ... final.mp4 ... bytes
FULL_FLOW_OK
```

该脚本覆盖：

- Agent 自动生成完整漫剧剧本。
- 根据剧本生成分镜列表和参考画面。
- 手动修改第一个分镜并标记为需要重新渲染。
- 确认分镜后自动生成镜头画面、配音音频并合成最终视频。
- 校验项目状态为 `completed` 且 `output/projects/{project_id}/output/final.mp4` 非空。

## 手动 UI 验收

1. 打开桌面端或 `http://127.0.0.1:5173`。
2. 点击左侧新建项目，在工作区输入项目名并创建。
3. 点击 `AI写剧本`，等待剧本文本自动生成并进入分镜生成。
4. 右侧运行日志应显示剧本解析、分镜生成、参考画面等步骤。
5. 分镜参考图出现后，可在右侧修改镜头类型、情绪、机位、时长、场景描述或对白。
6. 点击主预览区的 `确认分镜并继续`。
7. 等待画面生成、配音生成、视频合成、质量校验完成。
8. 主工作区切换到 `成片`，最终视频应显示原生播放控件并可直接播放。

## 常用校验命令

```bash
cd client
pnpm exec tsc --noEmit
pnpm exec vite build
```

```bash
cd server
python -m compileall .
python scripts/full_flow_smoke.py
```
