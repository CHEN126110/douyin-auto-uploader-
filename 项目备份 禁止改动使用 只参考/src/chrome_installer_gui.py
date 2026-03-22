"""
Chrome浏览器安装器GUI界面
提供友好的用户界面来下载和安装便携版Chrome
"""
# mypy: ignore-errors
# pyright: reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false
# type: ignore

import sys
import os
from pathlib import Path
from PySide2.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QProgressBar, QTextEdit, 
                               QMessageBox, QFrame)
from PySide2.QtCore import QThread, Signal, Qt
from PySide2.QtGui import QFont, QPixmap

try:
    from src.chrome_manager import ChromeManager
except ImportError:
    ChromeManager = None


class ChromeDownloadThread(QThread):
    """Chrome下载线程"""
    progress_updated = Signal(int)
    status_updated = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, chrome_manager):
        super().__init__()
        self.chrome_manager = chrome_manager
    
    def run(self):
        """执行下载"""
        try:
            self.status_updated.emit("[处理] 开始下载Chrome便携版...")
            
            def progress_callback(progress):
                self.progress_updated.emit(int(progress))
                self.status_updated.emit(f"[下载] 下载进度: {progress:.1f}%")
            
            success = self.chrome_manager.download_chrome(progress_callback)
            
            if success:
                self.status_updated.emit("[成功] Chrome下载完成!")
                self.finished_signal.emit(True, "Chrome安装成功")
            else:
                self.status_updated.emit("[失败] Chrome下载失败")
                self.finished_signal.emit(False, "下载失败,请检查网络连接")
                
        except Exception as e:
            self.status_updated.emit(f"[失败] 下载过程出错: {e}")
            self.finished_signal.emit(False, f"下载错误: {e}")


class ChromeInstallerGUI(QWidget):
    """Chrome安装器主界面"""
    
    def __init__(self):
        super().__init__()
        self.chrome_manager = ChromeManager() if ChromeManager else None
        self.download_thread = None
        self.init_ui()
        self.check_chrome_status()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("Chrome浏览器管理器 - 抖音袜子发布工具")
        self.setFixedSize(500, 400)
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                font-family: "Microsoft YaHei";
            }
            QLabel {
                color: #333;
                font-size: 12px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QTextEdit {
                background-color: #fff;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 5px;
                font-family: "Consolas";
                font-size: 10px;
            }
            QFrame {
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: white;
                margin: 5px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout()
        
        # 标题
        title = QLabel("[网络] Chrome浏览器管理器")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #2196F3; margin: 10px;")
        layout.addWidget(title)
        
        # 状态框
        status_frame = QFrame()
        status_layout = QVBoxLayout(status_frame)
        
        self.status_label = QLabel("[检查] 检测Chrome状态中...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #666;")
        status_layout.addWidget(self.status_label)
        
        self.version_label = QLabel("")
        self.version_label.setStyleSheet("font-size: 11px; color: #888;")
        status_layout.addWidget(self.version_label)
        
        layout.addWidget(status_frame)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.check_btn = QPushButton("[检查] 重新检测")
        self.check_btn.clicked.connect(self.check_chrome_status)
        button_layout.addWidget(self.check_btn)
        
        self.download_btn = QPushButton("[下载] 下载Chrome")
        self.download_btn.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_btn)
        
        layout.addLayout(button_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 日志区域
        log_label = QLabel("[说明] 操作日志:")
        log_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(120)
        layout.addWidget(self.log_text)
        
        # 说明文本
        info_text = QLabel(
            "[提示] 说明:\n"
            "* 工具会自动检测系统是否安装Chrome浏览器\n"
            "* 如未安装,可下载便携版Chrome(约100MB)\n" 
            "* 便携版Chrome不会影响系统现有浏览器\n"
            "* 首次下载可能需要几分钟,请耐心等待"
        )
        info_text.setStyleSheet("font-size: 10px; color: #666; margin: 10px;")
        layout.addWidget(info_text)
        
        self.setLayout(layout)
    
    def log_message(self, message):
        """添加日志消息"""
        self.log_text.append(f"[{self.get_time_str()}] {message}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def get_time_str(self):
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")
    
    def check_chrome_status(self):
        """检查Chrome状态"""
        if not self.chrome_manager:
            self.status_label.setText("[失败] Chrome管理器未可用")
            self.log_message("Chrome管理器模块未找到")
            return
        
        self.log_message("开始检测Chrome状态...")
        
        available, chrome_path = self.chrome_manager.check_chrome_available()
        
        if available:
            self.status_label.setText("[成功] Chrome已可用")
            self.version_label.setText(f"路径: {chrome_path}")
            self.download_btn.setText("[成功] 已安装")
            self.download_btn.setEnabled(False)
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                }
            """)
            
            # 尝试获取版本信息
            version = self.chrome_manager.get_chrome_version(chrome_path)
            if version:
                self.version_label.setText(f"路径: {chrome_path}\n版本: {version}")
            
            self.log_message(f"[成功] 检测到Chrome: {chrome_path}")
        else:
            self.status_label.setText("[失败] 未检测到Chrome")
            self.version_label.setText("需要下载便携版Chrome以确保工具正常运行")
            self.download_btn.setText("[下载] 下载Chrome")
            self.download_btn.setEnabled(True)
            self.download_btn.setStyleSheet("")
            self.log_message("[失败] 未检测到可用的Chrome浏览器")
    
    def start_download(self):
        """开始下载Chrome"""
        if not self.chrome_manager:
            QMessageBox.warning(self, "错误", "Chrome管理器未可用")
            return
        
        # 确认下载
        reply = QMessageBox.question(
            self, "确认下载", 
            "确定要下载便携版Chrome吗?\n\n"
            "* 下载大小: 约100-150MB\n"
            "* 下载时间: 根据网速而定\n"
            "* 安装位置: 工具目录/browser/\n\n"
            "请确保网络连接正常.",
            QMessageBox.Yes | QMessageBox.No  # type: ignore
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 禁用按钮,显示进度条
        self.download_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 启动下载线程
        self.download_thread = ChromeDownloadThread(self.chrome_manager)
        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.status_updated.connect(self.log_message)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.start()
    
    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)
    
    def download_finished(self, success, message):
        """下载完成处理"""
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "下载完成", f"[成功] {message}")
            self.check_chrome_status()  # 重新检测状态
        else:
            QMessageBox.warning(self, "下载失败", f"[失败] {message}")
        
        self.log_message(f"下载完成: {message}")


def show_chrome_installer():
    """显示Chrome安装器GUI"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    installer = ChromeInstallerGUI()
    installer.show()
    
    return installer


if __name__ == "__main__":
    app = QApplication(sys.argv)
    installer = ChromeInstallerGUI()
    installer.show()
    sys.exit(app.exec_())