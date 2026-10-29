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

电商产品发布工具 v4.0（内部名「抖音袜子发布工具」）：从 PySide6 + QtWebEngine 迁移到 **Tauri 2 + Vue 3 + TypeScript + Element Plus + Python Flask Sidecar** 的桌面应用，目标是把"商品采集 → 资料整理 → 抖店发布"流水线封装成本地客户端。原 v3.0 GUI / 自动化模块仍以共享业务库的形式存在于 `src/`。

> **名称约定（2026-10-20）**：应用已不只服务抖音，对外名是「**电商产品发布工具**」，窗口标题、页面标题、欢迎页和启动脚本的提示已改用它。
> 下面这些仍是内部名，**不要顺手改**：`tauri.conf.json` 的 `productName`（安装包名、卸载列表、exe 文件描述、应用内更新链路；NSIS 安装器按它找旧安装，改了会并排装出第二份，要改须先做安装迁移）、
> `identifier = com.dyin.sock-publisher`（**决定数据目录**，改了就找不到商品库和店铺登录）、Cargo 包名 / exe 名 `douyin-sock-publisher`（启动器、`lab/` 脚本和进程检查都按它找）。

> 根目录 `README.md` 已在 2026-10-18 重写为当前 v4.0 的概览；原来的 v1.0「淘宝商品信息采集系统」说明归档在 `docs/历史/README_v1.0_淘宝采集系统.md`，**不要据那份归档文档判断技术栈或入口**。技术细节以本文件、`tauri-app/README.md` 和 `docs/TAURI_MIGRATION_SPEC.md` 为准。

## Git 分支与工作区

- 实际开发分支是 **`DouYin`**（主工作区 `E:\Script Project\Dyin\beiufen\2.1` 检出该分支）；`main` 分支只有一个 initial commit（仅 README.md）。
- 因此基于 `main` 新建的分支或 worktree 里看不到任何代码属正常现象，**不要据此判断"项目是空的"**；代码以 `DouYin` 分支和主工作区为准。
- 主工作区有大量未提交 / 未跟踪文件（包括本文件和 `CLAUDE.md`），改动前先看 `git status`，不要假设工作区是干净的。
- ⚠️ 2026-10-18 实测：`C:\Users\12611\Desktop\2.1` 这份副本**没有 `.git`**，且比 `E:\Script Project\Dyin\beiufen\2.1` 新（前者 4.0.30，后者 `DouYin` 分支停在 4.0.28、最后提交 2026-05-27）。两份代码已经分叉，动手前先确认以哪份为准；在没有 git 的副本里做大改动，先把要改的文件备份出来再改。

## 高层架构

应用分四个层次，互相通过本地 HTTP / 进程托管协作：

1. **Tauri Rust 壳层** (`tauri-app/src-tauri/src/main.rs`)
   - 负责窗口、文件拖拽事件、Sidecar 进程托管（启动 / 健康检查 / 强杀 / 日志重定向）。
   - 通过 `reqwest` 调用 Sidecar 的 `/internal/terminate` 优雅停止，必要时回退到 PowerShell `Stop-Process` 查找 `python-backend.exe`。
   - 资源打包配置见 `tauri.conf.json`：把 `python-backend.exe`、`mcp-server`、`skills/douyin-publisher-mcp`、`runtime/node.exe` 全部内置。
   - `src/ui_watchdog.rs`（2026-10-20）：UI 事件循环存活监测，**只写证据日志、不改任何行为**。每 15 秒往 UI 线程投一个空任务，20 秒没执行就在 `tauri-runtime.log` 写 `[ui-watchdog] STALL ...`（窗口状态、最近事件、UI 线程调用栈）。背景：旧实例曾对三种关闭请求都没有反应——机制已复现（UI 线程停在回调里的嵌套消息循环，tao 把新事件缓冲起来，`CloseRequested` 到不了 `on_window_event`），触发原因没查到，详见 `docs/窗口关闭无响应排查_2026-10-20.md`。看到 `STALL` 先留日志再强杀；改关闭 / 退出 / 事件循环相关代码后，用 `lab/shell_close_probe/` 在隔离数据目录里验证（会拒绝在真实应用开着时运行）。
   - `src/event_target_guard.rs`（2026-10-20）：给 tao 的内部窗口 `Tao Thread Event Target`（可见、无标题、尺寸为 0，进程里的第二个顶层窗口）挂子类过程，`WM_CLOSE` 只记一行日志（`[event-target-guard] ignored WM_CLOSE`）。原因：主窗口最小化后 `Process.MainWindowHandle` / `CloseMainWindow()` 会指向它，`WM_CLOSE` 把它销毁后 tao 的事件循环永远不结束——主窗口能关、清理也执行，但进程退不出去。**关应用要按类名 `Tauri Window` 找真窗口再发 `WM_CLOSE`（见 `lab/shell_close_probe/Probe-Lib.ps1`），别用 `CloseMainWindow()` 返回 True 当作成功。**

2. **Vue 3 前端** (`tauri-app/src/`)
   - 入口 `main.ts` → `App.vue`，路由 `router/index.ts`，状态 `stores/productStore.ts`（Pinia），HTTP 与 Tauri 命令封装在 `services/api.ts`。
   - 视图：`views/ProductManager.vue`（主页面，只做装配）、`views/Settings.vue`；组件：`components/CaptureSection.vue`、`SkuList.vue`、`SettingsPanel.vue`（设置页外壳）、`ContextMenu.vue`、`OnboardingGuide.vue`、`PricingResultsDialog.vue`、`UploadProgressPanel.vue` 等。
   - 流程逻辑不写在页面里（2026-10-19 整理）：主页的店铺账户、上传任务监控、SKU 勾选、商品表单、智能填充价格、发起发布、商品目录各一个 composable（`composables/use*.ts`，装配顺序见 `ProductManager.vue` 的 `<script>`）；设置页按 Tab 拆在 `components/settings/`（`PricingTab` / `ModelTab` / `AutomationTab` / `McpTab` / `AboutTab`），各 Tab 的表单状态在 `composables/settings/`，由 `SettingsPanel.vue` 创建并通过 `model` prop 传给 Tab——不是全局状态。确认框的小工具在 `utils/dialog.ts`。
   - **所有 HTTP 请求只走 `services/api.ts`**：组件 / composable 里不要 `import axios`、不要 `fetch`、不要写死 `127.0.0.1:5001`；后端地址用它导出的 `BACKEND_URL`，错误文字 / 状态码用 `apiErrorMessage` / `apiErrorStatus` / `apiErrorRejectedExplicitly`。与 Sidecar 通信的地址是 `http://127.0.0.1:5001`；通过 `tauriCommands` 调用 Rust 侧 `start_python_backend / stop_python_backend / check_backend_status / import_dropped_files`。

