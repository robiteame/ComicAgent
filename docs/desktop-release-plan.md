# 桌面版多平台发布方案(探索稿)

> 目标:发布 macOS / Windows(可选 Linux)的正式 Release 版本;用户安装后**无需自装 Python 与依赖**,启动桌面版即自动拉起后台 FastAPI 服务。

## 1. 现状盘点

已经具备的能力:

- `client/electron-builder.yml`:asar 打包、`extraResources` 携带 `server/` 源码、排除运行期数据与 `.env`。
- `client/src/main/main.ts`:打包态启动时已实现——spawn 后端进程、30s 健康探测(`/health` + service 标识校验)、随机 token 本地鉴权、单实例锁、`before-quit` 回收子进程。**"自动启动后台服务"的壳已就绪,缺的是自带 Python 运行时**。
- `server/requirements.lock`:带多平台 hash 的 universal lock,CI(`ci.yml`)已在 Python 3.11 上用它做可复现安装。

核心缺口:

| # | 缺口 | 位置 |
|---|------|------|
| 1 | 打包态用**系统 Python** 启动后端,用户必须自装 Python 3.11+ 与全部 pip 依赖 | `client/src/main/main.ts:199-204` |
| 2 | FFmpeg 依赖系统 PATH,未随 app 分发 | `server/main.py:161`(`shutil.which("ffmpeg")`) |
| 3 | 无发布流水线:`ci.yml` 只跑测试;electron-builder 未配置 targets / publish | `.github/workflows/ci.yml`、`electron-builder.yml` |
| 4 | **现成 bug**:extraResources filter 漏了 `.venv`,当前 dmg(131MB)里 142MB 是开发机 venv 死重(运行时根本不用) | `client/electron-builder.yml` filter 列表 |

## 2. 后端打包选型(核心决策)

| 方案 | 思路 | 优点 | 缺点 |
|------|------|------|------|
| A. PyInstaller 冻结 | 把 `server/main.py` 冻结成每平台独立可执行 | 单文件入口、生态教程多 | langgraph/langchain 动态导入需长期维护 hidden-imports;bootloader 是杀软误报重灾区(需 onedir + 代码签名缓解);每次调依赖都可能重调 spec |
| **B. python-build-standalone + uv(推荐)** | 随 app 附带完整**可重定位** CPython(PBS,现由 Astral 维护,即 uv 装的那种),构建期把生产依赖直接装进其 site-packages | 真解释器:一切动态导入天然可用;无冻结/误报问题;JupyterLab Desktop 同路线;PBS 二进制按相对路径解析 prefix,放进 .app/Resources 即可 relocation | 安装包增大(估算每平台 200–280MB) |
| C. 首次启动联网引导 | 安装包只带 `requirements.lock`,首启由 uv 联网装运行时 | 安装包最小(~30MB) | 首启必须联网、失败面大、离线不可用;不建议做默认,可留作"修复/精简"通道 |

**推荐 B**,理由:本项目依赖面(langgraph、langchain、pydantic v2 原生扩展、aiohttp、Pillow)决定了"真解释器"路线最省心;PBS 可重定位特性与 Electron `extraResources` 的组合已被 JupyterLab Desktop 等验证;构建期用 `uv pip install --require-hashes -r requirements.lock` 直接复用现有锁文件,可复现性与 CI 一致。

体积参考:本地 `server/.venv` 255MB(含 dev 依赖、未压缩);生产依赖压缩后约 60–90MB + PBS 运行时压缩约 30–50MB + Electron 约 100MB → 每平台安装包估 200–280MB,与 JupyterLab Desktop 同量级,可接受。

## 3. 目标架构

### 3.1 包内布局(extraResources)

```text
ComicAgent.app/Contents/Resources/        (win: resources/)
├── server/            # 现有 Python 源码(严格排除 .venv/.env/data/脚本)
├── python/            # PBS 运行时 + 构建期装好的 site-packages
└── bin/ffmpeg         # 每平台静态 ffmpeg 二进制
```

### 3.2 构建期(每平台各跑一次)

1. `uv python install 3.12`(取 PBS 发行版;版本钉死,与 lock 兼容性已由 CI 在 3.11 验证、本机 3.14 验证,3.12 是全平台 wheel 覆盖最稳的选择)
2. `uv pip install --python <PBS>/bin/python --require-hashes -r server/requirements.lock`
   —— 直接装进 PBS 自带 site-packages,**不建 venv**,规避 `pyvenv.cfg`/shebang 绝对路径问题
3. 下载对应 OS/arch 的静态 ffmpeg 到 `bin/`
4. `pnpm build` → electron-builder 打包并把上述目录按 `extraResources` 收进安装包

### 3.3 运行期(改动集中在 main.ts,均为小改)

