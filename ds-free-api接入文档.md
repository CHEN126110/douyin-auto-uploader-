# ds-free-api 接入文档

## 当前服务

- 服务地址：`http://127.0.0.1:8000`
- OpenAI 兼容 Base URL：`http://127.0.0.1:8000/v1`
- 当前唯一可用模型：`deepseek-v4-pro`
- 鉴权方式：`Authorization: Bearer <DeepSeek网页端userToken>`

## 模型说明

本地代理已只保留 `deepseek-v4-pro`。该模型会映射到 DeepSeek 网页端的 Expert 模式，并默认开启 Thinking。

旧模型名如 `deepseek-chat`、`deepseek-r1`、`deepseek-reasoner`、`deepseek-search` 已不再接受，请统一改成：

```text
deepseek-v4-pro
```

## OpenAI SDK 示例

```python
from openai import OpenAI

client = OpenAI(
    api_key="你的DeepSeek网页端userToken",
    base_url="http://127.0.0.1:8000/v1",
)

resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "user", "content": "请只回复四个字：测试成功"}
    ],
)

print(resp.choices[0].message.content)
```

## LobeChat / NextChat / Dify 配置

- API 类型：OpenAI Compatible / 自定义 OpenAI 接口
- Base URL：`http://127.0.0.1:8000/v1`
- API Key：填写 DeepSeek 网页端 `userToken`
- Model：`deepseek-v4-pro`

如果客户端有模型列表刷新功能，刷新后应该只看到 `deepseek-v4-pro`。

## PowerShell 验证

```powershell
$token = "你的DeepSeek网页端userToken"
$headers = @{ Authorization = "Bearer $token" }
$body = @{
  model = "deepseek-v4-pro"
  messages = @(@{ role = "user"; content = "请只回复四个字：测试成功" })
  stream = $false
} | ConvertTo-Json -Depth 20 -Compress

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/chat/completions" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## PM2 管理

```powershell
pm2 status ds-free-api
pm2 logs ds-free-api --lines 100
pm2 restart ds-free-api
pm2 save
```

## 注意事项

- `userToken` 是 DeepSeek 网页端登录态，不是官方 API Key，不要公开泄露。
- 该项目是网页端代理，稳定性取决于 DeepSeek 网页接口变化。
- 如果 DeepSeek Expert 模式高峰期繁忙，代理也会受到同样影响。
- 如果 PowerShell 输出中文乱码，先执行：

```powershell
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```
