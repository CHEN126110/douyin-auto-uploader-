#!/bin/bash
# 淘宝商品信息采集系统启动脚本

echo "=========================================="
echo "淘宝商品信息采集系统启动脚本"
echo "=========================================="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: Python3未安装，请先安装Python3"
    exit 1
fi

echo "Python版本: $(python3 --version)"

# 检查pip
if ! command -v pip3 &> /dev/null; then
    echo "错误: pip3未安装，请先安装pip3"
    exit 1
fi

# 检查虚拟环境if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# 安装依赖
echo "安装Python依赖..."
pip install -r requirements.txt

# 安装Playwright浏览器
echo "安装Playwright浏览器..."
playwright install chromium

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p uploads/products
mkdir -p cache
mkdir -p logs
mkdir -p static/images

# 创建默认图片
echo "创建默认图片..."
cat > static/images/no-image.png << 'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==
EOF

# 检查配置文件
if [ ! -f "config.yaml" ]; then
    echo "创建默认配置文件..."
    cat > config.yaml << 'EOF'
capture:
  max_concurrent_tasks: 3
  retry_attempts: 3
  timeout_seconds: 300

browser:
  headless: false
  viewport: {width: 1920, height: 1080}
  user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

storage:
  download_directory: "uploads/products/"
  cache_directory: "cache/"
  max_cache_age: 86400  # 24小时

rate_limit:
  max_requests_per_minute: 10
  user_cooldown_seconds: 60

logging:
  level: INFO
  file: capture.log
EOF
fi

# 启动服务
echo "启动淘宝商品采集服务..."
echo "服务地址: http://localhost:5000"
echo "日志文件: capture.log"
echo "=========================================="

# 运行服务
python capture_service.py

echo "服务启动完成！"
