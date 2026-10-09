# scripts · 只读探针

本目录的脚本**只能观察，不能动手**。它们存在的唯一目的是为
`contracts/` 收集证据。

## 红线

| 允许 | 禁止 |
|---|---|
| 通过 CDP 读页面结构 | 点击、输入、上传、保存草稿、提交 |
| 被动观察网络请求 | 请求拦截、修改、重放、重发 |
| 读取控件的 `id` / `placeholder` / `aria-label` / 文本 | **读取输入框的 `value`**（页面可能已被卖家填过资料） |
| 写原始产物到 `tmp/`（已 gitignore） | 直接把原始产物写进 `captures/` |

**与抖店探针的区别**：抖店的 `probe-fxg-upload.mjs` 在 `UPLOAD_IMAGE_PATH` 授权下
会真的触发一次上传。本目录的探针**连这样的开关都没有** —— 淘宝发布页的字段
一条都没实证，任何写操作都无从设计，装了开关只会诱惑人去试。

## 脚本

### `probe-publish-workbench.mjs`

勘察当前发布工作台的页面结构：控件清单（tag / id / name / placeholder / 文本）、
带 `attr-field-id` 的字段容器、按业务关键词（类目 / 标题 / 属性 / 规格 /
价格库存 / 运费 / 图片 / 提交）分组的候选区块。**不导航**——它只看你当前停留的那个页面。

```powershell
node taobao-publisher/scripts/probe-publish-workbench.mjs
```

输出 → `taobao-publisher/tmp/tb_workbench_probe_raw_<时间戳>.json`

**它的输出是「候选」，不是「结论」**。把选择器写进 `contracts/selectors.json` 之前
必须人工确认唯一性（会匹配到多个元素的选择器不能用来驱动写操作）。

### `watch-publish-flow.mjs`（推荐：走一遍就收全）

`probe-publish-workbench.mjs` 是**一次性**快照，你每走一步都得手动重跑。
淘宝发布流程有 6–7 步，手动重跑极易漏步。这个脚本每 1.5 秒问一次页面
「你换步了吗」（轻量指纹），一换步就自动落一份完整结构快照。

```powershell
node taobao-publisher/scripts/watch-publish-flow.mjs                          # 默认 30 分钟
node taobao-publisher/scripts/watch-publish-flow.mjs --seconds 3600 --interval 2000
```

你只需要在浏览器里**正常手动走一遍**流程，不用管脚本，也不用回来找它。
产出 → `taobao-publisher/tmp/publish-flow-<时间戳>/step-NN.json`

它会自动发现新开的标签页、自动跳过登录页并提示扫码、Chrome 重启后自动重连。
最多落 40 份快照，防止被遗忘在后台时写满磁盘。

### `capture-publish-requests.mjs`

被动观察请求。**你自己手动在浏览器里操作发布流程**，它只记录。

```powershell
node taobao-publisher/scripts/capture-publish-requests.mjs                 # 默认 180 秒
node taobao-publisher/scripts/capture-publish-requests.mjs --seconds 1800
node taobao-publisher/scripts/capture-publish-requests.mjs --wait 300      # 等 CDP 最多 300 秒
node taobao-publisher/scripts/capture-publish-requests.mjs --out tmp/my.json
```

只记录这些 host 的请求（避免把无关第三方流量写进产物）：
`item.upload.taobao.com`、`item.upload.tmall.com`、`h5api.m.taobao.com`、
`mtop.taobao.com`、`api.m.taobao.com`、`market.m.taobao.com`、`img.taobao.com`、
`stream.taobao.com`、`qn.taobao.com`。

对 XHR / Fetch 会尽力回读响应体，但**只提取 `ret` 字段**，整段响应体不入库
（可能含大量店铺数据）。POST body 截断到 4000 字符并标记是否被截断。

命中 `publish` / `submit` / `save` / `add` / `update` / `create` / `upload` /
`commit` / `apply` 这类关键词的非 GET 请求会被标为 `write_like` —— 那表示
**你刚刚真的写进平台了**，值得仔细看。

输出 → `taobao-publisher/tmp/tb_publish_requests_raw_<时间戳>.json`

### `watch-publish-flow-visual.py`（无 CDP 时的兜底）

用户日常 Chrome 已登录、但**不开调试端口**时用这个。它定时用 Win32 `PrintWindow`
截取指定窗口，画面有明显变化就存一帧（均值哈希去重），把一次手动走查变成可回看的流程图。