3. **Python Flask Sidecar** (`tauri-app/python-sidecar/app.py`)
   - Flask 启动与依赖组装入口。仍留在 `app.py` 的：产品 CRUD、上传任务的流程编排（任务字典、浏览器会话、DOM / 协议两条流水线、`/api/upload/*`、`/api/protocol/fxg/runtime-options`、`/start`，下一步拆）；抖店发布页的页面级操作已拆到 `src/sidecar/upload_steps.py`；运营闭环、AI 配置、标题生成、设置、定价、图片 / 白底图、店铺会话、CDP 调试浏览器、素材导入、小红书批量填表、链接采集、淘宝发布等业务域已拆成 `src/sidecar/` 下的 Blueprint 模块（见下文「Sidecar 模块边界」）。
   - 关键路由前缀：`/api/products`、`/load_detail`、`/save_info`、`/api/capture/*`、`/api/upload/*`、`/api/pricing/*`、`/api/debug/browser/*`、`/api/shop/*`、`/api/protocol/fxg/*`、`/api/ops/*`、`/settings*`。
   - 路由同时使用 `@app.route` 和 `@app.get` / `@app.post` 两种风格注册，grep 路由时不要只搜 `@app.route`；已拆出的域在 `src/sidecar/` 里用 `@routes.get` / `@routes.post`。完整路由表见 `tests/fixtures/sidecar_routes.txt`（128 条，URL 契约快照）。
   - 通过 `repo_root` 注入 `sys.path` 后从 `src/` 导入业务模块（开发模式）；打包后由 `PyInstaller` 一并冻结。
   - 运行时路径统一走 `src/runtime_paths.py` 的 `resolve_data_file` / `bootstrap_runtime_environment`，会按 `DOUYIN_DATA_DIR` → `LOCALAPPDATA\com.dyin.sock-publisher` → 仓库根目录的顺序解析 `cfg.yaml / sqlite.db / pricing_config.json / user_settings.json / trending_keywords.db / ops_ledger.db`，并自动从源位置 seed 到运行目录，**不要在代码里写死绝对路径**。
   - Sidecar 模式由 `SIDECAR_MODE=1` 区分：sidecar 模式 5001 端口、纯后端；非 sidecar 时会尝试加载 PySide6 GUI（保留 v3.0 行为）。

4. **共享业务库** (`src/`)
   - 被 Sidecar 直接 import 的 Python 模块：`orm.py`（Peewee + SQLite + 列迁移）、`utils.py`（DrissionPage 浏览器自动化）、`ops_engine.py`（运营闭环）、`enhanced_category_selector.py`、`smart_pricing_engine.py`、`professional_title_generator.py`、`chrome_manager.py`、`config.py`、`runtime_paths.py`、`shop_session.py`（多店铺登录会话与店铺身份实测）、`thread.py`、`constants.py`、`trending_keywords_scraper.py`。
   - 数据库主表 `Record` 在 `orm.py:21`，`_ensure_record_columns()` 实现向后兼容字段迁移。新增字段要同时更新模型类和 `migrations` 列表。
   - ⚠️ `config_manager.py`、`confidence_scorer.py`、`quantity_extraction_enhanced.py`、`post_interaction_validator.py`、`chrome_installer_gui.py` 虽然业务代码不直接 import，但被 `tauri-app/python-sidecar/build_sidecar.py` 和 `python-backend.spec` 列为 PyInstaller hiddenimports，**不能删除或移动**（2025-11-14 曾误回收后又恢复）。

### Sidecar 模块边界（2026-10-09 起，2026-10-20 扩展）

已拆出的业务域（都是 `create_xxx_blueprint(**显式依赖)` 工厂，`app.py` 末尾统一注册）：

| 域 | 模块 | 路由前缀 | 注入的依赖 |
|---|---|---|---|
| 运营闭环 | `src/sidecar/ops/`（`support` / `planning_routes` / `ledger_routes` / `sourcing_routes` / `browser_routes` / `blueprint`） | `/api/ops/*`（37 条） | `record_model`、`OpsBrowserPort`（浏览器能力）、`is_sidecar_mode`、`get_sidecar_port`、`repo_root` |
| AI 配置 | `src/sidecar/ai_routes.py` | `/api/ai/*` | 无 |
| 标题生成 | `src/sidecar/title_routes.py` | `/api/generate_*`、`/api/trending_keywords/*` | `record_model` |
| 设置 | `src/sidecar/settings_routes.py` | `/settings*` | `get_runtime_data_path` |
| 定价 | `src/sidecar/pricing_routes.py` | `/api/pricing/*` | `record_model`、`get_runtime_data_path` |
| 店铺会话 | `src/sidecar/shop_routes.py`（Blueprint）+ `shop_service.py`（`ShopSessionService`）+ `shop_accounts.py`（`ShopAccountGuard`） | `/api/shop/*`（6 条） | `accounts`、`service`、`shop_session`；浏览器能力经 `ShopBrowserPort` |
| 调试浏览器 | `src/sidecar/debug_browser_routes.py`（Blueprint）+ `debug_browser_service.py`（`BrowserDebugService`） | `/api/debug/browser/*`（10 条） | `service`；浏览器能力经 `DebugBrowserPort` |
| 素材导入 | `src/sidecar/import_routes.py` | `/api/import/folders`（1 条） | `record_model`、`split_number_prefix` |
| 小红书批量填表 | `src/sidecar/xhs_batch_routes.py`（Blueprint）+ `xhs_batch_service.py`（`XhsBatchService`） | `/api/xhs/fill-batch`、`fill-status/<id>`、`fill-cancel/<id>`（3 条） | `record_model`、`service`、`accounts`（平台门禁） |
| 链接采集 | `src/sidecar/capture_routes.py`（Blueprint）+ `capture_service.py`（`CaptureService`）+ `capture_helpers.py`（无状态函数） | `/api/capture/*`（5 条） | 路由：`service`、`normalize_save_path`、`get_app_root`、`settings_manager`；服务：`record_model`、`logger`、协议引擎、共用函数和端口段 |
| 淘宝发布 | `src/sidecar/taobao_routes.py`（Blueprint）+ `taobao_service.py`（`TaobaoPublishService`）+ `taobao_helpers.py`（纯函数） | `/api/taobao/*`（8 条） | 路由：`service`、`accounts`、`record_model`、`resolve_data_file`、`require_product_revision`；服务：`record_model`、`repo_root`、`accounts`（账户门禁）、`shop_service`（店铺会话）、`normalize_debug_address`、`resolve_data_file`、`bootstrap_log` |
| 抖店上传（页面操作） | `src/sidecar/upload_steps.py` | 无路由（62 个页面操作函数 + `PublishUnconfirmedError` + 13 个常量） | 无注入：直接导入 `src.utils`，不碰任务状态（边界由 `tests/test_upload_steps.py` 钉着） |

共同约定：

- 模块里的函数体是从 `app.py` **逐字搬来**的，只改了依赖的取法（`app` → `routes` / `current_app`，全局 → 注入参数，服务类里是 `self.xxx`）；改行为请单独提交，不要和搬迁混在一起。
- `/api/ops/*` 里依赖浏览器的 5 个接口（健康检查、经营指标同步、发布前安全闸三件套）只通过 `OpsBrowserPort` 访问浏览器；该包不导入 `src.utils` / DrissionPage，导入它不会初始化浏览器。
- 接口模块里的 ``Record`` 一律由工厂参数 `record_model` 传入，测试里换成隔离库的最小模型（见 `tests/sidecar_test_support.py`）。
- 拆分后 URL、方法、JSON 结构一律不变；`tests/test_sidecar_app_smoke.py` 会在子进程里真实导入 `app.py` 并和 `tests/fixtures/sidecar_routes.txt` 对比路由表——有意增删路由时同步更新这份快照以及 `tauri-app/src/services/api.ts`、`mcp-server`。
- 该冒烟测试还用 `symtable` 扫描 `app.py` 与 `src/**`：函数里引用了模块没定义的全局名会直接失败（曾因此查出 `_json` 未定义，淘宝批量发布 / 小红书批量填表在第一条记录就抛 `NameError`）。

