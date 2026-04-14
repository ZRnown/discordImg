# Discord Marketing Desktop (Tauri)

这是 `discord-marketing-system` 的 Windows 桌面版，目标是：

- 保留原项目核心业务能力（账号与规则、抓取、以图搜图、日志、机器人控制等）
- 去掉多用户管理能力（桌面版固定单用户模式）
- 复用原前端样式和组件体系（Next.js + Tailwind + shadcn UI）
- 通过 GitHub Actions 自动产出可安装的 Windows EXE

## 桌面版关键点

- 前端使用原 `frontend/` 项目，静态导出后由 Tauri 内置 WebView 加载
- 后端仍是原 `backend/app.py`，由 Tauri 启动本地 sidecar 进程
- 后端以 `DESKTOP_SINGLE_USER=1` 运行，自动使用本地单用户上下文
- 数据目录支持 `APP_DATA_DIR`，可写入用户目录，避免安装目录权限问题
- 已接入 `manageLicense` 授权系统，默认授权服务器 `http://107.172.1.7:8888`
- 首次启动会先显示授权激活页，输入密钥后才能进入主系统
- 授权请求内置指数退避重试（默认 4 次，可通过环境变量调整）
- 当前设备激活后会写入本地授权信息，并禁止重复激活（同设备只允许激活一次）
- 新增桌面握手检测：若 5001 端口被其他程序占用，会提示后端冲突而不是静默异常
- 新增全局代理设置入口：侧边栏 `系统设置` 可配置 HTTP/HTTPS 代理，抓取实时生效

## 本地开发

1. 安装依赖

```bash
pnpm install
pnpm --dir frontend install
python3 -m pip install -r backend/requirements.txt
```

2. 启动桌面开发模式

```bash
pnpm start
# 或 pnpm desktop:dev
```

> `pnpm start` 会一条命令同时启动桌面窗口 + 前端 + 后端（后端由 Tauri 自动拉起）。

3. 本地只构建前端静态文件（不会打开窗口）

```bash
pnpm --dir frontend build:desktop
```

说明：
- Tauri 会先启动前端开发服务器（`127.0.0.1:1420`）
- 应用启动时自动拉起后端 `backend/app.py`
- 可通过环境变量覆盖授权服务器：`LICENSE_SERVER_URL=http://107.172.1.7:8888`
- 可调重试参数：`LICENSE_RETRY_ATTEMPTS`、`LICENSE_RETRY_BASE_DELAY`、`LICENSE_RETRY_MAX_DELAY`

## 本地打包（当前平台）

```bash
pnpm desktop:build
```

打包流程会自动执行：
- 构建前端静态产物
- 使用 PyInstaller 生成后端 sidecar
- 调用 Tauri 进行桌面应用打包

## Windows 一键运行说明

- 安装生成的 Windows 安装包（NSIS）后，双击桌面应用图标即可启动
- 应用启动时会自动拉起内置后端 sidecar，无需再手工启动任何服务

## GitHub Actions（Windows EXE）

工作流文件：`.github/workflows/build-windows-exe.yml`

支持触发方式：
- `workflow_dispatch` 手动触发
- 推送到 `main` 分支自动触发

产物：
- 通过 `tauri-action` 生成 Windows 安装包（NSIS）
- 自动附加到 Draft Release
