# 研究产物命名与落盘规范

本文用于统一协议自动化研究阶段的产物命名、目录布局和回写规则。

目标：

- 让每一份只读探针产物、截停证据、矩阵报告都能快速追溯来源。
- 避免同类文件重复命名、覆盖旧文件或混淆不同类目样本。
- 保证文档结论、字段矩阵和证据文件之间能一一对应。

## 基本原则

- 研究产物只写入 `protocol-research/` 目录，不混入正式主链路目录。
- 同一类产物固定目录，不临时散落到多个路径。
- 文件名必须包含：`产物类型 + 类目/样本 + 日期时间戳`。
- 文件名优先使用 ASCII，可读类目标识使用英文短名或拼音短名，避免后续脚本处理困难。
- 任何结论性文档都必须能追溯到至少一个实际产物文件。

## 时间戳规范

- 统一使用本地时间，格式：

```text
YYYYMMDD_HHMMSS
```

- 示例：

```text
20260429_153015
```

- 同一批连续执行的探针可以共用一个 `run_id`，便于汇总。

## 运行批次规范

- 每一轮执行建议先生成一个批次号：

```text
run_<YYYYMMDD_HHMMSS>
```

- 示例：

```text
run_20260429_153015
```

- 这个批次号可用于：
  - 目录分组
  - 报告标题
  - 文档回写引用
  - 字段矩阵备注

## 类目标识规范

- 文件名中的类目部分不直接使用完整中文类目路径。
- 统一使用简短标识，例如：

```text
long_socks
mid_socks
short_socks
boat_socks
phone_case
```

- 如果是“当前页面基线样本”，可用：

```text
current_page
```

- 如果是记录样本，可用：

```text
record_<id>
```

## 目录规范

建议按以下目录分层：

```text
protocol-research/
  captures/
    environment/
    qualification/
    material/
    submit-preflight/
  schemas/
    live/
    runtime/
    freight/
    submit/
    category-matrix/
  reports/
    stage-reviews/
    field-diffs/
    blocker-reviews/
  dry_run/
    generated/
    comparisons/
```

## 文件命名规范

### 1. 环境检查

```text
env_check_<sample>_<timestamp>.json
```

- 示例：

```text
env_check_current_page_20260429_153015.json
```

### 2. schema 探针

```text
fxg_schema_probe_<sample>_<timestamp>.json
```

- 示例：

```text
fxg_schema_probe_long_socks_20260429_153015.json
```

### 3. runtime options 探针

```text
fxg_runtime_options_<sample>_<timestamp>.json
```

### 4. freight 探针

```text
fxg_freight_probe_<sample>_<timestamp>.json
```

### 5. submit 字段形状探针

```text
fxg_submit_probe_<sample>_<timestamp>.json
```

### 6. qualification 探针

```text
fxg_qualification_probe_<sample>_<timestamp>.json
```

### 7. material 探针

```text
fxg_material_probe_<sample>_<timestamp>.json
```

### 8. category matrix 探针

```text
fxg_category_matrix_<sample_set>_<timestamp>.json
```

- 示例：

```text
fxg_category_matrix_socks_20260429_153015.json
```

### 9. 本地截停产物

```text
fxg_protocol_capture_<profile>_<sample>_<timestamp>.json
```

- 示例：

```text
fxg_protocol_capture_submit_preflight_long_socks_20260429_153015.json
```

### 10. dry-run 产物

```text
protocol_dry_run_<sample>_<timestamp>.json
```

### 11. 提交预检 body

```text
add_with_schema_preflight_<sample>_<timestamp>.json
```

### 12. 分析报告

```text
<topic>_review_<sample>_<timestamp>.md
```

- 示例：

```text
media_chain_review_long_socks_20260429_153015.md
sku_blocker_review_mid_socks_20260429_153015.md
```

## 文档回写规范

每次执行后，至少做三件事：

1. 在 `docs/field_evidence_matrix.md` 更新字段证据等级。
2. 在相关阶段文档中补充“新增证据”或“新增阻塞项”。
3. 在报告中写清这批产物对应的 `run_id` 和文件名。

## 产物引用规范

- 文档引用具体产物时，至少包含：
  - 产物类型
  - 样本名
  - 时间戳
- 不要只写“最新一次探针结果”这类无法追溯的描述。

- 推荐写法：

```text
本轮 schema 基线产物：fxg_schema_probe_long_socks_20260429_153015.json
本轮 submit 字段形状产物：fxg_submit_probe_long_socks_20260429_153015.json
```

## 样本命名建议

- 袜子类目研究建议统一样本名：

```text
long_socks
mid_socks
short_socks
boat_socks
children_socks
```

- 通用样本建议：

```text
current_page
latest_record
record_<id>
```

## 禁止事项

- 禁止覆盖旧产物，只保留“latest”而丢失历史样本。
- 禁止把研究产物写入主项目正式目录。
- 禁止使用模糊命名，例如：

```text
test.json
new_probe.json
最新结果.json
最终版.json
```

- 禁止文档结论无法追溯到实际文件。

## 当前建议

当前研究阶段建议先以“单类目、单样本、单批次”推进。

推荐第一轮统一使用：

```text
sample = long_socks
run_id = run_<timestamp>
```

这样方便先把 schema、runtime、freight、submit、qualification、material 六类只读探针产物对齐，再回写字段证据矩阵。