#### 店铺会话与调试浏览器（2026-10-19）

- 店铺会话分三层：`shop_routes.py`（`create_shop_blueprint(accounts, service, shop_session)`，只做 HTTP 适配）、`shop_service.py`（`ShopSessionService`：找出「发布流程这一刻用的浏览器」、实测当前登录的店铺并写回注册表、切换账户时丢弃旧浏览器句柄）、`shop_accounts.py`（`ShopAccountGuard`：账户锁、当前账户绑定的平台、`require_publish_platform` 平台门禁、`account_change_blocked` 账户切换互斥）。
- 调试浏览器两层：`debug_browser_routes.py`（`create_debug_browser_blueprint(service)`）和 `debug_browser_service.py`（`BrowserDebugService`：调试会话 / 事件 / 最近一次错误报告 / 浏览器实例这些**进程级状态**，以及页面查询、等待、截图、启动可连接的 Chrome）。
- **状态属于服务对象，不是模块全局**：账户锁在 `ShopAccountGuard` 里，调试状态在 `BrowserDebugService` 里，都由 `app.py` 创建一次（实例名 `shop_accounts` / `browser_debug` / `shop_session_service`）。不要再往 `app.py` 加 `_browser_debug_state` 之类的模块级字典。
- 浏览器能力只经端口对象注入（`DebugBrowserPort` / `ShopBrowserPort`，frozen dataclass，字段是 `app.py` 里已有的函数）；这几个模块不导入 `src.utils` / DrissionPage / `app.py`，导入它们不会初始化浏览器（有子进程测试守着）。端口里的 `page_state` 是 `lambda: gui`：必须每次取最新的 `gui`，因为 GUI 兼容模式（非 sidecar）启动后会把它重绑成 `Gui` 实例，缓存引用会让两边各持一份 `page`。
- 其它业务域（上传 / 小红书 / 保存；采集和淘宝发布已在 2026-10-20 拆出，直接依赖 `capture_service` / `shop_accounts` + `shop_session_service`）还留在 `app.py`，沿用旧函数名使用这些服务：`_shop_account_lock`、`_active_shop_profile`、`_active_shop_account`、`_with_shop_account_lock`（装饰器）、`_require_publish_platform`、`_get_current_browser_tab`、`_snapshot_browser_context`、`_record_browser_automation_error`、`_latest_browser_debug_error_after`、`_set_browser_debug_instance`、`_find_debug_browser_process`、`_get_gui_page_debug_address`、`_debug_bool`、`_debug_int` 现在是 `app.py` 里指向服务方法 / 函数的别名（装配块在 `_publish_tasks_running` 之后、`_is_local_port_available` 之后）。这些域拆出去时改为直接依赖服务，再删别名（`_account_change_blocked` / `_resolve_active_shop_browser` / `_activate_shop_profile` 就是随淘宝发布一起删掉的，它们是淘宝域的唯一使用者）。旧名字到新方法名的对应表写在各模块的文档字符串里。
- 「是否有发布任务在跑」留在 `app.py` 的 `_publish_tasks_running()`（`_upload_tasks` 属于上传域，淘宝任务字典在 `taobao_service.tasks`），经 `has_running_publish_tasks` 注入 `ShopAccountGuard`。这是本轮唯一一处不是逐字搬迁的函数：原 `_account_change_blocked` 被拆成「查任务字典」和「拼 409 响应」两半，等价性由新旧对打和 `tests/test_shop_accounts.py` 守着。
- 端口范围常量（`_DEBUG_BROWSER_*` / `_CAPTURE_BROWSER_*` / `_SHOP_BROWSER_PORT_*`）仍定义在 `app.py`（采集 / 小红书 / 协议端口扫描也在用，`tests/test_sidecar_protocol_ports.py` 按名字读取它们），通过端口对象传给服务。
- 相关回归：`tests/test_shop_accounts.py`、`tests/test_shop_routes.py`（真实 `shop_session` + 隔离数据目录）、`tests/test_debug_browser_service.py`、`tests/test_debug_browser_routes.py`（假标签页 + 虚拟时钟，共用 `tests/debug_browser_fakes.py`）。`tests/test_shop_platform_api.py`、`tests/test_taobao_desktop_api.py`、`tests/test_product_save_snapshot.py` 用的是真实的 `ShopAccountGuard` / `ShopSessionService` 对象，不再从 `app.py` 源码里抽这些函数；`tests/test_sidecar_app_smoke.py` 多了一块「装配接线」探针（别名绑定、共用同一把账户锁、`gui` 被重绑后页面状态跟随、`_publish_tasks_running` 读到真实任务字典）。

#### 素材导入与小红书批量填表（2026-10-20）

- 导入：`import_routes.py`（`create_import_blueprint(record_model, split_number_prefix)`）只有 `POST /api/import/folders` 一条路由。扫描 SKU 文件夹、收集图片、按名称去重这些辅助函数是模块级纯函数；`split_number_prefix` 在 `src.utils` 里（会连带导入浏览器库），所以由 `app.py` 注入，模块本身不导入 `src.utils`。
- 小红书批量填表分两层：`xhs_batch_service.py`（`XhsBatchService`：任务字典 `tasks` + 锁 `lock`、`run_fill_batch_task`（worker）、`prune_finished_locked`（清理已结束任务，最多留 20 条 / 24 小时）、`images_from_record` / `category_from_record`、`debug_port`（按小红书域名在账户浏览器端口段里找调试页））和 `xhs_batch_routes.py`（`create_xhs_batch_blueprint(record_model, service, accounts)`：`/api/xhs/fill-batch`、`/api/xhs/fill-status/<id>`、`/api/xhs/fill-cancel/<id>`，入口用 `accounts.require_publish_platform('xiaohongshu')` 做平台门禁）。单条填表 / 状态探针的 Blueprint 仍是早就独立的 `xhs_routes.py`。
- **状态属于服务对象**：`app.py` 里创建一次 `xhs_batch`，不要再往 `app.py` 加 `_xhs_tasks` 之类的模块级字典。单条填表的执行器 / 状态探针包装（`_xhs_runner_with_account_port`、`_xhs_status_probe_with_account_port`）也经 `xhs_batch.debug_port(...)` 取端口，批量和单条共用同一套找端口逻辑。
- 红线不变：批量填表**只填表、不提交**——没有提交 / 保存草稿 / 上架类路由，`allow_upload` 默认关；不要为了方便加这类接口。
- 相关回归：`tests/test_import_routes.py`、`tests/test_xhs_batch.py`（假执行器 + 假端口探测，worker 线程换成同步线程）、`tests/test_xhs_task_prune.py`（直接构造 `XhsBatchService`，不再从 `app.py` 抽函数）；`tests/test_sidecar_app_smoke.py` 的接线探针守着 `app.py` 里 `xhs_batch` 的端口段、批量路由用的门禁和服务、导入接口注入的 `split_number_prefix`。

#### 链接采集（2026-10-20）

