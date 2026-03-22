#!/usr/bin/env python3
"""
测试采集API是否正常工作
"""

import requests
import json
import time

def test_capture_api():
    """测试采集API接口"""
    print("=" * 80)
    print("🧪 开始测试采集API")
    print("=" * 80)
    
    # 1. 测试服务器是否运行
    print("\n1️⃣ 测试Flask服务器是否运行...")
    try:
        response = requests.get('http://localhost:5000/', timeout=5)
        print(f"   ✅ 服务器运行正常 (状态码: {response.status_code})")
    except requests.exceptions.ConnectionError:
        print("   ❌ 无法连接到服务器！")
        print("   💡 请确保Flask应用已启动: python app.py")
        return False
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False
    
    # 2. 测试采集API端点
    print("\n2️⃣ 测试 /api/capture/start 端点...")
    url = "http://localhost:5000/api/capture/start"
    headers = {'Content-Type': 'application/json'}
    data = {
        'url': 'https://detail.tmall.com/item.htm?id=682468632663',
        'options': {
            'download_images': True,
            'extract_sku': True,
            'extract_params': True
        }
    }
    
    try:
        print(f"   📤 发送POST请求到: {url}")
        print(f"   📦 请求数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
        
        response = requests.post(url, json=data, headers=headers, timeout=10)
        
        print(f"   📥 响应状态码: {response.status_code}")
        print(f"   📄 响应头: {dict(response.headers)}")
        print(f"   📝 响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"\n   ✅ API测试成功！")
                print(f"   🆔 任务ID: {result.get('task_id')}")
                print(f"   💬 消息: {result.get('message')}")
                
                # 3. 测试状态查询
                task_id = result.get('task_id')
                if task_id:
                    print(f"\n3️⃣ 测试任务状态查询...")
                    time.sleep(2)  # 等待2秒
                    
                    status_url = f"http://localhost:5000/api/capture/status/{task_id}"
                    status_response = requests.get(status_url, timeout=5)
                    
                    print(f"   📥 状态响应: {status_response.text}")
                    
                    if status_response.status_code == 200:
                        status_result = status_response.json()
                        print(f"   ✅ 状态查询成功！")
                        print(f"   📊 状态: {status_result.get('status')}")
                        print(f"   📈 进度: {status_result.get('progress')}%")
                        print(f"   💬 消息: {status_result.get('message')}")
                    else:
                        print(f"   ⚠️ 状态查询失败: {status_response.status_code}")
                
                return True
            else:
                print(f"\n   ❌ API返回失败: {result.get('message')}")
                return False
        else:
            print(f"\n   ❌ HTTP错误: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print("   ❌ 请求超时！")
        return False
    except Exception as e:
        print(f"   ❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)

def test_frontend_connection():
    """测试前端能否访问"""
    print("\n4️⃣ 测试前端页面...")
    try:
        response = requests.get('http://localhost:5000/view/operate', timeout=5)
        if response.status_code == 200:
            print(f"   ✅ 前端页面可访问")
        else:
            print(f"   ⚠️ 前端页面状态码: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 无法访问前端: {e}")

if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                    采集API诊断工具                              ║
║                                                               ║
║  此工具会测试：                                               ║
║  1. Flask服务器是否运行                                       ║
║  2. /api/capture/start 接口是否正常                          ║
║  3. /api/capture/status/<task_id> 接口是否正常               ║
║  4. 前端页面是否可访问                                       ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    success = test_capture_api()
    test_frontend_connection()
    
    print("\n" + "=" * 80)
    if success:
        print("✅✅✅ 所有测试通过！")
        print("💡 如果前端仍然报错，请：")
        print("   1. 打开浏览器开发者工具（F12）")
        print("   2. 切换到Network（网络）标签")
        print("   3. 点击"开始采集"按钮")
        print("   4. 查看 /api/capture/start 请求的详细信息")
        print("   5. 截图发送给开发者")
    else:
        print("❌❌❌ 测试失败！")
        print("💡 请检查：")
        print("   1. Flask应用是否已启动: python app.py")
        print("   2. 端口5000是否被占用")
        print("   3. 防火墙是否阻止连接")
        print("   4. 查看Flask终端输出的错误信息")
    print("=" * 80)

