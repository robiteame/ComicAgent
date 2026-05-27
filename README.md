# ComicAgent

Electron + React + FastAPI 的漫剧 Agent 桌面端。当前主链路已打通：

1. Agent 自动生成完整漫剧剧本。
2. 根据剧本生成规范分镜列表和分镜参考画面。
3. 用户可手动修改分镜并确认定稿。
4. 系统基于定稿分镜渲染镜头画面、合成对白音频、拼接输出可播放视频。

## 端口

- 后端：`http://127.0.0.1:8011`
- 前端：`http://127.0.0.1:5173`

使用 `127.0.0.1` 是为了避免 Windows/Electron 环境中 `localhost` 解析到不可用地址。

## 开发启动

后端：

```bash
cd server
python main.py
```

桌面端：

```bash
cd client
pnpm run electron:dev
```

仅启动网页前端：

```bash
cd client
pnpm dev
```

`pnpm dev` 会显式监听 `127.0.0.1:5173`，与 Electron 加载地址保持一致。

## 全链路冒烟测试

后端启动后执行：

```bash
cd server
python scripts/full_flow_smoke.py
```

成功标志：

```text
FULL_FLOW_OK
```

测试脚本会验证：自动剧本生成、分镜和参考图生成、手动修改分镜、确认分镜、最终视频生成，并校验 `output/projects/{project_id}/output/final.mp4` 非空。

更详细的测试说明见 [docs/FULL_FLOW_TEST.md](docs/FULL_FLOW_TEST.md)。

## 常用检查

前端：

```bash
cd client
pnpm exec tsc --noEmit
pnpm exec vite build
```

后端：

```bash
cd server
python -m compileall .
python scripts/full_flow_smoke.py
```