- 分三层：`capture_helpers.py`（31 个无状态函数：URL 识别 / 短链、价格与 1688 SKU 解析、1688 页面快照与风控页判断、淘宝 ICE 提取、失败原因归类、协议采集产物写入、本机代理检测 ……，**不碰**任务字典 / 锁 / 浏览器单例 / Flask 上下文）、`capture_service.py`（`CaptureService`：任务字典 `tasks`、互斥锁 `lock`、`running_task_id`、mtop 商品缓存、浏览器 cookie 缓存，加 14 个要用到它们或日志的方法）、`capture_routes.py`（`create_capture_blueprint(service, normalize_save_path, get_app_root, settings_manager)`，五个接口；`start_capture` 的 1140 行原样搬在这里，**下一步按阶段 2 拆成阶段函数**）。
- **状态属于服务对象**：`app.py` 里只有一个 `capture_service`；`_active_update_tasks()`（更新器的「有没有任务在跑」）读 `capture_service.lock` / `capture_service.running_task_id`。不要再往 `app.py` 加 `capture_tasks` 之类的模块级变量（接线探针会检查）。
- **日志走注入的 logger**：采集线程里没有 Flask 应用上下文，所以服务 / 路由里用的是 `service.logger`（应用入口传入的 `app.logger`），**不能**换成 `current_app.logger`；`tests/test_capture_routes.py::test_worker_logs_through_the_injected_logger` 守着。
- 留在 `app.py`、经注入传给服务的：`normalize_save_path` / `get_app_root`（路径规则依赖入口文件位置，白底图服务也在用）、`_is_local_port_available`、`_find_cdp_port` / `_load_capture_attributes`（上传、淘宝域共用）、`_PROTOCOL_CAPTURE_ENGINE`，以及来自 `src.utils` 的 `_normalize_debug_address` / `_verify_debug_browser` / `discover_debuggable_browsers`。这三个模块不导入 `src.utils` / DrissionPage / `app.py`。`capture_url_utils.py` 已从 `tauri-app/python-sidecar/` 搬进 `src/`（新模块不该依赖「入口目录在 `sys.path` 里」）。
- 搬迁时发现 6 个整个仓库都没有调用方的函数（`_extract_taobao_tmall_item_id` 等），原样放在 `capture_helpers.py` 并在模块文档里点名；是否删除见方案文档「未决问题」。
- 验证方式（以后拆 `start_capture` 照这个来）：`lab/sidecar_split/scen_capture*.py` 新旧对打（假 DrissionPage / websocket / requests / 虚拟时钟，103 个请求），旧代码语句覆盖 1468/1478，没覆盖的 10 条是 4 个 `global` 声明（没有字节码）和 6 条结构上走不到的；单元层面的兜底是 `tests/test_capture_{helpers,service,routes}.py` 和 `tests/test_sidecar_service_attribute_refs.py`（所有「服务 + 路由」对的属性引用静态检查），共用假件在 `tests/capture_fake_world.py` / `tests/capture_test_support.py`。
- 被改写成「直接构造 `CaptureService`」的旧测试：`test_capture_attribute_storage.py`（它的 `storage` 夹具被白底图选择、淘宝 SKU 测试共用，里面是真实的服务 + 蓝图）、`test_capture_completeness.py`、`test_capture_browser_connection.py`。

#### 淘宝发布（2026-10-20）

- 分三层：`taobao_helpers.py`（纯函数：`_parse_taobao_publish_options` 发布开关的解析与校验、`_taobao_product_from_record` 批量发布用的载荷构造，加 `TAOBAO_LISTING_MODES` / `_CATEGORY_LABELS` 两个常量）、`taobao_service.py`（`TaobaoPublishService`：任务字典 `tasks`、互斥锁 `lock`、淘宝模块的延迟加载 `load_desktop` / `load_pipeline`、`cdp_list_url`、`ensure_fill_browser`、界面资料 → 流水线请求的翻译 `product_request_payload`、单品 worker `run_publish_task`、批量 worker `run_publish_batch_task`）、`taobao_routes.py`（`create_taobao_blueprint(service, accounts, record_model, resolve_data_file, require_product_revision)`，八个接口）。
- **状态属于服务对象**：`app.py` 里只有一个 `taobao_service`；`_publish_tasks_running()`、`_record_edit_blocked()`（保存商品的编辑保护）、`save_info`（保存时按淘宝契约校验标题）、`_active_update_tasks()`（更新器）读 `taobao_service.tasks` / `.lock` / `.product_request_payload`。不要再往 `app.py` 加 `_taobao_tasks` 之类的模块级变量（接线探针会检查）。
- **直接依赖账户门禁和店铺会话服务，不走别名**：服务对象持有 `ShopAccountGuard`（`accounts`）和 `ShopSessionService`（`shop_service`）；`app.py` 里原来给淘宝用的三个别名已删。模块不导入 `src.utils` / DrissionPage / `app.py`；`taobao_publish` 包在请求里才加载（缺依赖只让淘宝接口不可用，不影响 Sidecar 启动）。
- **红线不变**：默认 `dry_run=True` / `stop_before_submit=True` / `save_draft=False`（`test_taobao_helpers.py` 钉着）；填写任务（`fill_only`）只授予本次上传 / 表单输入的权限，永不授权提交；任务完成不等于商品已上架，`publish_confirmed` 永远是 `False`；`run_publish_task` 和 `run_publish_batch_task` 都会临时把 `TAOBAO_MEDIA_ROUTE` 设成 `protocol`（进程级环境变量），**结束时必须还原**，否则会泄漏给同一进程里后面的任务（`test_taobao_service.py` 里单品、批量的各种结局都有用例钉着；批量那条曾经漏了，2026-10-21 补上）。
- 验证方式（以后拆上传域照这个来）：`lab/sidecar_split/scen_taobao.py` 新旧对打（真实的 `taobao_publish` 包和账户注册表，只替换流水线 / 素材准备 / 浏览器入口；209 个请求），旧代码 18 个函数每条语句都执行过；单元层面的兜底是 `tests/test_taobao_{helpers,service,routes}.py`、`test_sidecar_taobao_concurrency.py` 和 `test_sidecar_service_attribute_refs.py`，共用假件在 `tests/taobao_test_support.py`。
- **`taobao-publisher/tests` 是另一套测试，必须一起跑**：它里面有十几个文件按文本读或 `exec` Sidecar 源码，这轮之前的几轮拆分只跑了根目录 `tests/`，结果它悄悄坏了 28 条。现在这些测试经 `taobao-publisher/scripts/sidecar_source.py`（按函数名用 AST 从 `app.py` 与 `src/sidecar/**` 取源码）读取，位置无关；`test_desktop_fill_entry.py` / `test_offline_pipeline_handoff.py` 等直接构造真实的服务和蓝图。
- **批量发布的三个既有问题已在 2026-10-21 作为独立的行为修改修掉**（搬迁时发现，方案文档「未决问题」第 20~22 条，详见方案文档第 12 节）：①`_taobao_product_from_record` 把「去掉首尾空白后全是 ASCII 数字」的字符串转成整数再走 `_CATEGORY_LABELS`（`Record.clazz` 是 `CharField`，读出来是 `'2'`，以前批量发布的类目关键词因此是 `'2'`；认不得的代码给空串，文字类目原样）；②`taobao_publish_start_all` 与单品同一套准入：先过 `accounts.account_change_blocked()`（**不能写进 `service.lock` 里**——它内部读任务表也要拿这把不可重入的锁），再在同一把 `service.lock` 里查 `pending` / `running` 并登记，已有任务时 409（`test_sidecar_taobao_concurrency.py` 用 AST 钉着 `start` 和 `start-all` 两处的结构）；③`run_publish_batch_task` 开始时置 `running`（带 `started_at`），每条记录的资料翻译在 per-record 的 `try` 里（失败只记成该条 `类型名: 消息`、计入 `failed`、继续下一条），外层再兜一层（主体在 `_publish_batch`，其它意外让任务 `failed` 并把回溯打到 stderr），所以任务一定以 `succeeded` / `failed` / `cancelled` 之一结束——`pending` / `running` 都算「在跑」，会挡住账户切换、保存该商品和单品发布。**新旧对打从此不再逐字相同**（`cmp` 有 18 个请求不同，规整任务 id 后 16 个实质差异，`final` 里只有 `env` 一项不同：类目关键词、有任务在跑时 `start-all` 409、批量里翻译异常不再卡线程、批量运行中状态是 `running`、批量跑完后进程里不再留着 `TAOBAO_MEDIA_ROUTE=protocol`；清单见方案文档 12.3），别再把「对打 diff 为空」当这个域的验收标准。同日又补修了「未决问题」第 25 条：批量 worker 以前结束时不还原 `TAOBAO_MEDIA_ROUTE`（单品 worker 会；批量是照单品抄的、漏了 `finally`），现在 `run_publish_batch_task` 进门先记下原值、`finally` 里还原（方案文档 12.6）。

