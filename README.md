# 电商产品发布工具

把「商品采集 → 资料整理 → 多平台发布」封装成本地桌面客户端的多平台电商发布工具。

> **关于名称**：项目对外名为 **电商产品发布工具**；发行物的内部产品名是 **抖音袜子发布工具**
> —— `tauri.conf.json` 的 `productName` 与应用窗口标题都用它，本地打包出的安装包是
> `抖音袜子发布工具_<版本>_x64-setup.exe`；发布到 GitHub 时由 `.github/workflows/release.yml`
> 的 `ASSET_PREFIX` 重命名为 ASCII 资产名 `DouyinSockPublisher_<版本>_x64-setup.exe`，
> 应用内更新读的就是后者。两者指同一个应用；统一改名会牵动发布工作流与更新签名，故暂按现状并存。

---

## 覆盖平台

| 平台 | 现状 | 代码位置 |
|---|---|---|
| 抖音（抖店 `fxg.jinritemai.com`） | 主链路，已用于日常发布 | `tauri-app/python-sidecar/app.py`、`src/`、`mcp-server/` |
| 淘宝（千牛 / 发布工作台） | 资料准备与表单链路，进行中 | `taobao-publisher/` |
| 小红书（千帆） | 表单测绘与部分链路，进行中 | `xiaohongshu-publisher/` |

## 架构

Tauri 2 桌面壳 + Vue 3 前端 + Python Flask Sidecar + 共享 Python 业务库，
四层通过本地 HTTP 与进程托管协作：

- **Tauri Rust 壳层**（`tauri-app/src-tauri/`）：窗口、Sidecar 进程托管
  （启动 / 健康检查 / 强杀 / 日志重定向）。文件拖拽事件在 Rust 侧只开了
  `tauri.conf.json` 的 `dragDropEnabled`，实际的 `onDragDropEvent` 处理在前端 `App.vue`。
- **Vue 3 前端**（`tauri-app/src/`）：Vue 3 + TypeScript + Element Plus + Pinia。
  视图为 `views/ProductManager.vue`（主页面）与 `views/Settings.vue`。
- **Python Sidecar**（`tauri-app/python-sidecar/app.py`）：Flask 入口，承载产品 CRUD、
  链接采集、智能标题与定价、商品发布、CDP 调试浏览器、协议化上传、运营闭环与设置管理。
- **共享业务库**（`src/`）：ORM、浏览器自动化、运营闭环、白底图语义抠图等。

## 下载安装

安装包发布在 GitHub Releases：

- 最新版：<https://github.com/CHEN126110/douyin-auto-uploader-/releases/latest>
- v4.0.30 直链：
  `https://github.com/CHEN126110/douyin-auto-uploader-/releases/download/v4.0.30/DouyinSockPublisher_4.0.30_x64-setup.exe`
- 应用内更新源：`https://github.com/CHEN126110/douyin-auto-uploader-/releases/latest/download/latest.json`

## 从源码构建

前置：Node.js、Rust 工具链、Python 3.11。

```powershell
git clone https://github.com/CHEN126110/douyin-auto-uploader-.git
cd douyin-auto-uploader-
git checkout DouYin

# 1) 前端依赖
cd tauri-app
npm install

# 2) mcp-server 依赖（必须装）
#    tauri.conf.json 的 bundle.resources 会把整个 mcp-server 目录打进安装包，
#    而 node_modules 被 .gitignore 排除 —— 不装的话装机后内置 MCP 一启动就
#    ERR_MODULE_NOT_FOUND。CI 里同样有这一步，见 .github/workflows/release.yml。
cd ../mcp-server
npm install

# 3) 补齐打包前置资产：sqlite.db / trending_keywords.db / user_settings.json（根与 tauri-app 各一份）
#    以及 runtime/node.exe（该文件不入库）
cd ../tauri-app
python scripts/ci_prepare_build_assets.py

# 4) 构建 Python sidecar，产物落 src-tauri/sidecar/（构建产物不入库）
cd python-sidecar
pip install -r requirements.txt
python build_sidecar.py

# 5) 打包桌面应用
cd ..
npm run tauri:build -- --no-bundle           # 只产出可执行文件
npm run tauri:build                          # 产出 NSIS 安装包
```

