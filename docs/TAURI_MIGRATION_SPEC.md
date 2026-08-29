# 抖音袜子发布工具 v3.0 → Tauri 迁移规格文档

> **目标**：完整重构到Tauri + Vue 3架构，确保功能和视觉效果与当前版本差异最小

---

## 📋 一、当前项目架构总览

### 1.1 技术栈


| 层级     | 当前技术                     | 迁移目标                              |
| ------ | ------------------------ | --------------------------------- |
| 桌面框架   | PySide6 + QWebEngineView | Tauri (Rust)                      |
| 前端     | HTML/CSS/JS + Layui      | Vue 3 + TypeScript + Element Plus |
| 后端     | Flask (Python)           | Python Sidecar (保持Flask)          |
| 数据库    | SQLite (Peewee ORM)      | SQLite (保持)                       |
| 浏览器自动化 | DrissionPage             | DrissionPage (保持)                 |


### 1.2 文件结构映射

```
当前结构                          → Tauri结构
├── app.py (Flask主入口)          → python-sidecar/app.py
├── src/
│   ├── gui.py (Qt窗口)           → src-tauri/src/main.rs (Tauri窗口)
│   ├── orm.py (数据模型)         → python-sidecar/src/orm.py
│   ├── thread.py (线程)          → python-sidecar/src/thread.py
│   ├── utils.py (工具函数)       → python-sidecar/src/utils.py
│   └── ...                       → python-sidecar/src/...
├── web/
│   ├── view/operate/index.html   → src/views/ProductManager.vue
│   ├── admin/css/*.css           → src/styles/*.css
│   └── component/layui/          → (移除，使用Element Plus)
└── templates/                    → src/views/
```

---

## 🎨 二、视觉设计规格

### 2.1 主色调系统

```css
/* 品牌色 - 必须保持一致 */
--primary-color: #5c7cfa;           /* 主色 - 蓝紫色 */
--primary-gradient: linear-gradient(135deg, #5c7cfa 0%, #748ffc 100%);
--primary-hover: #4c6ef5;
--primary-shadow: rgba(92, 124, 250, 0.3);

/* 辅助色 */
--success-color: #69db7c;           /* 绿色 - 成功 */
--success-gradient: linear-gradient(135deg, #69db7c 0%, #51cf66 100%);

--warning-color: #ff8cc8;           /* 粉色 - 警告/warm */
--warning-gradient: linear-gradient(135deg, #ff8cc8 0%, #ff6b9d 100%);

--danger-color: #ff8a80;            /* 红色 - 危险 */
--danger-gradient: linear-gradient(135deg, #ff8a80 0%, #ff7043 100%);

/* 背景色 */
--background-gradient: linear-gradient(135deg, #f8f9ff 0%, #fdf2f8 50%, #fffbf0 100%);
--card-background: rgba(255, 255, 255, 0.85);
--card-background-hover: rgba(255, 255, 255, 0.92);

/* 文字色 */
--text-primary: #2c3e50;
--text-secondary: #6c757d;
--text-placeholder: rgba(44, 62, 80, 0.5);
```

### 2.2 圆角系统

```css
--radius-sm: 8px;                   /* 按钮、输入框 */
--radius-md: 12px;                  /* 卡片、面板 */
--radius-lg: 20px;                  /* 大卡片、左侧面板 */
```

### 2.3 阴影系统

```css
--shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.05);
--shadow-md: 0 4px 16px rgba(92, 124, 250, 0.3);
--shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.06);
--shadow-hover: 0 12px 40px rgba(0, 0, 0, 0.08);
```

### 2.4 字体系统

```css
--font-family: 'Microsoft YaHei UI', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
--font-size-xs: 12px;
--font-size-sm: 13px;
--font-size-base: 14px;
--font-size-lg: 15px;
--font-size-xl: 18px;
--font-size-title: 24px;
```

### 2.5 布局尺寸

```css
/* 左侧面板 */
--left-panel-width: 420px;
--left-panel-top: 130px;

/* 间距 */
--container-padding: 20px;
--form-gap: 16px;
--button-gap: 8px;

/* 按钮 */
--button-padding: 14px 24px;
--button-padding-sm: 8px 12px;
```

---

## 🔧 三、功能模块清单

### 3.1 产品管理（主页面）

#### 3.1.1 左侧面板 - 产品列表


| 功能     | 描述        | 实现方式                        |
| ------ | --------- | --------------------------- |
| 产品列表展示 | 显示所有待上传产品 | GET `/api/products`         |
| 列表点击   | 切换右侧配置区域  | GET `/load_detail?_id={id}` |
| 右键菜单   | 打开/删除产品   | 自定义右键菜单                     |
| 选中状态   | 高亮当前选中行   | CSS `.active` 类             |
| 缓存优化   | 已加载数据缓存   | 前端 `detailCache` Map        |


