# Douyin Publisher MCP Capabilities

This file is the detailed index for the `douyin-publisher-mcp` skill. It should match the actual MCP server implementation.

## Runtime Endpoints

- Backend default: `http://127.0.0.1:5001`
- MCP streamable HTTP endpoint: `http://127.0.0.1:3300/mcp`
- Local stdio entry: `mcp-server/server.js`
- OpenClaw server name: `douyin-publisher`

## Resources

| Resource | URI | Use |
| --- | --- | --- |
| `backend-health` | `douyin://health` | Read current backend health state |
| `products` | `douyin://products` | Read the current product list |
| `settings` | `douyin://settings` | Read pricing, model, and automation settings |
| `upload-tasks` | `douyin://upload/tasks` | Read upload tasks and browser automation state |

## Prompts

| Prompt | Use |
| --- | --- |
| `prepare-product-for-upload` | Review one product, generate title and prices, and inspect readiness before any mutation |
| `fix-upload-blockers` | Turn validation failures into concrete repair steps |
| `review-sku-quantities` | Review pair counts before pricing |
| `upload-product-safely` | Validate first, then upload if ready |
| `monitor-upload-task` | Track one upload task until terminal state |
| `capture-multiple-products` | Launch and monitor many capture tasks |

## Tool Index By Workflow Stage

### Health and Discovery

- `health_check`
- `list_products`
- `get_product_detail`
- `list_category_options`
- `get_settings`

### Capture and Import

- `start_capture`
- `start_capture_batch`
- `get_capture_status`
- `import_capture_result`
- `get_capture_history`
- `cancel_capture`
- `import_product_folders`

### Product Editing

- `generate_smart_title`
- `prepare_product_draft`
- `apply_preparation_draft`
- `update_product_info`
- `set_product_category`
- `analyze_sku_quantities`
- `calculate_smart_prices`

### File and Asset Inspection

- `list_sku_assets`
- `list_product_files`
- `get_product_asset_manifest`
- `validate_product_assets`
- `open_product_folder`

### Settings

- `get_settings`
- `update_settings`
- `reset_settings`

### Upload

- `validate_product_for_upload`
- `start_validated_upload`
- `start_upload`
- `start_batch_upload`
- `get_upload_status`
- `list_upload_tasks`
- `cancel_upload`

### Destructive Operations

- `delete_sku`
- `delete_product`
- `delete_all_products`

Use these only when the user explicitly asks for deletion.

### Browser Debug and Failure Analysis

- `debug_browser_ensure`
- `get_browser_debug_session`
- `debug_browser_snapshot`
- `debug_browser_find_elements`
- `debug_browser_action`
- `debug_browser_capture_artifacts`
- `get_last_browser_debug_report`

Use these only when upload automation fails, page state must be inspected, or the user explicitly wants browser troubleshooting.

## Important Behavior Notes

- `get_product_detail` should usually keep `loadImages=false` unless image payloads are required.
- `prepare_product_draft` is the safest high-level read path for title plus pricing suggestions.
- `apply_preparation_draft` persists generated title and/or prices.
- `update_product_info` is the safe write path for title, remark, repo, category, and SKU updates.
- `set_product_category` accepts either a numeric category code or a human-readable label.
- `calculate_smart_prices`, `prepare_product_draft`, and `apply_preparation_draft` accept `quantityOverrides`.
- Use `quantityOverrides` with `skuPath` whenever pair counts were corrected from image review or model judgment.
- `start_upload` supports either `recordId` or `allProducts=true`, never both.
- `start_validated_upload` should be preferred over `start_upload` for one product because it validates readiness first.
- `list_upload_tasks` is the best first read when another agent may already be uploading.
- `cancel_upload` and `cancel_capture` are available and should be surfaced when a user asks to stop work.

## OpenClaw Notes

- OpenClaw should call this MCP through `mcporter`.
- Preferred flow:
  1. `mcporter list douyin-publisher --schema`
  2. `mcporter call douyin-publisher.health_check --output json`
  3. Call the task-specific tool with the same `douyin-publisher.<tool>` naming.
- Keep the OpenClaw server name and the MCP entry path conceptually separate:
  - Server name: `douyin-publisher`
  - Local entry file: `mcp-server/server.js`
