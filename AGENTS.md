# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

本项目必须遵守 `C:\Users\12611\.Codex\AGENTS.md` 中的全局提示词。

## 项目级补充规则

- 所有面向用户可见的进度说明、计划、工具说明、复盘和最终回答必须使用简体中文。
- 代码、命令、文件路径、URL、包名、API 名称、协议字段、日志片段、堆栈和精确错误文本保持原文。
- 处理中文文本时统一使用 UTF-8，发现乱码要先判断编码来源，不要把乱码继续写入代码或文档。
- 复杂开发任务按需求分析 → 架构判断 → 实现 → 验证 → 代码审查的顺序推进。
- 不要用兜底、吞错、重试或额外绕行逻辑掩盖真实问题；优先修复根因并验证结果。
- 任务目标明确时持续推进到可交付阶段，不要因为普通"下一步"停下来等待用户说"继续"。

## 项目身份

抖音袜子发布工具 v4.0：从 PySide6 + QtWebEngine 迁移到 **Tauri 2 + Vue 3 + TypeScript + Element Plus + Python Flask Sidecar** 的桌面应用，目标是把"商品采集 → 资料整理 → 抖店发布"流水线封装成本地客户端。原 v3.0 GUI / 自动化模块仍以共享业务库的形式存在于 `src/`。

> ⚠️ 根目录的 `README.md` 是 v1.0「淘宝商品信息采集系统」遗留文档，与当前 v4.0 项目身份不符，**不要据它判断技术栈或入口**。当前以本文件、`tauri-app/README.md` 和 `docs/TAURI_MIGRATION_SPEC.md` 为准。

## Git 分支与工作区

- 实际开发分支是 **`DouYin`**（主工作区 `E:\Script Project\Dyin\beiufen\2.1` 检出该分支）；`main` 分支只有一个 initial commit（仅 README.md）。
- 因此基于 `main` 新建的分支或 worktree 里看不到任何代码属正常现象，**不要据此判断"项目是空的"**；代码以 `DouYin` 分支和主工作区为准。
- 主工作区有大量未提交 / 未跟踪文件（包括本文件和 `CLAUDE.md`），改动前先看 `git status`，不要假设工作区是干净的。

## 高层架构

应用分四个层次，互相通过本地 HTTP / 进程托管协作：

1. **Tauri Rust 壳层** (`tauri-app/src-tauri/src/main.rs`)
   - 负责窗口、文件拖拽事件、Sidecar 进程托管（启动 / 健康检查 / 强杀 / 日志重定向）。
   - 通过 `reqwest` 调用 Sidecar 的 `/internal/terminate` 优雅停止，必要时回退到 PowerShell `Stop-Process` 查找 `python-backend.exe`。
   - 资源打包配置见 `tauri.conf.json`：把 `python-backend.exe`、`mcp-server`、`skills/douyin-publisher-mcp`、`runtime/node.exe` 全部内置。

2. **Vue 3 前端** (`tauri-app/src/`)
   - 入口 `main.ts` → `App.vue`，路由 `router/index.ts`，状态 `stores/productStore.ts`（Pinia），HTTP 与 Tauri 命令封装在 `services/api.ts`。
   - 视图：`views/ProductManager.vue`（主页面）、`views/Settings.vue`；组件：`components/CaptureSection.vue`、`SkuList.vue`、`SettingsPanel.vue`、`ContextMenu.vue`、`OnboardingGuide.vue`。
   - 与 Sidecar 通信硬编码 `http://127.0.0.1:5001`；通过 `tauriCommands` 调用 Rust 侧 `start_python_backend / stop_python_backend / check_backend_status / import_dropped_files`。

