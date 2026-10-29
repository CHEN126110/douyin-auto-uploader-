# 前端 A/B 对照验证（改动前 vs 改动后）

2026-10-19 整理前端结构（`SettingsPanel.vue` / `ProductManager.vue` 拆分，见 `docs/前端结构整理_2026-10-19.md`）时建的验证工具。
项目里**没有前端单元测试**，而重构要保证「界面外观和行为一点没变」，所以做成了「同一套操作、分别打原版和新版、逐项对比」。
以后再动前端结构（例如 `CaptureSection` / `ShopStatusBar` / `TaobaoPublishPanel`），可以直接复用。

## 它怎么工作

```text
浏览器同一个标签页              验证代理 5003                              隔离的 Sidecar 5002（隔离数据目录）
  ├─ 原版前端  :1421  ──┐                                          ┌─ 商品 / 设置 / 定价 / 图片 …… 照常处理
  └─ 新版前端  :1420  ──┴─▶  记录每个请求（方法 / 路径 / 查询 / 请求体）──┤
                              「会操作抖店 / 淘宝 / 小红书 / 采集」的接口 ─┘  由代理给脚本化的假响应
```

> **为什么是 5003、不是前端写死的 5001？** 5001 是**真实桌面应用**的 Sidecar 端口，里面是用户的真实数据，
> 验证的时候应用可能正开着。验证工具绝不占用、也不碰它：两个前端开发服务器用 `vite.ab.config.mts` 启动，
> 它在不改被测源码的前提下，把开发服务器吐给浏览器的模块里的 `127.0.0.1:5001` 改写成代理端口；
> `harness.js` 在每个场景开跑前还会核对一次「被测前端实际用的后端地址就是验证代理」，对不上直接中止、什么都不做；
> `ab.ps1` 只会停掉自己起的进程（先核对命令行），端口被别的程序占着就报错退出。

- **页面里跑场景脚本**（`scenarios/*.js`）：像用户一样点按钮、填表单，在每个检查点把 DOM 树 + 每个元素的
  **79 项计算样式 + 位置尺寸**、弹出的提示（toast）、确认框文字、控制台错误记成文本文件。
- **代理**（`proxy_mock.py`）：转发请求给真实后端并按**到达顺序**记录；发布类 / 采集类接口给假响应，
  所以抖音、淘宝、小红书的发布流程、取消、失败、结果未知、外部任务接入都能完整走一遍，**不会启动浏览器、不会碰平台**。
- **对比**（`cmp.py`）：两次运行的快照、事件、请求日志逐项比；差异会指出是哪一行。

## 准备（一次）

需要 Windows + PowerShell、Python 3.11（`py -3.11`）、Chromium 内核浏览器。所有文件都放在 `$env:AB_WORK`
（默认 `lab/frontend_ab/.work/`，已被 `.gitignore` 忽略），**不碰用户真实数据目录**。

```powershell
Set-Location lab\frontend_ab
.\ab.ps1 setup                                   # 建虚拟环境 + 假商品 + 基线数据（首次几分钟）
.\ab.ps1 orig -Src <改动前备份的 src 目录>         # 生成原版前端副本（端口 1421）
```

另开两个终端起前端（**一定要带 `--config`**，否则页面会去连真实的 5001）：

```powershell
# 新版  http://127.0.0.1:1420 （在仓库根目录执行）
npm --prefix tauri-app run dev -- --config "$PWD\lab\frontend_ab\vite.ab.config.mts"
# 原版  http://127.0.0.1:1421
Set-Location lab\frontend_ab\.work\orig-app;  npm run dev -- --config vite.ab.config.mts
```

起来之后可以先确认改写生效（不会碰 5001）：`(Invoke-WebRequest http://127.0.0.1:1420/src/services/api.ts).Content` 里应当是 `127.0.0.1:5003`。

> 改动前一定要先把 `tauri-app/src` 备份出来（这个项目没有 git）；`orig` 只是把备份套上 Vite 配置。

## 跑一轮 A/B

每个场景都要：**恢复数据 → 打开页面 → 跑脚本**，原版和新版各一遍。

1. `.\ab.ps1 prep`（`settings_session` 要加 `-WashLabel`）——恢复隔离数据、重启后端与代理、清空请求日志。
2. 浏览器**固定一个标签页**，先把视口设成 1280×800，再打开原版 `http://127.0.0.1:1421/#/settings`（场景不同入口不同，见下表）。
3. 在开发者工具控制台粘贴（`<场景>`、`<阶段名>` 换成实际值，例如 `settings_main` / `a1`）：

   ```js
   await (async () => {
     localStorage.setItem('onboarding_completed', 'true');
     const load = (src) => new Promise((res, rej) => { const s = document.createElement('script'); s.src = src + '?' + Date.now(); s.onload = res; s.onerror = rej; document.head.appendChild(s); });
     await load('http://127.0.0.1:5003/__ctl/harness.js');
     await load('http://127.0.0.1:5003/__ctl/script/<场景>.js');
     return await window.__scn.<场景>('<阶段名>');
   })()
   ```
