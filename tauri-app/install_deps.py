# -*- coding: utf-8 -*-
"""安装Tauri项目依赖"""
import subprocess
import os
import sys

def main():
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print(f"📁 工作目录: {script_dir}")
    print("📦 开始安装npm依赖...")
    
    # 运行npm install
    result = subprocess.run(
        ["npm", "install"],
        cwd=script_dir,
        shell=True,
        capture_output=False
    )
    
    if result.returncode == 0:
        print("\n✅ npm依赖安装成功!")
    else:
        print(f"\n❌ npm安装失败，退出码: {result.returncode}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
