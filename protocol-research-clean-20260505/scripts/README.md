# scripts

本目录只放干净研究区专用脚本。

脚本要求：

- 默认只读或离线分析。
- 不默认发送写请求。
- 不保存敏感原文。
- 输出 JSON 时使用 `ensure_ascii=false`，避免中文被错误转义或乱码。
- PowerShell 入口必须设置 UTF-8 输出编码。

当前暂不放执行脚本，先完成证据模型和目标边界。

## 当前脚本

### `sanitize_cookie_export.py`

用于把 Cookie-Editor 导出的 Cookie 转成去敏摘要。禁止保存原始 Cookie value。

### `sanitize_fxg_probe_outputs.py`

用于清理 FXG 探针产物中的敏感字段。输出 UTF-8 JSON，`ensure_ascii=false`。

### `analyze_price_stock_capture.py`

离线分析 `cdp_fxg_protocol_capture` 产物中的价格库存字段。它只读取本地 JSON，不发送请求，不 replay，不接入正式上传。

示例：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

python protocol-research-clean-20260505\scripts\analyze_price_stock_capture.py `
  --capture tmp_runtime_probe_live\fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json `
  --output protocol-research-clean-20260505\outputs\price_stock_capture_analysis_legacy_20260504.json `
  --source-label legacy-reference-20260504
```

输出只保留字段位置、计数、哈希和 blocker。若输入中存在 `<max-depth>` 或 `<unsupported>`，脚本会标记 `CAPTURE_SANITIZED_DEPTH_LIMIT`，不允许把截断样本当成完整映射证据。

## Windows 中文文件名注意事项

真实上传探针支持 `UPLOAD_FILE_NAME`。在 Windows/CDP 链路中，中文源文件路径可以用于读取本地文件，但文件名跨 Node、CDP、浏览器运行时返回时可能出现 mojibake。验收请求应显式设置 ASCII 文件名，例如：

```powershell
$env:UPLOAD_IMAGE_PATH = '<project-root>\项目备份 禁止改动使用 只参考\C-975\主图\白底.jpg'
$env:UPLOAD_FILE_NAME = 'c975-white-bg.jpg'
$env:UPLOAD_MODE = 'single'
npm run probe:fxg-upload
```

这只改变 multipart 里的测试文件名，不改变图片内容，也不掩盖接口字段错误。

批量上传验收使用分号分隔路径和文件名：

```powershell
$env:UPLOAD_IMAGE_PATHS = '<project-root>\项目备份 禁止改动使用 只参考\C-975\主图\TM.png;<project-root>\项目备份 禁止改动使用 只参考\C-975\主图\白底.jpg'
$env:UPLOAD_FILE_NAMES = 'c975-tm.png;c975-white-bg.jpg'
$env:UPLOAD_MODE = 'batch'
npm run probe:fxg-upload
```
