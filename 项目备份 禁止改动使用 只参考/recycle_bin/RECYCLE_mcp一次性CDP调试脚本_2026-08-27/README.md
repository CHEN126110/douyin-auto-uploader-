# RECYCLE_mcp一次性CDP调试脚本_2026-08-27

本目录收纳了原先位于 `mcp-server/scripts/` 的 **10 个零引用一次性调试脚本**
（9 个 `cdp-*.mjs` + 1 个 `_test_dynamic_output.mjs`），于 2026-08-27 代码质量治理任务中移出。

**这些文件没有被删除，只是移动。** 恢复方式见文末。

## 回收原因

### 1. 全仓零引用

移动前做过两次独立全仓扫描（`os.walk` 覆盖 `.py/.js/.mjs/.cjs/.ts/.vue/.rs/.json/.md/.bat/.ps1/.toml/.yaml/.spec/.html`，
排除 `node_modules/.git/dist/target/__pycache__/.venv/.runtime`，共 12055 个文件）：

- 9 个 `cdp-*.mjs` 文件名：**全部 0 命中**（连自身文件里都不出现自己的名字）。
- `_test_dynamic_output`：**仅 1 命中，就是它自己**，无任何外部引用。

具体核对过的引用位置：

- `mcp-server/package.json` 的 `scripts` 段（`check` / `test:ops` / `capture:*` / `probe:*` / `start:*` / `inject:*`）——全部不含这 10 个文件；
- `mcp-server/README.md`、`skills/douyin-publisher-mcp/*.md`、`docs/`；
- Rust 壳 (`tauri-app/src-tauri/`)、Vue 前端、Python Sidecar 与 `src/`；
- 根目录及各处 `.bat` / `.ps1` 启动脚本。

### 2. 不受 `npm run check` 语法体检覆盖

`package.json` 的 `check` 脚本逐个列出要 `node --check` 的文件，
从 `cdp-client.js` 到 `scripts/probe-fxg-upload.mjs`，**一个 `cdp-*.mjs` 都没有**，
`_test_dynamic_output.mjs` 同样不在列。也就是说这 10 个文件长期处于「改坏了也没人发现」的状态。

### 3. 其中 4 个会绕开 `UPLOAD_*` 授权红线执行写操作

项目对 FXG CDP 工具有硬红线：**没有 `UPLOAD_*` 显式授权，不得触发上传 / saveMaterial /
batchApplyMaterial / addWithSchema / 草稿保存 / 提交**，probe / capture 脚本只能观察。
这些一次性脚本完全没有接受这套门禁——`node scripts/cdp-xxx.mjs` 直接就写页面。
留在 `scripts/` 目录里，等于在只读探针中间埋了一组绕过红线的入口。

### 4. 硬编码了另一个工作区的绝对路径

`cdp-upload-and-advance.mjs:3` 与 `cdp-type-and-upload.mjs:79` 都写死了
`E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\test_images\TM.png`
（**2.0** 工作区，本机不存在），说明它们是历史手工调试的残留，早已无法按原样运行。

## 每个脚本原本做什么

10 个文件全部通过 `../cdp-client.js` 的 `withCdpTarget` 连接
硬编码的 `http://127.0.0.1:9333/json/list`，挂到 URL 含
`fxg.jinritemai.com/ffa/g/create`（抖店发布页第一步）的 target 上。

### 有写操作风险的 4 个（红线相关）

| 文件 | 行数 | 做什么 | 写操作 |
|------|------|--------|--------|
| `cdp-type-and-upload.mjs` | 128 | 聚焦标题输入框，用 `Input.insertText` 模拟真人打字塞入 `C975长筒袜棉质透气多色可选`（重复 3 次），再给主图 file input 塞图，最后条件点击「下一步」 | `Input.enable` + `Input.insertText` 真实打字；`DOM.setFileInputFiles` 真实上传；`.click()` 推进步骤 |
| `cdp-upload-and-advance.mjs` | 128 | 给 `[attr-field-id="主图"]` 下第一个 file input 打标记后塞图并派发 `change`，等 5 秒，再用 native setter 写标题 `C975测试商品-长筒袜-棉质透气-多色可选`，然后条件点击「下一步」并读取第二步页面状态 | `DOM.setFileInputFiles` 真实上传；写标题；`.click()` 推进步骤 |
| `cdp-advance-to-step2.mjs` | 75 | 读「下一步」按钮状态 → 用 native setter 写标题 `测试商品SKU规格图验证用` 并 dispatch `input`/`change` → 点击「下一步」→ 等 2 秒读页面状态 | 写标题；`nextBtn.click()` 推进步骤 |
| `cdp-fill-and-check.mjs` | 111 | 用 native setter + 遍历 React fiber 直接调 `memoizedProps.onChange/onInput` 强行写入标题 `C975测试商品 长筒袜 棉质透气 多色可选`，再诊断「下一步」为何仍 disabled（列必填项、校验提示、主图错误） | 写标题（含直接触发 React onChange） |

### 只读观察的 5 个（无写操作）