#### 3.1.2 链接采集区域


| 功能    | 描述         | 实现方式                               |
| ----- | ---------- | ---------------------------------- |
| URL输入 | 粘贴淘宝/天猫链接  | Input组件                            |
| 开始采集  | 启动采集任务     | POST `/api/capture/start`          |
| 进度显示  | 实时采集进度     | 轮询 `/api/capture/status/{task_id}` |
| 状态展示  | 采集状态文字+进度条 | 响应式UI                              |


#### 3.1.3 右侧面板 - 配置区域


| 功能   | 描述           | 实现方式                                       |
| ---- | ------------ | ------------------------------------------ |
| 类目选择 | 下拉选择类目       | Select (0-4: 船袜/短袜/中筒袜/长筒袜/袜套)             |
| 标题输入 | 商品标题 (60字限制) | Input + 字数统计                               |
| 智能标题 | AI标题建议       | POST `/api/generate_smart_title`           |
| 增强标题 | 热门词+标题       | POST `/api/generate_smart_title_enhanced`  |
| 卖点备注 | 备注说明         | Input                                      |
| 库存设置 | 数字输入         | Number Input                               |
| 单价设置 | 价格输入         | Number Input                               |
| 智能填充 | 基于成本计算价格     | POST `/api/pricing/calculate_smart_prices` |
| 简单填充 | 统一填充价格       | 前端逻辑                                       |
| 保存   | 保存配置         | POST `/save_info`                          |


#### 3.1.4 SKU管理区域


| 功能    | 描述           | 实现方式                  |
| ----- | ------------ | --------------------- |
| SKU列表 | 缩略图+名称+价格+删除 | 虚拟滚动 (>50项)           |
| 图片预览  | 悬停显示大图       | 悬浮面板                  |
| SKU选中 | 点击选中/取消      | CSS `.sku-selected` 类 |
| SKU删除 | 删除单个SKU      | POST `/delete_sku`    |
| 懒加载   | 图片懒加载优化      | LazyLoader            |


#### 3.1.5 底部操作按钮


| 功能   | 描述        | 实现方式                 |
| ---- | --------- | -------------------- |
| 开始上传 | 启动自动化上传   | POST `/start`        |
| 取消勾选 | 清除SKU选中状态 | 前端逻辑                 |
| 清空全部 | 删除所有产品    | DELETE `/delete_all` |
| 设置   | 打开设置弹窗    | GET `/settings/page` |


### 3.2 设置页面


| 功能     | 描述          | API                                      |
| ------ | ----------- | ---------------------------------------- |
| 成本项目管理 | 添加/编辑/删除成本项 | POST `/api/pricing/cost-item`            |
| 利润率配置  | 设置目标利润率     | POST `/api/pricing/profit-margin-config` |
| 图片命名规则 | 支持格式/过滤器    | POST `/settings`                         |
| UI设置   | 主题/动画/悬停图片  | POST `/settings`                         |
| 处理设置   | 自动检测/批量模式   | POST `/settings`                         |


### 3.3 文件导入（拖拽）


| 功能   | 描述       | 实现方式                    |
| ---- | -------- | ----------------------- |
| 拖拽导入 | 将文件夹拖入窗口 | Tauri `tauri://drop` 事件 |
| 文件扫描 | 扫描SKU图片  | Python后端处理              |
| 数据入库 | 创建产品记录   | Record.create()         |


---

## 📡 四、API接口清单

### 4.1 产品管理

```typescript
// 获取产品列表
GET /api/products
Response: { success: boolean, products: Product[] }

// 获取产品详情
GET /load_detail?_id={id}&images={true|false}
Response: { success: boolean, data: ProductDetail }

// 保存产品信息
POST /save_info
Body: { _id, title, remark, clazz, repo, attr_size, attr_path_*, attr_name_*, attr_price_* }
Response: { success: boolean, msg: string }

// 删除SKU
POST /delete_sku
Body: { sku_path: string, record_id: string }
Response: { success: boolean, msg: string }

// 删除所有产品
DELETE /delete_all
Response: { success: boolean, msg: string }

// 打开产品文件夹
GET /menu_open?_id={id}

// 删除产品
GET /menu_delete?_id={id}
```

### 4.2 采集功能

```typescript
// 开始采集
POST /api/capture/start
Body: { url: string, options: CaptureOptions }
Response: { success: boolean, task_id: string }

// 查询采集状态
GET /api/capture/status/{task_id}
Response: { success: boolean, status: string, progress: number, ... }

// 导入采集结果
POST /api/capture/import
Body: { task_id: string }
Response: { success: boolean, ... }
```

