# 图片上传接口验收

日期：2026-05-05

## 目标

用本地真实图片验证 FXG 图片上传接口，而不是只依赖模块扫描或旧抓包。

## 样本

源文件：

- `项目备份 禁止改动使用 只参考/C-975/主图/白底.jpg`

请求中显式使用 ASCII 文件名：

- `c975-white-bg.jpg`

原因：首次测试发现中文文件名在 CDP/Node 传递后的产物中变成异常非中文文件名。图片内容上传成功，但文件名证据不合格。后续 Windows 测试统一显式指定 ASCII `UPLOAD_FILE_NAME`，避免污染请求和产物。

## 验收产物

- `captures/fxg_upload_sample_c975_white_bg_20260505.json`
- `captures/fxg_upload_sample_c975_white_bg_ascii_20260505.json`
- `captures/fxg_upload_batch_c975_main_images_20260505.json`

第二份和第三份为正式采信产物。

## 已验证

单图接口：

- `POST /product/img/batchupload`

请求形状：

- multipart
- 文件字段：`image`
- 附加字段：`extra={"request_source":"pc"}`

服务端结果：

- HTTP 状态：`200`
- 返回 `code=0`
- `data` 为数组
- 返回 1 条平台图片 URL

样本文件：

- MIME：`image/jpeg`
- 大小：`511945`
- 耗时：`360ms`

批量接口：

- `POST /product/img/batchupload?_bid=ffa_goods`

请求形状：

- multipart
- 文件字段：`image[0]`、`image[1]`
- 附加字段：`extra={"request_source":"pc"}`

服务端结果：

- HTTP 状态：`200`
- 返回 `code=0`
- `data` 为数组
- 返回 2 条平台图片 URL

样本文件：

- `c975-tm.png`：`image/png`，`523150`
- `c975-white-bg.jpg`：`image/jpeg`，`511945`
- 耗时：`661ms`

## 当前结论

`/product/img/batchupload` 单图和批量上传都可以从 `source_hint` 升级为 `server_accept_verified`。

该结论只覆盖图片二进制上传，不覆盖详情图绑定、白底图审核、素材保存和最终 `addWithSchema` 引用关系。

## 下一步

1. 截停主图上传后的页面状态，确认返回 URL 如何进入 `schema.model.pic.value[]`。
2. 继续验证详情图字段 `description` 的最终序列化。
3. 不直接假设上传 URL 一定可用于详情图、白底图或视频素材字段。
