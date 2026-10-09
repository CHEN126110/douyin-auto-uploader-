# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本项目必须遵守 `C:\Users\12611\.claude\CLAUDE.md` 中的全局提示词。

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
- 主工作区有大量未提交 / 未跟踪文件（包括本文件和 `AGENTS.md`），改动前先看 `git status`，不要假设工作区是干净的。

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
   - Flask 启动与依赖组装入口，保留产品 CRUD、智能标题、智能定价、链接采集、商品发布、CDP 调试浏览器、协议化上传、运营闭环与设置管理；图片相关接口和任务服务已拆至 `src/sidecar/`。
   - 关键路由前缀：`/api/products`、`/load_detail`、`/save_info`、`/api/capture/*`、`/api/upload/*`、`/api/pricing/*`、`/api/debug/browser/*`、`/api/shop/*`、`/api/protocol/fxg/*`、`/api/ops/*`、`/settings*`。
   - 路由同时使用 `@app.route` 和 `@app.get` / `@app.post` 两种风格注册，grep 路由时不要只搜 `@app.route`。
   - 通过 `repo_root` 注入 `sys.path` 后从 `src/` 导入业务模块（开发模式）；打包后由 `PyInstaller` 一并冻结。
   - 运行时路径统一走 `src/runtime_paths.py` 的 `resolve_data_file` / `bootstrap_runtime_environment`，会按 `DOUYIN_DATA_DIR` → `LOCALAPPDATA\com.dyin.sock-publisher` → 仓库根目录的顺序解析 `cfg.yaml / sqlite.db / pricing_config.json / user_settings.json / trending_keywords.db / ops_ledger.db`，并自动从源位置 seed 到运行目录，**不要在代码里写死绝对路径**。
   - Sidecar 模式由 `SIDECAR_MODE=1` 区分：sidecar 模式 5001 端口、纯后端；非 sidecar 时会尝试加载 PySide6 GUI（保留 v3.0 行为）。

4. **共享业务库** (`src/`)
   - 被 Sidecar 直接 import 的 Python 模块：`orm.py`（Peewee + SQLite + 列迁移）、`utils.py`（DrissionPage 浏览器自动化）、`ops_engine.py`（运营闭环）、`enhanced_category_selector.py`、`smart_pricing_engine.py`、`professional_title_generator.py`、`chrome_manager.py`、`config.py`、`runtime_paths.py`、`shop_session.py`（多店铺登录会话与店铺身份实测）、`thread.py`、`constants.py`、`trending_keywords_scraper.py`。
   - 数据库主表 `Record` 在 `orm.py:21`，`_ensure_record_columns()` 实现向后兼容字段迁移。新增字段要同时更新模型类和 `migrations` 列表。
   - ⚠️ `config_manager.py`、`confidence_scorer.py`、`quantity_extraction_enhanced.py`、`post_interaction_validator.py`、`chrome_installer_gui.py` 虽然业务代码不直接 import，但被 `tauri-app/python-sidecar/build_sidecar.py` 和 `python-backend.spec` 列为 PyInstaller hiddenimports，**不能删除或移动**（2025-11-14 曾误回收后又恢复）。

### Sidecar 图片模块边界（2026-10-09）

- `src/sidecar/media_routes.py`：商品目录、预览和发布白底图选择的 Flask Blueprint；继续复用 `src/product_media.py` 的目录安全与文件校验。
- `src/sidecar/whitebg_routes.py`：白底图状态、启动、进度、产物和预览的 HTTP 适配；原有 URL、方法和 JSON 结构保持不变。
- `src/sidecar/whitebg_service.py`：独立任务状态、参数解析、模型缓存和串行推理。状态锁与执行锁分开；模型配置及整个推理过程必须在同一执行锁内，不能让并发任务改写共享处理器配置。
- `src/sidecar/responses.py`：轻量返回结构。`src/utils.py` 继续导出 `api_ok/api_error` 以兼容原调用方，接口模块不要为这两个函数依赖浏览器工具库。
- `app.py` 是依赖组装入口：显式传入 `Record`、当前账户、发布编辑保护、版本计算与同一把账户锁；新模块禁止反向导入 `app.py` 或通过全局字典注入依赖。
- `WhiteBgService` 不在模块导入时加载 ONNX、初始化真实数据库或启动浏览器。不要恢复模块级 `_whitebg_tasks` / `_whitebg_processor` 平行状态。
- 新接口测试直接注册 Blueprint，使用隔离数据库和临时图片；不要新增按 `app.py` 源码位置截取这些路由的测试。相关回归：`tests/test_product_media.py`、`tests/test_whitebg_selection.py`、`tests/test_whitebg_service.py`、`tests/test_whitebg_geometry.py`。
- 本次未拆分采集、发布及运营业务，不改变前端或数据库结构；后续按域拆分时继续保留接口兼容与独立回归。

### 运营闭环（Ops）子系统

- `src/ops_engine.py`：选品评估、库存计划、日计划 / 日复盘、利润阶梯（目标日净利 500）、转化诊断、无品牌标题审计与整改等运营逻辑。**只做本地规则计算 + SQLite 账本读写，不调用任何外部 AI 或抖店官方 API**（模块内 `AI_POLICY` 明确禁用外部提供商，改动时不得违反）。
- 账本数据库 `ops_ledger.db`，路径经 `resolve_ops_ledger_path()` → `resolve_data_file` 解析。
- Sidecar 在 `/api/ops/*` 暴露这些能力（含 `publish-preflight-safety`、`save-edit-human-gate` 等发布安全门）；`mcp-server/core.js` 把大部分 ops 接口包装成 MCP 工具，`mcp-server/ops-metrics-cdp.js` 负责经营数据的 CDP 采集。
- 改动 ops 逻辑后至少跑 `tests/test_ops_engine.py` 和 `tests/test_publish_preflight_safety.py`。