| 文件 | 行数 | 做什么 |
|------|------|--------|
| `cdp-check-page-state.mjs` | 71 | 一次性 dump 发布页第一步状态：「下一步」按钮 disabled/className、标题 textarea 值、主图 img 数量与 src、商品类目文本、全部 `[attr-field-id]` 字段及是否有值、可见的错误/提示元素 |
| `cdp-check-step2.mjs` | 19 | 最小脚本：读前 20 个 `attr-field-id`、是否存在「价格与库存」、是否存在 `skuValue-颜色分类`、前 10 个按钮文案、当前 URL，用来判断是否已进入第二步 |
| `cdp-find-title-input.mjs` | 77 | 排查「标题输入框到底是哪个元素」：列出标题区所有 `input/textarea/[contenteditable]` 的 tag/type/class/placeholder/可见性，找含「标题内容需包含」的文本容器，检测 React fiber，附带探类目区 innerHTML 与前 8 个按钮 |
| `cdp-explore-addWithSchema.mjs` | 175 | 通过 `window.__fxgWebpackRequire` 遍历 webpack 模块找表单 store（`mod.ox()` / `store.na('sku_detail')`），列出提交模块 `51313` 的导出键与类型，读 `sku_detail/spec_detail/title/pic/goods_category` 各节点是否有值。**只读，不调用提交函数** |
| `cdp-call-addWithSchema.mjs` | 112 | 名字有误导性：它**不会真的调用** `addWithSchema`。第 84 行注释明写 `// Don't actually call it - just inspect`，只把 `submitMod.f$` / `KB` / `DQ` 的 `toString().slice(0, 300)` 打印出来看函数签名，外加探 store 候选模块 `99281/991/265/1471` |

> 注：原审查清单说 `cdp-call-addWithSchema.mjs`「直奔提交模块」，措辞夸张；
> 实际是只读探查，已在本文更正。它被一并回收的理由是零引用 + 不受 check 覆盖，不是写操作风险。

### 附带回收的 1 个

| 文件 | 行数 | 做什么 |
|------|------|--------|
| `_test_dynamic_output.mjs` | 16 | 一次性验证脚手架：设置 `OUTPUT_PATH` / `CAPTURE_PROFILE=submit-preflight` / `DURATION_MS=500` 后 `await import('./capture-fxg-protocol-requests.mjs')`，再 `fs.stat` 确认文件写出来了。用来一次性验证 capture 脚本支持动态 `OUTPUT_PATH` 环境变量 |

**为什么它也移走：** 与 9 个 `cdp-*.mjs` 完全同一套判据——零外部引用、不在 `check` 列表、
不在 `test:ops`（`node --test tests/*.test.mjs` 只扫 `mcp-server/tests/`，不含 `scripts/`）、
文件名 `_test_` 前缀本身表明是临时脚手架。一个不会被任何流程执行的验证脚本就是死代码。

**风险等级与前面不同：** 它是**只读**的（`capture-fxg-protocol-requests.mjs` 只观察请求并脱敏，
`DURATION_MS=500` 即 0.5 秒），**没有任何写操作或红线问题**，纯粹是死代码清理。
它依赖的 `capture-fxg-protocol-requests.mjs` 仍在 `mcp-server/scripts/` 正常存活。

## 行数统计

9 个 `cdp-*.mjs` 合计 **896 行**（75+112+71+19+175+111+77+128+128），
加 `_test_dynamic_output.mjs` 的 16 行，本次共移出 **912 行**。

## 影响评估

对运行中的 MCP Server、Python Sidecar、Tauri 壳**零影响**——没有任何代码 `import` 它们，
没有任何 npm script 调用它们，没有任何文档引用它们。

唯一的可观察变化：如果有人凭记忆手工敲 `node scripts/cdp-xxx.mjs`，
移动后会报「文件不存在」。按下面的恢复方式取回即可。

`mcp-server/scripts/` 中被 `package.json` 引用的脚本**一个都没动**，移动后仍完整保留：
`capture-fxg-protocol-requests.mjs`、`capture-fxg-submit-preflight.mjs`、`capture-price-stock-apis.mjs`、
`check-cdp-environment.mjs`、`start-fxg-cdp-chrome.mjs`、
`probe-fxg-category-matrix.mjs`、`probe-fxg-freight.mjs`、`probe-fxg-material.mjs`、
`probe-fxg-qualification.mjs`、`probe-fxg-runtime-options.mjs`、`probe-fxg-schema.mjs`、
`probe-fxg-submit.mjs`、`probe-fxg-upload.mjs`（共 13 个）。

`mcp-server/package.json` **未作任何修改**——这 10 个文件本来就不在其中任何一条 script 里。

## 恢复方式

把需要的文件从本目录移回 `mcp-server/scripts/` 即可，无需改 `package.json`（它们本来就没被登记）：

```powershell
$src = "C:\Users\CRB\Desktop\2.1\项目备份 禁止改动使用 只参考\recycle_bin\RECYCLE_mcp一次性CDP调试脚本_2026-08-27"
$dst = "C:\Users\CRB\Desktop\2.1\mcp-server\scripts"
Move-Item "$src\cdp-check-page-state.mjs" $dst    # 按需逐个，或用 *.mjs 全部移回
```

运行前提（这些脚本自身不做任何检查，缺一个就直接报错退出）：

1. 先按 `npm run start:fxg-cdp` 启动带 9333 远程调试端口的 Chrome，并已登录抖店；
2. 浏览器停在 `fxg.jinritemai.com/ffa/g/create` 发布页；
3. 用到 webpack 模块的两个（`cdp-explore-addWithSchema` / `cdp-call-addWithSchema`）
   还需要页面上已注入 `window.__fxgWebpackRequire`（见 `mcp-server/fxg-webpack-bootstrap.js`）；
4. `cdp-type-and-upload.mjs` / `cdp-upload-and-advance.mjs` 里硬编码的
   `E:\Script Project\Dyin\beiufen\2.0\...\TM.png` **必须先改成本机存在的路径**，否则上传必然失败。

## 更推荐的做法

不要直接恢复这几个写操作脚本。如果后续确实需要它们的探索能力，
按项目规范**重新以只读方式**实现到 `mcp-server/fxg-*-probe.js` 里，
并接入 `UPLOAD_*` 显式授权门禁与 `npm run check` 语法体检，
输出统一落到 `tmp_runtime_probe_live/`。本目录的文件只作实现参考。
