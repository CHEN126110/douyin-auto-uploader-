# 淘宝商品信息采集系统

一个基于Python + Playwright的自动化淘宝商品信息采集工具，支持商品信息提取、图片下载、登录处理等功能。

## 功能特性

- ✅ **自动化采集**: 支持淘宝/天猫商品页面自动访问和信息提取
- ✅ **智能登录**: 自动检测登录需求，友好的用户引导
- ✅ **信息提取**: 提取商品标题、价格、主图、详情图、SKU信息、商品参数
- ✅ **图片下载**: 自动下载商品图片到本地目录
- ✅ **任务管理**: 实时任务状态监控和历史记录管理
- ✅ **缓存机制**: 智能缓存避免重复采集
- ✅ **频率限制**: 防止过度访问的安全机制
- ✅ **错误处理**: 完善的异常处理和重试机制
- ✅ **Web界面**: 现代化的前端操作界面

## 系统要求

- Python 3.7+
- Windows/Linux/macOS 操作系统
- 网络连接（用于访问淘宝页面）

## 快速开始

### 1. 安装系统

#### Windows系统
```bash
# 运行安装脚本
install.bat
```

#### Linux/macOS系统
```bash
# 运行安装脚本
bash install.sh
```

### 2. 手动安装（可选）

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装Playwright浏览器
playwright install chromium
```

### 3. 启动服务

```bash
# 运行启动脚本
start_service.bat  # Windows
# 或
python capture_service.py
```

### 4. 访问系统

打开浏览器访问：http://localhost:5000

## 使用说明

### 基本采集流程

1. **输入商品链接**: 在输入框中粘贴淘宝/天猫商品链接
2. **选择采集选项**: 选择需要采集的内容（图片、SKU、参数等）
3. **开始采集**: 点击"开始采集"按钮启动任务
4. **等待完成**: 系统会自动处理，包括登录检测
5. **查看结果**: 采集完成后查看提取的信息
6. **导入数据**: 可以将采集结果导入到系统中

### 支持的链接格式

- 淘宝商品：`https://item.taobao.com/item.htm?id=123456`
- 天猫商品：`https://detail.tmall.com/item.htm?id=123456`
- 天猫国际：`https://detail.tmall.hk/item.htm?id=123456`

### 采集选项说明

- **下载图片**: 自动下载商品主图和详情图片
- **提取SKU信息**: 获取商品的规格、颜色、尺寸等SKU信息
- **提取商品参数**: 获取商品的详细参数和属性

### 登录处理

当系统检测到需要登录时：
1. 会弹出提示框引导用户登录
2. 浏览器窗口会自动打开
3. 用户手动完成登录操作
4. 点击"我已登录完成"继续采集

## 文件结构

```
淘宝商品信息采集系统/
├── capture_service.py          # 主服务文件
├── requirements.txt            # Python依赖
├── install.bat                 # Windows安装脚本
├── start_service.bat           # Windows启动脚本
├── templates/                  # HTML模板文件
│   ├── index.html             # 主页重定向
│   ├── capture.html           # 采集控制台
│   └── history.html           # 历史记录页面
├── static/                     # 静态资源
│   ├── css/
│   │   └── capture.css        # 样式文件
│   └── js/
│       ├── capture.js         # 采集功能JS
│       └── history.js         # 历史记录JS
├── uploads/products/           # 下载的图片存储
├── cache/                      # 缓存文件
└── logs/                       # 日志文件
```

## API接口

### 开始采集任务
```http
POST /api/product/capture/start
Content-Type: application/json

{
    "url": "https://detail.tmall.com/item.htm?id=123456",
    "options": {
        "download_images": true,
        "extract_sku": true,
        "extract_params": true
    }
}
```

### 获取任务状态
```http
GET /api/product/capture/status/{task_id}
```

### 取消采集任务
```http
POST /api/product/capture/cancel/{task_id}
```

### 导入采集结果
```http
POST /api/product/capture/import
Content-Type: application/json

{
    "task_id": "capture_123456",
    "product_data": {
        // 采集结果数据
    }
}
```