3. **Python Flask Sidecar** (`tauri-app/python-sidecar/app.py`)
   - 单文件 Flask 应用（6000+ 行），承担所有业务逻辑：产品 CRUD、智能标题、智能定价、链接采集、商品发布、CDP 调试浏览器、协议化上传、运营闭环、设置管理。
   - 关键路由前缀：`/api/products`、`/load_detail`、`/save_info`、`/api/capture/*`、`/api/upload/*`、`/api/pricing/*`、`/api/debug/browser/*`、`/api/protocol/fxg/*`、`/api/ops/*`、`/settings*`。
   - 路由同时使用 `@app.route` 和 `@app.get` / `@app.post` 两种风格注册，grep 路由时不要只搜 `@app.route`。
   - 通过 `repo_root` 注入 `sys.path` 后从 `src/` 导入业务模块（开发模式）；打包后由 `PyInstaller` 一并冻结。
   - 运行时路径统一走 `src/runtime_paths.py` 的 `resolve_data_file` / `bootstrap_runtime_environment`，会按 `DOUYIN_DATA_DIR` → `LOCALAPPDATA\com.dyin.sock-publisher` → 仓库根目录的顺序解析 `cfg.yaml / sqlite.db / pricing_config.json / user_settings.json / trending_keywords.db / ops_ledger.db`，并自动从源位置 seed 到运行目录，**不要在代码里写死绝对路径**。
   - Sidecar 模式由 `SIDECAR_MODE=1` 区分：sidecar 模式 5001 端口、纯后端；非 sidecar 时会尝试加载 PySide6 GUI（保留 v3.0 行为）。

4. **共享业务库** (`src/`)
   - 被 Sidecar 直接 import 的 Python 模块：`orm.py`（Peewee + SQLite + 列迁移）、`utils.py`（DrissionPage 浏览器自动化）、`ops_engine.py`（运营闭环）、`enhanced_category_selector.py`、`smart_pricing_engine.py`、`professional_title_generator.py`、`chrome_manager.py`、`config.py`、`runtime_paths.py`、`thread.py`、`constants.py`、`trending_keywords_scraper.py`。
   - 数据库主表 `Record` 在 `orm.py:21`，`_ensure_record_columns()` 实现向后兼容字段迁移。新增字段要同时更新模型类和 `migrations` 列表。
   - ⚠️ `config_manager.py`、`confidence_scorer.py`、`quantity_extraction_enhanced.py`、`post_interaction_validator.py`、`chrome_installer_gui.py` 虽然业务代码不直接 import，但被 `tauri-app/python-sidecar/build_sidecar.py` 和 `python-backend.spec` 列为 PyInstaller hiddenimports，**不能删除或移动**（2025-11-14 曾误回收后又恢复）。

### 运营闭环（Ops）子系统

- `src/ops_engine.py`：选品评估、库存计划、日计划 / 日复盘、利润阶梯（目标日净利 500）、转化诊断、无品牌标题审计与整改等运营逻辑。**只做本地规则计算 + SQLite 账本读写，不调用任何外部 AI 或抖店官方 API**（模块内 `AI_POLICY` 明确禁用外部提供商，改动时不得违反）。
- 账本数据库 `ops_ledger.db`，路径经 `resolve_ops_ledger_path()` → `resolve_data_file` 解析。
- Sidecar 在 `/api/ops/*` 暴露这些能力（含 `publish-preflight-safety`、`save-edit-human-gate` 等发布安全门）；`mcp-server/core.js` 把大部分 ops 接口包装成 MCP 工具，`mcp-server/ops-metrics-cdp.js` 负责经营数据的 CDP 采集。
- 改动 ops 逻辑后至少跑 `tests/test_ops_engine.py` 和 `tests/test_publish_preflight_safety.py`。

### MCP / 协议研究子系统

- `mcp-server/` (Node.js)：把 Sidecar 5001 暴露为 MCP 工具，并增加一组独立 CDP 工具（`cdp_*`），通过 `DOUYIN_CDP_LIST_URL`（默认 `http://127.0.0.1:9333/json/list`）连接已开远程调试的 Chrome。`server.js` 是 stdio 入口，`server-http.js` 是 Streamable HTTP 入口（默认 3300），`scripts/` 下是只读探针。运行 MCP 之前必须先启动 Sidecar。
- `protocol-research-clean-20260505/`：当前唯一允许扩展的协议研究目录（详见目录内 `AGENTS.md`）。约束很硬：只能输出去敏产物、不接入正式上传、不绕过登录/验证码/风控、不写兜底掩盖映射错误。核心脚本 `scripts/fxg_protocol_v4.py` 已被 Sidecar 引用。
- `protocol-research/`（旧）、`protocol-capture/`、`protocol-publish/`：运行时落地目录或历史研究目录，作参考但不要把旧结论直接搬到新流水线。
- `skills/douyin-publisher-mcp/`：Codex 技能包定义（SKILL.md、playbooks、capabilities），与 MCP Server 配对。

