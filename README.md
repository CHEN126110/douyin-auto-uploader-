# 电商产品发布工具（抖音袜子发布工具 v4.0）

把「商品采集 → 资料整理 → 平台发布」做成本地桌面客户端：**Tauri 2（Rust 壳）+ Vue 3 前端 + Python Flask Sidecar**，
业务逻辑和浏览器自动化都在本机运行。

> 对外名称是「电商产品发布工具」（2026-10-20 起，窗口标题、页面标题和欢迎页也改用它）；安装包名、`tauri.conf.json` 的 `productName`、exe 文件描述与应用内更新链路仍沿用内部名「抖音袜子发布工具」，`identifier`（`com.dyin.sock-publisher`，决定数据目录）和 exe 名 `douyin-sock-publisher` 也不改。两者是同一个应用。
> 旧版 README（v1.0「淘宝商品信息采集系统」）已归档到 [`docs/历史/README_v1.0_淘宝采集系统.md`](docs/历史/README_v1.0_淘宝采集系统.md)。

## 平台与现状

| 平台 | 目录 | 现状 |
|---|---|---|
| 抖店 | `src/`、`tauri-app/python-sidecar/` | 主线：采集、整理、发布（DOM 与协议化两条路径） |
| 淘宝 | `taobao-publisher/` | 独立子项目，与抖店链路隔离；就绪度和红线以其 `README.md` / `AGENTS.md` 为准 |
| 小红书千帆 | `xiaohongshu-publisher/` | 独立子项目；默认零写入，提交上架需单独授权 |

## 架构

```text
Vue 3 前端 ──HTTP──▶ Python Flask Sidecar（127.0.0.1:5001）
    ▲                   ├─ tauri-app/python-sidecar/app.py   入口与依赖组装、尚未拆出的业务
    │                   ├─ src/sidecar/                       按业务域拆出的 Blueprint（运营闭环、设置、定价、AI、标题、图片…）
Tauri 壳（Rust）        └─ src/                               共享业务库（ORM、浏览器自动化、定价、运营引擎…）
 窗口 / 拖拽 / 更新                                              └─▶ SQLite、本地文件、经 CDP 控制的 Chrome
 托管 Sidecar 进程
```

## 目录

| 目录 | 内容 |
|---|---|
| `tauri-app/` | 桌面端：`src/` Vue 前端、`src-tauri/` Rust 壳、`python-sidecar/` Flask 入口与打包脚本 |
| `src/` | 共享业务库；`src/sidecar/` 是各业务域的接口模块 |
| `mcp-server/` | 把 Sidecar 暴露为 MCP 工具，另带只读的 CDP 探针 |
| `skills/douyin-publisher-mcp/` | 与 MCP Server 配对的技能包 |
| `taobao-publisher/`、`xiaohongshu-publisher/` | 另两个平台的研究与实现 |
| `ecom-agent/` | 选品 / 盈利分析（发布之前的环节） |
| `protocol-research-clean-20260505/` | 协议化上传的研究与脚本（唯一允许扩展的协议研究目录，只输出去敏产物，约束见其 `AGENTS.md`） |
| `tests/` | Python 回归测试 |
| `docs/` | 设计、实证与运维文档 |
| `lab/` | 实验与辅助脚本（白底图实验、Sidecar 拆分工具） |

## 快速开始

```powershell
.\start_frontend.bat           # 启动已构建的应用（不会自动编译；还没有构建时会提示先 npm run tauri:build -- --no-bundle）
.\start_frontend.bat --dev     # 改了源码后重新编译运行（tauri dev）
```

开发环境配置、构建与打包命令见 [`tauri-app/README.md`](tauri-app/README.md)。后端依赖只有一份清单：
[`tauri-app/python-sidecar/requirements.txt`](tauri-app/python-sidecar/requirements.txt)（根目录 `requirements.txt` 只转发到它）。

## 测试

```powershell
# Python：需要 3.10+；依赖见上面的清单（不需要 PySide6 / onnxruntime 也能跑全量）
python -m pytest tests

# 前端类型检查
Set-Location tauri-app; npx vue-tsc --noEmit

# MCP Server
Set-Location mcp-server; npm run check; npm run test:ops
```

## 文档索引

- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md)：工程约定、模块边界、常用命令（两份内容保持同步）。
- [`docs/架构重构方案_2026-10-18.md`](docs/架构重构方案_2026-10-18.md)：Sidecar 按业务域拆分的方案与进度。
- [`docs/TAURI_MIGRATION_SPEC.md`](docs/TAURI_MIGRATION_SPEC.md)：v3.0 → v4.0 迁移规格。
- [`tauri-app/README.md`](tauri-app/README.md)：桌面端结构、构建、端口、主要接口。
- [`mcp-server/README.md`](mcp-server/README.md)：MCP 工具与 CDP 探针。

## 安全红线

- 不绕过登录、验证码和平台风控。
- 上传、保存、提交等会改动平台数据的动作，必须有显式授权；探针和抓包脚本只做观察。
- 运营闭环（`src/ops_engine.py`）只做本地规则计算和账本读写，不调用外部 AI。