```powershell
python taobao-publisher/scripts/watch-publish-flow-visual.py --pid 29424 --seconds 1800 --title-filter 商品发布
python taobao-publisher/scripts/watch-publish-flow-visual.py --title 商品发布 --interval 2 --title-filter 商品发布
```

产物：`taobao-publisher/tmp/visual-flow-<时间戳>/frame-NN.png` + `manifest.json`

> ⚠️ **务必加 `--title-filter`。** 它是同一窗口里切换标签页时的唯一护栏：
> 不加的话，用户中途去干别的事（回消息、看视频）也会被拍下来。
> 2026-10-03 首次实跑就踩了这个坑——60 帧里有一大半是无关浏览。
> 加上过滤后，标题不含该子串时直接跳过、不落盘。
>
> 窗口最小化时也会跳过（`GetWindowRect` 在最小化状态下返回 `158x26` 的假尺寸，
> 截出来是个无意义小图，还会被误判成「画面变了」）。只在**启动时**恢复一次显示，
> 运行中不再自动弹窗——用户主动最小化时反复把它拉回来是在跟用户抢桌面。

**能看到**：页面长什么样、有哪几步、每步有哪些字段与按钮、校验提示原文。
**看不到**：CSS 选择器、DOM 层级、接口名与请求字段。

> ⚠️ 它的产物**禁止**用来填 `contracts/selectors.json`。画面看出来的选择器是猜的，
> 而契约门要求 `verified`。本脚本只用来**理解流程**，不能用来**做自动化**。
>
> ⚠️ 截图含**已登录的页面内容**（店铺名、商品资料）。留在 gitignore 的 `tmp/` 下，
> **不要**提交进仓库。

唯一的可见副作用：目标窗口若已最小化，会先 `ShowWindow(SW_RESTORE)` 恢复显示，
否则 `PrintWindow` 只能拿到黑图。可逆。

### `lib/workbench-snapshot.mjs`

两个脚本共用的页面内表达式（`DETAIL_EXPRESSION` / `FINGERPRINT_EXPRESSION` /
`fingerprintKey`）。抽出来的原因很简单：那是一段约 3.6KB 的 JS，两处各维护一份
迟早会不一致。

**只读保证写在这个模块的注释里**，改之前先读：不 `click()`、不 `focus()`、
不 `dispatchEvent()`、不读输入框 `value`、不改 DOM、不发请求。

## 推荐的取证顺序

```powershell
# 1) 起调试实例（独立 profile，需扫码一次）
node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs

# 2) 两个窗口分别挂上观察器（都是只读）
node taobao-publisher/scripts/watch-publish-flow.mjs --seconds 1800
node taobao-publisher/scripts/capture-publish-requests.mjs --seconds 1800 --wait 300

# 3) 在浏览器里手动走一遍：选类目 → 标题 → 属性 → 规格 → 主图 → 价格库存 → 运费
#    走到「保存草稿」前停下，**不要点提交**

# 4) 收产物
ls taobao-publisher/tmp/publish-flow-*/
```

两个观察器可以**同时**跑：一个看 DOM 结构，一个看网络请求，互不干扰。

## 端口守卫

两个脚本都硬性要求 CDP 地址含 `:9334`。抖店用 9333，连错实例会把抖店的登录态
当成淘宝的用 —— 所以是**前置校验**，在任何网络调用之前就拒绝。

## 脱敏流程

```
探针 → tmp/<raw>.json              （原始，绝不进仓库）
  │
  └─ python -m taobao_publish sanitize tmp/<raw>.json captures/<脱敏>.json
       └─ 通过 assert_clean 自检后才落盘
```

命名规范沿用研究区惯例：ASCII + `tb_<用途>_<YYYYMMDD>.json`。

## 依赖

复用 `mcp-server/cdp-client.js`（需要 `mcp-server/node_modules` 里的 `ws`）。
首次使用前：

```powershell
Set-Location mcp-server; npm install
```

语法体检：

```powershell
node --check taobao-publisher/scripts/probe-publish-workbench.mjs
node --check taobao-publisher/scripts/capture-publish-requests.mjs
```

## 前置条件

两个脚本都需要 **9334 上有一个已登录的淘宝标签页**。启动方式：

```powershell
node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs
node protocol-research-taobao-20260908/scripts/check-taobao-cdp-environment.mjs
```

该 profile（`.runtime/chrome-taobao-cdp`）需要**独立扫码登录一次**。
两条「复用系统 Chrome 登录态」的路都已实证失败，不要再试（见 `docs/05` 的 R-001 / R-002）。
