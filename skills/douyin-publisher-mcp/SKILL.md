---
name: douyin-publisher-mcp
description: Use this skill when a model should operate the local Douyin publisher app through MCP instead of editing code or clicking the UI manually. Covers capture, folder import, product inspection, category and title edits, smart pricing, settings changes, upload validation, upload start, task monitoring, and OpenClaw-specific MCP calling patterns.
---

# Douyin Publisher MCP

Use this skill when work should happen through the local app's MCP layer instead of by patching code or driving the UI manually.

## Preconditions

- The local Douyin backend must be running. Default backend URL is `http://127.0.0.1:5001`.
- The MCP server must be available through either local `stdio` or `streamable_http`.
- Start with `health_check` before capture, import, pricing, settings writes, or upload actions.
- Prefer the runtime-generated launch command shown in the desktop app settings. If that is unavailable, use the MCP server instructions from this repo's `mcp-server/README.md`.

## Supported Runtimes

### OpenClaw

- Keep OpenClaw support enabled. Call this MCP through `mcporter` with the registered server name `douyin-publisher`.
- Inspect schema with `mcporter list douyin-publisher --schema`.
- Call tools with `mcporter call douyin-publisher.<tool> ...`.
- Prefer `mcporter call douyin-publisher.health_check --output json` before any write, capture, or upload operation.

### Other MCP clients

- Use local `stdio` when the client supports launching a local command.
- Use `streamable_http` when the client supports remote MCP and you want the local HTTP endpoint at `http://127.0.0.1:3300/mcp`.
- When a packaged MCP executable is available, prefer that `stdio` entry over raw Node startup.

## Safe Default Workflow

1. Inspect current state with `health_check`, `list_products`, `get_product_detail`, `list_category_options`, or the `douyin://...` resources.
2. Use `start_capture` or `start_capture_batch` for source links, then `get_capture_status`, `import_capture_result`, and `get_capture_history` as needed.
3. Use `import_product_folders` for local product directories.
4. Use `prepare_product_draft` for the main edit flow when the user wants title plus pricing suggestions together.
5. Use `apply_preparation_draft`, `update_product_info`, `set_product_category`, or `update_settings` only when the user wants changes persisted.
6. Before upload, use `validate_product_for_upload` and, when files matter, `validate_product_assets`.
7. For one product, prefer `start_validated_upload`, then poll `get_upload_status`.
8. Use `list_upload_tasks` or `cancel_upload` when task coordination matters. Use browser debug tools only for troubleshooting.

## When To Use Which Tool

- Category edits: `list_category_options`, then `set_product_category`.
- Title-only work: `generate_smart_title` or `prepare_product_draft`.
- Pricing work: `analyze_sku_quantities`, optional `quantityOverrides`, then `calculate_smart_prices` or `prepare_product_draft`.
- Save title, remark, repo, or SKU edits: `update_product_info`.
- Settings read or write: `get_settings`, `update_settings`, `reset_settings`.
- File and asset inspection: `list_product_files`, `get_product_asset_manifest`, `list_sku_assets`, `validate_product_assets`, `open_product_folder`.
- Upload safety: `validate_product_for_upload`, `start_validated_upload`, `get_upload_status`, `list_upload_tasks`, `cancel_upload`.
- Capture safety: `start_capture`, `start_capture_batch`, `get_capture_status`, `import_capture_result`, `cancel_capture`.

## OpenClaw Command Patterns

- Health: `mcporter call douyin-publisher.health_check --output json`
- List products: `mcporter call douyin-publisher.list_products --output json`
- Read one product: `mcporter call douyin-publisher.get_product_detail recordId:123 --output json`
- Import folders: `mcporter call douyin-publisher.import_product_folders --args '{"paths":["D:\\\\your-product-folder"]}' --output json`
- Capture one link: `mcporter call douyin-publisher.start_capture url:https://detail.tmall.com/item.htm?... --output json`
- Validate upload: `mcporter call douyin-publisher.validate_product_for_upload recordId:123 --output json`
- Apply draft: `mcporter call douyin-publisher.apply_preparation_draft recordId:123 unitPrice:3.8 applyTitle:true applyPrices:true --output json`

## Prompts

- `prepare-product-for-upload`: guided review before any mutation.
- `fix-upload-blockers`: convert readiness failures into concrete fixes.
- `review-sku-quantities`: inspect SKU pair counts before pricing.
- `upload-product-safely`: validate first, then upload if ready.
- `monitor-upload-task`: follow one upload task until completion.
- `capture-multiple-products`: process many source links as one workflow.

## Guardrails

- Prefer single-product mutations and uploads unless the user explicitly asks for batch behavior.
- Keep `get_product_detail(loadImages=false)` unless image payloads are necessary.
- Use `update_product_info` rather than constructing the legacy `save_info` payload manually.
- Use `set_product_category` when the user speaks in category labels instead of raw category codes.
- Prefer `quantityOverrides` with `skuPath` when the correct pair count comes from model judgment or image review. Avoid `skuName` overrides for duplicated names.
- Use `validate_product_assets` when the question is about missing folders, pictures, videos, or upload materials.
- Use `validate_product_for_upload` or `start_validated_upload` instead of blindly starting uploads.
- If upload is already running, switch to `get_upload_status`, `list_upload_tasks`, or `cancel_upload` instead of starting a duplicate task.
- Do not treat a validation error as a transport failure. Surface blocker categories clearly.
- Do not mutate local files unless the user explicitly asked for file-level changes.
- Prefer `start_capture_batch` over ad hoc loops when the user provides multiple source links.
- Keep browser debug tools for troubleshooting and upload failure analysis, not as the default operating path.

## Additional References

- Detailed tool, resource, and prompt index: [capabilities.md](capabilities.md)
- End-to-end business workflows and troubleshooting: [playbooks.md](playbooks.md)