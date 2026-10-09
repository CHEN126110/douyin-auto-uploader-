# contracts · 事实来源

本目录是子项目的**唯一事实来源**。平台字段名、选择器、平台硬约束只允许写在这里，
不允许硬编码进 `taobao_publish/` 的 dataclass 或任何逻辑代码。

| 文件 | 内容 | 谁在读 |
|---|---|---|
| `field_mapping.json` | 发布意图 → 平台字段映射，含证据等级与写门规则 | `contracts.FieldMappingContract`、`mapping.build_platform_payload` |
| `selectors.json` | DOM 路线选择器，含写关键标记 | `contracts.SelectorContract` |
| `rules.json` | 平台硬约束（数量 / 尺寸 / 长度 / 价格） | `contracts.RulesContract`、`mapping.validate_*` |
| `publish_item.schema.json` | 入参契约（平台无关层） | sidecar / CLI 请求体校验 |

## 为什么要有这一层

如果 `pid`、`sku_prices`、`postage_id` 这些名字散落在代码里，后人会自然而然
把它们当成事实，然后照着写代码、写测试、写文档。集中之后：

- `taobao_publish/` 里**搜索不到任何淘宝字段名**；
- 每条映射都**必须**带证据等级，`verified` 还必须带来源；
- `candidate` 不足以放行写操作（见下面的写门）。

## 证据等级

| 等级 | 含义 |
|---|---|
| `verified` | 有可复现实验证据（脚本输出 / 抓包产物 / 官方文档），且已归档 |
| `candidate` | 有间接证据或合理推断，尚未实证。可以写代码，但必须能被证伪 |
| `unknown` | 查不到。**必须进 blockers**，不得用默认值填充 |
| `rejected` | 已实证不成立。必须写明证伪方式 |

## 写门

`field_mapping.json` 的 `write_gate`：

> `platform_field` 非 null 且 `evidence.level` 属于 `["verified"]` 时，
> 该字段才允许进入真实写操作。

**为什么 `candidate` 不够**：本契约里大多数 `candidate` 来自**已下线的开放平台
老接口文档**。那些字段语义能帮我们理解新版 schema，但**不能证明**当前网页工作台
仍使用同名协议字段。拿 `candidate` 去写平台，等于拿猜测当事实。

## 自检

契约与代码常量对不上时会**直接报错**，不是打日志：

```powershell
python -m pytest taobao-publisher/tests/test_contracts.py -q
python -m taobao_publish contracts          # 列出所有证据项与来源
python -m taobao_publish readiness          # 看两条写路线能不能用
```

自检覆盖：

- 证据等级必须是四个合法值之一；`stage` 必须是已知阶段。
- 标为 `verified` 的字段**必须**有 `evidence.source`（证据必须可追溯）。
- 必填但不可写的字段**必须**有 `blocker_hint`（后人要知道去做什么）。
- `selectors.json` 里填了 `selector` 但证据还是 `unknown` → **报错**。
  这条是防止「先把选择器抄进去，证据回头再补」——那种做法迟早会变成
  「抄进去就忘了补」。
- `rules.json` 里被流水线当作硬约束使用的规则，`hard` 必须真的是 `true`。
- 入参 schema 的 `required` 必须包含 `record_id` / `title` / `skus`。

## 怎么增补证据

1. 跑只读探针（见 `../scripts/README.md`），原始产物落 `tmp/`。
2. `python -m taobao_publish sanitize` 脱敏后写入 `captures/`。
3. 编辑本目录的 JSON：填 `platform_field` / `selector`，升 `evidence.level`，
   **`evidence.source` 指向 `captures/` 里的具体产物**。
4. 在 `../docs/05-证据日志.md` 追加 E-xxx（实证）或 R-xxx（证伪）条目。
5. 跑自检与测试：

```powershell
python -m pytest taobao-publisher/tests -q
python -m taobao_publish readiness
```
