# 抖音袜子发布工具 v4.0 (Tauri版)

基于 **Tauri + Vue 3 + TypeScript + Element Plus** 的现代化桌面应用。

## 🚀 技术栈

- **前端**: Vue 3 + TypeScript + Vite + Element Plus + Pinia
- **桌面框架**: Tauri 2.0 (Rust)
- **后端**: Python Flask (Sidecar)
- **数据库**: SQLite (Peewee ORM)

## 📦 项目结构

```
tauri-app/
├── src/                    # Vue前端源码
│   ├── components/         # 组件
│   │   ├── CaptureSection.vue    # 链接采集区域
│   │   ├── ContextMenu.vue       # 右键菜单
│   │   ├── SettingsDialog.vue    # 设置弹窗
│   │   └── SkuList.vue           # SKU列表
│   ├── views/              # 页面
│   │   ├── ProductManager.vue    # 主页面
│   │   └── Settings.vue          # 设置页面
│   ├── stores/             # Pinia状态管理
│   │   └── productStore.ts
│   ├── services/           # API服务
│   │   └── api.ts                # HTTP + Tauri命令
│   ├── styles/             # 样式
│   │   ├── variables.scss        # 设计变量
│   │   ├── global.scss           # 全局样式
│   │   └── components.scss       # 组件覆盖
│   ├── types/              # 类型定义
│   │   └── index.ts
│   ├── router/             # 路由
│   │   └── index.ts
│   ├── App.vue             # 根组件
│   └── main.ts             # 入口文件
├── src-tauri/              # Tauri Rust源码
│   ├── src/main.rs         # 主入口 (窗口、命令、事件)
│   ├── tauri.conf.json     # Tauri配置
│   ├── Cargo.toml          # Rust依赖
│   └── sidecar/            # Sidecar可执行文件目录
├── python-sidecar/         # Python后端
│   ├── app.py              # Flask应用
│   ├── requirements.txt    # Python依赖
│   ├── build_sidecar.py    # PyInstaller打包脚本
│   └── README.md
├── package.json            # 前端依赖
├── vite.config.ts          # Vite配置
├── tsconfig.json           # TypeScript配置
├── setup_dev.bat           # Windows开发环境配置
├── setup_dev.ps1           # PowerShell开发环境配置
└── README.md               # 说明文档
```

## 🛠️ 开发环境要求

| 工具 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Node.js | 18.0+ | 20.x LTS |
| Rust | 1.70+ | 最新稳定版 |
| Python | 3.10+ | 3.11.x |
| npm | 9.0+ | 10.x |

## 🔧 快速开始

### 1. 配置开发环境

**Windows (推荐)**
```powershell
# 运行配置脚本
.\setup_dev.ps1
```

或使用批处理:
```batch
setup_dev.bat
```

### 2. 手动安装 (可选)

```bash
# 安装前端依赖
npm install

# 安装Python依赖 (在项目根目录)
cd ..
pip install -r requirements.txt
```

### 3. 开发模式

```bash
# 方式1: 分别启动前端和后端
# 终端1: 启动Python后端
python python-sidecar/app.py

# 终端2: 启动Vue开发服务器
npm run dev

# 方式2: 启动完整的Tauri开发环境 (推荐)
npm run tauri:dev
```

### 4. 构建生产版本

```bash
# 1. 构建Python Sidecar (可选，如果需要打包)
cd python-sidecar
python build_sidecar.py
cd ..

# 2. 构建Tauri应用
npm run tauri:build
```

## 📋 从v3.0迁移说明

### 变更点
| 项目 | v3.0 | v4.0 |
|------|------|------|
| 桌面框架 | PySide6 + QtWebEngine | Tauri (Rust) |
| 前端技术 | HTML/CSS/JS + Layui | Vue 3 + Element Plus |
| 打包体积 | ~150MB | ~10MB |
| 渲染引擎 | QtWebEngine | 系统WebView2 |
| 类型系统 | 无 | TypeScript |
| 状态管理 | 无 | Pinia |

### 保持不变
- ✅ Flask后端API接口
- ✅ SQLite数据库结构 (Peewee ORM)
- ✅ DrissionPage自动化
- ✅ 视觉设计规格 (颜色、圆角、阴影)
- ✅ 核心业务逻辑

## 🎨 设计规格

### 主色调
```scss
--primary-color: #5c7cfa;       // 主色 - 蓝紫色
--success-color: #69db7c;       // 成功 - 绿色
--warning-color: #ff8cc8;       // 警告 - 粉色
--danger-color: #ff8a80;        // 危险 - 红色
```

### 圆角系统
```scss
--radius-sm: 8px;               // 按钮、输入框
--radius-md: 12px;              // 卡片、面板
--radius-lg: 20px;              // 大卡片
```

完整设计规格请查看 `docs/TAURI_MIGRATION_SPEC.md`

## 📡 API接口

### 产品管理
- `GET /api/products` - 获取产品列表
- `GET /load_detail?_id={id}` - 获取产品详情
- `POST /save_info` - 保存产品信息
- `POST /delete_sku` - 删除SKU
- `DELETE /delete_all` - 清空所有产品

### 智能标题
- `POST /api/generate_smart_title` - 标准版标题生成
- `POST /api/generate_smart_title_enhanced` - 增强版标题生成

### 智能定价
- `POST /api/pricing/calculate_smart_prices` - 智能价格计算

### 采集功能
- `POST /api/capture/start` - 开始采集
- `GET /api/capture/status/{task_id}` - 获取采集状态
- `POST /api/capture/import` - 导入采集结果

## 🐛 常见问题

### Q: 后端启动失败？
A: 检查Python环境和依赖是否正确安装：
```bash
python --version  # 应为 3.10+
pip list | grep flask
```

### Q: Tauri编译失败？
A: 确保Rust已正确安装：
```bash
rustc --version
cargo --version
```

### Q: 前端样式不生效？
A: 检查SCSS编译：
```bash
npm install sass -D
npm run dev
```

### Q: 文件拖拽不工作？
A: 确保 `tauri.conf.json` 中 `fileDropEnabled` 为 `true`

## 📝 开发日志

### 2026-01-08
- ✅ 创建Tauri项目结构
- ✅ 迁移Vue 3前端框架
- ✅ 实现Python Sidecar集成
- ✅ 完成主要组件开发

## 📄 许可证

MIT License