- spawn 目标从系统 `python3` 改为 `resources/python/bin/python3`(win 为 `python/python.exe`);保留 `COMIC_AGENT_PYTHON` 环境变量作调试逃生口
- spawn 的 `env.PATH` 头部插入 `resources/bin`,让 `shutil.which("ffmpeg")` 命中捆绑二进制,`server/` 零改动
- 健康探测、token、单实例、优雅退出逻辑**原样保留**

## 4. 发布流水线(GitHub Releases)

新增 `.github/workflows/release.yml`,push tag `v*` 触发,matrix 构建:

| runner | 目标 | 产物 |
|--------|------|------|
| `macos-14`(arm64) | dmg + zip | `ComicAgent-<ver>-arm64.dmg` |
| `macos-13`(x64) | dmg + zip | `ComicAgent-<ver>-x64.dmg` |
| `windows-latest`(x64) | nsis + zip | `ComicAgent-Setup-<ver>.exe` |
| `ubuntu-latest`(可选,后置) | AppImage | `ComicAgent-<ver>.AppImage` |

说明:

- Python 侧必须与 Electron 侧同 OS/arch 构建成套,因此不走 macOS universal(PBS 有 universal2,但 pydantic-core 等原生 wheel 大多无 universal2),分架构出包。
- `electron-builder.yml` 补充:显式 `mac.target/win.target`、`artifactName` 含版本与 arch、`publish: { provider: github, owner: robiteame, repo: ComicAgent }`;CI 注入 `GH_TOKEN`,由 electron-builder 直传 GitHub Releases(自动带 latest.yml 支撑以后做自动更新)。
- 版本单一来源 `client/package.json`,发版流程 = bump version → push tag。

## 5. 签名与公证(发布形态的决策点)

- **macOS**:无 Developer ID 时 Gatekeeper 直接拦("已损坏")。正式对外必须 Apple Developer($99/年),CI 注入 `CSC_LINK`/`CSC_KEYCHAIN_PASSWORD` + 公证四件套(`APPLE_ID`/`APPLE_APP_SPECIFIC_PASSWORD`/`APPLE_TEAM_ID`);**公证会校验包内所有可执行文件**,extraResources 里的 PBS 二进制/dylib 需要一并重签(electron-builder 的签名配置或 afterSign hook 覆盖)。内测期可先发未签名版,README 注明 `xattr -cr` 绕过。
- **Windows**:无证书则 SmartScreen 警告,内测可接受;正式发布建议 OV/EV 代码签名证书。
- **FFmpeg 许可**:选静态构建时优先 LGPL 变体;若用 GPL 构建(含 x264),以独立进程、独立二进制分发 + 附许可文本与源码获取说明,是业界普遍做法,风险低,发布页需列第三方声明。

## 6. 分阶段实施

| 阶段 | 内容 | 产出 |
|------|------|------|
| 0(立即) | filter 增加 `!**/.venv/**`;顺手排除 `!.pytest_cache` 等开发残留 | dmg 131MB → ~30MB(纯源码态) |
| 1 | `scripts/build-python-runtime.sh`:uv 构建 runtime 目录;main.ts 改 spawn 捆绑解释器 + PATH 插入 ffmpeg;ffmpeg 下载脚本 | 本地 arm64 一键出"零依赖"dmg,真机验证 |
| 2 | `release.yml` 三平台 matrix + GitHub Releases 自动发布(未签名);README 增加"下载安装"章节 | tag 即发版 |
| 3 | 代码签名 + macOS 公证(拿到证书后);Linux AppImage;latest.yml 自动更新 | 正式对外形态 |

## 7. 风险与开放问题

- PBS 在 mac .app 内 + 公证重签的组合需要阶段 1/2 实测一次(已知 JupyterLab Desktop 可行,注意 `DYLD` 环境变量不继承即可,我们 spawn 不传)。
- `uvicorn[standard]` 里的 uvloop 无 Windows wheel,pip 自动跳过、fallback 到 asyncio——现有 universal lock 已兼容,无动作。
- 安装包 200MB+ 的下载体验:GitHub Releases 带断点续传,可接受;若未来要瘦,再评估裁剪 langchain 子包。
- 需要决策:macOS 是否首发 x64(用户群 Windows 为主?)——当前仓库只有 arm64 mac 构建记录,先 arm64 后补 x64 亦可。

## 参考

- [Astral 接管 python-build-standalone](https://astral.sh/blog/python-build-standalone) / [PBS 仓库](https://github.com/astral-sh/python-build-standalone)
- [Simon Willison: Python inside Electron](https://til.simonwillison.net/electron/python-inside-electron)
- [JupyterLab Desktop(捆绑 Python 先例)](https://discourse.jupyter.org/t/how-to-package-python-with-electron-how-does-jupyterlab-do/18126)
- [PyInstaller 杀软误报问题追踪](https://github.com/pyinstaller/pyinstaller/issues/6754)
- [electron-python-example(PyInstaller 路线参考)](https://github.com/fyears/electron-python-example)