#### 抖店上传：页面操作（2026-10-21，上传域第一步）

- 上传域分两步搬（侦察：`lab/sidecar_split/closure_levels.py`）：闭包 95 个定义 / 3515 行，**65 个不碰任何服务状态**（不读写任务字典 / 锁 / `gui` / 账户别名 / 路径与端口常量，也不调用会碰这些的函数），
  其余是服务侧；依赖单向（服务侧调用纯的一侧，反过来没有），所以先搬纯的。**第一步已完成**：`upload_steps.py`（2336 行）= 62 个页面操作函数 + 异常类 `PublishUnconfirmedError` + 13 个常量，函数体与搬迁前**逐字相同**，没有任何改写规则。
  `app.py` 5235 → 2946 行。**第二步还没做**：`UploadService`（任务字典 + 锁 + 浏览器会话 + 两条流水线 + worker）和 `upload_routes.py`（`/api/upload/*` 7 条 + `/api/protocol/fxg/runtime-options` + `/start`），仍在 `app.py` 里调用 `upload_steps` 的函数。
- **边界契约**（`tests/test_upload_steps.py` 钉着）：`upload_steps.py` 不导入 flask / `app` / `src.orm` / `src.shop_session` / `src.config` / 任何 `src.sidecar.*`；函数里不引用 `gui`、`_upload_tasks`、`request`、`Record`、`settings_manager`、账户别名这类服务状态名（symtable 按作用域规则算）；
  顶层只有 import / 函数 / 类 / 常量赋值，导入它没有副作用。**它直接导入 `src.utils`（页面操作本来就靠那套浏览器工具），所以别的 `src/sidecar` 模块不要导入它——需要页面操作时由 `app.py` 把函数作为端口注入。**
- `app.py` 里仍有的：从 `upload_steps` 导入的 17 个名字（2 个常量 + 15 个流水线要调用的步骤）；`register_interaction_recovery_hook(_dismiss_interfering_overlays)`（`src.utils` 里的进程级钩子，导入时注册，**不能搬进 `upload_steps`**——否则“导入无副作用”这条契约就破了；`test_sidecar_app_smoke.py` 的接线探针守着注册的就是那个函数）。
  `_PUBLISH_CREATE_URL` 在 `upload_steps` 里定义，`app.py` 的调试浏览器默认地址（`_BROWSER_DEBUG_DEFAULT_URL`）从那里导入。
- 读发布流程源码的旧测试（`test_publish_stability_fixes.py`、`test_price_stock_virtual_scroll_fill.py`、`test_submit_publish_unconfirmed.py`、`test_upload_brand_safety.py`、`test_upload_price_stock_locators.py`、`test_select_text_brand_verification.py`、`test_shop_platform_api.py`）已改指新位置，断言一条没删；
  「整个发布流程里某字符串出现几次 / 不应出现」这类文本断言读 `tests/sidecar_function_source.py` 的 `upload_text()`（`app.py` + `src/sidecar/upload_*.py` 的全文，用文件名通配，第二步再拆出新模块不用改），不会因为代码搬家而空转。
- 纯搬迁的验证补充（AST 重放够不着的地方）：`lab/sidecar_split/check_import_equiv.py`（导入来源逐名一致；**`app.py` 里的 `time` 是 `src.utils` 里的类，标准库的叫 `system_time`**）、`check_builtin_shadow.py`（`print` 在 `app.py` 里被重绑，等价性见 lab README）、`list_leftovers.py`（搬走区域里留下的孤立常量）。
- 改坏验证：`lab/sidecar_split/sabotage.py` 里 `upload-steps:` / `app: 交互恢复钩子` / `app: 页面步骤` 开头的 16 条。2026-10-21 实测第一遍就**全部变红**：边界 6 条（导入 flask / 导入设置管理器 / 读任务字典 / 读 `gui` / 导入时打印 / 常量右值里调函数）由 `test_upload_steps` 抓住，装配 3 条（钩子没注册 / 注册成别的函数 / 步骤在 `app.py` 里被换成副本）由冒烟测试抓住，搬过去的代码本身 7 条由改指新位置的老测试抓住。

#### 图片模块

- `src/sidecar/media_routes.py`：商品目录、预览和发布白底图选择的 Flask Blueprint；继续复用 `src/product_media.py` 的目录安全与文件校验。
- `src/sidecar/whitebg_routes.py`：白底图状态、启动、进度、产物和预览的 HTTP 适配；原有 URL、方法和 JSON 结构保持不变。
- `src/sidecar/whitebg_service.py`：独立任务状态、参数解析、模型缓存和串行推理。状态锁与执行锁分开；模型配置及整个推理过程必须在同一执行锁内，不能让并发任务改写共享处理器配置。
- `src/sidecar/responses.py`：轻量返回结构。`src/utils.py` 继续导出 `api_ok/api_error` 以兼容原调用方，接口模块不要为这两个函数依赖浏览器工具库。
- `app.py` 是依赖组装入口：显式传入 `Record`、当前账户、发布编辑保护、版本计算与同一把账户锁；新模块禁止反向导入 `app.py` 或通过全局字典注入依赖。
- `WhiteBgService` 不在模块导入时加载 ONNX、初始化真实数据库或启动浏览器。不要恢复模块级 `_whitebg_tasks` / `_whitebg_processor` 平行状态。
- 新接口测试直接注册 Blueprint，使用隔离数据库和临时图片；不要新增按 `app.py` 源码位置截取这些路由的测试。相关回归：`tests/test_product_media.py`、`tests/test_whitebg_selection.py`、`tests/test_whitebg_service.py`、`tests/test_whitebg_geometry.py`。
- 拆分工具在 `lab/sidecar_split/`（按 AST 机械搬迁 + 独立校验 + 新旧对打，用法见其 README）；搬迁和逻辑修改分开做。
- 尚未拆分的域（按优先级）：抖店上传的服务侧（`/api/upload/*` 的任务 / 会话 / 流水线 / 路由，页面操作部分已在 2026-10-21 搬走，见上）、产品 CRUD。链接采集、淘宝发布已拆完（2026-10-20），但 `start_capture` 一个函数 1140 行还要按阶段 2 拆成阶段函数。按域拆分时继续保留接口兼容与独立回归；拆分方案和进度见 `docs/架构重构方案_2026-10-18.md`。
- 仍有部分旧测试按文本截取 `app.py` 里的函数来校验（`test_upload_*`、`test_submit_*` 等；淘宝相关的已在 2026-10-20 改为按函数名取源码 / 直接构造服务对象）。搬走某个函数时，先 grep `tests/` 里谁在读它，并把测试指向新位置，**不要让「X 不在源码里」这类反向断言因为代码搬家而空转**。

