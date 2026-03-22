#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PySide6 桌面应用闪烁修复测试脚本
专门测试 QtWebEngine 在桌面应用中的渲染稳定性
"""

import sys
import time
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('desktop_app_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def test_desktop_app_startup():
    """测试桌面应用启动过程"""
    logging.info("🚀 开始测试 PySide6 桌面应用启动...")
    
    try:
        # 导入 GUI 模块
        from src.gui import Gui
        logging.info("✅ GUI 模块导入成功")
        
        # 检查是否有现有的 Flask 应用
        try:
            import app
            flask_app = app.app
            logging.info("✅ Flask 应用获取成功")
        except Exception as e:
            logging.error(f"❌ Flask 应用获取失败: {e}")
            return False
        
        # 创建 GUI 实例（这会启动 PySide6 桌面应用）
        logging.info("🔧 创建 PySide6 桌面应用实例...")
        
        gui = Gui(
            title='抖音袜子发布工具（v4.0）- 闪烁修复测试',
            logo='web/admin/images/logo.png',
            width=1200,
            height=900,
            app=flask_app
        )
        
        logging.info("✅ PySide6 桌面应用实例创建成功")
        
        # 启动应用（这会显示桌面窗口）
        logging.info("🖥️  启动 PySide6 桌面应用窗口...")
        logging.info("📋 请观察以下方面：")
        logging.info("   1. 窗口启动过程是否平滑，无闪烁")
        logging.info("   2. QtWebEngine 渲染是否稳定")
        logging.info("   3. 页面加载是否无花屏现象")
        logging.info("   4. 界面元素显示是否正常")
        
        # 启动应用（这是阻塞调用，会显示桌面窗口）
        exit_code = gui.start()
        
        logging.info(f"🏁 PySide6 桌面应用退出，退出码: {exit_code}")
        return exit_code == 0
        
    except Exception as e:
        logging.error(f"❌ 桌面应用测试失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return False

def main():
    """主函数"""
    print("🔧 PySide6 + QtWebEngine 桌面应用闪烁修复测试")
    print("="*60)
    print("📋 测试说明：")
    print("   - 这将启动真正的 PySide6 桌面应用窗口")
    print("   - 请观察启动过程是否有闪烁、花屏现象")
    print("   - 检查 QtWebEngine 渲染是否稳定")
    print("   - 验证界面元素显示是否正常")
    print("   - 关闭窗口完成测试")
    print("="*60)
    
    # 等待用户确认
    input("按 Enter 键开始测试...")
    
    success = test_desktop_app_startup()
    
    if success:
        print("\n✅ 桌面应用测试完成！")
        print("📝 详细日志已保存到 desktop_app_test.log")
        print("📝 启动调试日志请查看 flicker_debug.log")
        return 0
    else:
        print("\n❌ 桌面应用测试失败！")
        return 1

if __name__ == "__main__":
    sys.exit(main())
