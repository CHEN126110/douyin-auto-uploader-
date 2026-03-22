#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析 /load_detail 接口响应大小的问题
检查响应数据的具体内容和大小
"""

import sys
import os
import requests
import json
from datetime import datetime

# 添加项目路径到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def analyze_response_size():
    """分析响应大小"""
    print("=" * 60)
    print("分析 /load_detail 接口响应大小")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:5000"
    endpoint = "/load_detail"
    params = {"_id": 1, "images": "true"}
    
    try:
        print(f"请求URL: {base_url}{endpoint}")
        print(f"参数: {params}")
        
        response = requests.get(f"{base_url}{endpoint}", params=params, timeout=30)
        
        print(f"\n响应状态码: {response.status_code}")
        print(f"响应大小: {len(response.content):,} 字节 ({len(response.content)/1024/1024:.2f} MB)")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"\nJSON结构分析:")
                print(f"- 顶级键: {list(data.keys())}")
                
                if 'data' in data and isinstance(data['data'], dict):
                    data_content = data['data']
                    print(f"- data字段键: {list(data_content.keys())}")
                    
                    # 分析每个字段的大小
                    for key, value in data_content.items():
                        if isinstance(value, str):
                            size = len(value.encode('utf-8'))
                            print(f"  - {key}: {size:,} 字节 ({size/1024:.1f} KB)")
                            if size > 1024 * 1024:  # 大于1MB的字段
                                print(f"    ⚠️  {key} 字段过大！")
                                # 显示前100个字符
                                preview = value[:100] + "..." if len(value) > 100 else value
                                print(f"    预览: {preview}")
                        elif isinstance(value, (list, dict)):
                            json_str = json.dumps(value, ensure_ascii=False)
                            size = len(json_str.encode('utf-8'))
                            print(f"  - {key}: {size:,} 字节 ({size/1024:.1f} KB)")
                            if size > 1024 * 1024:  # 大于1MB的字段
                                print(f"    ⚠️  {key} 字段过大！")
                        else:
                            print(f"  - {key}: {type(value).__name__}")
                
                # 检查是否有图片数据
                if 'data' in data and 'content' in data['data']:
                    content = data['data']['content']
                    if isinstance(content, str):
                        try:
                            content_data = json.loads(content)
                            if isinstance(content_data, dict):
                                print(f"\ncontent字段JSON分析:")
                                for key, value in content_data.items():
                                    if isinstance(value, str) and ('data:image' in value or 'base64' in value):
                                        print(f"  - {key}: 可能包含base64图片数据")
                                    elif isinstance(value, list):
                                        print(f"  - {key}: 列表，长度 {len(value)}")
                                        # 检查列表中是否有图片
                                        for i, item in enumerate(value[:3]):  # 只检查前3个
                                            if isinstance(item, dict):
                                                for sub_key, sub_value in item.items():
                                                    if isinstance(sub_value, str) and ('data:image' in sub_value or len(sub_value) > 10000):
                                                        print(f"    - [{i}].{sub_key}: 可能包含大量数据")
                        except json.JSONDecodeError:
                            print("  content字段不是有效的JSON")
                
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {e}")
        
        return response
        
    except Exception as e:
        print(f"请求失败: {e}")
        return None

def suggest_solutions():
    """提供解决方案建议"""
    print("\n" + "=" * 60)
    print("解决方案建议")
    print("=" * 60)
    
    print("问题分析:")
    print("- 响应数据过大（约30MB）")
    print("- 前端AJAX超时设置为10秒")
    print("- 大数据量在10秒内传输可能超时")
    print("- 浏览器取消请求导致 net::ERR_ABORTED")
    
    print("\n解决方案:")
    print("1. 增加前端超时时间（临时解决）")
    print("2. 优化后端响应数据大小（推荐）")
    print("   - 移除或压缩base64图片数据")
    print("   - 实现分页或按需加载")
    print("   - 使用图片URL替代base64数据")
    print("3. 实现数据压缩")
    print("4. 添加进度显示和取消机制")

def main():
    """主函数"""
    print(f"开始分析响应大小问题")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    response = analyze_response_size()
    suggest_solutions()

if __name__ == "__main__":
    main()

def analyze_response_size():
    """分析响应大小"""
    print("=" * 60)
    print("分析 /load_detail 接口响应大小")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:5000"
    endpoint = "/load_detail"
    params = {"_id": 1, "images": "true"}
    
    try:
        print(f"请求URL: {base_url}{endpoint}")
        print(f"参数: {params}")
        
        response = requests.get(f"{base_url}{endpoint}", params=params, timeout=30)
        
        print(f"\n响应状态码: {response.status_code}")
        print(f"响应大小: {len(response.content):,} 字节 ({len(response.content)/1024/1024:.2f} MB)")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"\nJSON结构分析:")
                print(f"- 顶级键: {list(data.keys())}")
                
                if 'data' in data and isinstance(data['data'], dict):
                    data_content = data['data']
                    print(f"- data字段键: {list(data_content.keys())}")
                    
                    # 分析每个字段的大小
                    for key, value in data_content.items():
                        if isinstance(value, str):
                            size = len(value.encode('utf-8'))
                            print(f"  - {key}: {size:,} 字节 ({size/1024:.1f} KB)")
                            if size > 1024 * 1024:  # 大于1MB的字段
                                print(f"    ⚠️  {key} 字段过大！")
                                # 显示前100个字符
                                preview = value[:100] + "..." if len(value) > 100 else value
                                print(f"    预览: {preview}")
                        elif isinstance(value, (list, dict)):
                            json_str = json.dumps(value, ensure_ascii=False)
                            size = len(json_str.encode('utf-8'))
                            print(f"  - {key}: {size:,} 字节 ({size/1024:.1f} KB)")
                            if size > 1024 * 1024:  # 大于1MB的字段
                                print(f"    ⚠️  {key} 字段过大！")
                        else:
                            print(f"  - {key}: {type(value).__name__}")
                
                # 检查是否有图片数据
                if 'data' in data and 'content' in data['data']:
                    content = data['data']['content']
                    if isinstance(content, str):
                        try:
                            content_data = json.loads(content)
                            if isinstance(content_data, dict):
                                print(f"\ncontent字段JSON分析:")
                                for key, value in content_data.items():
                                    if isinstance(value, str) and ('data:image' in value or 'base64' in value):
                                        print(f"  - {key}: 可能包含base64图片数据")
                                    elif isinstance(value, list):
                                        print(f"  - {key}: 列表，长度 {len(value)}")
                                        # 检查列表中是否有图片
                                        for i, item in enumerate(value[:3]):  # 只检查前3个
                                            if isinstance(item, dict):
                                                for sub_key, sub_value in item.items():
                                                    if isinstance(sub_value, str) and ('data:image' in sub_value or len(sub_value) > 10000):
                                                        print(f"    - [{i}].{sub_key}: 可能包含大量数据")
                        except json.JSONDecodeError:
                            print("  content字段不是有效的JSON")
                
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {e}")
        
        return response
        
    except Exception as e:
        print(f"请求失败: {e}")
        return None

def suggest_solutions():
    """提供解决方案建议"""
    print("\n" + "=" * 60)
    print("解决方案建议")
    print("=" * 60)
    
    print("问题分析:")
    print("- 响应数据过大（约30MB）")
    print("- 前端AJAX超时设置为10秒")
    print("- 大数据量在10秒内传输可能超时")
    print("- 浏览器取消请求导致 net::ERR_ABORTED")
    
    print("\n解决方案:")
    print("1. 增加前端超时时间（临时解决）")
    print("2. 优化后端响应数据大小（推荐）")
    print("   - 移除或压缩base64图片数据")
    print("   - 实现分页或按需加载")
    print("   - 使用图片URL替代base64数据")
    print("3. 实现数据压缩")
    print("4. 添加进度显示和取消机制")

def main():
    """主函数"""
    print(f"开始分析响应大小问题")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    response = analyze_response_size()
    suggest_solutions()

if __name__ == "__main__":
    main()
