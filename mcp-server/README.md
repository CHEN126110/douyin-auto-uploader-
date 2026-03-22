# Douyin Publisher MCP Server

This server exposes the existing local Flask sidecar as MCP tools, resources, and prompts.

## Preconditions

- The Douyin publisher backend must already be running on `http://127.0.0.1:5001`, or another URL set via `DOUYIN_BACKEND_URL`.
- The safest way is to start the Tauri app first, then connect the MCP client.

## Run

`stdio` mode:

```powershell
Set-Location 'E:\Script Project\Dyin\beiufen\2.0\mcp-server'
npm start
```

`streamable_http` mode:

```powershell
Set-Location 'E:\Script Project\Dyin\beiufen\2.0\mcp-server'
npm run start:http
```

## Example MCP client config

```json
{
  "mcpServers": {
    "douyin-publisher": {
      "command": "node",
      "args": [
        "E:\\Script Project\\Dyin\\beiufen\\2.0\\mcp-server\\server.js"
      ],
      "env": {
        "DOUYIN_BACKEND_URL": "http://127.0.0.1:5001"
      }
    }
  }
}
```

Example Streamable HTTP endpoint:

```text
http://127.0.0.1:3300/mcp
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

## Exposed prompts

- `prepare-product-for-upload`
- `fix-upload-blockers`
- `review-sku-quantities`
- `upload-product-safely`
- `monitor-upload-task`
- `capture-multiple-products`

## Recommended model workflow

1. `health_check`
2. `list_products`, `get_product_detail`, or `get_product_asset_manifest`
3. `analyze_sku_quantities` and, when needed, pass `quantityOverrides` into `calculate_smart_prices` or `prepare_product_draft`
4. `validate_product_for_upload` and `validate_product_assets`
5. `prepare_product_draft`
6. `apply_preparation_draft`, `update_product_info`, or `set_product_category`
7. `start_validated_upload`
8. `get_upload_status`

Use `fix-upload-blockers` when the product is not ready yet, `review-sku-quantities` when SKU pair counts are ambiguous, `capture-multiple-products` when the user provides many source links, and `monitor-upload-task` after upload has started.
