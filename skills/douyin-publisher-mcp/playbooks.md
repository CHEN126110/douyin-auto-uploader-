# Douyin Publisher MCP Playbooks

Use this file when the task requires the full business flow instead of only a quick tool lookup.

## Playbook 1: Capture Source Products And Import Them

1. Call `health_check`.
2. For one URL, call `start_capture`. For many URLs, call `start_capture_batch`.
3. Poll `get_capture_status` until each task reaches a terminal state.
4. Import completed tasks with `import_capture_result`.
5. If the user wants to stop the workflow, call `cancel_capture`.
6. If the user wants the historical record, call `get_capture_history`.

Use this playbook when the user provides Taobao, Tmall, or 1688 links and wants products brought into the local app.

## Playbook 2: Import Local Product Folders

1. Call `health_check`.
2. Call `import_product_folders` with absolute folder paths.
3. Call `list_products` to confirm import results.
4. Call `get_product_detail` for the imported product if the user wants immediate review.

Use this playbook when the user already has prepared product folders on disk.

## Playbook 3: Review And Edit One Product

1. Call `get_product_detail`.
2. If category options are needed, call `list_category_options`.
3. If the user only wants category changes, call `set_product_category`.
4. If the user wants direct title, remark, repo, or SKU edits, call `update_product_info`.
5. Re-read with `get_product_detail` if a post-save confirmation is useful.

Use this playbook for explicit manual edits.

## Playbook 4: Smart Title And Pricing Workflow

1. Call `get_product_detail` with `loadImages=false`.
2. If SKU pair counts may be ambiguous, call `analyze_sku_quantities` and `list_sku_assets`.
3. Build `quantityOverrides` using `skuPath` for any corrected pair count.
4. For title-only work, call `generate_smart_title`.
5. For the combined preparation flow, call `prepare_product_draft`.
6. If the user wants the generated title or prices saved, call `apply_preparation_draft`.
7. If the user wants custom edits instead of generated ones, use `update_product_info`.

Use this playbook for "智能填充", title generation, or price generation.

## Playbook 5: Upload Safely

1. Call `validate_product_for_upload`.
2. If blockers mention files or images, call `validate_product_assets`, `get_product_asset_manifest`, `list_product_files`, `list_sku_assets`, or `open_product_folder`.
3. If blockers mention title, category, SKU names, or prices:
   - Missing title or prices: use `prepare_product_draft`, then `apply_preparation_draft` if the user wants persistence.
   - Missing category: use `list_category_options`, then `set_product_category`.
   - Duplicate SKU names or direct field problems: use `get_product_detail`, then `update_product_info`.
4. Re-run `validate_product_for_upload`.
5. Only when readiness is clean, call `start_validated_upload`.
6. Poll `get_upload_status` until the task reaches `success`, `failed`, or `cancelled`.
7. Use `list_upload_tasks` when another upload may already be in progress.
8. Use `cancel_upload` if the user explicitly asks to stop the upload.

Prefer this playbook over raw `start_upload`.

## Playbook 6: Batch Upload Or Legacy Upload Scope

1. Use `start_batch_upload` when the user explicitly chooses several record IDs.
2. Use `start_upload(allProducts=true)` only when the user clearly wants the legacy all-products behavior.
3. Use `list_upload_tasks` and `get_upload_status` to coordinate progress.

Do not default to batch behavior.

## Playbook 7: Settings Changes

1. Call `get_settings` first if the current configuration matters.
2. Call `update_settings` with only the top-level keys that need to change.
3. Use `reset_settings` only when the user explicitly wants defaults restored.

Typical uses include automation settings, pricing settings, and material composition updates.

## Playbook 8: Browser Troubleshooting

1. Start with `get_last_browser_debug_report` when an upload failed and the automation already captured a report.
2. Use `debug_browser_ensure` to create or reconnect to the shared browser session.
3. Use `debug_browser_snapshot` or `debug_browser_find_elements` to inspect the current page safely.
4. Use `debug_browser_action` only for narrow troubleshooting steps such as navigate, hover, click, scroll, clear, or input.
5. Use `debug_browser_capture_artifacts` when the user needs screenshots, HTML, or saved debug context.

Keep browser debug tools as a troubleshooting path, not the normal operating flow.

## Guardrails Summary

- Start with `health_check` for every new workflow.
- Prefer read tools first, then mutating tools only when the user wants persisted changes.
- Prefer single-product scope.
- Prefer `skuPath` over `skuName` in `quantityOverrides`.
- Prefer `start_validated_upload` over raw upload start for one product.
- Treat validation failures as business blockers, not transport failures.
- Use OpenClaw `mcporter` commands when operating inside OpenClaw, but keep the workflow logic identical to other MCP clients.
