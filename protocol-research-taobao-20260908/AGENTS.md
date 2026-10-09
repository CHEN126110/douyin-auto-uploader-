# protocol-research-taobao-20260908 工作约束

本目录是**淘宝 / 千牛商品发布流程**的独立协议研究区。

淘宝与抖店（fxg）是**两套互不相通的账号与协议体系**，本目录不得与
`protocol-research-clean-20260505/`（抖店）混用结论、脚本或字段映射。

## 红线（与抖店研究区一致，不得放宽）

- 只在本目录内新增研究文档、脚本和去敏产物。
- **只观察，不写入**：不触发图片上传、不保存草稿、不调用发布/提交接口、
  不修改任何线上商品。探针脚本里不允许出现写操作调用路径。
- 不保存 cookie、token、`_m_h5_tk`、`_tb_token_`、手机号、店铺敏感信息、
  完整签名 URL 或未脱敏请求头。
- 不做登录绕过、验证码绕过、风控绕过、平台权限绕过或高频探测。
- 不使用兜底代码掩盖字段映射错误；字段缺证据时必须记录为 blocker。
- 旧的 `docs/淘宝天猫店铺采集技术文档.md` 只覆盖**读接口**（mtop 商品采集），
  其结论不能直接推广到**写接口**（发布），必须重新实证。

## 环境

| 项 | 值 |
|---|---|
| CDP 端口 | `9334`（抖店用 9333，不要复用） |
| 调试 profile | `.runtime/chrome-taobao-cdp` |
| 目标页 | `https://item.upload.taobao.com/sell/ai/category.htm` |

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs
node protocol-research-taobao-20260908/scripts/check-taobao-cdp-environment.mjs
```

## 已实证的环境限制（2026-09-08，Chrome 152.0.7977.76）

复用用户现有登录态的两条路都**实测失败**，不要再重试：

1. **冷复制 cookie 库失败**。Chrome 127+ 的 App-Bound Encryption 把 cookie
   加密成 `v20` 前缀；把 `Default/Network/Cookies` + `Local State` 复制到另一个
   user-data-dir 后，Chrome 解密失败并丢弃全部 v20 记录（实测 63 条淘宝 cookie
   全部失效，只剩重新种下的 v10 登录页 cookie）。
2. **主 profile 开调试端口失败**。Chrome 136+ 起明确拒绝：
   `DevTools remote debugging requires a non-default data directory.`

因此本目录的调试 profile 需要**独立登录一次**（扫码），登录态随 profile 持久化；
或改用浏览器扩展直连用户现有 Chrome。

## 研究收口要求

每轮研究至少产出以下一种结果：

- 缩小一个关键不确定性。
- 证明一个接口或字段是已实证、候选、阻塞或排除。
- 形成可复跑的只读探针或离线分析脚本。
- 给出淘宝发布能否协议化的明确判断。