### 运营闭环（Ops）子系统

- `src/ops_engine.py`：选品评估、库存计划、日计划 / 日复盘、利润阶梯（目标日净利 500）、转化诊断、无品牌标题审计与整改等运营逻辑。**只做本地规则计算 + SQLite 账本读写，不调用任何外部 AI 或抖店官方 API**（模块内 `AI_POLICY` 明确禁用外部提供商，改动时不得违反）。
- 账本数据库 `ops_ledger.db`，路径经 `resolve_ops_ledger_path()` → `resolve_data_file` 解析。
- Sidecar 在 `/api/ops/*` 暴露这些能力（实现在 `src/sidecar/ops/`，含 `publish-preflight-safety`、`save-edit-human-gate` 等发布安全门）；`mcp-server/core.js` 把大部分 ops 接口包装成 MCP 工具，`mcp-server/ops-metrics-cdp.js` 负责经营数据的 CDP 采集。
- 改动 ops 逻辑后至少跑 `tests/test_ops_engine.py`、`tests/test_publish_preflight_safety.py` 和 `tests/test_ops_routes.py`（后者用假浏览器守住「安全闸未通过就绝不上传」）。

### MCP / 协议研究子系统

- `mcp-server/` (Node.js)：把 Sidecar 5001 暴露为 MCP 工具，并增加一组独立 CDP 工具（`cdp_*`），通过 `DOUYIN_CDP_LIST_URL`（默认 `http://127.0.0.1:9333/json/list`）连接已开远程调试的 Chrome。`server.js` 是 stdio 入口，`server-http.js` 是 Streamable HTTP 入口（默认 3300），`scripts/` 下是只读探针。运行 MCP 之前必须先启动 Sidecar。
- `protocol-research-clean-20260505/`：当前唯一允许扩展的协议研究目录（详见目录内 `AGENTS.md`）。约束很硬：只能输出去敏产物、不接入正式上传、不绕过登录/验证码/风控、不写兜底掩盖映射错误。核心脚本 `scripts/fxg_protocol_v4.py` 已被 Sidecar 引用。
- `protocol-research/`（旧）、`protocol-capture/`、`protocol-publish/`：运行时落地目录或历史研究目录，作参考但不要把旧结论直接搬到新流水线。
- `skills/douyin-publisher-mcp/`：Codex 技能包定义（SKILL.md、playbooks、capabilities），与 MCP Server 配对。

### 白底图语义抠图子系统

- `src/whitebg/`：把采集图做成**合规白底图**（只有袜子、转正、1:1、主体居中）。分层：
  `matte.py`（matte 模型 + 二次聚焦 + 引导滤波 + alpha 收紧）、`clip_gate.py`（CLIP 零样本
  语义闸门 + 整图场景判断）、`geometry.py`（转正护栏 / 裁主体 / 1:1 居中 / 原图方图化）、
  `pipeline.py`（单张编排）、`product.py`（目录级编排）、`paths.py`（模型路径解析）、
  `setup_models.py`（一次性下模型）。
- 和平台「一键抠图 → 白底图」的关键区别：平台用**显著性**分割，摆拍的鞋子、毯子会被一起
  抠进白底图。这里在 matte 之后加一层 CLIP 语义判断，逐连通域问「是不是袜子」，只留袜子。
- **模型不进仓库、不进安装包**（`models/whitebg/` 已在 .gitignore）。按
  `DOUYIN_WHITEBG_MODEL_DIR`（设了就只认它）→ `resolve_data_file('models/whitebg')`
  → 仓库根 `models/whitebg` 解析。装模型：`python -m whitebg.setup_models`（默认拉 birefnet-general + CLIP）。
- 实测结论（证据和出图在 `lab/whitebg/`，改之前先读 `lab/whitebg/README.md`）：
  - 默认 matte 模型是 **`birefnet-general`（MIT 许可，927MB）**。能把两只袜子之间那条
    地毯缝隙分开的只有它和 `bria-rmbg`；`u2netp` / `u2net` / `isnet-general-use` /
    `birefnet-general-lite` 都把缝隙填成实前景。选 birefnet 是因为许可干净、抠得更净、
    22 张多场景图里成 19 张（bria 只成 13 张）。
  - ⚠️ `bria-rmbg` 权重是 **CC BY-NC 4.0（非商用）**，可用 `--matte bria-rmbg` 切过去，
    但商用要自己谈授权。`birefnet-general-lite`（213MB）分不开缝隙，不能当省体积替代。
  - 两个好模型给鞋子的都是满 alpha，**靠阈值筛不掉**，语义闸门不是可选项 ——
    模型越好这层越必需。
  - 转正必须带**三道**护栏：①整图场景不是群图（`max(many,packaged) - single_pair < 0.20`）
    ②主体细长度 ≥1.45 ③多主体长轴方向偏差 ≤20°。密排成一行的袜子 mask 是实心矩形，
    PCA 长轴指的是排列方向，照着转会把袜子转倒 87.8°（实测）。
    **细长度那道是跟着 matte 模型变的**：换 birefnet 后主图_02 从 1.39 升到 1.47，
    直接溜过 1.45；第①道只看整图不看 matte，换模型不会失效，实测两组数据中间有
    0.42 的空档。改 matte 模型后必须重跑 22 张确认转正没退化。
  - 场景四分类只有 59% 准确率，所以只有 `worn`（穿着图）用作硬拒绝；`many`/`packaged`
    不拒绝，只用来关掉转正 —— 硬拒会误杀真实单品图。
- 流水线**宁可明确拒绝也不悄悄输出错图**：多色对照图、穿着图会带 `code` + 中文原因返回，
  前端如实展示。但 `SKU_1x1/` 那份不依赖模型、不会失败，兜住平台的 1:1 比例要求。
- 产出落在采集目录里，只新增不改原图：`白底图/<SKU名>.jpg`、`白底图/_report.json`、
  `白底图.jpg`（目录根，`src/utils.py` 的 `get_white_pic()` 会自动取用，发布端无需改动）、
  `SKU_1x1/<SKU名>.jpg`。
- Sidecar 在 `/api/whitebg/*` 暴露：`status`（模型就绪）、`start`（异步任务）、
  `task/<id>`（轮询）、`list`（已有产物）、`image`（预览，**只放行 uploads/products 之内**）。
  所有 `src.whitebg` 导入都在请求里延迟做：缺 onnxruntime/scipy 只是白底图不可用，
  不影响 sidecar 启动。
- 前端：`components/WhiteBgPanel.vue`（按钮 + 进度 + 结果弹窗），挂在 `ProductMediaManager.vue`
  的图片处理区域；接口在 `services/api.ts`，类型在 `types/index.ts` 的 `WhiteBg*`。
- 改 `src/whitebg/` 后至少跑 `tests/test_whitebg_geometry.py`（合成 mask，不加载模型）。

### 受保护目录

