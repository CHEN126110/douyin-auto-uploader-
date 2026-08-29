# 协议化上传引擎

这个目录用于承载抖店商品发布的**协议自动化前置研究层**和 dry-run 引擎。当前原则是：保留已验证稳定的 DOM 自动化流水线，协议化能力先以只读探针、本地预检、字段审计和受控 replay 为主，不默认接管正式上传。

当前还不能把这里视为“完整协议上传引擎”。更准确的定位是：

- 正式上传主路径仍是 DOM 自动化。
- `protocol_publish` 当前主要负责：
  - 协议证据收集
  - 字段与 envelope 审计
  - dry-run 预检
  - 受控 replay 与风控边界研究
- 只有当某个阶段具备真实请求体、稳定入参模型、接口级校验和独立替代能力后，才算进入“阶段性协议自动化执行器”。

稳定入口文档：

- `docs/协议化上传当前规划.md`
- `docs/协议化上传接口实证_2026-04-22.md`

## 合规边界

- 仅用于用户本人已登录抖店页面的本地调试、字段核验和流程稳定性验证。
- 不做登录绕过、验证码绕过、风控绕过、账号探测、高频请求或批量探测。
- 不保存 cookie、token、手机号、店铺敏感信息和完整签名 URL。
- 默认只读。发布、保存类请求只能在显式调试模式下做本地请求预检，并在请求到达平台服务端前中止。

## 当前状态

- `models.py`：协议抓包记录、阶段定义、执行计划模型。
- `artifacts.py`：协议抓包与执行产物落盘，支持导入 `cdp_fxg_protocol_capture` 的去敏结果，并保留本地预检状态。
- `engine.py`：协议上传引擎基础结构、运行上下文、阶段计划导出。
- `schema_mapping.py`：只读 schema 摘要到内部字段计划的映射层。
- `dry_run.py`：协议化上传 dry-run 生成器，把本地商品、SKU、素材和 schema 摘要转换为可审计的拟提交模型；默认不提交、不保存草稿。
- `stages/price_stock_runtime.py` 和 `stages/sku_runtime.py`：当前仍是 DOM 执行器，用于保留已验证的正式流水线能力。
- MCP `cdp_fxg_runtime_options_probe`：读取真实类目、类目属性、规格轴、SKU 列、运费模板、上下架和发布控制字段。
- MCP `cdp_fxg_qualification_probe`：只读扫描资质相关 DOM 区块、提交 schema 形状和模块线索。
- MCP `cdp_fxg_protocol_capture`：默认只观察发布相关请求；显式开启 `blockMatchedRequests` 或使用 `CAPTURE_PROFILE=submit-preflight` 时，记录去敏摘要后在本地中止匹配请求，并按提交、SKU/价格库存、图片/详情、资质链路汇总证据。

当前阶段不应再把“抓到 `addWithSchema`”直接等同于“已经做成协议自动化”。现阶段更重要的是把研究结论收口成可执行的阶段模块。

## 已确认的协议证据

- 类目搜索接口：`/product/tproduct/searchCategoryN?key=<关键词>&search_type=1`。
- Schema 读取接口：`/product/tproduct/getSchema`。
- 运费模板读取接口：`/product/tproduct/refetchSchema?action=freight_template_options_load`。
- 提交入口：`/product/tproduct/addWithSchema` 和 `/product/tproduct/editWithSchema`，但当前未启用协议正式提交。
- 图片上传端点：`/product/img/batchupload`，单图字段为 `image`，批量字段为 `image[index]`，附带 `extra={"request_source":"pc"}`。
- SKU/价格库存提交 schema：`spec_detail` 是规格轴数组，`sku_detail` 是 SKU 数组；`sku_detail.price` 为字符串，`stock` 为数字，`stock_info` 为可选对象。
- 提交模型媒体字段：`pic/main_image_three_to_four/long_pic/white_background_pic` 为 `array<{ url: string }>`。
- 主图视频字段：`main_pic_video` 为 `array<{ resource_id: string, video_choice?: number, video_source?: string, video_application_type?: enum }>`。
- 资质字段：`qualification` 只能确认到 `record<string, unknown>`，当前不能硬编码为“合格证”。
- 当前页面可见资质子区块包括：`赠品资质`、`报关单`、`质检报告`、`老字号认证证书`、`包装标签图`；`水洗标/吊牌图` 属于类目属性 OCR 辅助入口，不等同于 `qualification`。