### 受保护目录

- `项目备份 禁止改动使用 只参考/`：v3.0 原版（含 `app.py`、`capture_service.py`、`web/`、`1688货品网站源码/`）。**只读参考**，禁止修改或拷贝改写；唯一例外是向 `recycle_bin/` 新增回收子目录。
- `app3.0版本/`：另一个旧版本快照，同样只读。

## 常用命令

以下命令均以仓库根目录（`E:\Script Project\Dyin\beiufen\2.1`，路径含空格，引用时注意加引号）为基准。所有桌面端启动入口已收口到根目录 `start_frontend.bat`；`tauri-app/start_backend.bat`、根目录 `start_backend.bat` 会跳回 `start_frontend.bat`，**不要再单独启 Sidecar**。

### 桌面应用开发 / 构建

```powershell
# 开发模式（同时启动 Vite + Rust + 自动拉起 Python sidecar）
Set-Location tauri-app
npm run tauri:dev          # 实际执行 tauri dev -- --release，Rust 壳按 release 编译

# 仅构建前端
npm run build              # vue-tsc + vite build

# 生产打包（Windows NSIS）
npm run tauri:build
npm run package:release    # 调用 package-release.ps1，一并产出安装包

# Python sidecar 单独打包（PyInstaller，产物落到 src-tauri/sidecar/）
Set-Location tauri-app/python-sidecar
python build_sidecar.py
```

Vite Dev Server 占用 `127.0.0.1:1420`；Sidecar 占用 `127.0.0.1:5001`。这两个端口写死在 `tauri.conf.json` 和 `tauri-app/src/services/api.ts`，调整需同步改两边。

### Python 后端

```powershell
# 仅做静态检查 / 单步调试（一般不需要，sidecar 由 Tauri 自动启动）
Set-Location tauri-app/python-sidecar
python app.py                                          # GUI/兼容模式
$env:SIDECAR_MODE = '1'; python app.py                 # Sidecar 模式（端口 5001）

# 全量后端依赖（根目录 requirements.txt 比 sidecar 子集更全，两份都要看）
pip install -r requirements.txt                        # 仓库根
pip install -r tauri-app/python-sidecar/requirements.txt
```

后端启动会在 `%LOCALAPPDATA%\com.dyin.sock-publisher\logs\` 写 `python-backend.bootstrap.log`，排查启动失败先看它。

### 测试

```powershell
# Python 测试：必须在仓库根目录运行（测试文件自行把仓库根注入 sys.path，没有根级 conftest/pytest.ini）
python -m pytest tests                                  # 全量
python -m pytest tests/test_ops_engine.py               # 单个文件
python -m pytest tests/test_ops_engine.py -k daily_plan # 单个用例

# mcp-server 测试与语法体检
Set-Location mcp-server
npm run check              # node --check 覆盖所有脚本
npm run test:ops           # node --test tests/*.test.mjs
```

已知环境问题：PATH 上的 `python` 是 3.9，而 `tests/test_protocol_no_brand_policy.py` 经 `protocol_publish/models.py` 用到 `dataclass(slots=True)`（需 Python 3.10+），在 3.9 下收集即报错；机器上的 Python 3.11（`py -3.11`）未装 pytest。跑全量时可先 `--ignore=tests/test_protocol_no_brand_policy.py`，或修复解释器环境后再跑全量。

`tests/` 重点覆盖发布安全门（`test_publish_preflight_safety.py`、`test_sidecar_upload_safety.py`、`test_upload_brand_safety.py`）和无品牌策略（`test_*_no_brand_policy.py`），涉及上传 / 发布 / 标题逻辑的改动必须跑对应文件。

### MCP Server / CDP 探针

```powershell
Set-Location mcp-server
npm install                # 首次

# 启动方式
npm start                  # stdio
npm run start:http         # Streamable HTTP, 默认 3300

# 启动一个带 9333 远程调试端口的 Chrome（独立 profile）
npm run start:fxg-cdp
npm run check:cdp          # 验证 /json/list 可达且页面已登录

