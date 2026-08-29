# Douyin Publisher MCP Server

This server exposes the existing local Flask sidecar as MCP tools, resources, and prompts.

## Preconditions

- The Douyin publisher backend must already be running on `http://127.0.0.1:5001`, or another URL set via `DOUYIN_BACKEND_URL`.
- The safest way is to start the Tauri app first, then connect the MCP client.

## Run

The Settings page inside the desktop app now generates the exact local launch command from the current runtime paths. If you are starting MCP manually, replace `<project-root>` with your own install or repo location instead of copying a machine-specific path.

`stdio` mode:

```powershell
Set-Location '<project-root>\mcp-server'
npm start
```

`streamable_http` mode:

```powershell
Set-Location '<project-root>\mcp-server'
npm run start:http
```

Future packaged EXE mode:

```powershell
& '<install-root>\douyin-publisher-mcp.exe'
```

When a standalone MCP executable is available, prefer that `stdio` entry for distribution because it removes the Node.js and source-path dependency.

## Example MCP client config

```json
{
  "mcpServers": {
    "douyin-publisher": {
      "command": "node",
      "args": [
        "<project-root>\\mcp-server\\server.js"
      ],
      "env": {
        "DOUYIN_BACKEND_URL": "http://127.0.0.1:5001",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}
```

Example Streamable HTTP endpoint:

```text
http://127.0.0.1:3300/mcp
```

Example packaged EXE client config:

```json
{
  "mcpServers": {
    "douyin-publisher": {
      "command": "<install-root>\\douyin-publisher-mcp.exe",
      "args": [],
      "env": {
        "DOUYIN_BACKEND_URL": "http://127.0.0.1:5001",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}
```

## Exposed capabilities

- Product listing and detail loading
- Product folder opening and file listing
- SKU name to SKU image inspection
- SKU quantity analysis with optional model-reviewed quantity overrides
- Product asset manifest inspection and local asset validation
- Upload-readiness validation
- Preparation drafts with generated titles and smart pricing
- Apply generated preparation results back to a product
- Folder import
- Smart title generation
- Smart pricing calculation
- Batch capture start for multiple source links
- Product info, SKU update, and category setting
- Upload-readiness validation across both product fields and local assets
- Product deletion, SKU deletion, and full database clear
- Capture task start/status/import/cancel/history
- Upload task start/status/list/cancel
- Start upload only after readiness validation
- Settings read, update, and reset
- Daily operations loop tools: `ops_ai_policy`, `ops_health_check`, `ops_read_shop_metrics_cdp`, `ops_read_strategy_signals_cdp`, `ops_sync_shop_metrics`, `ops_sync_strategy_signals`, `ops_product_issue_actions`, `ops_update_product_issue_action`, `ops_sync_product_record_mappings`, `ops_product_record_mappings`, `ops_evaluate_product`, `ops_stock_plan`, `ops_product_candidates`, `ops_apply_candidate_pricing`, `ops_daily_plan`, `ops_profit_ramp_plan`, `ops_daily_review`
- Shared browser debug session management
- Browser page snapshots, element queries, and simple debug actions
- Automatic browser error report retrieval with screenshot/HTML/context artifacts

### Standalone CDP (interface mining, no Flask)

When Chrome/Edge is started with a remote debugging port (for example `--remote-debugging-port=9333`), the MCP process can talk to CDP directly via WebSocket:

| Env | Default | Meaning |
|-----|---------|--------|
| `DOUYIN_CDP_LIST_URL` | `http://127.0.0.1:9333/json/list` | `/json/list` endpoint for picking a page target |

Tools (prefix `cdp_`): `cdp_discover_targets`, `cdp_environment_check`, `cdp_page_snapshot`, `cdp_find_elements`, `cdp_action`, `cdp_evaluate`, `cdp_fetch_json` (run `fetch` in page context with cookies), `cdp_network_capture` (record `Network.requestWillBeSent` for a few seconds to list API URLs; use `urlContains` / `resourceTypes` to filter), `cdp_capture_price_stock_candidates`, `cdp_fxg_schema_probe` (read-only category search + `getSchema` summary), `cdp_fxg_category_matrix_probe` (read-only multi-category schema capability matrix), `cdp_fxg_runtime_options_probe` (read-only settings UI options from live schema/freight), `cdp_fxg_freight_probe` (read-only freight template action/options probe), `cdp_fxg_upload_probe` (module scanner by default; performs one explicit sample image upload only when `uploadImagePath` / `UPLOAD_IMAGE_PATH` is provided), `cdp_fxg_material_probe` (read-only material module scanner for `saveMaterial` / `materialDetail` / material type constants), `cdp_fxg_qualification_probe` (read-only qualification/attachment field scanner), `cdp_fxg_protocol_capture` (targeted sanitized request observer for publish endpoints), `cdp_fxg_submit_probe` (read-only submit/SKU module scanner). Prompt: `investigate-douyin-fxg-api`.