4. 再 `prep` 一次，换成新版 `http://127.0.0.1:1420/...`，同一场景、阶段名换成 `b1`。
5. 对比：`python cmp.py a1 b1`（在 `lab/frontend_ab` 下，用 `.work/venv` 的 Python，或设 `AB_PY`）。
   输出 `same` = 逐字一致；`same*` = 只是并发请求的先后不同；`DIFF` = 有差异，会列出前几行。

| 场景脚本 | 入口 | 前置 | 覆盖 |
|---|---|---|---|
| `settings_main` | `/#/settings` | `prep` | 设置页 5 个 Tab 全部交互、保存请求体、材质校验拦截 |
| `settings_session` | `/#/` | `prep -WashLabel`，再 `POST /__ctl/mock {"mock_platform":"douyin","freight_mode":"ok"}` | 有店铺会话时的运费模板各分支（成功 / 缺失 / 需发布页 / 500）、水洗标预览与清空、切账户后重读 |
| `settings_extras` | `/#/` | `prep` | 假 Tauri 环境下「高级集成 / 关于」的文案（4 种运行环境）、`?tab=`、加载失败与重试 |
| `settings_freight_cache` | `/#/` | `prep`，再 `POST /__ctl/mock {"mock_platform":"douyin","freight_mode":"ok"}` | 运费模板名单缓存：读取失败 / 没读到 / 换账户后下拉里还剩什么、保存时发什么、什么时候算「有未保存的更改」（下拉选项在浮层里，快照看不到，所以单独读） |
| `home_main` | `/#/` | `prep` | 商品列表 / 选择 / 表单 / 填充 / 智能填充弹窗 / 保存 / 重复规格 / 删 SKU / 右键菜单 / 图片管理 / 删除 / 清空 |
| `home_publish` | `/#/` | `prep` | 抖音（确认取消、卡住后取消、成功、失败、启动出错×3、轮询失败暂停与恢复）、批量、淘宝（填写成功 / 未确认 / 真实发布 / 失败 / 启动结果未知后接回）、小红书、外部任务接入 |
| `capture_entry` | `/#/` | `prep` | 链接校验、启动、进度、导入完成、失败重试、取消 |

阶段名只是文件名前缀：快照存为 `<阶段名>_<检查点>.txt`，请求日志为 `*_requests.jsonl`。

## 已知的坑（照做能避开）

- **别占 5001，别杀 5001 上的进程。** 那是真实桌面应用的 Sidecar。验证工具最初写死占 5001、还会按端口直接杀进程，
  应用开着时就会撞上（实际遇到过：用户的应用开着，5001 被真实 Sidecar 占着）。现在代理默认 5003
  （`AB_PROXY_PORT` 可改，但工具拒绝使用 5001）。

- **设备像素比（DPR）会在两次运行之间跳变（1 ↔ 1.5）**，布局取整不同会让几何数值差 ≤1px。每个快照头都记了
  `#env dpr=… viewport=…`；`cmp.py` 发现不一致会标 `ENV` 而不是 `DIFF`。遇到就把两边重跑，直到 DPR 一致
  （`cmp.py … --nogeo` 可在 DPR 不同时只比结构 / 文本 / 非几何样式，是退路，不是证明）。
- **浏览器面板宽度变化会清掉视口设置**：每轮开始前重新设一次 1280×800，并看快照头里的 `viewport=`。
- **页面在后台时动画帧不触发**：`harness.js` 装了 `requestAnimationFrame` 垫片并关闭了 CSS 过渡 / 动画，
  所以弹窗过渡能走完、计算样式直接是终态；这也意味着**看不到动画本身**，动画效果要人眼看。
- **后台定时器会插进来**（30 秒商品同步、外部任务发现、账户栏轮询）：`home_*` / `capture_entry` 脚本开头调了
  `H.quiet()`（让页面自认「不可见」），外部任务发现那一条会临时恢复。
- 「进度卡住 / 外部任务」类流程里**轮询了几次取决于点击时机**，`cmp.py` 对这几类（`LOOSE_POLL_FLOWS`）折叠连续的轮询。

## 局限（别把它说成真机验证）

没有连真实的抖店 / 淘宝 / 小红书页面，也没有跑 Tauri 壳：窗口拖拽、文件选择对话框、打开文件夹、剪贴板（需要窗口焦点）、
真实的自动更新、安装包，这些都不在覆盖范围内（`settings_extras` 用假的 `__TAURI_INTERNALS__` 只验证了文案生成）。
它验证的是「前端在同样的后端响应下，渲染和请求是否和改动前一致」。

## 写新场景

参考 `scenarios/home_main.js`：`window.__scn.<名字> = async (phase) => {...}`，用 `H.click / H.setValue / H.waitFor / H.dumpAll`
等工具（`harness.js`），检查点用 `H.dumpAll('<phase>_<名字>.txt', [根选择器…])`，最后 `H.save` 事件文件、
`H.ctl('save-log?name=…')` 存请求日志。要给后端接口加假响应，改 `proxy_mock.py` 的 `mock_response`，
并在 `/__ctl/mock` 里加对应开关。注意：验证用的假数据要和被测代码无关，且场景里不要去点会操作真实文件的入口
（例如「打开文件夹」）。