### 4.3 智能标题

```typescript
// 标准版标题生成
POST /api/generate_smart_title
Body: { record_id: string }
Response: { success: boolean, data: { suggestions: TitleSuggestion[] } }

// 增强版标题生成
POST /api/generate_smart_title_enhanced
Body: { record_id: string, use_trending: boolean }
Response: { success: boolean, data: { suggestions: TitleSuggestion[], trending_keywords: Keyword[] } }

// 专业标题生成
POST /api/generate_professional_title
Body: { record_id: string, style: string }
```

### 4.4 价格计算

```typescript
// 智能价格计算
POST /api/pricing/calculate_smart_prices
Body: { record_id: string, unit_price?: number }
Response: { success: boolean, data: { pricing_results: PricingResult[], statistics: Stats } }

// 成本项目管理
POST /api/pricing/cost-item
GET /api/pricing/cost-items
GET /api/pricing/config
POST /api/pricing/cost-config
POST /api/pricing/profit-margin-config
```

### 4.5 设置管理

```typescript
// 获取设置
GET /settings
Response: { success: boolean, data: { settings: Settings } }

// 更新设置
POST /settings
Body: Settings

// 重置设置
POST /settings/reset

// 设置页面
GET /settings/page
```

### 4.6 上传功能

```typescript
// 开始上传
POST /start
Response: { success: boolean, msg: string }
```

---

## 🗃️ 五、数据模型

### 5.1 Record 表

```python
class Record(Model):
    id = PrimaryKeyField()
    name = CharField()              # 产品名称/文件夹名
    path = CharField()              # 文件夹路径
    type = IntegerField()           # 类型
    status = IntegerField()         # 状态
    repo = IntegerField(null=True)  # 库存数量
    title = CharField(null=True)    # 商品标题
    clazz = CharField(null=True)    # 类目 (0-4)
    remark = CharField(null=True)   # 备注
    content = TextField()           # SKU列表 JSON
    update_time = DateTimeField()   # 更新时间
    publish_time = DateTimeField(null=True)  # 发布时间
    shipping_template = CharField(default='中通包邮')  # 运费模板
```

### 5.2 SKU数据结构

```typescript
interface SKU {
    path: string;       // 图片文件路径
    name: string;       // SKU名称
    price: number;      // 价格
    url?: string;       // Base64图片数据 (动态加载)
}
```

---

## 🎯 六、交互规格

### 6.1 列表行点击

1. 显示选中状态 (左侧蓝色边框 + 渐变背景)
2. 加载产品详情 (带缓存检查)
3. 更新右侧配置区域
4. 渲染SKU列表

### 6.2 SKU缩略图交互

1. **点击**: 切换选中状态 (`.sku-selected`)
2. **悬停**: 显示预览大图面板 (右上角 220x220)
3. **选中效果**: 蓝色边框 + 缩放1.05 + 蓝色阴影

### 6.3 右键菜单

1. 触发: 右键点击列表行
2. 位置: 鼠标位置 (clientX, clientY)
3. 选项: 打开、删除
4. 关闭: 点击其他区域

### 6.4 弹窗样式

1. 标题栏: 蓝紫渐变背景, 白色文字
2. 关闭按钮: 垂直居中于标题栏
3. 内容区: 白色背景
4. 按钮: 蓝紫渐变, 圆角8px

---

## 🚀 七、迁移步骤

### Phase 1: 基础设施 (Day 1-2)

- 安装 Rust + Tauri CLI
- 创建 Tauri 项目结构
- 配置 Python Sidecar
- 验证 Flask 后端在 Sidecar 中运行

### Phase 2: 前端迁移 (Day 3-5)

- 设置 Vue 3 + Vite
- 安装 Element Plus
- 迁移 CSS 变量系统
- 实现主布局组件
- 实现产品列表组件
- 实现 SKU 管理组件
- 实现设置弹窗组件

### Phase 3: API集成 (Day 6-7)

- 实现 Tauri Commands (Rust ↔ Python)
- 实现前端 API 服务层
- 实现拖拽文件导入
- 实现右键菜单

### Phase 4: 测试优化 (Day 8-10)

- 功能完整性测试
- 视觉一致性验证
- 性能优化
- 打包测试

---

## 📝 八、注意事项

1. **保持视觉一致**: 所有颜色、间距、圆角严格按照规格文档
2. **API兼容**: 保持现有API不变，前端适配
3. **渐进式迁移**: 先验证核心功能，再优化细节
4. **数据兼容**: 确保现有SQLite数据可直接使用

---

*文档版本: 1.0*  
*创建日期: 2026-01-08*