## 仍需补证的阻塞点

- `schema.model.qualification` 的真实子键和值结构。
- 白底图 `submitWhiteImg` 的 `action_list` 真实值和审核闭环。
- 商品详情 `description` 的最终提交结构。
- 主图视频上传、素材 `saveMaterial` 和最终 `addWithSchema` envelope 的完整实证。
- `stock` 与 `stock_info` 的真实运行时关系、规格值 ID 和 SKU 组合 ID 的生成规则。
- 不同类目下资质、规格轴、类目属性和 SKU 列的差异矩阵。

## 当前优先级

当前优先级已经重新排序，不再默认把媒体和最终提交放在最前面：

1. `价格库存` 的真实协议执行证据
2. `spec_detail/sku_detail` 的真实组合规则
3. 高频类目属性的稳定映射闭环
4. 媒体字段映射与触发条件收口
5. 最终 `addWithSchema` 正式执行评估

下一轮只允许从下面三项里选一个高价值目标推进：

- 明确价格库存真实请求体与校验规则
- 明确 `spec_detail/sku_detail` 的真实组合 ID 规则
- 明确 `main_pic_video.resource_id` 的真实来源链

## 常用命令

先启动带 CDP 调试端口的已登录浏览器，再运行只读探针：

```powershell
Set-Location '<project-root>\mcp-server'
npm run start:fxg-cdp
npm run check:cdp

$env:CATEGORY_KEYWORD = '长筒袜'
$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_schema_probe_long_socks.json'
npm run probe:fxg-schema

$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_runtime_options.json'
npm run probe:fxg-runtime-options

$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_freight_probe_long_socks.json'
npm run probe:fxg-freight

$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_material_probe.json'
npm run probe:fxg-material

$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_qualification_probe.json'
npm run probe:fxg-qualification

$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_submit_probe.json'
npm run probe:fxg-submit
```

`start:fxg-cdp` 使用独立 Chrome 用户目录 `<project-root>\.runtime\chrome-fxg-cdp`，只开启远程调试端口，不添加会触发 Chrome 顶部警告的自动化隐藏参数。

本地请求预检模式只用于研究写接口请求体。该模式会让页面对应操作失败，但匹配请求会在到达平台服务端前被中止：

```powershell
Set-Location '<project-root>\mcp-server'
$env:DURATION_MS = '15000'
$env:CAPTURE_PROFILE = 'submit-preflight'
$env:OUTPUT_PATH = '<project-root>\tmp_runtime_probe_live\fxg_protocol_capture_blocked.json'
npm run capture:fxg-protocol
```

或一键使用默认 120s 与自动输出到 `tmp_runtime_probe_live\fxg_protocol_submit_preflight_<时间戳>.json`（仍建议在发布**第 2 步及之后**操作保存/提交/价库，否则可能只有读请求、捕不到 `addWithSchema`）：

```powershell
Set-Location '<project-root>\mcp-server'
npm run capture:fxg-submit-preflight
```

可用 profile：

- `submit-preflight`：覆盖 `addWithSchema/editWithSchema`、图片上传、素材、白底图、白底图识别、资质列表等本轮优先证据链，并默认本地截停。
- `submit-only`：只截停最终 `addWithSchema/editWithSchema`。
- `media-preflight`：截停图片、素材、详情图、白底图相关请求。

离线分析截停产物：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\analyze_capture_evidence.py' `
  --capture 'tmp_runtime_probe_live\fxg_protocol_capture_blocked.json' `
  --dry-run 'tmp_runtime_probe_live\protocol_dry_run_latest_record_mid_socks_20260427.json' `
  --output 'tmp_runtime_probe_live\fxg_protocol_capture_blocked_analysis.json'
```

该脚本只读取本地 JSON，不访问平台；输出会按 `submit`、`sku_price_stock`、`media`、`qualification` 标注哪些请求体证据已抓到。

从 deep capture 构造 `785.measure_info` 变体，并先输出准备信息：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\replay_measure_info_variants.py' `
  --capture 'tmp_runtime_probe_live\fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json' `
  --variant 'sum_not_100,value_name_mismatch,material_name_mismatch' `
  --output 'tmp_runtime_probe_live\measure_info_variant_replay_prepare.json'