### MCP / 协议研究子系统

- `mcp-server/` (Node.js)：把 Sidecar 5001 暴露为 MCP 工具，并增加一组独立 CDP 工具（`cdp_*`），通过 `DOUYIN_CDP_LIST_URL`（默认 `http://127.0.0.1:9333/json/list`）连接已开远程调试的 Chrome。`server.js` 是 stdio 入口，`server-http.js` 是 Streamable HTTP 入口（默认 3300），`scripts/` 下是只读探针。运行 MCP 之前必须先启动 Sidecar。
- `protocol-research-clean-20260505/`：当前唯一允许扩展的协议研究目录（详见目录内 `AGENTS.md`）。约束很硬：只能输出去敏产物、不接入正式上传、不绕过登录/验证码/风控、不写兜底掩盖映射错误。核心脚本 `scripts/fxg_protocol_v4.py` 已被 Sidecar 引用。
- `protocol-research/`（旧）、`protocol-capture/`、`protocol-publish/`：运行时落地目录或历史研究目录，作参考但不要把旧结论直接搬到新流水线。
- `skills/douyin-publisher-mcp/`：Claude 技能包定义（SKILL.md、playbooks、capabilities），与 MCP Server 配对。

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

# 全量后端依赖（根目录 requirements.txt 比 sidecar 子集更全，两份都要看）
pip install -r requirements.txt                        # 仓库根
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
python -m pytest tests/test_ops_engine.py               # 单个文件
python -m pytest tests/test_ops_engine.py -k daily_plan # 单个用例

# mcp-server 测试与语法体检
Set-Location mcp-server
npm run check              # node --check 覆盖所有脚本
npm run test:ops           # node --test tests/*.test.mjs
```

环境现状（2026-09-15 实测）：PATH 上的 `python` 已经是 **3.11.16** 且装了 pytest，`python -m pytest tests` 全量 262 passed，`tests/test_protocol_no_brand_policy.py` 也能正常跑（它经 `protocol_publish/models.py` 用到 `dataclass(slots=True)`，需 3.10+）。历史文档里「PATH 上的 python 是 3.9、要 `--ignore` 这个文件」的说法已经过期，不必再照着做。

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
- 新增 MCP 工具要同步检查 `mcp-server/core.js`、`server.js`、`server-http.js` 与 `skills/douyin-publisher-mcp/SKILL.md`、`capabilities.md`、`playbooks.md`。
- `AGENTS.md` 是本文件面向 Codex 的镜像版本，内容应保持同步；更新本文件后同步更新 `AGENTS.md`。
- **不要往 `tauri-app/src-tauri/sidecar/` 里放任何非打包资源**（回滚备份、`.bak`、日志一律不要）。`tauri.conf.json` 的 `"sidecar/*": "./"` 会把该目录**照单全收**进安装包，而 PyInstaller onefile 产物实测 98.5% 不可压缩——已经出过两次：`python-backend.exe.bak`（85 MB）和 `python-backend.exe.known-good-20260924`（143 MB）。回滚备份请放 `tauri-app/_sidecar_backups/`；`build_sidecar.py` 的 `prune_output_dir()` 会把误放的文件自动挪过去，`verify_output_dir()` 会在还有杂物时直接让构建失败。详见 `docs/轻量化与性能优化_2026-10-01.md`。
- 改 sidecar 打包配置/资源清单后，要真跑一次 `python build_sidecar.py`，并用 `PyInstaller.archive.readers.CArchiveReader` 核对归档条目，不要只看「构建成功」。实测旧 exe 142.72 MB、解压后 354.99 MB / 630 条——`--onefile` 每次冷启动都要写这么多。
- 协议研究产出落到 `protocol-research-clean-20260505/`，**不要复活 `protocol-research/` 下的旧脚本**；如需复用先重新实证。
- 写 Windows 路径或 PowerShell 命令时，先设置 UTF-8 编码（参见全局规则），避免中文文件名乱码。
- 编辑现有 Python 文件前先确认编码：`app.py` 顶部带 `# -*- coding: utf-8 -*-`，stdout/stderr 被 `_SafeConsoleStream` 包装，禁止替换为裸 `print` 流。
- 遇到 `python-backend.exe` 残留进程：先调用 Sidecar 的 `POST /internal/terminate`（只允许 127.0.0.1），再用 Tauri 内置的强杀路径，最后才考虑手工 Stop-Process。
- `docs/` 已经积累了大量历史调研和规划文档（协议化上传、平台错误映射、DOM 对照分析等），写新方案前先翻一遍同名前缀的最新文件，避免重复结论。
- **禁止直接删除代码文件**（`.cursor/rules/local-file-source-of-truth.mdc` 硬约束）。需要"删除"时移动到 `项目备份 禁止改动使用 只参考/recycle_bin/RECYCLE_<原因>_<YYYY-MM-DD>/`，参考已有的 `RECYCLE_测试文件_2025-11-13/`、`RECYCLE_根目录调试脚本_2026-06-13/` 等子目录命名，并在子目录内附 README 说明原因与恢复方式。
- 修改代码后如果需要重启 Sidecar / 重编译 Tauri 才能生效，**自行重启，不要问用户**；但务必先彻底关闭旧实例（先 `POST /internal/terminate`，再 `Stop-Process -Name python-backend -Force`，最后再启动新进程），避免端口占用或多实例冲突。
