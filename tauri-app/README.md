# 抖音袜子发布工具 4.0.30 · Tauri 桌面端

> **关于名称**：项目对外名为「**电商产品发布工具**」；安装包名、应用窗口标题、
> `tauri.conf.json` 的 `productName` 与应用内更新链路仍沿用内部产品名
> 「**抖音袜子发布工具**」。两者指同一个应用，详见根 [README](../README.md)。

基于 **Tauri 2 + Vue 3 + TypeScript + Element Plus** 的桌面端，业务后端是 Python Flask Sidecar。
本目录只是桌面端；共享业务库在仓库根 `src/`，MCP Server 在根 `mcp-server/`。

## 🚀 技术栈

| 层 | 技术 | 依据 |
|---|---|---|
| 桌面壳 | Tauri 2（Rust），窗口 / 拖拽事件 / Sidecar 进程托管 | `src-tauri/Cargo.toml`、`src-tauri/src/main.rs` |
| 前端 | Vue 3.4 + TypeScript 5.3 + Vite 5.1 + Element Plus 2.6 + Pinia 2.1 + vue-router 4.3 + axios | `package.json` |
| 后端 | Python 3.11 + Flask Sidecar（端口 5001） | `python-sidecar/app.py`、`src/services/api.ts` |
| 数据库 | SQLite + Peewee ORM（在根 `src/orm.py`，不在本目录） | 共享业务库 |
| 浏览器自动化 | DrissionPage（根 `src/utils.py` 等） | 共享业务库 |
| 打包 | PyInstaller onefile（sidecar）+ Tauri NSIS（安装包） | `python-sidecar/build_sidecar.py`、`package-release.ps1` |

## 📦 项目结构

```text
tauri-app/
├── src/                        # Vue 3 前端
│   ├── components/             # CaptureSection / SkuList / SettingsPanel / ContextMenu /
│   │                           # OnboardingGuide / ProductMediaManager / WhiteBgPanel /
│   │                           # ShopStatusBar / TaobaoPublishPanel / TaobaoPreflightSummary /
│   │                           # XhsPublishPanel
│   ├── views/                  # ProductManager.vue（主页面）、Settings.vue
│   ├── stores/productStore.ts  # Pinia 状态
│   ├── services/               # api.ts（HTTP + Tauri 命令）、updater.ts（应用内更新）
│   ├── styles/                 # variables.scss / global.scss / components.scss
│   ├── types/index.ts          # 类型定义
│   ├── router/index.ts         # 路由
│   ├── utils/                  # taobaoFormVerification.ts、taobaoTextLength.ts
│   ├── App.vue、main.ts        # 根组件与入口
│   └── auto-imports.d.ts、components.d.ts   # unplugin 自动生成（勿手改）
├── src-tauri/                  # Tauri Rust 壳层
│   ├── src/main.rs             # 窗口、命令、Sidecar 托管
│   ├── tauri.conf.json         # 窗口 / 打包资源 / 更新配置
│   ├── Cargo.toml、Cargo.lock、build.rs
│   ├── capabilities/default.json、icons/、nsis_hooks.nsh
│   └── sidecar/                # Sidecar 打包资源输出目录（构建产物，不入库）
├── python-sidecar/             # Python Flask 后端
│   ├── app.py                  # Flask 应用（依赖组装入口）
│   ├── requirements.txt        # 后端依赖（含 pyinstaller）
│   ├── build_sidecar.py        # PyInstaller 打包脚本（无命令行参数）
│   ├── python-backend.spec     # PyInstaller spec
│   ├── protocol_publish/、protocol_capture/     # 协议化发布 / 采集
│   ├── automation_assets/      # 自动化素材（gitignore）
│   └── README.md               # ⚠️ 内容较旧，命令以本文件与 build_sidecar.py 为准
├── scripts/                    # bump-version.ps1、ci_prepare_build_assets.py
├── runtime/node.exe            # 打包内置的 MCP 运行时（不入库）
├── package.json                # 前端依赖与脚本
├── package-release.ps1         # 一键打包（sidecar → tauri build → 冒烟测试）
├── setup_dev.bat / setup_dev.ps1   # 开发环境配置
├── start_backend.bat / start_backend.ps1   # 已停用，跳回根 start_frontend.bat
├── start_tauri_dev.ps1         # 根 start_frontend.bat 实际调用的启动脚本
├── start_frontend.bat          # 跳回根 start_frontend.bat
├── vite.config.ts、tsconfig.json、index.html
└── README.md
```

## 🛠️ 开发环境要求

本机实测（2026-10-17）：Node.js **v22.22.3**、npm **10.9.8**、Python **3.11.16**、rustc / cargo **1.96.0**。