# 只读探针（仅观察当前页面，不主动上传/保存/提交）
npm run probe:fxg-schema
npm run probe:fxg-category-matrix
npm run probe:fxg-runtime-options
npm run probe:fxg-freight
npm run probe:fxg-upload                # 默认仅扫描；提供 UPLOAD_IMAGE_PATH 才会触发一次样图上传
npm run probe:fxg-material
npm run probe:fxg-qualification
npm run probe:fxg-submit
npm run capture:fxg-protocol            # 短时观察请求并脱敏
npm run capture:fxg-submit-preflight    # 拦截匹配的写操作
```

所有 CDP 探针默认输出到 `tmp_runtime_probe_live/`。FXG 协议工具的红线：**不得在没有 `UPLOAD_*` 显式授权时触发上传 / saveMaterial / batchApplyMaterial / addWithSchema / 草稿保存 / 提交**。Probe / capture 脚本只能观察。

### 数据库 / 配置文件

| 文件 | 用途 |
|------|------|
| `sqlite.db`（根 + sidecar 副本） | 主业务库，被 `runtime_paths.resolve_data_file` 路由 |
| `ops_ledger.db` | 运营闭环账本（`src/ops_engine.py` 读写） |
| `cfg.yaml` | 应用 base 配置（名称、版本、access_token） |
| `pricing_config.json` | 智能定价规则 |
| `user_settings.json` | 用户级设置（材质成分、运费模板等） |
| `trending_keywords.db` | 趋势关键词缓存 |

修改 `Record` 字段必须同时改 `src/orm.py` 的模型和 `_ensure_record_columns` 的 `migrations` 列表，否则升级安装会缺列报错。

## 端口与外部依赖

| 端口 | 用途 |
|------|------|
| 1420 | Vite dev server |
| 5001 | Python Flask Sidecar |
| 9333 | Chrome 远程调试（FXG CDP 探针，使用独立 profile `.runtime/chrome-fxg-cdp/`） |
| 3300 | MCP Streamable HTTP |

外部组件：DrissionPage / Playwright 驱动 Chrome / Edge 进行电商页面采集和发布；商品发布走抖店发布工作台（fxg.jinritemai.com）。

## 工作约定

- 改 Sidecar HTTP 接口必须同步更新 `tauri-app/src/services/api.ts`、`tauri-app/src/types/index.ts`、Pinia store 与相关 Vue 视图。
- 新增 MCP 工具要同步检查 `mcp-server/core.js`、`server.js`、`server-http.js` 与 `skills/douyin-publisher-mcp/SKILL.md`、`capabilities.md`、`playbooks.md`。
- `CLAUDE.md` 是本文件面向 Claude Code 的镜像版本，内容应保持同步；更新本文件后同步更新 `CLAUDE.md`。
- 协议研究产出落到 `protocol-research-clean-20260505/`，**不要复活 `protocol-research/` 下的旧脚本**；如需复用先重新实证。
- 写 Windows 路径或 PowerShell 命令时，先设置 UTF-8 编码（参见全局规则），避免中文文件名乱码。
- 编辑现有 Python 文件前先确认编码：`app.py` 顶部带 `# -*- coding: utf-8 -*-`，stdout/stderr 被 `_SafeConsoleStream` 包装，禁止替换为裸 `print` 流。
- 遇到 `python-backend.exe` 残留进程：先调用 Sidecar 的 `POST /internal/terminate`（只允许 127.0.0.1），再用 Tauri 内置的强杀路径，最后才考虑手工 Stop-Process。
- `docs/` 已经积累了大量历史调研和规划文档（协议化上传、平台错误映射、DOM 对照分析等），写新方案前先翻一遍同名前缀的最新文件，避免重复结论。
- **禁止直接删除代码文件**（`.cursor/rules/local-file-source-of-truth.mdc` 硬约束）。需要"删除"时移动到 `项目备份 禁止改动使用 只参考/recycle_bin/RECYCLE_<原因>_<YYYY-MM-DD>/`，参考已有的 `RECYCLE_测试文件_2025-11-13/`、`RECYCLE_根目录调试脚本_2026-06-13/` 等子目录命名，并在子目录内附 README 说明原因与恢复方式。
- 修改代码后如果需要重启 Sidecar / 重编译 Tauri 才能生效，**自行重启，不要问用户**；但务必先彻底关闭旧实例（先 `POST /internal/terminate`，再 `Stop-Process -Name python-backend -Force`，最后再启动新进程），避免端口占用或多实例冲突。