- `项目备份 禁止改动使用 只参考/`：v3.0 原版（含 `app.py`、`capture_service.py`、`web/`、`1688货品网站源码/`）。**只读参考**，禁止修改或拷贝改写；唯一例外是向 `recycle_bin/` 新增回收子目录。
- `app3.0版本/`：另一个旧版本快照，同样只读。

## 常用命令

以下命令均以仓库根目录（`E:\Script Project\Dyin\beiufen\2.1`，路径含空格，引用时注意加引号）为基准。所有桌面端启动入口已收口到根目录 `start_frontend.bat`；`tauri-app/start_backend.bat`、根目录 `start_backend.bat` 会跳回 `start_frontend.bat`，**不要再单独启 Sidecar**。

启动行为（2026-10-07 起）：桌面快捷方式 / `start_frontend.bat` **默认直接启动已构建的 `target\release\douyin-sock-publisher.exe`，不再每次编译**；需要重新编译时用 `start_frontend.bat --dev`（走 `tauri dev`，Vite + cargo）。源码改动需要生效时，先重建（`build_sidecar.py` / `npm run tauri:build`）再重启应用。

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

# 后端依赖只有一份清单：tauri-app/python-sidecar/requirements.txt（CI 与打包都用它）；根目录 requirements.txt 只转发到它
# （2026-10-18 之前根清单是 v1.0 遗留，缺 peewee / DrissionPage 等启动必需依赖，setup_dev.ps1 按它装环境会装不全）。
# 两份清单首行都带 `# -*- coding: utf-8 -*-`，pip 在中文 Windows 上不再按 GBK 误读中文注释。
pip install -r tauri-app/python-sidecar/requirements.txt
```

后端启动会在 `%LOCALAPPDATA%\com.dyin.sock-publisher\logs\` 写 `python-backend.bootstrap.log`，排查启动失败先看它。

### 白底图（语义抠图）

```powershell
# 一次性装模型（bria-rmbg 977MB + CLIP 147MB → models/whitebg/，已在 .gitignore）
$env:PYTHONPATH = 'src'
python -m whitebg.setup_models
python -m whitebg.setup_models --status    # 只看齐不齐

# 给采集目录补白底图 + 1:1 规格图（只新增，不动 SKU/ 主图/ 详情页/ 原图）
python -m whitebg "$env:LOCALAPPDATA\com.dyin.sock-publisher\uploads\products\ID-1075636304051"
python -m whitebg <目录> --canvas 1200 --matte isnet-general-use --no-deskew

# 实验室：多场景批量验证 + 调试出图（结论见 lab/whitebg/README.md）
python lab/whitebg/scripts/run_lab.py --matte bria-rmbg --out lab/whitebg/out/xx --src <SKU目录>

# Sidecar 接口冒烟（用 Flask test_client，不抢 5001 端口）
python lab/whitebg/scripts/smoke_api.py
python lab/whitebg/scripts/smoke_api.py --run    # 连带真跑一次生成（约 80 秒）
```

一个商品 7 张图约 80 秒（bria-rmbg 单张 ~11s，两轮聚焦）。打包体积代价：
onnxruntime + scipy + numpy 约 +280MB；模型 1.1GB 不打包。

### 测试

```powershell
# Python 测试：必须在仓库根目录运行（测试文件自行把仓库根注入 sys.path，没有根级 conftest/pytest.ini）
python -m pytest tests                                  # 全量
Set-Location taobao-publisher; python -m pytest tests; Set-Location ..   # 淘宝流水线子项目的另一套测试（约 10 分钟）。**必须在 `taobao-publisher/` 里跑**：它的 `pytest.ini` 里 `--basetemp=tmp/pytest-basetemp` 是相对当前目录的，从仓库根跑 `taobao-publisher/tests` 会让每个用到 `tmp_path` 的测试在 setup 阶段 ERROR（或者从根跑时加 `--basetemp=taobao-publisher/tmp/pytest-basetemp`）。改 Sidecar 结构后两套都要跑，但别和上一条同时跑（它的本地浏览器夹具读 profile 里的 DevToolsActivePort，同时跑 / 偶尔单独跑都出现过 Windows 文件锁的 PermissionError，单个文件重跑全过）
python -m pytest tests/test_ops_engine.py               # 单个文件
python -m pytest tests/test_ops_engine.py -k daily_plan # 单个用例