| 工具 | 最低版本 | 说明 |
|---|---|---|
| Node.js | 18+（`setup_dev.ps1` 的检查阈值） | 实测 22.x |
| Rust | 稳定版工具链（`cargo` / `rustc` 在 PATH 上） | 实测 1.96.0 |
| Python | 3.11+（`setup_dev.ps1` 的检查阈值） | 实测 3.11.16 |
| PyInstaller | 6.0+ | 只在打 sidecar 时需要，已列在 `python-sidecar/requirements.txt` |

## 🔧 快速开始

### 1. 配置开发环境

```powershell
Set-Location tauri-app
.\setup_dev.ps1      # 或双击 setup_dev.bat
```

脚本会检查 Node / Rust / Python，然后 `npm install` + 在仓库根 `pip install -r requirements.txt`。

### 2. 手动安装（可选）

```powershell
Set-Location tauri-app
npm install

Set-Location ..
pip install -r requirements.txt                      # 仓库根，较全
pip install -r tauri-app/python-sidecar/requirements.txt   # sidecar 子集
```

### 3. 开发模式

```powershell
Set-Location tauri-app
npm run tauri:dev      # = tauri dev -- --release，自动起 Vite 并由 Rust 壳拉起 sidecar
```

只调前端时可以 `npm run dev`（纯 Vite，`http://127.0.0.1:1420`），但此时后端需另行可用。

**单独调 sidecar**（一般不需要，Tauri 会自动托管；且 `start_backend.bat` 已停用）：

```powershell
Set-Location tauri-app/python-sidecar
python app.py                          # 非 sidecar 模式：会尝试加载 PySide6 GUI
$env:SIDECAR_MODE = '1'; python app.py  # sidecar 模式：纯后端，监听 5001
```

启动失败先看 `%LOCALAPPDATA%\com.dyin.sock-publisher\logs\python-backend.bootstrap.log`。

### 4. 构建与打包

```powershell
# 仅构建前端（vue-tsc 类型检查 + vite build → dist/）
Set-Location tauri-app
npm run build

# 打包 Python sidecar（必须在 tauri:build 之前；构建前会自动确认 sidecar 没在跑）
Set-Location python-sidecar
python build_sidecar.py            # 产物：tauri-app/src-tauri/sidecar/python-backend.exe
Set-Location ..

# 生产打包（NSIS 安装包 → src-tauri/target/release/bundle/nsis/）
npm run tauri:build

# 一键：sidecar → tauri build → 已打包应用的冒烟测试
npm run package:release

# 需要更新签名产物时直接调脚本（可用参数：-EmitUpdaterManifest / -ReleaseNotes "..." /
# -SkipSidecarBuild / -SkipSmokeTest），会另出 ASCII 改名的安装包与 latest.json
powershell -ExecutionPolicy Bypass -File .\package-release.ps1 -EmitUpdaterManifest -ReleaseNotes "说明"
```

注意事项：

- `src-tauri/sidecar/` 是 `tauri.conf.json` 里 `"sidecar/*": "./"` 的采集源，**只允许放打包资源**
  （`python-backend.exe` + `sqlite.db` / `cfg.yaml` / `pricing_config.json` / `user_settings.json` / `trending_keywords.db` 共 6 个文件）。
  `build_sidecar.py` 会把白名单外的文件挪到 `tauri-app/_sidecar_backups/`，仍有杂物时直接让构建失败。
- 构建前必须停掉正在运行的 sidecar，否则 PyInstaller 会在最后一步写 exe 时报 `PermissionError`；
  `build_sidecar.py` 会提前检查 5001 端口与 exe 占用并给出提示。
- 打包内置的 `runtime/node.exe` 不入库，用 `python scripts/ci_prepare_build_assets.py` 生成。
- 本机现存产物实测体积（2026-10-17）：sidecar exe 87.0 MB、壳 exe 7.1 MB、NSIS 安装包 113.8 MB。

## 🔌 端口

| 端口 | 用途 | 写在哪 |
|---|---|---|
| 1420 | Vite dev server | `vite.config.ts`（`strictPort`）、`tauri.conf.json` 的 `devUrl` |
| 5001 | Python Flask Sidecar | `src/services/api.ts` 的 `BACKEND_URL` |

改这两个端口要同步改两处；改动 5001 还需核对 `src-tauri/src/main.rs` 的健康检查与终止逻辑。

## 📋 从 v3.0 迁移说明