### 获取历史记录
```http
GET /api/product/capture/history
```

## 配置说明

系统支持通过配置文件进行自定义设置：

```yaml
# config.yaml
capture:
  max_concurrent_tasks: 3      # 最大并发任务数
  retry_attempts: 3            # 重试次数
  timeout_seconds: 300         # 超时时间

browser:
  headless: false              # 是否无头模式
  viewport: {width: 1920, height: 1080}
  user_agent: "自定义User-Agent"

storage:
  download_directory: "uploads/products/"  # 图片下载目录
  cache_directory: "cache/"                # 缓存目录
  max_cache_age: 86400                   # 缓存有效期（秒）

rate_limit:
  max_requests_per_minute: 10  # 每分钟最大请求数
  user_cooldown_seconds: 60    # 用户冷却时间
```

## 常见问题

### Q: 系统无法启动？
A: 请检查Python版本是否符合要求（3.7+），并确保所有依赖已正确安装。

### Q: 浏览器无法打开？
A: 确保已安装Playwright浏览器：`playwright install chromium`

### Q: 采集失败？
A: 检查网络连接，确认商品链接有效，查看日志文件了解详细错误信息。

### Q: 登录后无法继续？
A: 确保在浏览器中完成登录后，点击"我已登录完成"按钮。

### Q: 图片下载失败？
A: 检查网络连接，确认图片URL可访问，查看日志了解具体错误。

## 安全说明

- 系统仅在本地运行，不会上传用户数据到外部服务器
- 所有采集的图片和数据存储在本地
- 支持访问频率限制，防止过度访问
- 输入验证和清理，防止恶意输入

## 更新日志

### v1.1.0 (2024-11-13)
- 🔧 **重构右键菜单功能**
  - **第一阶段**：移除复杂的右键菜单代码（约400行）
    - 原因：代码包含多层对抗性修复，违反项目开发原则
    - 移除内容：复杂的环境兼容代码、多重定位方式、大量调试日志
  - **第二阶段**：从1.0版本还原简洁实现（约90行）
    - 来源：`1.0最早版本/web/view/operate/index.html`
    - 实现方式：
      - HTML: 简单的 `div + ul + li` 结构（5行）
      - CSS: 基础样式，无复杂效果（约30行）
      - JavaScript: 清晰的事件绑定和处理逻辑（约55行）
    - 特点：
      - ✅ 代码简洁易维护
      - ✅ 无对抗性修复
      - ✅ 使用标准的 `position: absolute` + `e.pageX/pageY`
      - ✅ 清晰的变量作用域管理
      - ✅ 完整的错误处理
  - **诊断系统**：添加完整的调试工具用于排查问题
    - `testContextMenu()`: 基础诊断测试
    - `fullDiagnosis()`: 完整诊断报告（推荐）
    - 功能：
      - ✅ 检查菜单元素和产品行
      - ✅ 验证jQuery和原生事件系统
      - ✅ 手动显示菜单测试
      - ✅ 自动绑定测试事件
      - ✅ 详细的样式和结构分析
  - 使用方法：刷新页面 → 按F12 → 控制台输入 `fullDiagnosis()`
  - 参考文档：`右键菜单问题系统分析.md`
- 🐛 **修复导入完成后列表不刷新问题**
  - 问题：后端返回 `success: true`，但前端判断失败
  - 原因：`/api/capture/import` 的 AJAX 请求缺少 `dataType: 'json'`
  - 修复：添加 `dataType: 'json'` 确保响应被正确解析为对象
  - 增强：添加详细调试日志，兼容字符串和布尔值类型的 success 字段

### v1.0.0 (2024-01-01)
- ✨ 初始版本发布
- ✅ 基础采集功能
- ✅ Web操作界面
- ✅ 历史记录管理
- ✅ 图片下载功能
- ✅ 登录处理机制

## 技术支持

如遇到问题，请查看日志文件`capture.log`获取详细信息，或检查系统配置。

## 许可证

MIT License - 详见LICENSE文件