# mcp-server 测试与语法体检
Set-Location mcp-server
npm run check              # node --check 覆盖所有脚本
npm run test:ops           # node --test tests/*.test.mjs
```

环境现状：测试需要 **Python 3.10+**（淘宝 / 协议模块用了 `dataclass(slots=True)`）。2026-09-15 那台机器 PATH 上就是 3.11；**2026-10-18 这台机器 PATH 上的 `python` 是 3.9.13，直接跑会在收集阶段报 `dataclass() got an unexpected keyword argument 'slots'`**，要用 `py -3.11`（已装 3.11 但没有依赖）建一个 venv，装 `tauri-app/python-sidecar/requirements.txt` 的子集（flask、flask-cors、peewee、requests、websocket-client、aiohttp、psutil、DrissionPage、pillow、pyyaml、ruamel.yaml、Flask-JWT-Extended、natsort、py7zr、numpy、scipy）加 pytest 即可，不需要 PySide6 / onnxruntime。该环境下 `python -m pytest tests` 全量 **1704 passed**、`taobao-publisher/` 里 `python -m pytest tests` 全量 **1724 passed, 2 skipped**（2026-10-21，抖店上传第一步——页面操作搬进 `upload_steps.py`——之后；`tests/` 此前依次是 1681 passed（淘宝发布拆完、批量发布的 3 个既有问题修完并补上批量 worker 的 `TAOBAO_MEDIA_ROUTE` 还原之后）、1669 passed（只修了前 3 个问题时）、1629 passed（淘宝发布刚拆完、还没修批量问题时）、1333 passed（拆出链接采集之后）、1232 passed（拆出素材导入和小红书批量填表之后）、1191 passed（前端整理收尾，`test_custom_material_options.py` 改为读 `SettingsPanel.vue` + `components/settings/*.vue` + `composables/settings/*.ts` 的全文）、1190 passed + 1 条因前端拆分而失败（拆出店铺会话和调试浏览器之后）、870 passed、基线 778 passed + 1 个因测试按文本截取而误报的失败）。

`tests/` 重点覆盖发布安全门（`test_publish_preflight_safety.py`、`test_sidecar_upload_safety.py`、`test_upload_brand_safety.py`）和无品牌策略（`test_*_no_brand_policy.py`），涉及上传 / 发布 / 标题逻辑的改动必须跑对应文件。`tests/test_whitebg_geometry.py` 覆盖白底图的几何归一化与 alpha 处理（合成 mask，不加载 ONNX 模型，没装模型的机器也能跑）。

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
- 改前端结构（拆组件 / 抽 composable / 动 `api.ts` 的请求封装）不能只靠 `vue-tsc`：项目没有前端单元测试。2026-10-19 的整理用的是 **A/B 对照**——改动前把 `tauri-app/src` 备份出来，原版（1421）和新版（1420）跑同一套操作、打同一个隔离后端（`DOUYIN_DATA_DIR` 指到临时目录），比对 DOM + 计算样式、提示文字和每个后端请求；工具与用法在 `lab/frontend_ab/`（含 README 和已知的坑）；**验证代理用 5003，不要占用 / 杀 5001**——那是用户桌面应用的真实 Sidecar（里面是真实数据，应用开着时就占着），前端开发服务器要用 `lab/frontend_ab/vite.ab.config.mts` 启动，把写死的 5001 改写成代理端口。有 3 份 Python 测试按文本读前端源码（`tests/test_custom_material_options.py` 读 `SettingsPanel.vue` + `components/settings/` + `composables/settings/`；`test_taobao_frontend_validation.py`、`test_sidecar_taobao_publish.py` 读 `TaobaoPublishPanel.vue`、`api.ts`、`types/index.ts`），搬动这些文件里的代码前先 grep `tests/` 和 `taobao-publisher/tests/`（后者按文本读 `app.py` / 前端的测试统一经 `taobao-publisher/scripts/sidecar_source.py`，它同时找 `app.py` 和 `src/sidecar/**`，搬域时不用改）。
- 新增 MCP 工具要同步检查 `mcp-server/core.js`、`server.js`、`server-http.js` 与 `skills/douyin-publisher-mcp/SKILL.md`、`capabilities.md`、`playbooks.md`。
- **`tests/` 里的辅助模块不要和 `taobao-publisher/scripts/`、`taobao-publisher/tests/` 里的模块重名**：两套测试共用 `sys.path` 的插入顺序（`test_offline_pipeline_handoff.py` 会把仓库根的 `tests/` 插到最前面），同名模块在同一个 pytest 会话里会互相顶替，表现为「单独跑全绿、凑在一起跑才红」。`tests/sidecar_function_source.py` 就是因此没有叫 `sidecar_source`（后者是 `taobao-publisher/scripts/` 里的那个）。
- `CLAUDE.md` 是本文件面向 Claude Code 的镜像版本，内容应保持同步；更新本文件后同步更新 `CLAUDE.md`。
- **不要往 `tauri-app/src-tauri/sidecar/` 里放任何非打包资源**（回滚备份、`.bak`、日志一律不要）。`tauri.conf.json` 的 `"sidecar/*": "./"` 会把该目录**照单全收**进安装包，而 PyInstaller onefile 产物实测 98.5% 不可压缩——已经出过两次：`python-backend.exe.bak`（85 MB）和 `python-backend.exe.known-good-20260924`（143 MB）。回滚备份请放 `tauri-app/_sidecar_backups/`；`build_sidecar.py` 的 `prune_output_dir()` 会把误放的文件自动挪过去，`verify_output_dir()` 会在还有杂物时直接让构建失败。详见 `docs/轻量化与性能优化_2026-10-01.md`。
- 改 sidecar 打包配置/资源清单后，要真跑一次 `python build_sidecar.py`，并用 `PyInstaller.archive.readers.CArchiveReader` 核对归档条目，不要只看「构建成功」。实测旧 exe 142.72 MB、解压后 354.99 MB / 630 条——`--onefile` 每次冷启动都要写这么多。
- 协议研究产出落到 `protocol-research-clean-20260505/`，**不要复活 `protocol-research/` 下的旧脚本**；如需复用先重新实证。
- 写 Windows 路径或 PowerShell 命令时，先设置 UTF-8 编码（参见全局规则），避免中文文件名乱码。
- 编辑现有 Python 文件前先确认编码：`app.py` 顶部带 `# -*- coding: utf-8 -*-`，stdout/stderr 被 `_SafeConsoleStream` 包装，禁止替换为裸 `print` 流。
- 遇到 `python-backend.exe` 残留进程：先调用 Sidecar 的 `POST /internal/terminate`（只允许 127.0.0.1），再用 Tauri 内置的强杀路径，最后才考虑手工 Stop-Process。
- `docs/` 已经积累了大量历史调研和规划文档（协议化上传、平台错误映射、DOM 对照分析等），写新方案前先翻一遍同名前缀的最新文件，避免重复结论。
- **禁止直接删除代码文件**（`.cursor/rules/local-file-source-of-truth.mdc` 硬约束）。需要"删除"时移动到 `项目备份 禁止改动使用 只参考/recycle_bin/RECYCLE_<原因>_<YYYY-MM-DD>/`，参考已有的 `RECYCLE_测试文件_2025-11-13/`、`RECYCLE_根目录调试脚本_2026-06-13/` 等子目录命名，并在子目录内附 README 说明原因与恢复方式。
- 修改代码后如果需要重启 Sidecar / 重编译 Tauri 才能生效，**自行重启，不要问用户**；但务必先彻底关闭旧实例（先 `POST /internal/terminate`，再 `Stop-Process -Name python-backend -Force`，最后再启动新进程），避免端口占用或多实例冲突。
- **重启桌面应用的实操要点（2026-10-20 实际踩过，别重走）**：
  - 构建：`cd tauri-app; npm run tauri:build -- --no-bundle`（启动器 `start_frontend.bat` 只直接启动已构建的 exe，不会自己编译）。应用开着时构建会在复制资源时失败（`python-backend.exe` 被占用，os error 32），所以要先关应用；但可以先跑一次，把依赖编译进缓存，缩短停机时间。构建后用 `assets/` 资源名核对 exe 里内嵌的是不是新前端（扫描 exe 里的 `assets/*.js|css` 字符串，应与 `dist/assets` 完全一致）。
  - 关闭：先 `POST /internal/terminate` 让后端自己退出，再关窗口。**关窗口要按类名 `Tauri Window` 找到真窗口再发 `WM_CLOSE`**：`Process.MainWindowHandle` / `CloseMainWindow()` 在主窗口最小化时指向 tao 的内部窗口（请求会被 `event_target_guard` 忽略，而 `CloseMainWindow()` 照样返回 True）；不带 `/F` 的 `taskkill` 在启动后头几秒也无效。确认发给了真窗口、应用壳对 `CloseMainWindow` / `WM_CLOSE` / `SC_CLOSE` 仍都没反应的情况出现过一次（运行日志 `tauri-runtime.log` 里不出现 `window close requested`；机制与排查见 `docs/窗口关闭无响应排查_2026-10-20.md`，新版壳会在日志里留 `[ui-watchdog] STALL` 现场），此时再 `Stop-Process` 结束壳，并确认 WebView2 和 `python-backend.exe` 都已退出、5001 已释放（强杀壳后后端约 1.5 秒内会自己退出，实测）。
  - **从哪里启动决定读到哪份数据**：从 Claude 会话里启动的应用，数据（商品库、已登录的店铺、上传记录）落在 Claude 桌面应用的包虚拟存储里（`%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\com.dyin.sock-publisher`，在 Git Bash / Read / Glob 里看到的路径仍是 `%LOCALAPPDATA%\com.dyin.sock-publisher`）。**要走 Git Bash → Windows PowerShell 5.1 → `start_frontend.bat --no-pause` 这条链路**（继承 Claude 的包身份，读到的才是同一份数据）。Store 版 `pwsh` 7 自带独立包身份，它看到的 `%LOCALAPPDATA%\com.dyin.sock-publisher` 只有一个空的 `logs`——从它启动应用大概率会读到另一份几乎为空的数据（没实测，别试）。启动后用 `GET /api/products` 对照重启前的商品列表确认数据没变。
  - 启动前清掉环境里的 `ANTHROPIC_*` / `CLAUDE*` / `PYTHON*`（Claude 会话的令牌不能带进长期运行的应用）；不要用 `Start-Process -Wait` 调启动器（会一直等应用这个后代进程）。
