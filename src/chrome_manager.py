"""
Chrome浏览器自动下载和管理模块
支持自动下载便携版Chrome并配置DrissionPage使用
"""

import os
import zipfile
import requests
import logging
import shutil
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class ChromeManager:
    """Chrome浏览器管理器"""
    
    def __init__(self, app_dir: Optional[str] = None):
        """
        初始化Chrome管理器
        
        Args:
            app_dir: 应用程序目录,默认使用当前目录
        """
        self.app_dir = app_dir or os.path.dirname(os.path.dirname(__file__))
        self.browser_dir = os.path.join(self.app_dir, 'browser')
        self.chrome_exe = os.path.join(self.browser_dir, 'chrome.exe')
        
        # Chrome便携版下载链接(使用开源项目)
        self.chrome_urls = [
            "https://github.com/portapps/ungoogled-chromium-portable/releases/download/v119.0.6045.199-1/ungoogled-chromium-portable-119.0.6045.199-1-win64.7z",
            "https://commondatastorage.googleapis.com/chromium-browser-snapshots/Win_x64/latest/chrome-win.zip",
            "https://dl.google.com/chrome/install/375.126/chrome_installer.exe"
        ]
    
    def check_chrome_available(self) -> Tuple[bool, Optional[str]]:
        """
        检查Chrome是否可用
        
        Returns:
            (是否可用, Chrome路径)
        """
        # 检查内置Chrome
        if os.path.exists(self.chrome_exe):
            return True, self.chrome_exe
        
        # 检查系统Chrome
        system_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        ]
        
        for path in system_paths:
            if os.path.exists(path):
                return True, path
        
        return False, None
    
    def download_chrome(self, progress_callback=None) -> bool:
        """
        下载便携版Chrome
        
        Args:
            progress_callback: 进度回调函数
            
        Returns:
            下载是否成功
        """
        try:
            # 创建浏览器目录
            os.makedirs(self.browser_dir, exist_ok=True)
            
            # 下载Chrome便携版
            for url in self.chrome_urls:
                try:
                    logger.info(f"尝试从 {url} 下载Chrome...")
                    
                    if self._download_and_extract(url, progress_callback):
                        logger.info("Chrome下载完成")
                        return True
                        
                except Exception as e:
                    logger.warning(f"从 {url} 下载失败: {e}")
                    continue
            
            logger.error("所有下载源都失败")
            return False
            
        except Exception as e:
            logger.error(f"下载Chrome失败: {e}")
            return False
    
    def _download_and_extract(self, url: str, progress_callback=None) -> bool:
        """下载并解压Chrome"""
        try:
            # 下载文件
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            # 确定文件类型
            filename = url.split('/')[-1]
            if filename.endswith('.zip'):
                archive_path = os.path.join(self.browser_dir, 'chrome.zip')
            elif filename.endswith('.7z'):
                archive_path = os.path.join(self.browser_dir, 'chrome.7z')
            else:
                archive_path = os.path.join(self.browser_dir, 'chrome_installer.exe')
            
            # 下载文件
            with open(archive_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback and total_size > 0:
                            progress = (downloaded / total_size) * 100
                            progress_callback(progress)
            
            # 解压文件
            if archive_path.endswith('.zip'):
                return self._extract_zip(archive_path)
            elif archive_path.endswith('.7z'):
                return self._extract_7z(archive_path)
            else:
                # 对于exe安装程序,我们需要不同的处理方式
                return self._handle_installer(archive_path)
                
        except Exception as e:
            logger.error(f"下载和解压失败: {e}")
            return False
    
    def _extract_zip(self, zip_path: str) -> bool:
        """解压ZIP文件"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.browser_dir)
            
            # 查找chrome.exe
            for root, dirs, files in os.walk(self.browser_dir):
                for file in files:
                    if file.lower() == 'chrome.exe':
                        chrome_path = os.path.join(root, file)
                        # 如果不在预期位置,移动到正确位置
                        if chrome_path != self.chrome_exe:
                            shutil.move(chrome_path, self.chrome_exe)
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"解压ZIP失败: {e}")
            return False
    
    def _extract_7z(self, archive_path: str) -> bool:
        """解压7z文件(需要py7zr库)"""
        try:
            import py7zr  # type: ignore
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                z.extractall(self.browser_dir)
            
            # 查找chrome.exe
            for root, dirs, files in os.walk(self.browser_dir):
                for file in files:
                    if file.lower() == 'chrome.exe':
                        chrome_path = os.path.join(root, file)
                        if chrome_path != self.chrome_exe:
                            shutil.move(chrome_path, self.chrome_exe)
                        return True
            
            return False
            
        except ImportError:
            logger.error("需要安装py7zr库来解压7z文件")
            return False
        except Exception as e:
            logger.error(f"解压7z失败: {e}")
            return False
    
    def _handle_installer(self, installer_path: str) -> bool:
        """处理安装程序(这里简化处理)"""
        logger.warning("安装程序类型暂不支持自动安装")
        return False
    
    def setup_chrome_for_drissionpage(self) -> Optional[str]:
        """
        为DrissionPage设置Chrome
        
        Returns:
            Chrome路径,如果设置失败返回None
        """
        # 检查Chrome是否可用
        available, chrome_path = self.check_chrome_available()
        
        if available:
            logger.info(f"Chrome已可用: {chrome_path}")
            return chrome_path
        
        # 尝试下载Chrome
        logger.info("Chrome未安装,开始下载...")
        if self.download_chrome():
            return self.chrome_exe
        
        logger.error("Chrome设置失败")
        return None
    
    def get_chrome_version(self, chrome_path: str) -> Optional[str]:
        """获取Chrome版本信息"""
        try:
            import subprocess
            result = subprocess.run([chrome_path, '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"获取Chrome版本失败: {e}")
        
        return None


# 全局Chrome管理器实例
chrome_manager = ChromeManager()


def ensure_chrome_available() -> Optional[str]:
    """
    确保Chrome可用,如果不可用则自动下载
    
    Returns:
        Chrome路径,如果失败返回None
    """
    return chrome_manager.setup_chrome_for_drissionpage()


def get_chrome_path() -> Optional[str]:
    """
    获取Chrome路径
    
    Returns:
        Chrome路径,如果不可用返回None
    """
    available, chrome_path = chrome_manager.check_chrome_available()
    return chrome_path if available else None