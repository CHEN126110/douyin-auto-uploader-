#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 /load_detail 接口的 ERR_ABORTED 错误
检查数据库连接、记录存在性和接口响应
"""

import sys
import os
import requests
import json
from datetime import datetime

# 添加项目路径到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_database_connection():
    """测试数据库连接和记录"""
    print("=" * 50)
    print("1. 测试数据库连接和记录")
    print("=" * 50)
    
    try:
        # 导入数据库相关模块 - 使用正确的路径
        from src.orm import Record, database
        
        # 检查数据库连接
        print("✓ 数据库模块导入成功")
        
        # 测试数据库连接
        if database.is_closed():
            database.connect()
            print("✓ 数据库连接已建立")
        
        # 查询所有产品记录
        print("\n查询所有产品记录...")
        products = list(Record.select())
        print(f"数据库中共有 {len(products)} 条产品记录")
        
        if products:
            print("\n前5条记录的ID:")
            for i, product in enumerate(products[:5]):
                print(f"  - ID: {product.id}, 标题: {getattr(product, 'title', 'N/A')}")
        
        # 特别检查 ID=1 的记录
        print(f"\n检查 ID=1 的记录...")
        try:
            product_1 = Record.get_or_none(Record.id == 1)
            if product_1:
                print(f"✓ 找到 ID=1 的记录:")
                print(f"  - 标题: {getattr(product_1, 'title', 'N/A')}")
                print(f"  - 分类: {getattr(product_1, 'clazz', 'N/A')}")
                print(f"  - 内容长度: {len(getattr(product_1, 'content', ''))}")
                print(f"  - 状态: {getattr(product_1, 'status', 'N/A')}")
                return True
            else:
                print("✗ 未找到 ID=1 的记录")
                return False
        except Exception as e:
            print(f"✗ 查询 ID=1 记录时出错: {e}")
            return False
            
    except Exception as e:
        print(f"✗ 数据库连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_load_detail_api():
    """测试 /load_detail 接口"""
    print("\n" + "=" * 50)
    print("2. 测试 /load_detail 接口")
    print("=" * 50)
    
    base_url = "http://127.0.0.1:5000"
    endpoint = "/load_detail"
    
    # 测试不同的参数组合
    test_cases = [
        {"_id": 1, "images": "true"},
        {"_id": 1},
        {"_id": "1", "images": "true"},
    ]
    
    for i, params in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}: {params}")
        try:
            response = requests.get(f"{base_url}{endpoint}", params=params, timeout=10)
            print(f"  状态码: {response.status_code}")
            print(f"  响应头: {dict(response.headers)}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"  ✓ JSON响应成功")
                    print(f"  响应数据键: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    if isinstance(data, dict) and 'data' in data:
                        print(f"  数据字段: {list(data['data'].keys()) if isinstance(data['data'], dict) else 'Not a dict'}")
                except json.JSONDecodeError as e:
                    print(f"  ✗ JSON解析失败: {e}")
                    print(f"  原始响应: {response.text[:200]}...")
            else:
                print(f"  ✗ 请求失败")
                print(f"  错误响应: {response.text[:200]}...")
                
        except requests.exceptions.ConnectionError:
            print(f"  ✗ 连接失败 - 服务器可能未启动")
        except requests.exceptions.Timeout:
            print(f"  ✗ 请求超时")
        except Exception as e:
            print(f"  ✗ 请求异常: {e}")

def test_flask_service():
    """测试Flask服务状态"""
    print("\n" + "=" * 50)
    print("3. 测试Flask服务状态")
    print("=" * 50)
    
    base_url = "http://127.0.0.1:5000"
    
    try:
        # 测试根路径
        response = requests.get(base_url, timeout=5)
        print(f"根路径状态码: {response.status_code}")
        
        # 测试健康检查（如果有的话）
        health_endpoints = ["/health", "/status", "/api/health"]
        for endpoint in health_endpoints:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=5)
                if response.status_code == 200:
                    print(f"✓ {endpoint} 可用")
                    break
            except:
                continue
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("✗ Flask服务未启动或无法连接")
        return False
    except Exception as e:
        print(f"✗ Flask服务测试失败: {e}")
        return False

def main():
    """主函数"""
    print(f"开始诊断 /load_detail 接口问题")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 测试数据库
    db_ok = test_database_connection()
    
    # 2. 测试Flask服务
    flask_ok = test_flask_service()
    
    # 3. 测试API接口
    if flask_ok:
        test_load_detail_api()
    else:
        print("\n跳过API测试 - Flask服务不可用")
    
    # 总结
    print("\n" + "=" * 50)
    print("诊断总结")
    print("=" * 50)
    print(f"数据库连接: {'✓ 正常' if db_ok else '✗ 异常'}")
    print(f"Flask服务: {'✓ 正常' if flask_ok else '✗ 异常'}")
    
    if not db_ok:
        print("\n建议:")
        print("- 检查数据库文件是否存在")
        print("- 确认数据库中有 ID=1 的记录")
        print("- 检查数据库连接配置")
    
    if not flask_ok:
        print("\n建议:")
        print("- 启动Flask服务: python app.py")
        print("- 检查端口5000是否被占用")
        print("- 查看Flask启动日志")

if __name__ == "__main__":
    main()