```

该模式不会发送请求，只会列出选中的变体、其 `property_785` 摘要，以及 live replay 需要补抓的真实请求来源。

如需进入受控 live replay，脚本会先附着到当前已登录发布页，通过 CDP `Fetch.requestPaused` 拦截**未脱敏**的 `addWithSchema/editWithSchema` 请求 URL、headers 与 body，再逐个 replay 指定变体：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\replay_measure_info_variants.py' `
  --capture 'tmp_runtime_probe_live\fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json' `
  --variant 'sum_not_100' `
  --execute-live `
  --debug-address '127.0.0.1:9222' `
  --trigger save_draft `
  --replay-transport python_http `
  --output 'tmp_runtime_probe_live\measure_info_variant_replay_sum_not_100.json'
```

`--execute-live` 会真实触发一次 `保存草稿` 或 `发布商品` 来捕获请求，再向平台发送变体 replay；因此它只用于受控研究，不接入正式主链，且默认建议优先用 `save_draft`。`--replay-transport python_http` 可用于排除页内 XHR replay 被浏览器侧策略拦截的情况。

从 dry-run 生成 `addWithSchema` 本地预检 body：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\build_submit_preflight_body.py' `
  --dry-run 'tmp_runtime_probe_live\protocol_dry_run_latest_record_mid_socks_20260427.json' `
  --schema 'tmp_runtime_probe_live\fxg_schema_probe_mid_socks_20260427.json' `
  --output 'tmp_runtime_probe_live\add_with_schema_preflight_latest_record_mid_socks_20260427.json'
```

该文件只用于审计 envelope 和字段缺口，`submit_enabled=false`，不能发送到平台，也不能当作页面真实提交请求体证据。

生成 dry-run：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\build_dry_run.py' `
  --schema 'tmp_runtime_probe_live\fxg_schema_probe_long_socks.json' `
  --runtime 'tmp_runtime_probe_live\fxg_runtime_options.json' `
  --freight 'tmp_runtime_probe_live\fxg_freight_probe_long_socks.json' `
  --record '<record-json-path>' `
  --output 'tmp_runtime_probe_live\protocol_dry_run.json'
```

直接用已采集商品记录生成 dry-run：

```powershell
Set-Location '<project-root>'
python 'tauri-app\python-sidecar\protocol_publish\scripts\build_dry_run_from_record.py' `
  --schema 'tmp_runtime_probe_live\fxg_schema_probe_20260427_0120.json' `
  --runtime 'tmp_runtime_probe_live\fxg_runtime_options_probe_20260427_0120.json' `
  --freight 'tmp_runtime_probe_live\fxg_freight_probe_refresh_20260424.json' `
  --record-id 1 `
  --output 'tmp_runtime_probe_live\protocol_dry_run_record_1.json'
```

不传 `--record-id` 时会读取最近更新的已采集商品记录。该脚本只读本地数据库和证据 JSON，不调用平台接口。

品牌是安全硬规则：当前袜子商品无品牌资质时，dry-run 固定映射 `品牌=无品牌`，并忽略 `record.brand`、`record.brand_name` 和旧命令中的 `--brand` 入参；标题区 `使用品牌名` 仍保持关闭。`适用性别` 暂按现有 DOM 流水线的标题规则推断，也可以用 `--gender` 显式覆盖。

dry-run 输出中：

- `proposed_submit_model` 是完整拟提交模型，包含已验证字段和候选字段；候选但无协议值的字段会保留为 `null` 或候选结构。
- `field_verification_report.verified_fields` 标明当前可解释来源的字段。
- `field_verification_report.missing_fields` 标明本地商品缺素材或缺值的字段。
- `field_verification_report.cannot_submit_fields` 标明已有候选来源但缺本地截停请求体证据、不能真实提交的字段。

## 禁止事项

- 禁止用静态 HTML 文件推断最终协议入参。
- 禁止把袜子类目的属性、规格轴和默认值硬编码到其他类目。
- 禁止在正式上传中默认启用未验证协议写入。
- 禁止通过兜底代码掩盖字段映射错误。
- 禁止保存或提交包含 token、cookie、手机号、店铺敏感信息的抓包文件。
