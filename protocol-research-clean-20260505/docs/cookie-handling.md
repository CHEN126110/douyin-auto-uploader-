# Cookie 处理规范

创建日期：2026-05-05

Cookie-Editor 导出的 FXG/Jinritemai Cookie 属于登录态敏感信息。它可以帮助确认会话依赖和浏览器环境，但原始值不能进入研究产物。

## 本目录只允许保存的信息

- `domain`
- `name`
- `path`
- `httpOnly`
- `secure`
- `sameSite`
- `session`
- `hasExpiration`
- `expirationDate`
- `valueLength`
- `valuePreviewHash`

`valuePreviewHash` 只能用于判断同一份导出里是否有重复值，不能反推原文。

## 禁止保存的信息

- Cookie 原始 `value`
- 拼接后的 `Cookie` 请求头
- 完整签名 URL
- token、session、MFA、CSRF、店铺 ID 等可识别敏感原文

## 研究结论边界

这类 Cookie 只能说明：

- 当前接口研究需要在已登录浏览器上下文中进行。
- 一部分接口依赖平台会话、CSRF、设备和风控相关 Cookie。
- 直接脱离浏览器手搓请求的稳定性和合规风险都更高。

不能说明：

- 可以绕过登录。
- 可以长期复用 Cookie。
- 可以把 Cookie 固化进脚本。
- 可以把 Cookie 当成正式协议自动化凭证。

## 当前处理结论

用户在对话中贴出了完整 Cookie。后续研究不使用这些原始值，改为依赖本机已登录浏览器的 CDP 会话，并只保存去敏摘要。
