# 项目状态（当前）

> 最后核对：2026-10-17
>
> 本文件此前是 2026-01-08 ~ 2026-01-09 的会话工作日志（Tauri 迁移初期、淘宝/1688 链接采集调试）。
> 它引用的 `项目备份/`、`项目备份/capture_service.py`、`app3.0版本/`、旧相对路径 `python-sidecar/`
> 以及「总体进度 95%」这类完成度条**都已失效**，因此于 2026-10-17 重写为当前状态说明。
> 旧日志没有丢，可从 git 取回：`git show ff01f9e:project-status.md`。

---

## 一、身份与版本

| 项 | 当前值 | 核实依据（2026-10-17） |
|---|---|---|
| 对外名 | **电商产品发布工具** | 根 `README.md` |
| 内部产品名 | **抖音袜子发布工具**（安装包名、窗口标题、`productName`、应用内更新链路仍用它） | `tauri-app/src-tauri/tauri.conf.json` |
| 版本 | **4.0.30** | `tauri-app/package.json`、`tauri-app/src-tauri/tauri.conf.json`、`tauri-app/src-tauri/Cargo.toml` 三处一致 |
| 应用标识符 | `com.dyin.sock-publisher`（数据目录 `%LOCALAPPDATA%\com.dyin.sock-publisher\`） | `tauri.conf.json` 的 `identifier` |
| 仓库路径 | `C:\Users\CRB\Desktop\2.1` | — |
| 分支 / 提交 | `DouYin` / `ff01f9e`（2026-10-17） | `git rev-parse --abbrev-ref HEAD`、`git log --oneline -3` |

`main` 分支只有一个 initial commit（仅 README.md），**不要据 `main` 判断项目是空的**；代码以 `DouYin` 分支为准。

## 二、技术栈

- **桌面壳**：Tauri 2（Rust，`tauri-app/src-tauri/`）。窗口、文件拖拽事件、Sidecar 进程托管（启动 / 健康检查 / 强杀 / 日志重定向）都在这一层。
- **前端**：Vue 3.4 + TypeScript 5.3 + Vite 5.1 + Element Plus 2.6 + Pinia 2.1 + vue-router 4.3 + axios（版本取自 `tauri-app/package.json`）。
- **后端**：Python 3.11 + Flask Sidecar（`tauri-app/python-sidecar/app.py`，约 1.48 万行）；sidecar 模式下监听 5001，纯后端，非 sidecar 模式仍会尝试加载 PySide6 GUI（保留 v3.0 行为）。
- **共享业务库**：`src/`（Peewee + SQLite ORM 与列迁移、DrissionPage 浏览器自动化、运营闭环、白底图语义抠图等），被 Sidecar 直接 import。
- **MCP**：`mcp-server/`（Node.js），把 Sidecar 的 5001 暴露为 MCP 工具，并附一组独立 CDP 工具与只读探针。
- **打包**：PyInstaller onefile（sidecar，产出 `tauri-app/src-tauri/sidecar/python-backend.exe`）+ Tauri NSIS 安装包。

## 三、平台覆盖现状

| 平台 | 现状 | 代码位置 |
|---|---|---|
| 抖音（抖店 `fxg.jinritemai.com`） | 主链路，已用于日常发布 | `tauri-app/python-sidecar/app.py`、`src/`、`mcp-server/` |
| 淘宝（千牛 / 发布工作台） | 只读链路可跑（CDP 会话探测、发布前置检查、契约门与本地资料包）；**自动发布未就绪** | `taobao-publisher/` |
| 小红书（千帆 `ark.xiaohongshu.com`） | 表单测绘与部分链路，进行中 | `xiaohongshu-publisher/` |

> 淘宝能否发布以它自己的就绪度命令为准：`cd taobao-publisher; python -m taobao_publish readiness`。
> 该子项目 README（2026-10-02 / 10-03 记录）的结论是「是否存在可用发布路线：否」，本次核对**未重跑**该命令。

## 四、目录结构（2026-10-17 实测）

```text
2.1/
├── start_frontend.bat          # 桌面端唯一启动入口（默认直接跑已构建 EXE，--dev 才编译）
├── start_backend.bat           # 已停用，跳回 start_frontend.bat
├── start-hidden.vbs            # 无窗口启动包装
├── src/                        # 共享 Python 业务库（Sidecar 直接 import）
│   ├── sidecar/                # 图片 / 白底图 / 更新 / 小红书 等接口 Blueprint
│   └── whitebg/                # 白底图语义抠图流水线
├── tauri-app/                  # 桌面端（Vue 前端 + Rust 壳 + Flask Sidecar）
├── mcp-server/                 # MCP Server（stdio / HTTP）与 CDP 只读探针
├── taobao-publisher/           # 淘宝路线（独立子项目）
├── xiaohongshu-publisher/      # 小红书路线（独立子项目）
├── protocol-research-clean-20260505/   # 当前唯一允许扩展的协议研究目录
├── protocol-research/          # 历史协议研究目录（不要复活其中的旧脚本）
├── protocol-research-taobao-20260908/  # 淘宝协议研究（探针与脱敏产物）
├── tests/                      # Python 回归测试（2026-10-17：45 个 test_*.py，共 779 条用例）
├── lab/whitebg/                # 白底图多场景实验与出图证据（out/ 不要删）
├── models/whitebg/             # 白底图 ONNX 模型（约 2.2 GB，不进 git、不进安装包）
├── uploads/                    # 唯一商品采集资料（业务数据，不要删）
├── docs/                       # 历史调研、方案、复盘与升级验收记录
├── skills/douyin-publisher-mcp/  # MCP 技能包（SKILL.md / playbooks / capabilities）
├── ecom-agent/、openclaw-tools/、config/、output/、trash/   # 辅助目录，未在本文件展开
└── AGENTS.md / CLAUDE.md / README.md   # 约定、架构与项目说明（改动前必读）
```

## 五、启动与端口

- **日常启动**：双击根目录 `start_frontend.bat`（或桌面快捷方式）。它调用 `tauri-app/start_tauri_dev.ps1`，
  **默认直接运行已构建的 `tauri-app/src-tauri/target/release/douyin-sock-publisher.exe`，不重新编译**；
  需要编译时用 `start_frontend.bat --dev`。
- **源码改动要生效**：先重建（`python tauri-app/python-sidecar/build_sidecar.py` / `npm run tauri:build`），再重启应用。
- `tauri-app/start_backend.bat`、根 `start_backend.bat` 都已收口到 `start_frontend.bat`，不要再单独启 Sidecar。

| 端口 | 用途 | 依据 |
|---|---|---|
| 1420 | Vite dev server（`127.0.0.1:1420`） | `tauri-app/vite.config.ts`、`tauri.conf.json` 的 `devUrl` |
| 5001 | Python Flask Sidecar | `tauri-app/src/services/api.ts` 的 `BACKEND_URL` |
| 9333 | Chrome 远程调试（抖店 CDP 只读探针） | `mcp-server` 的 `DOUYIN_CDP_LIST_URL` 默认值 |
| 3300 | MCP Streamable HTTP | `mcp-server/server-http.js` 的 `MCP_HTTP_PORT` 默认值 |

## 六、2026-10-17 的清理与归档约定（**旧约定已失效**）

已删除（`Test-Path` 实测不存在）：

- `项目备份 禁止改动使用 只参考/`（v3.0 只读参考目录，约 1.79 GB）—— **由用户本人删除**；
- `app3.0版本/`（旧版本快照）；
- `.cursor/rules/local-file-source-of-truth.mdc`。

已搬出项目、放到 `2.1_外置归档_20261017\迁出_运行缓存与快照_20261017\`（同盘移动，项目内已不存在）：

- `.tmp/`、`runtime/`、`upload-browser-profile/`、`.mimocode/`、`tmp/`；
- ⚠️ `.runtime/` **只搬走了一部分**：项目内仍有约 158.5 MB（被进程占住的浏览器缓存文件），根目录 `.runtime/` 现在仍在。

因此：

- 旧规则「需要删除文件时移到 `项目备份 禁止改动使用 只参考/recycle_bin/`」**已失效**；
- 现行做法：移到**项目外的归档目录** `C:\Users\CRB\Desktop\2.1_外置归档_<日期>\`，并在归档子目录里附 README 说明原因与恢复方式（本机现为 `2.1_外置归档_20261017\`，已实测存在）；
- 本项目**当前没有受保护（只读参考）目录**；需要 v3.0 历史内容时从提交 `ff01f9e`（不含）之前的版本取回；
- 仍然**不要删**的两处：`uploads/`（唯一商品采集资料）、`lab/whitebg/out/`（白底图实测证据）。

体积（2026-10-17 02:12 实测，逐目录累加）：**项目内约 7.18 GB**，其中
`tauri-app/` 4.64 GB（含 `src-tauri/target/release` 构建产物）、`models/` 2.22 GB、`.git/` 161.5 MB、
`.runtime/` 158.5 MB、`uploads/` 65.1 MB、`lab/` 46.9 MB；外置归档目录另有约 10.31 GB。

## 七、完成度判断（按现状，不再用旧的百分比条）

- **抖音主链路：可用**。采集 → 资料整理 → 抖店发布的桌面链路、协议化上传、运营闭环（`/api/ops/*`）、
  白底图语义抠图（`/api/whitebg/*`）均已在代码树内；根 `README.md` 记录其「已用于日常发布」。
- **淘宝：未就绪**。只有只读部分与桌面资料准备，且「不能真的发布」是被代码硬性拦住的（见 `taobao-publisher/README.md`）。
- **小红书：进行中**。近 15 条提交集中在千帆表单测绘、必填判据、规格值控件与截图分配取证。
- **测试**：`python -m pytest tests --collect-only -q` = **779 tests collected**（2026-10-17 实测）。
  本次核对**没有**跑全量用例；外置归档 README 记录的「682 passed / 1 failed / 96 errors」是撤销发布改动后的历史数据，未复核。

## 八、文档索引

| 文档 | 用途 |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | 项目约定、架构、常用命令 —— **改动前必读** |
| `README.md`（根） | 对外说明、构建与下载入口 |
| `tauri-app/README.md` | 桌面端子项目说明 |
| `docs/TAURI_MIGRATION_SPEC.md` | v3.0 → v4.0 迁移规格 |
| `docs/轻量化与性能优化_2026-10-01.md` | sidecar 体积、行尾统一等实证记录 |
| `docs/升级验收记录_4.0.30_2026-10-10.md` | 当前版本的升级验收 |
| `lab/whitebg/README.md` | 白底图多场景实测结论 |
| `protocol-research-clean-20260505/AGENTS.md` | 协议研究的硬约束 |
| `taobao-publisher/AGENTS.md`、`xiaohongshu-publisher/AGENTS.md` | 两条子路线的红线与约定 |

## 九、本次核对未能确认、因此未写入的内容

- 全量测试的真实通过率（只统计了用例条数）。
- `taobao-publisher` 的 `readiness` 当前输出、小红书链路可发布程度（只读了它们的文档与提交信息）。
- `ecom-agent/`、`openclaw-tools/`、`output/`、`config/` 的具体职责（只看了目录清单，未展开阅读）。
- 安装包在本机的体量只核对了 `tauri-app/src-tauri/target/release/bundle/nsis/抖音袜子发布工具_4.0.30_x64-setup.exe` 为 113.8 MB；
  发布用资产名（`DouyinSockPublisher_4.0.30_x64-setup.exe`）来自 `tauri-app/package-release.ps1` 的改名逻辑，未实测发布流程。