启动桌面端用根目录 `start_frontend.bat`：它**默认直接运行已构建的**
`tauri-app/src-tauri/target/release/douyin-sock-publisher.exe`，不重新编译；
需要编译时用 `start_frontend.bat --dev`。其余启动类 `.bat`（`start_backend.bat`、
`tauri-app/` 下的同名脚本）都跳回它；例外是 `tauri-app/setup_dev.bat`，那是独立的环境安装脚本。

可选——白底图语义抠图需另装模型（不进仓库、不进安装包）：

```powershell
$env:PYTHONPATH = 'src'
python -m whitebg.setup_models        # 默认组合（birefnet-general + CLIP）约 1.1 GB
```

默认只下 `birefnet-general` + CLIP，约 **1.1 GB**；若再加 `bria-rmbg`（约 0.98 GB，
⚠️ CC BY-NC 4.0 非商用）与 `isnet-general-use`（约 0.17 GB），合计约 2.2 GB。

## 测试

```powershell
# Python：必须在仓库根目录运行（测试自行把仓库根注入 sys.path）
python -m pytest tests

# mcp-server
cd mcp-server
npm run check        # node --check 覆盖所有脚本
npm run test:ops     # node --test tests/*.test.mjs
```

## 目录结构

```
2.1/
├── start_frontend.bat          # 桌面端统一启动入口（其余 .bat 都跳回它）
├── AGENTS.md / CLAUDE.md       # 项目约定与架构说明（改动前先读）
├── src/                        # 共享 Python 业务库（Sidecar 直接 import）
│   ├── utils.py                # DrissionPage 浏览器自动化
│   ├── orm.py                  # Peewee + SQLite + 列迁移
│   ├── ops_engine.py           # 运营闭环（只做本地规则计算 + 账本读写）
│   ├── sidecar/                # 图片 / 白底图 / 更新 / 小红书 接口 Blueprint
│   └── whitebg/                # 白底图语义抠图流水线
├── tauri-app/                  # 桌面应用
│   ├── src/                    # Vue 3 前端
│   ├── src-tauri/              # Rust 壳层
│   ├── python-sidecar/         # Flask Sidecar 与 build_sidecar.py
│   └── scripts/                # 构建辅助脚本
├── mcp-server/                 # 把 Sidecar 暴露为 MCP 工具 + 独立 CDP 工具
├── taobao-publisher/           # 淘宝发布路线
├── xiaohongshu-publisher/      # 小红书发布路线
├── protocol-research-clean-20260505/   # 协议研究（只输出脱敏产物）
├── tests/                      # Python 回归测试
├── lab/whitebg/                # 白底图实验室（实测证据在 out/）
└── docs/                       # 历史调研、方案与复盘
```

## 端口

| 端口 | 用途 |
|---|---|
| 1420 | Vite dev server |
| 5001 | Python Flask Sidecar |
| 9333 | Chrome 远程调试（协议研究只读探针） |
| 3300 | MCP Streamable HTTP |

## 文档

| 文档 | 用途 |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | 项目约定、架构、常用命令 —— **改动前必读** |
| `tauri-app/README.md` | 桌面端说明 |
| `docs/TAURI_MIGRATION_SPEC.md` | v3.0 → v4.0 迁移规格 |
| `lab/whitebg/README.md` | 白底图多场景实测结论 |
| `protocol-research-clean-20260505/AGENTS.md` | 协议研究的硬约束 |

## 许可

仓库根目录**没有 `LICENSE` 文件**，也没有根级许可证声明。各包的清单文件里另有声明：
`tauri-app/package.json` 与 `tauri-app/src-tauri/Cargo.toml` 写的是 MIT，
`mcp-server/package.json` 写的是 ISC —— 这些只是包管理字段，不构成仓库级授权。
若要公开分发，建议补一份正式的 `LICENSE`。
