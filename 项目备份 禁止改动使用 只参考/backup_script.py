# -*- coding: utf-8 -*-
"""备份脚本 - 创建项目备份"""
import shutil
import os
from datetime import datetime

def backup_project():
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 获取父目录
    parent_dir = os.path.dirname(current_dir)
    
    # 创建备份目标目录名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"2.0_backup_tauri_{timestamp}"
    backup_path = os.path.join(parent_dir, backup_name)
    
    print(f"源目录: {current_dir}")
    print(f"备份目录: {backup_path}")
    
    # 排除不需要备份的大文件夹
    exclude_dirs = {'DouYin3.0', 'cache', 'logs', '__pycache__', '.git', 'node_modules'}
    
    def ignore_func(directory, files):
        ignored = []
        for f in files:
            if f in exclude_dirs:
                ignored.append(f)
        return ignored
    
    try:
        shutil.copytree(current_dir, backup_path, ignore=ignore_func)
        print(f"\n✅ 备份成功!")
        print(f"备份位置: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return None

if __name__ == "__main__":
    backup_project()
