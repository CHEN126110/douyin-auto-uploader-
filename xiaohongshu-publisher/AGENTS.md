# 小红书千帆发布（xiaohongshu-publisher）— 工作约定

本目录是**小红书千帆（`ark.xiaohongshu.com`）发布链路**的研究与实现区，与
`taobao-publisher/`（淘宝）、根目录 `src/`（抖店）并列。红线沿用
`taobao-publisher/AGENTS.md` 那一套：**默认零写入、提交上架单独授权、不绕过验证码/风控、
字段无实证记 `unknown` 不许猜、平台文档只作参考（以真机为准）**。

## 环境

| 项 | 值 |
|---|---|
| 调试端口 | **9336**（抖店 9333、淘宝 9334 不复用） |
| 独立 profile | `.runtime/chrome-xhs-cdp` |
| 启动方式 | 复用 `protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs`（它本来就参数化：`TAOBAO_CDP_PORT` / `TAOBAO_CDP_PROFILE_DIR` / `TAOBAO_PUBLISH_URL`） |
| 登录 | 人工完成（跳 `customer.xiaohongshu.com/login`），登录态随 profile 持久化 |
| 创建页 | `https://ark.xiaohongshu.com/app-item/good/create`（多步向导） |
| 探针目录 | `tmp/`（gitignore），脱敏产物才进 `captures/` |

## 四条实现纪律（全部由真机失败逼出来，违反就会踩坑）

1. **必须在可见标签页里操作。** `document.visibilityState !== 'visible'` 时**不执行点击**
   （隐藏标签页会被浏览器节流，点击静默失效 → 会被误判成"控件不存在"）。
   做法：`Target.activateTarget`；仍不可见就 `Target.createTarget` 新开前台标签页；
   窗口本身在后台时，`Target.activateTarget` 不够（`Page.setWebLifecycleState{state:'active'}`
   + `Emulation.setFocusEmulationEnabled` 只在**窗口已在前台**时有效）。
2. **表单填写只能用「原生 setter + input/change 事件」。**
   `Input.insertText`、逐字符 `dispatchKeyEvent`（补 `windowsVirtualKeyCode`）、
   IME 式（229+text）**全部无效**——该页是 React 受控组件，只认原生 setter：
   ```js
   const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
   setter.call(input, text);
   input.dispatchEvent(new Event('input', {bubbles:true}));
   input.dispatchEvent(new Event('change', {bubbles:true}));
   ```
   写完必须**主动失焦**（`blur()` + `blur`/`change` 事件），否则后续字段不出现。
3. **点击前先反查命中**：`document.elementFromPoint(x, y)` 确认最上层就是目标（或其子元素）。
   这一步用来区分三类完全不同的故障：**被覆盖层盖住** / **坐标不在视口** / **组件不响应**。
   不反查就会把前两类误判成第三类（本项目已各栽过一次）。
4. **素材空间抽屉是覆盖式的（drawer + mask + footer），开着就点不到页面控件。**
   任何针对创建页表单的操作前，先确认 `[class*="material-space-drawer"]` 可见数量为 0。
   关抽屉的正确办法是点**它自己的「取消」按钮**（点遮罩、按 Esc 实测都关不掉）。

## 已实证的关键事实（详见 `docs/05-证据日志.md`）

- **图片是整页的解锁开关**：未传图时页面只有「商品图片 + 商品标题」。
  上传入口 → **素材空间抽屉**（不是原生文件框）；上传走
  「真实点『上传本地图片』（`input[type=file]` 此刻才挂载）→ `DOM.setFileInputFiles`」，
  成功判据是平台文案「**本次共成功上传 N 个文件，M 个文件上传失败**」（**不是**素材列表的「共 0 条」）。
- **标题框识别**：可见 `input[type=text]` 中 **placeholder 提到「品牌」**的那个
  （文案「系统已自动在商品标题前拼接品牌名称，请勿重复填写品牌名称。」）。
  placeholder 是**轮换提示**，顶部还有一个同样轮换的帮助框，**都不能当锚点**。
- **标题规则**：`16-60 个字符（8-30 个字）`，且**计数器对汉字按 2 计**（28 汉字 = 56/60）
  → 实际可用上限约 **30 个汉字**；平台会自动拼品牌前缀，标题本身不要带品牌。
- **类目**：写完标题**失焦**后类目区块解锁 → 平台给出「**智能推荐**」（实测推荐
  长筒袜/中筒袜/连裤袜/短袜/运动袜，与商品吻合）+ **四级级联**（一级~四级）+ 关键词搜索 +
  「新增品类」。**"上面仅展示店铺可售类目"** → 未开通的类目不在列表里。
- **硬门**：未选类目时点「信息已确认，下一步」被拦，平台返回 **`错误：请选择商品类目`**
  → **进不了下一组表单**。

## 当前阻塞（详见 `docs/06-阻塞项.md`）

- ✅ **B-XHS-01 已解除**：袜子类目**已开通**（人工办理），实测可选并已选入
  `女士内衣/男士内衣/家居服 > 短袜/打底袜/丝袜/美腿袜 > 长筒袜`；
  向导已能推进到四组信息（基础信息 / 图文信息 / 价格库存 / 服务信息）。
- ⛔ **B-XHS-02（当前唯一硬阻塞）**：**运费/物流模板尚未创建** ✗
  （`app-order/logistics/template` 实测是"新建运费模版"空表单）。
  创建页 13 项必填里 `物流模板 / 物流类型 / 运费模板 / 发货模式 / 现货发货时间` 全未填
  → **模板建好之前，商品填不完、发布不了**。**只能人工在千帆后台建**（本工具不代做）。
- ⏳ 待定位：发货地址库入口（4 个候选已排除，记 `unknown`）。

## 实现约束：一气呵成，中途不导航

**实测（`verified`，2026-10-10）**：把页面导航到别处（哪怕只是去 `app-order/*` 读一眼）再回到
创建页，**表单里已填的图片/标题/类目全部丢失** ✗ —— 判据也回到"商品图片必填未填"的初始态。

→ **fill_only 必须在一次连续会话内跑完**，顺序固定：

```
进创建页 → 传图 → 填标题（失焦）→ 选类目（先关抽屉！）→ 点下一步
→ 读 required-icon 全集 + 三个判据 → 按缺口填属性/服务信息 → **停在提交前**
```

**不要**"读一半、去别的页面查点东西、再回来接着填" ✗ —— 那样只能从头再来（图片还得重传）。

## 目录约定

- `tmp/`：探针脚本（gitignore），命名 `probe-*.py` / `<动作>.py`，每个脚本顶部写清"只读/写入"与跑法。
- `docs/`：`05-证据日志.md`（每轮追加 `E-XHS-*` 条目，含**被证伪的假设**）、
  `06-阻塞项.md`、`07-字段测绘表.md`（待建）、验收记录。
- `captures/`：只放脱敏产物（URL 去掉查询串、不落 cookie/token）。
