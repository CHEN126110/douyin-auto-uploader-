# taobao-publisher 子项目工作约束

本目录是**淘宝/天猫商品「上传发布」流程**的独立研究 + 开发子项目。

## 0. 与既有目录的关系（先读这条，避免重复劳动）

| 目录 | 定位 | 本子项目如何对待 |
|---|---|---|
| `protocol-research-taobao-20260908/` | 淘宝发布环境的 **CDP 引导脚本 + 环境限制实证** | **复用其结论**，不重复实证。重启 Chrome 调试实例仍用它的 `start-taobao-cdp-chrome.mjs`。 |
| `protocol-research-clean-20260505/` | **抖店（fxg）** 协议研究区 | 只借架构（阶段划分 / 错误映射 / 安全门形态），**结论与字段一律不可搬用**。 |
| `tauri-app/python-sidecar/app.py` | 淘宝 **采集（读）** 已落地处 | `_extract_taobao_ice_data()` 等是**读路径**资产，发布（写）路径不得混入。 |
| `docs/淘宝天猫店铺采集技术文档.md` | 淘宝 **读接口** 旧文档 | 只覆盖采集，**不能推广到写接口**。 |

**淘宝与抖店是两套互不相通的账号、协议与字段体系**，本目录不得与 `protocol-research-clean-20260505/`（抖店）混用结论、脚本或字段映射。

## 1. 红线（不可放宽）

1. **默认零写入**。所有会改变平台状态的调用（图片上传 / 保存草稿 / 提交发布 / 修改商品）**默认禁用**，必须由调用方显式传入授权开关才可能发生。见 `docs/04-安全门与授权红线.md`。
2. **不绕过任何安全机制**。不做登录绕过、验证码绕过、风控绕过、平台权限绕过，不做高频探测。
3. **不落敏感数据**。禁止把 cookie、token、`_m_h5_tk`、`_tb_token_`、`cookie2`、手机号、店铺敏感信息、完整签名 URL、未脱敏请求头写进仓库、日志或产物。一切产物过 `taobao_publish.sanitize`。
4. **不用兜底掩盖映射错误**。字段没有实证证据时必须**显式记录为 blocker**，不允许"猜一个默认值让它跑通"。宁可拒绝执行，也不悄悄产出错误发布结果。
5. **研究产物只在本目录**。新增脚本、文档、去敏产物一律落在本目录内，不外溢到 `src/`、`protocol-research-*/`。
6. **禁止直接删除代码文件**（仓库级硬约束）。需要"删除"时移到 `项目备份 禁止改动使用 只参考/recycle_bin/RECYCLE_<原因>_<YYYY-MM-DD>/` 并附 README。

## 2. 证据分级（写文档必须标注）

文档、契约、字段映射里的每一条结论必须带证据等级，含义固定：

- **`verified`**：有可复现的实验证据（脚本输出 / 抓包产物 / 官方文档链接），且已归档到本目录。
- **`candidate`**：有间接证据或合理推断，尚未实证。可以直接写代码，但必须能在测试或探针里被证伪。
- **`unknown`**：查不到。**必须进 blockers**，不得用默认值填充。
- **`rejected`**：已实证不成立。必须写明证伪方式，避免后人重试。

禁止把 `candidate` 写成 `verified`。禁止删除 `rejected` 记录。

## 3. 环境

| 项 | 值 |
|---|---|
| CDP 端口 | `9334`（抖店用 9333，**不要复用**） |
| 调试 profile | `.runtime/chrome-taobao-cdp` |
| 发布工作台入口 | `https://item.upload.taobao.com/sell/ai/category.htm` |
| 登录态 | 该 profile **需独立扫码登录一次**，登录态随 profile 持久化 |

启动与环境检查（脚本在既有目录，本子项目不重复实现）：

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs
node protocol-research-taobao-20260908/scripts/check-taobao-cdp-environment.mjs
```

### 已实证的环境限制（**不要再重试**）

1. **冷复制 cookie 库失败**：Chrome 127+ 的 App-Bound Encryption 把 cookie 加密成 `v20`；复制 `Default/Network/Cookies` + `Local State` 到另一 user-data-dir 后解密失败，v20 记录被丢弃（实测 63 条淘宝 cookie 全部失效）。
2. **主 profile 开调试端口失败**：Chrome 136+ 明确拒绝 `DevTools remote debugging requires a non-default data directory.`

## 4. 本目录命令

```powershell
# 从仓库根目录执行
python -m pytest taobao-publisher/tests -q              # 离线测试（不联网、不碰平台）

# 从本目录执行
python -m taobao_publish readiness                      # 看两条写路线到底能不能用
python -m taobao_publish contracts                      # 列出所有证据项与来源

# 原始产物 → 脱敏产物。写到 captures/ 下会自动走更严的守卫。
python -m taobao_publish sanitize tmp/<raw>.json captures/tb_<用途>_<YYYYMMDD>.json

# 只读探针（需先启动 9334 调试 Chrome 并登录）
node taobao-publisher/scripts/probe-publish-workbench.mjs
node taobao-publisher/scripts/capture-publish-requests.mjs
```

## 4.1 产物边界（硬性）

```
探针 → tmp/<raw>.json                                ← 已 gitignore，绝不进仓库
  └─ python -m taobao_publish sanitize … → captures/ ← 过 assert_capture_ready 才能落盘
```

| 目录 | 进仓库 | 守卫 |
|---|---|---|
| `tmp/` | 否 | 无（原始产物就该待在这） |
| `outputs/` | 是 | `assert_clean` |
| `captures/` | 是 | **`assert_capture_ready`**（更严：出现敏感标记且附近无脱敏占位符即报错） |

**不要**把 `tmp/` 里的原始产物直接复制进 `captures/`。必须走 CLI 过一遍守卫。

## 5. 收口要求

每轮工作至少产出以下一种结果，并同步更新 `docs/05-证据日志.md` 与 `docs/06-阻塞项.md`：

- 缩小一个关键不确定性（`unknown` → `candidate`/`verified`/`rejected`）。
- 证明一个接口或字段是 `verified` / `candidate` / `unknown` / `rejected`。
- 形成可复跑的只读探针或离线分析脚本。
- 给出淘宝发布能否协议化、以及到哪一步能协议化的明确判断。