Before claiming live FXG page evidence, run `cdp_environment_check` or `cdp_discover_targets`. `cdp_environment_check` now validates both the matching URL and the visible page text, so a login page or blank page is not treated as probe-ready. If `/json/list` is not reachable, only offline/module evidence can be used.

Standalone CDP readiness check:

```powershell
Set-Location '<project-root>\mcp-server'
npm run start:fxg-cdp
npm run check:cdp
```

`start:fxg-cdp` opens a dedicated Chrome profile at `<project-root>\.runtime\chrome-fxg-cdp` with `--remote-debugging-port=9333` and the FXG publish page. It intentionally does not add `--disable-blink-features=AutomationControlled`, so Chrome should not show the unsupported automation flag warning.

Standalone schema probe:

```powershell
Set-Location '<project-root>\mcp-server'
$env:CATEGORY_KEYWORD = '长筒袜'
npm run probe:fxg-schema
npm run probe:fxg-category-matrix
npm run probe:fxg-runtime-options
npm run probe:fxg-freight
npm run probe:fxg-upload
npm run probe:fxg-material
npm run probe:fxg-qualification
npm run probe:fxg-submit
```

Material module probe:

```powershell
$env:OUTPUT_PATH = '..\tmp_runtime_probe_live\fxg_material_probe.json'
npm run probe:fxg-material
```

`probe:fxg-material` only scans the logged-in page runtime. It must not send `saveMaterial`, `batchApplyMaterial`, or `addWithSchema` requests.

Qualification probe:

```powershell
$env:OUTPUT_PATH = '..\tmp_runtime_probe_live\fxg_qualification_probe.json'
npm run probe:fxg-qualification
```

`probe:fxg-qualification` only scans current DOM sections, submit schema shape, and frontend modules. It must not upload files, save drafts, or submit products.

Targeted protocol capture:

```powershell
$env:DURATION_MS = '15000'
$env:OUTPUT_PATH = '..\tmp_runtime_probe_live\fxg_protocol_capture.json'
npm run capture:fxg-protocol
```

Submit-preflight (blocks matched write requests locally; default 120s, auto timestamped JSON under `tmp_runtime_probe_live`; the one-key script raises sanitize depth so `spec_detail` / `sku_detail` evidence is not silently collapsed to `<max-depth>`):

```powershell
npm run capture:fxg-submit-preflight
```

Run a short, intentional page operation during the capture window. The capture tool only observes traffic and redacts URL/body token-like fields; it does not trigger upload, save, or submit by itself. For `addWithSchema` evidence, advance past step 1 and trigger save/submit/price–stock actions while the capture is running.

Sample image upload verification:

```powershell
$env:UPLOAD_IMAGE_PATH = '<absolute-path-to-local-test-image>'
$env:UPLOAD_FILE_NAME = 'sample.jpg'
$env:UPLOAD_MODE = 'single'
$env:OUTPUT_PATH = '..\tmp_runtime_probe_live\fxg_upload_sample_single.json'
npm run probe:fxg-upload
```

Batch upload verification:

```powershell
$env:UPLOAD_IMAGE_PATHS = '<absolute-path-1>;<absolute-path-2>'
$env:UPLOAD_FILE_NAMES = 'sample-1.jpg;sample-2.jpg'
$env:UPLOAD_MODE = 'batch'
npm run probe:fxg-upload
```

Do not set `UPLOAD_IMAGE_PATH` unless you explicitly want to upload one sample image to the logged-in FXG account. Prefer an ASCII `UPLOAD_FILE_NAME` for tests on Windows to avoid CDP/PowerShell filename mojibake in artifacts. The output redacts long URLs and sensitive query parameters.

Runtime options matrix:

```powershell
$env:CATEGORY_KEYWORDS = '长筒袜,短袜,手机壳'
$env:OUTPUT_PATH = '..\tmp_runtime_probe_live\fxg_runtime_options_matrix.json'
npm run probe:fxg-runtime-options
```

## Exposed prompts

- `prepare-product-for-upload`
- `fix-upload-blockers`
- `review-sku-quantities`
- `upload-product-safely`
- `monitor-upload-task`
- `capture-multiple-products`
- `investigate-douyin-fxg-api` (CDP: discover FXG JSON endpoints from a logged-in tab)

## Recommended model workflow

1. `health_check`
2. `list_products`, `get_product_detail`, or `get_product_asset_manifest`
3. `analyze_sku_quantities` and, when needed, pass `quantityOverrides` into `calculate_smart_prices` or `prepare_product_draft`
4. `validate_product_for_upload` and `validate_product_assets`
5. `prepare_product_draft`
6. `apply_preparation_draft`, `update_product_info`, or `set_product_category`
7. `start_validated_upload` for a safe preflight; it defaults to `stopBeforeSubmit=true`
8. `get_upload_status`

## Operations loop workflow

Use this when the goal is daily shop operation rather than only product publishing.

1. `ops_health_check`
2. `ops_read_shop_metrics_cdp` when a logged-in FXG dashboard tab is available
3. `ops_read_strategy_signals_cdp` on the dashboard, product diagnosis page, after-sale page, or other logged-in FXG page when product diagnostics, risk-product counts, opportunity words, or wrong-order refund reasons are needed.
4. `ops_sync_strategy_signals` to persist the diagnosis snapshot and create local `open` product issue actions. If signals are omitted, the tool reads them first through CDP.
5. `ops_product_issue_actions` to read the open/in-progress action queue; if a product cannot be mapped to local material, record that fact instead of pretending the fix is done.
6. `ops_update_product_issue_action` to mark an action `in_progress`, `done`, `blocked`, or `skipped` with notes and evidence. This only writes the local ledger.
7. `ops_sync_product_record_mappings` to map diagnosis product IDs/titles to local Records by conservative title similarity. Treat `unmatched` as a real execution blocker for material fixes.
8. `ops_product_record_mappings` to review the latest mapping results.
9. `ops_sync_shop_metrics` with real browser/CDP/manual metrics; do not invent orders, GMV, refunds, ad spend, or net profit. Keep `net_profit_verified=false` unless an explicit net profit label is visible or the full cost formula is available.
10. `ops_evaluate_product` after offline goods cost is known
11. `ops_product_candidates` to rank local records by suggested sale price, per-order net profit, required daily orders, and trial stock
12. `ops_apply_candidate_pricing` dry-run first, then persist only when the local product needs its publish price corrected; the tool preserves `ops_goods_cost`
13. `ops_stock_plan` before publishing so local stock can be prepared conservatively
14. `ops_daily_plan`; pass `diagnosticSignals` from `ops_read_strategy_signals_cdp` or use the latest persisted strategy snapshot when available
15. `ops_profit_ramp_plan` to quantify the 500 CNY/day target into required orders, validation clicks/exposures, paid-ad readiness, and safety gates. Treat traffic estimates as assumptions until real order conversion exists.
16. `ops_daily_review` to combine the latest real snapshot, local product candidates, and strategy signals into practical operating actions

The operations loop is Codex-only for decision support. The local app must not call OpenAI, Ollama, DeepSeek, Claude, or other third-party model providers.

Use `fix-upload-blockers` when the product is not ready yet, `review-sku-quantities` when SKU pair counts are ambiguous, `capture-multiple-products` when the user provides many source links, and `monitor-upload-task` after upload has started.

Upload starts default to safe preflight (`stopBeforeSubmit=true`). This maps to Sidecar `stop_before_submit=true` and prevents the browser flow from performing the final publish/submit action. To run final publish, the caller must pass both `stopBeforeSubmit=false` and `confirmFinalPublish=true` after explicit user confirmation.

## Update material settings via MCP

To update automation material composition, call `update_settings` with `automation_config.material_compositions`.

```json
{
  "settings": {
    "automation_config": {
      "shipping_template": "中通包邮",
      "material_compositions": [
        { "material": "棉", "percentage": 75 },
        { "material": "氨纶", "percentage": 25 }
      ]
    }
  }
}
```

The percentages must sum to `100`, otherwise the desktop settings page will block saving.
