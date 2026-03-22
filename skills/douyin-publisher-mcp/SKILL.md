---
name: douyin-publisher-mcp
description: Use this skill when the user wants a model to operate the local Douyin publisher app through MCP, including importing folders, inspecting products, validating local assets, generating titles, calculating prices, editing categories and settings, managing files, and starting upload tasks.
---

# Douyin Publisher MCP

Use this skill when work should happen through the local app's MCP layer instead of by patching code or clicking the UI manually.

## Preconditions

- The MCP server for this repo must be registered and available.
- The local Douyin sidecar must be running, usually on `http://127.0.0.1:5001`.
- Start with `health_check` before attempting product or upload actions.
- Prefer the `streamable_http` endpoint if the client supports remote MCP; otherwise use the local `stdio` server.

## OpenClaw Runtime

- In OpenClaw, call this MCP through `mcporter`, using the registered server name `douyin-publisher`.
- Inspect the available tools with `mcporter list douyin-publisher --schema`.
- Call tools with `mcporter call douyin-publisher.<tool> ...`.
- On this machine, the server is registered as a local stdio command that runs `node E:\Script Project\Dyin\beiufen\2.0\mcp-server\server.js`.
- Prefer `mcporter call douyin-publisher.health_check --output json` before any write, capture, or upload operation.

## Workflow

1. Inspect current state with `health_check`, `list_products`, `get_product_detail`, `list_category_options`, or the `douyin://...` resources.
2. For imported folders, use `import_product_folders` with absolute paths.
3. Use `list_sku_assets` when the user needs SKU names matched to SKU images. Use `analyze_sku_quantities` when prices depend on understanding pair counts from free-form SKU text or SKU images.
4. If the rule-based quantity inference looks wrong, build `quantityOverrides` with `skuPath` plus the corrected pair count, then pass those overrides into `calculate_smart_prices`, `prepare_product_draft`, or `apply_preparation_draft`.
5. Use `list_product_files`, `get_product_asset_manifest`, or `validate_product_assets` when the user asks about folders, pictures, videos, or upload materials.
6. For captured source products, use `start_capture` for one link or `start_capture_batch` for many links, poll with `get_capture_status`, then `import_capture_result`. Use `get_capture_history` when the user needs prior task state.
7. Before upload, use `validate_product_for_upload` to surface missing title, category, SKU names, SKU prices, duplicate SKU names, and missing required local assets such as 3:4 main images.
8. For preparation, prefer `prepare_product_draft`; it combines title suggestions, smart pricing, and readiness before and after applying the draft.
9. If the user wants changes persisted, use `apply_preparation_draft`, `update_product_info`, or `set_product_category`.
10. Use `update_settings` and `reset_settings` for local settings changes, and `open_product_folder` when the user wants the OS folder opened.
11. For upload, prefer `start_validated_upload` on a single `recordId`, then poll `get_upload_status`. Use `start_batch_upload` or `start_upload(allProducts=true)` only when the user clearly wants batch scope.

## OpenClaw Command Patterns

- Health: `mcporter call douyin-publisher.health_check --output json`
- List products: `mcporter call douyin-publisher.list_products --output json`
- Read one product: `mcporter call douyin-publisher.get_product_detail recordId:123 --output json`
- Import folders: `mcporter call douyin-publisher.import_product_folders --args '{"paths":["D:\\\\A1 neveralone旗舰店\\\\C-1048"]}' --output json`
- Capture one link: `mcporter call douyin-publisher.start_capture url:https://detail.tmall.com/item.htm?... --output json`
- Validate upload: `mcporter call douyin-publisher.validate_product_for_upload recordId:123 --output json`
- Apply draft: `mcporter call douyin-publisher.apply_preparation_draft recordId:123 unitPrice:3.8 applyTitle:true applyPrices:true --output json`

## Upload Playbook

1. Start with `validate_product_for_upload`.
2. If blockers exist, fix them before upload:
   - Missing title or prices: use `prepare_product_draft`, then `apply_preparation_draft`.
   - Missing category: use `list_category_options`, then `set_product_category`.
   - Missing files or pictures: use `validate_product_assets`, `get_product_asset_manifest`, `list_product_files`, `list_sku_assets`, and `open_product_folder`.
   - Duplicate SKU names: inspect with `get_product_detail`, then correct via `update_product_info`.
3. Re-run `validate_product_for_upload` after each meaningful fix until the product is ready.
4. Only start upload when readiness is clean or the user explicitly accepts the remaining risk.
5. Use `start_validated_upload` for a single product.
6. After upload starts, keep polling `get_upload_status` until the task reaches a terminal state, then summarize success, failure reason, and any partial completion.

## MCP Prompts

- Use `prepare-product-for-upload` when the user wants a guided end-to-end preparation flow for one product.
- Use `upload-product-safely` when the user wants an upload started with validation first.
- Use `fix-upload-blockers` when the user wants help clearing readiness failures without immediately starting upload.
- Use `monitor-upload-task` when the user wants upload progress tracked to completion.
- Use `review-sku-quantities` when the SKU text is unusual and pricing should follow model-reviewed pair counts instead of only the rule extractor.
- Use `capture-multiple-products` when the user provides many source links and wants them processed as one workflow.

## Guardrails

- Prefer single-product mutations and uploads unless the user explicitly asks for batch behavior.
- Keep `get_product_detail(loadImages=false)` unless image payloads are necessary.
- Use `update_product_info` rather than trying to construct the legacy `save_info` payload yourself.
- Use `set_product_category` when the user speaks in category labels instead of raw category codes.
- Prefer `quantityOverrides` with `skuPath` when the correct pair count comes from model judgment or image review; avoid `skuName` overrides for duplicated names.
- Use `validate_product_assets` before upload when the question is about missing folders, pictures, or videos.
- Use `validate_product_for_upload` or `start_validated_upload` instead of blindly starting uploads.
- If upload is already running, do not start a second upload for the same product; switch to `get_upload_status`.
- Do not treat a validation error as a transport failure; surface the blocker categories clearly to the user or calling model.
- Do not mutate local files unless the user explicitly asked for file-level changes.
- Prefer `start_capture_batch` over ad hoc loops when the user provides multiple source links.
- If the MCP tools are unavailable, ask the user to register `E:\Script Project\Dyin\beiufen\2.0\mcp-server\server.js` as a local stdio MCP server, or `http://127.0.0.1:3300/mcp` as a streamable HTTP MCP endpoint.