| 项目 | v3.0 | v4.0 |
|---|---|---|
| 桌面框架 | PySide6 + QtWebEngine | Tauri 2（Rust） |
| 前端技术 | HTML/CSS/JS + Layui | Vue 3 + Element Plus |
| 渲染引擎 | QtWebEngine | 系统 WebView2（NSIS 内置 bootstrapper） |
| 类型系统 | 无 | TypeScript |
| 状态管理 | 无 | Pinia |

更完整的设计与迁移规格见 [`../docs/TAURI_MIGRATION_SPEC.md`](../docs/TAURI_MIGRATION_SPEC.md)。

**保持不变**：Flask 后端接口、SQLite + Peewee 数据结构、DrissionPage 自动化、视觉设计规格与核心业务逻辑。
共享业务库仍在仓库根 `src/`，Sidecar 通过注入 `sys.path` 直接 import，没有复制一份。

## 🎨 设计规格

设计令牌集中在 `src/styles/variables.scss`（2026-10-17 核对一致）：

```scss
--primary-color: #5c7cfa;   // 主色
--success-color: #69db7c;   // 成功
--warning-color: #ff8cc8;   // 警告
--danger-color:  #ff8a80;   // 危险
--radius-sm: 8px; --radius-md: 12px; --radius-lg: 20px;
```

## 📡 主要 API 接口

接口实现在 `python-sidecar/app.py`（同时用 `@app.route` 与 `@app.get` / `@app.post` 注册，
grep 路由时两种都要搜）。改接口必须同步 `src/services/api.ts`、`src/types/index.ts`、Pinia store 与相关视图。

### 产品管理
- `GET /api/products` - 获取产品列表
- `GET /load_detail?_id={id}` - 获取产品详情（`images=false` 可跳过 Base64 图片）
- `POST /save_info` - 保存产品信息
- `POST /delete_sku` - 删除 SKU
- `DELETE /delete_all` - 清空所有产品
- `GET /health` - 健康检查

### 智能标题 / 定价
- `POST /api/generate_smart_title` - 标准版标题生成
- `POST /api/generate_smart_title_enhanced` - 增强版标题生成
- `POST /api/pricing/calculate_smart_prices` - 智能价格计算

### 采集
- `POST /api/capture/start` - 开始采集
- `GET /api/capture/status/{task_id}` - 采集状态
- `POST /api/capture/cancel/{task_id}` - 取消采集
- `GET /api/capture/history` - 采集历史
- `POST /api/capture/import` - 导入采集结果

其余路由前缀：`/api/upload/*`、`/api/debug/browser/*`、`/api/shop/*`、`/api/protocol/fxg/*`、
`/api/ops/*`、`/api/whitebg/*`、`/settings*`。

## 🐛 常见问题

**Q: 后端起不来？**
A: 先看 `%LOCALAPPDATA%\com.dyin.sock-publisher\logs\python-backend.bootstrap.log`，再确认依赖：
`pip install -r tauri-app/python-sidecar/requirements.txt`。

**Q: Tauri 编译失败？**
A: 确认 Rust 工具链可用（`rustc --version`、`cargo --version`），并检查 `src-tauri/target/` 是否被其它进程占用。

**Q: 前端样式不生效？**
A: `sass` 已在 `devDependencies` 里，先 `npm install`；改动 SCSS 后重启 `npm run dev` / `npm run tauri:dev`。

**Q: 文件拖拽不工作？**
A: 确认 `tauri.conf.json` 里 `app.windows[0].dragDropEnabled` 为 `true`
（Tauri 2 的键名是 `dragDropEnabled`，不是旧文档里的 `fileDropEnabled`）。

**Q: 改了 `app.py` 但界面没变化？**
A: 生产/日常启动用的是冻结的 sidecar，需重建 sidecar 再重启应用：
`python python-sidecar/build_sidecar.py`；只改了 `.vue` 则 `npm run build` 后 `npm run tauri:build`。

## 📚 相关文档

| 文档 | 用途 |
|---|---|
| [`../AGENTS.md`](../AGENTS.md) / [`../CLAUDE.md`](../CLAUDE.md) | 项目约定、架构与全部常用命令 —— 改动前必读 |
| [`../README.md`](../README.md) | 对外说明、下载与从源码构建 |
| [`../docs/TAURI_MIGRATION_SPEC.md`](../docs/TAURI_MIGRATION_SPEC.md) | v3.0 → v4.0 迁移规格 |
| [`../project-status.md`](../project-status.md) | 当前项目状态 |

## 📄 许可证

仓库内**没有** `LICENSE` 文件（2026-10-17 实测）；根 [README](../README.md) 的结论是「本仓库当前未声明许可证」。
`package.json` 与 `src-tauri/Cargo.toml` 中的 `"license": "MIT"` 只是包管理字段，不代表仓库已附许可证文本。
