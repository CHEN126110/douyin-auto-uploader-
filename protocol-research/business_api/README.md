# business_api —— 抖店电商业务域 DOM 自动化 API

基于 **DrissionPage 接管真实 Chrome** 的合规 RPA 方案：用用户自己已登录的真实浏览器，
在真实页面上做真人式 DOM 操作，对外暴露统一 HTTP 业务接口。覆盖 11 个大项业务域。

## 合规边界

- 只接管用户自己、已登录的真实浏览器，操作用户自己的店铺数据。
- 不复现平台私有签名、不拼裸协议请求、不绕过验证码 / 风控（命中即交人工）。
- 通过控频按真人节奏操作。
- 与逆向签名 / 绕风控的"非官方协议接口"是**不同路线**，本模块不做后者。

## 目录结构

```
business_api/
├── core/            # 框架底座
│   ├── errors.py        # 错误码 + 业务异常
│   ├── responses.py     # 统一响应 envelope + HTTP 状态映射
│   ├── driver.py        # BrowserDriver 抽象 + DrissionPage 实现 + connect_chromium
│   └── context.py       # HumanPacer 控频 / CaptchaGuard 验证码守卫 / BrowserContext 编排
├── domains/         # 业务域
│   ├── base.py          # 上下文工厂 / 异常处理装饰器 / 参数校验 / 骨架注册
│   ├── product.py       # ✅ 商品域（真实编排范本）
│   ├── order.py         # ✅ 订单域（列表脱敏 + 发货定位 dry_run）
│   ├── aftersale.py     # ✅ 售后域（列表脱敏 + 退款定位 dry_run）
│   ├── compass.py       # ✅ 电商罗盘域（核心数据指标卡，只读）
│   └── skeletons.py     # 🔲 其余 7 域契约骨架
├── tests/           # 单元测试（FakeDriver，免真实浏览器）
├── server.py        # Flask 独立服务入口
├── API_BLUEPRINT.md # 全部接口蓝图
└── README.md
```

## 安装依赖

依赖与主项目 `tauri-app/python-sidecar/requirements.txt` 一致（flask、DrissionPage 等）。
测试额外需要 `pytest`。

## 启动

1. 以远程调试端口启动 Chrome（或复用项目现有的浏览器启动流程），并在其中登录抖店：

   ```bat
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug"
   ```

2. 启动服务（在 `protocol-research` 目录下）：

   ```bat
   set DOUYIN_CHROME_ADDRESS=127.0.0.1:9222
   set BUSINESS_API_PORT=8800
   python -m business_api.server
   ```

3. 调用：

   ```bash
   curl http://127.0.0.1:8800/health
   curl http://127.0.0.1:8800/catalog
   curl -X POST http://127.0.0.1:8800/api/product/list -H "Content-Type: application/json" -d "{\"keyword\":\"\",\"limit\":20}"
   ```

## 与主项目 app.py 集成（可选）

`app.py` 已有成熟的浏览器会话管理（`_get_current_browser_tab` 等）。如需复用其会话而非自行
attach，可在启动时注入上下文工厂：

```python
from business_api.domains.base import set_context_factory
from business_api.core import BrowserContext, DrissionDriver

def factory():
    tab = get_current_tab_from_app()   # 复用 app.py 的 tab
    return BrowserContext(DrissionDriver(tab))

set_context_factory(factory)
```

## 提供给 Agent 使用

business_api 自带工具发现与统一调用，任何支持 MCP / function-calling 的 Agent 都能消费：

- `GET /mcp/tools`：返回全部业务接口的工具 schema（`name` / `description` / `inputSchema` + 决策元数据）。
- `POST /mcp/call`：统一调用入口，body `{"name": "product.list", "arguments": {...}}`，
  返回 MCP 风格结果（`structuredContent` + `content[].text` + `isError`）。

为 Agent 安全设计：

- 工具标注 `readOnlyHint` / `destructiveHint`，Agent 可区分"查询"与"会改动店铺的写操作"。
- 写操作（上下架 / 改价等）默认 `dry_run`，需显式 `confirm=true` 才真实执行。
- 命中验证码 / 登录失效返回 `CAPTCHA_REQUIRED` / `LOGIN_REQUIRED`，Agent 据此暂停并交回人类。

也可由现有 Node `mcp-server` 桥接：它本就是 "backend HTTP → MCP tools" 模式，把 backend 指向 business_api 即可。

## 测试

```bash
python -m pytest business_api/tests -q
```

测试用 `FakeDriver` 脚本化页面行为，**无需真实浏览器**即可验证编排逻辑、错误处理与 HTTP 层。

## 已知限制（如实说明）

- **已联调 4 域**：商品 / 订单 / 售后 / 电商罗盘的 `URLS` / `SEL` 已在真实登录环境验证跑通；
  写操作（上下架 / 发货 / 退款）默认 dry_run，资金敏感的真实提交暂不开放（见 API_BLUEPRINT.md）。
- **7 个域为契约骨架**：流量运营 / 营销活动 / 付费推广 / 巨量千川 / 资金 / 店铺 / 用户的
  API 面已可对接，真实 DOM 编排待逐个联调填充。
- **页面改版风险**：选择器依赖现网 DOM 结构，平台改版会使其失效，需按 PAGE_STRUCTURE_CHANGED / ELEMENT_NOT_FOUND 报错定位维护。
- **DOM 方案固有局限**：比协议慢、页面改版会使选择器失效需维护、并发能力弱。
- **环境提示**：当前环境 `flask 2.3.2` + `werkzeug 3.1.3` 版本错配（新版 werkzeug 移除了
  `__version__`，Flask 2.3.2 的 test_client 仍引用它）。测试已用 conftest 垫片绕开；
  若主项目运行时也用到受影响的 werkzeug API，建议把二者对齐到兼容版本（如 flask 2.3.x + werkzeug 2.3.x）。
