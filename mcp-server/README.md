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

Example packaged EXE client config:

```json
{
  "mcpServers": {
    "douyin-publisher": {
      "command": "<install-root>\\douyin-publisher-mcp.exe",
      "args": [],
      "env": {
        "DOUYIN_BACKEND_URL": "http://127.0.0.1:5001"
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
- Shared browser debug session management
- Browser page snapshots, element queries, and simple debug actions
- Automatic browser error report retrieval with screenshot/HTML/context artifacts

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
