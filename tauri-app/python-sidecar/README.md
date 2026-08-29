# Python Sidecar 后端

这是Tauri应用的Python后端服务。

## 结构

```
python-sidecar/
├── app.py           # Flask主应用（从原项目迁移）
├── src/
│   ├── orm.py       # 数据模型
│   ├── utils.py     # 工具函数
│   ├── thread.py    # 线程处理
│   └── ...          # 其他模块
├── requirements.txt # 依赖
└── README.md        # 说明文档
```

## 部署方式

1. **开发模式**: 直接运行 `python app.py`
2. **生产模式**: 使用PyInstaller打包为可执行文件

## 打包命令

```bash
pyinstaller --onefile --name python-backend app.py
```

打包后的可执行文件放到 `src-tauri/sidecar/` 目录。
