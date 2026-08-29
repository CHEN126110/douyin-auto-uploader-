# 抖音协议流水线 vs DOM 流水线对照分析

## DOM 流水线 11 阶段覆盖情况

| # | DOM阶段 | 操作 | addWithSchema字段 | 协议状态 |
|---|---------|------|-------------------|----------|
| 1 | `open_publish_page` | 导航到发布页 | (会话建立) | ✅ CDP cookies可替代 |
| 2 | `fill_title` | 填写标题输入框 | `title` | ✅ 协议body已有 |
| 3 | `upload_main_images` | 上传1:1主图(800px) | `pic` | ✅ batchupload已验证 |
| 4 | `select_category` | 选择类目树 | `goods_category` | ✅ body已有 |
| 5 | `fill_category_attributes` | 材质/筒高/吊牌图 | `category_properties` | ⚠️ 部分覆盖 |
| 6 | `upload_media_assets` | 上传3:4/白底/详情/视频 | `main_image_3_to_4`/`white_background_pic`/`description`/`main_pic_video` | ⚠️ body已有,batchupload验证 |
| 7 | `configure_sku_entries` | 填写SKU规格值 | `spec_detail` | ⚠️ spec_detail结构已知,需验证 |
| 8 | `configure_sku_structure` | 配置SKU组合 | `sku_detail` | ⚠️ sku_detail结构已知,需验证 |
| 9 | `fill_price_stock` | 填写价格库存运费 | `sku_detail.price`/`stock`/`freight_id` | ✅ body已有 |
| 10 | `submit_publish` | 点击发布按钮 | addWithSchema请求 | ⚠️ 端点已知,待实发测试 |

## 资产准备覆盖情况

| 资产 | DOM来源 | 协议来源 |
|------|---------|----------|
| 主图(1:1,800px) | `get_pic_list(record, '800')` | 主图目录下 `_1x1.jpg` 文件 |
| 主图(3:4,750px) | `get_pic_list(record, '750')` | 主图目录下 `.webp`/`.jpg` 文件 |
| 详情图 | `get_detail_pic_list(record)` | 详情页目录 |
| 吊牌图 | `get_diaopai_pic(record)` | ⚠️ 无明确来源 |
| 白底图 | `get_white_pic(record, sku_list)` | 第一张1:1主图 |
| 视频 | `get_my_video(record)` | ⚠️ 无明确来源(可选) |
| SKU数据 | `json.loads(record.content)` | mtop缓存/ICE数据 |

## 类目属性详情 (category_properties)

| 属性ID | 名称 | DOM填充方式 | 协议值 |
|--------|------|-------------|--------|
| 1865 | 筒高 | 选择匹配的选项 | value_id映射表 |
| 785 | 材质成分 | 填写measure_info | 模板873,material拆分 |
| 1687 | 适用性别 | 选择"通用" | value_id=32880 |
| 品牌 | 品牌 | 填写或选择"无品牌" | ⚠️ 缺value_id |
| 水洗标/吊牌图 | 图片上传 | upload_file | ⚠️ batchupload可用,缺属性ID |

## 未覆盖项目

| 项目 | 影响 | 优先级 |
|------|------|--------|
| **品牌属性** | 必填 | 🔴 高 |
| **吊牌图(category_properties中的图片字段)** | 类目属性 | 🔴 高 |
| **spec_detail IDs规则** | SKU必须 | 🟡 中 |
| **sku_detail IDs规则** | SKU必须 | 🟡 中 |
| **运费模板ID动态获取** | 不同店铺不同 | 🟡 中 |
| **视频上传** | 可选 | 🟢 低 |
| **publishId获取** | addWithSchema可能需要 | 🟡 中 |

## 双轨架构设计

```
                     ┌─ use_protocol=True? ─┐
                     │                       │
              ┌──────▼──────┐        ┌──────▼──────┐
用户点击发布  │ 协议流水线   │        │ DOM流水线    │
              │ batchupload  │        │ DrissionPage │
              │ addWithSchema│        │ 11阶段自动化 │
              └──────┬──────┘        └──────┬──────┘
                     │                       │
                     └───────┬───────────────┘
                             │
                     ┌───────▼───────┐
                     │  结果统一处理  │
                     │  错误/重试/日志 │
                     └───────────────┘
```

**关键原则**：
- 协议流水线是 DOM 的**增强**，不是替代
- DOM 流水线作为兜底默认保留
- 通过 `use_protocol` 标志切换
- 任何协议阶段失败自动回退到 DOM
