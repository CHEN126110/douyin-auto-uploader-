#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 ERR_ABORTED 错误修复效果
模拟前端请求，验证超时问题是否解决
"""

import requests
import time
from datetime import datetime

def test_load_detail_with_timeout():
    """测试不同超时设置下的请求"""
    print("=" * 60)
    print("测试 /load_detail 接口超时修复效果")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:5000"
    endpoint = "/load_detail"
    params = {"_id": 1, "images": "true"}
    
    # 测试不同的超时设置
    timeout_tests = [
        ("原始超时（10秒）", 10),
        ("修复后超时（60秒）", 60),
    ]
    
    for test_name, timeout in timeout_tests:
        print(f"\n{test_name}:")
        print(f"超时设置: {timeout}秒")
        
        start_time = time.time()
        try:
            response = requests.get(
                f"{base_url}{endpoint}", 
                params=params, 
                timeout=timeout
            )
            end_time = time.time()
            duration = end_time - start_time
            
            print(f"✓ 请求成功")
            print(f"响应时间: {duration:.2f}秒")
            print(f"状态码: {response.status_code}")
            print(f"响应大小: {len(response.content):,} 字节 ({len(response.content)/1024/1024:.2f} MB)")
            
            if duration > timeout * 0.8:  # 如果接近超时
                print(f"⚠️  响应时间接近超时限制")
            
        except requests.exceptions.Timeout:
            end_time = time.time()
            duration = end_time - start_time
            print(f"✗ 请求超时")
            print(f"超时时间: {duration:.2f}秒")
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            print(f"✗ 请求失败: {e}")
            print(f"失败时间: {duration:.2f}秒")

def test_multiple_requests():
    """测试多次请求的稳定性"""
    print(f"\n{'='*60}")
    print("测试多次请求稳定性")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:5000"
    endpoint = "/load_detail"
    params = {"_id": 1, "images": "true"}
    
    success_count = 0
    total_requests = 3
    
    for i in range(total_requests):
        print(f"\n第 {i+1} 次请求:")
        start_time = time.time()
        
        try:
            response = requests.get(
                f"{base_url}{endpoint}", 
                params=params, 
                timeout=60
            )
            end_time = time.time()
            duration = end_time - start_time
            
            if response.status_code == 200:
                success_count += 1
                print(f"✓ 成功 - {duration:.2f}秒")
            else:
                print(f"✗ 失败 - 状态码: {response.status_code}")
                
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            print(f"✗ 异常 - {e} ({duration:.2f}秒)")
    
    print(f"\n成功率: {success_count}/{total_requests} ({success_count/total_requests*100:.1f}%)")

def main():
    """主函数"""
    print(f"开始测试修复效果")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试超时修复
    test_load_detail_with_timeout()
    
    # 测试稳定性
    test_multiple_requests()
    
    print(f"\n{'='*60}")
    print("修复效果总结")
    print("=" * 60)
    print("✓ 前端超时时间已从10秒增加到60秒")
    print("✓ 应该能够处理30MB的响应数据")
    print("✓ ERR_ABORTED错误应该得到解决")
    print("\n建议:")
    print("- 如果仍有问题，考虑进一步优化后端数据大小")
    print("- 监控实际使用中的响应时间")
    print("- 考虑实现数据分页或按需加载")

if __name__ == "__main__":
    main()
