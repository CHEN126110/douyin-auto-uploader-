import json
import logging
import os
import os.path
import sys
import ctypes
import traceback
import win32api
import win32con
import time as time_module
from typing import Optional, TYPE_CHECKING
from natsort import natsorted
from PySide6.QtCore import QUrl, Qt, QMutex, QMutexLocker, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QFont, QIcon, QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile, QWebEnginePage
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

# 修复导入路径
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import time, get_nick
from src.orm import Record, database
from src.thread import Thread

# 避免循环导入，使用条件导入
if TYPE_CHECKING:
    from DrissionPage import ChromiumPage


def list_files(startpath) -> list:
    """list_files函数。
    
    :param startpath: 起始路径
    :return: 文件路径列表
    """
    result = []
    for (root, _, files) in os.walk(startpath):
        for filename in natsorted(files):
            result.append(os.path.join(root, filename))
    return result


def list_files_2(startpath) -> list:
    """list_files_2函数。
    
    :param startpath: 起始路径
    :return: 文件路径列表
    """
    dir_list = []
    temp_list = []
    for dir_path in natsorted(os.listdir(startpath)):
        if ('自选备注' in dir_path):
            temp_list.append(os.path.join(startpath, dir_path))
            continue
        dir_list.append(os.path.join(startpath, dir_path))
        dir_list.extend(temp_list)
        temp_list = []
    file_list = []
    for dir_path in dir_list:
        for file_name in natsorted(os.listdir(dir_path)):
            file_list.append(os.path.join(dir_path, file_name))
    return file_list


class ConsoleLoggingWebEnginePage(QWebEnginePage):
    """自定义WebEnginePage - 捕获JavaScript console消息到Python日志。"""
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """捕获JavaScript console消息并输出到Python日志。
        
        :param level: 日志级别
        :param message: 消息内容
        :param lineNumber: 行号
        :param sourceID: 源文件ID
        """
        # 格式化日志级别
        level_map = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "INFO",
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "ERROR"
        }
        level_str = level_map.get(level, "INFO")
        
        # 简化sourceID显示
        source_name = sourceID.split('/')[-1] if sourceID else "unknown"
        
        # 输出到Python日志
        log_msg = f"[JS-{level_str}] {message}"
        if lineNumber > 0:
            log_msg += f" (Line {lineNumber})"
        
        # 根据级别选择合适的日志方法
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logging.error(log_msg)
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            logging.warning(log_msg)
        else:
            logging.info(log_msg)


class NoContextMenuWebEngineView(QWebEngineView):
    """NoContextMenuWebEngineView类 - 专业级反闪烁WebEngine视图。"""
    
    # 添加信号用于状态通知
    loadingStateChanged = Signal(bool)  # 加载状态变化信号
    # 🔧 拖拽信号 - 将拖拽事件传递给父窗口
    fileDropped = Signal(list)  # 文件拖放信号

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化WebEngineView - 专业级反闪烁配置。
        
        :param parent: 父窗口
        """
        super().__init__(parent)
        
        # 🔧 启用拖拽接受
        self.setAcceptDrops(True)
        
        # 🔧 安装事件过滤器以确保拖拽事件能被正确处理
        self.installEventFilter(self)
        
        # 🔧 延迟安装到focusProxy（QWebEngineView内部渲染widget）
        QTimer.singleShot(100, self._install_focus_proxy_filter)
        
        # 🔧 设置自定义Page以捕获JavaScript console消息
        custom_page = ConsoleLoggingWebEnginePage(self)
        self.setPage(custom_page)
        logging.info("✅ 已启用JavaScript console日志捕获")
        
        # 初始化状态
        self._is_loading = False
        self._load_timer = QTimer()
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._on_load_timeout)
        
        try:
            # 🔧 配置WebEngine Profile - 关键反闪烁设置
            profile = QWebEngineProfile.defaultProfile()
            
            # 🚀 启用缓存以提升性能
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            profile.setHttpCacheMaximumSize(100 * 1024 * 1024)  # 100MB缓存
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            
            # 获取页面和设置（现在是自定义的Page）
            page = self.page()
            settings = page.settings()
            
            # 🔧 核心反闪烁设置
            # 禁用可能导致闪烁的功能
            settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            
            # 🔧 启用硬件加速与滚动动画，提升稳定性与流畅度
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)  # 禁用错误页面
            settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)  # 保持图片加载
            
            # 🔧 字体和显示设置
            settings.setFontFamily(QWebEngineSettings.FontFamily.StandardFont, "Microsoft YaHei")
            settings.setFontFamily(QWebEngineSettings.FontFamily.SansSerifFont, "Microsoft YaHei")
            settings.setFontSize(QWebEngineSettings.FontSize.DefaultFontSize, 14)
            settings.setFontSize(QWebEngineSettings.FontSize.MinimumFontSize, 12)
            
            # 🔧 固定缩放比例，避免DPI相关闪烁
            page.setZoomFactor(1.0)
            
            # 🔧 连接加载信号
            page.loadStarted.connect(self._on_load_started)
            page.loadFinished.connect(self._on_load_finished)
            page.loadProgress.connect(self._on_load_progress)
            
            
            # 🔧 优化插件和扩展设置
            settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, False)
            
            # 🔧 优化字体渲染设置
            settings.setAttribute(QWebEngineSettings.WebAttribute.ForceDarkMode, False)
            
            logging.info("WebEngine基础配置完成：插件已禁用，字体渲染已优化")
                
            # 🔧 增强Chromium参数 - 彻底修复棋盘格花屏问题
            chromium_args = [
                # === 核心稳定性设置 ===
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",  # 禁用软件光栅化，强制GPU

                # === 禁用不必要的功能 ===
                "--disable-extensions",
                "--disable-plugins",
                "--disable-translate",
                "--disable-sync",
                "--no-default-browser-check",
                "--no-first-run",

                # === GPU 与渲染路径（修复棋盘格花屏） ===
                "--use-angle=d3d11",
                "--enable-features=UseSkiaRenderer,Vulkan",
                "--disable-zero-copy",  # ✅ 禁用零拷贝，避免缓冲区竞争
                "--enable-begin-frame-scheduling",  # ✅ 确保帧调度正确
                "--disable-partial-raster",  # ✅ 禁用部分光栅化，确保完整渲染
                "--disable-checker-imaging",  # ✅ 禁用棋盘格图像，防止加载时闪烁
                
                # === 合成器优化（关键修复棋盘格） ===
                "--disable-composited-antialiasing",  # ✅ 禁用合成抗锯齿
                "--disable-gpu-compositing",  # ✅ 禁用GPU合成（如果问题严重可启用）
                "--num-raster-threads=4",  # ✅ 增加光栅化线程数
                "--enable-gpu-rasterization",  # ✅ 启用GPU光栅化
                "--enable-oop-rasterization",  # ✅ 启用进程外光栅化
                
                # === 缓冲区和帧同步（修复棋盘格） ===
                "--disable-frame-rate-limit",  # ✅ 禁用帧率限制
                "--disable-gpu-vsync",  # ✅ 禁用垂直同步
                "--max-gum-fps=60",  # ✅ 限制最大帧率
                
                # === 背景渲染优化 ===
                "--force-color-profile=srgb",
                "--disable-lcd-text",  # ✅ 禁用LCD文本渲染优化
                "--disable-font-subpixel-positioning",  # ✅ 禁用子像素定位

                # === 启动和后台优化 ===
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-ipc-flooding-protection",  # ✅ 禁用IPC洪泛保护
            ]
            
            # 设置Chromium启动参数
            chromium_flags = " ".join(chromium_args)
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_flags
            
            # 记录优化配置
            logging.info(f"Chromium参数已优化 - 应用了 {len(chromium_args)} 个稳定性参数")
            logging.info("配置重点:")
            logging.info("   ✅ 启用GPU加速并明确ANGLE路径")
            logging.info("   ✅ 统一渲染策略 (Skia/OOP Rasterization)")
            logging.info("   ✅ 优化后台行为以减少干扰")
            
            # 7. 添加动态操作事件过滤器
            self.installEventFilter(self)
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            
            # 8. 设置渲染优化定时器
            self._render_timer = QTimer()
            self._render_timer.setSingleShot(True)
            self._render_timer.timeout.connect(self._optimize_rendering)
            
            # 9. 初始化动态操作状态跟踪
            self._is_dragging = False
            self._is_resizing = False
            self._last_operation_time = 0
            
            logging.info("动态操作闪烁修复配置完成")
            logging.info("WebEngine反闪烁配置完成")
                
        except Exception as e:
            logging.error(f"WebEngine反闪烁配置失败: {e}")
            # 即使配置失败，也不应该阻止应用程序启动

    def _on_load_started(self) -> None:
        """页面开始加载时的处理"""
        self._is_loading = True
        self.loadingStateChanged.emit(True)
        # 设置加载超时保护
        self._load_timer.start(10000)  # 10秒超时
        
        # 🔧 使用专业调试系统
        debug_logger.log_webengine_event("页面开始加载", "启动加载超时保护")
        perf_monitor.start_timing("页面加载")

    def _on_load_finished(self, success: bool) -> None:
        """页面加载完成时的处理 - 增强版棋盘格修复"""
        self._is_loading = False
        self._load_timer.stop()
        self.loadingStateChanged.emit(False)
        
        # 🔧 记录加载性能和结果
        load_duration = perf_monitor.end_timing("页面加载")
        
        if success:
            debug_logger.log_webengine_event("页面加载成功", f"耗时: {load_duration:.3f}秒")
            # 🔧 页面加载完成后注入渲染稳定化脚本
            self._inject_render_stabilization()
        else:
            debug_logger.log_error("页面加载失败", f"耗时: {load_duration:.3f}秒")

    def _inject_render_stabilization(self) -> None:
        """注入渲染稳定化脚本 - 修复棋盘格花屏和拖拽功能"""
        stabilization_script = """
        (function() {
            // 标记为QWebEngine环境
            document.body.classList.add('qwebengine');
            
            // 🔧 禁用HTML默认拖拽行为，让事件传播到Qt层面处理
            document.addEventListener('dragover', function(e) {
                e.preventDefault();
                e.stopPropagation();
            }, true);
            
            document.addEventListener('drop', function(e) {
                e.preventDefault();
                e.stopPropagation();
            }, true);
            
            // 禁用所有元素的draggable属性
            document.querySelectorAll('[draggable]').forEach(function(el) {
                el.setAttribute('draggable', 'false');
            });
            
            console.log('✅ HTML拖拽行为已禁用，拖拽事件将由Qt处理');
            
            // 强制重绘以消除棋盘格
            function forceRepaint() {
                document.body.style.display = 'none';
                document.body.offsetHeight; // 触发重排
                document.body.style.display = '';
            }
            
            // 延迟执行重绘
            setTimeout(forceRepaint, 50);
            setTimeout(forceRepaint, 200);
            
            // 禁用所有CSS动画以防止棋盘格
            var style = document.createElement('style');
            style.id = 'qwebengine-stabilization';
            style.textContent = `
                /* QtWebEngine渲染稳定化 */
                *, *::before, *::after {
                    animation-play-state: paused !important;
                }
                
                /* 1秒后恢复必要动画 */
                .qwebengine-animations-ready *, 
                .qwebengine-animations-ready *::before, 
                .qwebengine-animations-ready *::after {
                    animation-play-state: running !important;
                }
            `;
            document.head.appendChild(style);
            
            // 1秒后恢复动画（此时渲染应该已稳定）
            setTimeout(function() {
                document.body.classList.add('qwebengine-animations-ready');
            }, 1000);
            
            // 监听窗口大小变化，触发重绘
            var resizeTimeout;
            window.addEventListener('resize', function() {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(forceRepaint, 100);
            });
            
            console.log('✅ QWebEngine渲染稳定化脚本已注入');
        })();
        """
        try:
            self.page().runJavaScript(stabilization_script)
            logging.info("✅ 渲染稳定化脚本已注入")
        except Exception as e:
            logging.warning(f"渲染稳定化脚本注入失败: {e}")

    def _on_load_progress(self, progress: int) -> None:
        """页面加载进度处理"""
        # 🔧 只记录关键进度节点，避免日志过多
        if progress in [25, 50, 75, 100]:
            debug_logger.log_webengine_event("加载进度", f"{progress}%")

    def _on_load_timeout(self) -> None:
        """加载超时处理"""
        self._is_loading = False
        self.loadingStateChanged.emit(False)
        
        # 🔧 记录超时错误
        perf_monitor.end_timing("页面加载")
        debug_logger.log_error("页面加载超时", "10秒超时限制")

    def is_loading(self) -> bool:
        """检查是否正在加载"""
        return self._is_loading

    def dragEnterEvent(self, event) -> None:
        """处理拖拽进入事件，传递给父窗口。
        
        :param event: 拖拽进入事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event) -> None:
        """处理拖拽移动事件。
        
        :param event: 拖拽移动事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event) -> None:
        """处理拖放事件，将文件列表通过信号传递给父窗口。
        
        :param event: 拖放事件
        """
        urls = event.mimeData().urls()
        if urls:
            file_paths = [url.toLocalFile() for url in urls]
            logging.info(f"🔧 WebView接收到拖放文件: {file_paths}")
            # 发送信号给父窗口处理
            self.fileDropped.emit(file_paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """完全禁用Qt默认右键菜单，让JavaScript接管。
        
        :param event: 上下文菜单事件
        """
        # ✅ 彻底修复：不调用super()，避免显示Qt的默认菜单
        # 接受事件但不处理，让事件传递到网页JavaScript
        event.accept()
        # 注意：不调用pass，因为我们要accept事件

    def eventFilter(self, obj, event):
        try:
            from PySide6.QtCore import QEvent
            event_type = event.type()
            
            # 🔧 处理所有对象的拖拽事件（包括self和focusProxy）
            if event_type == QEvent.Type.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    logging.info("📂 DragEnter事件已接受")
                    return True  # 已处理
                
            if event_type == QEvent.Type.DragMove:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True  # 已处理
            
            if event_type == QEvent.Type.Drop:
                urls = event.mimeData().urls()
                if urls:
                    file_paths = [url.toLocalFile() for url in urls]
                    logging.info(f"📂 Drop事件，文件: {file_paths}")
                    self.fileDropped.emit(file_paths)
                    event.acceptProposedAction()
                    return True  # 已处理
            
            # 以下只处理self对象的事件
            if obj == self:
                # 🔍 调试：记录所有鼠标相关事件
                if event_type in (
                    QEvent.Type.ContextMenu,
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick
                ):
                    try:
                        button = event.button() if hasattr(event, 'button') else 'N/A'
                        pos = f"({event.pos().x()}, {event.pos().y()})" if hasattr(event, 'pos') else 'N/A'
                        logging.info(f"🖱️ Qt事件: {event_type.name}, 按钮: {button}, 位置: {pos}")
                    except:
                        logging.info(f"🖱️ Qt事件: {event_type.name}")
                
                # ✅ 特殊处理：ContextMenu事件不拦截，让它传递到网页
                if event_type == QEvent.Type.ContextMenu:
                    logging.info("✅ ContextMenu事件，允许传播到网页")
                    return False  # False表示继续传播
                
                # ✅ 鼠标右键事件也不拦截
                if event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                    try:
                        from PySide6.QtCore import Qt
                        if hasattr(event, 'button') and event.button() == Qt.MouseButton.RightButton:
                            logging.info(f"✅ 右键{event_type.name}事件，允许传播到网页")
                            return False  # 让右键事件传播
                    except:
                        pass
        except Exception as e:
            logging.warning(f"事件过滤器处理异常: {e}")
        return super().eventFilter(obj, event)
    
    def _install_focus_proxy_filter(self):
        """在focusProxy上安装事件过滤器以捕获拖拽事件"""
        try:
            focus_proxy = self.focusProxy()
            if focus_proxy:
                focus_proxy.setAcceptDrops(True)
                focus_proxy.installEventFilter(self)
                logging.info("✅ 已在focusProxy上安装拖拽事件过滤器")
            else:
                # 如果focusProxy还不存在，稍后重试
                QTimer.singleShot(200, self._install_focus_proxy_filter)
        except Exception as e:
            logging.warning(f"安装focusProxy过滤器失败: {e}")
    
    def _optimize_for_operation(self):
        try:
            self._optimization_active = False
        except Exception as e:
            logging.error(f"渲染优化失败: {e}")
            
    def _restore_normal_rendering(self):
        try:
            self._optimization_active = False
            self._resize_optimization_active = False
            self._is_dragging = False
            self._is_resizing = False
        except Exception as e:
            logging.error(f"渲染恢复失败: {e}")
            
    def _optimize_rendering(self):
        """定时器触发的渲染优化恢复（保持向后兼容）"""
        self._restore_normal_rendering()



class MainWindow(QMainWindow):
    """MainWindow类 - 专业级反闪烁主窗口。"""
    
    # 添加信号用于线程安全的GUI操作
    toggle_label_signal = Signal(bool)

    def __init__(self, port) -> None:
        """__init__函数 - 专业级反闪烁初始化。
        
        :param port: 端口号
        """
        super().__init__()
        self.port = port
        
        # 🔧 设置正确的窗口标志，确保标题栏按钮正确显示
        self.setWindowFlags(
            Qt.WindowType.Window |                    # 标准窗口
            Qt.WindowType.WindowTitleHint |           # 显示标题栏
            Qt.WindowType.WindowSystemMenuHint |      # 显示系统菜单
            Qt.WindowType.WindowMinimizeButtonHint |  # 显示最小化按钮
            Qt.WindowType.WindowMaximizeButtonHint |  # 显示最大化按钮
            Qt.WindowType.WindowCloseButtonHint       # 显示关闭按钮
        )
        
        # 🔧 强制刷新窗口标志以确保按钮正确显示
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        
        # 🔧 设置窗口属性，确保正确的标题栏行为
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # 🔧 强制使用原生标题栏，避免自定义样式影响
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, False)
        
        # 🔧 确保窗口正确显示在任务栏
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        
        # 🔧 增强GUI状态保护
        self._gui_mutex = QMutex()
        self._is_updating = False
        self._startup_complete = False
        
        # 🔧 创建WebView - 专业级反闪烁配置
        self.webview = NoContextMenuWebEngineView()
        
        # 🔧 连接WebView加载状态信号
        self.webview.loadingStateChanged.connect(self._on_webview_loading_changed)
        
        # 🔧 连接WebView拖放信号 - 修复拖拽导入功能
        self.webview.fileDropped.connect(self._handle_file_drop)
        
        # 🔧 统一背景色为纯白，避免阶段性切换造成闪屏
        self.webview.setStyleSheet("QWebEngineView { background-color: #ffffff; }")
        
        self.setCentralWidget(self.webview)
        
        # 🔧 创建启动延迟定时器
        self._startup_timer = QTimer()
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._complete_startup)
        
        # 🔧 创建拖拽区域标签
        self.label = QLabel(self)
        self.label.setText('请将待处理文件夹拖入此处')
        self.label.setGeometry(20, 10, 420, 110)
        self.label.setAlignment(Qt.AlignCenter)  # type: ignore
        
        # 🔧 设置字体 - 确保字体正确显示
        font = QFont()
        font.setPointSize(13)
        font.setWeight(QFont.Weight.Bold)
        font.setFamily("Microsoft YaHei UI")
        # 移除可能影响字体渲染的设置
        self.label.setFont(font)
        
        # 🔧 恢复原始样式表设置，确保边框和字体正确显示
        self.label.setStyleSheet('''
            QLabel {
                border-radius: 16px;
                color: #333;
                background-color: #ffffff;
                border: 2px solid rgba(102, 126, 234, 0.3);
                padding: 20px;
                font-weight: bold;
                letter-spacing: 1px;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif !important;
                font-size: 13pt !important;
            }
            QLabel:hover {
                background-color: #ffffff;
                border: 2px solid rgba(102, 126, 234, 0.5);
                color: #667eea;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif !important;
                font-size: 13pt !important;
            }
        ''')
        
        self.setAcceptDrops(True)
        
        # 🔧 精确的窗口样式，完全避免影响标题栏
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            /* 移除所有可能影响标题栏的样式 */
        """)

        # 设置窗口居中
        self.center_window()
        
        # 🔧 连接信号到槽函数，确保GUI操作在主线程中执行
        self.toggle_label_signal.connect(self._on_toggle_label)
        
        # 🔧 强制刷新窗口以确保标题栏按钮正确显示
        self._refresh_title_bar()
    
    def _refresh_title_bar(self) -> None:
        """强制刷新标题栏以确保按钮正确显示"""
        try:
            # 临时隐藏再显示窗口以强制刷新标题栏
            current_flags = self.windowFlags()
            self.setWindowFlags(current_flags)
            
            # 确保窗口按钮可见
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
            
            # 强制更新窗口
            self.update()
            
        except Exception as e:
            logging.error(f"刷新标题栏失败: {e}")
    
    def _on_webview_loading_changed(self, is_loading: bool) -> None:
        """优化的WebView加载状态处理"""
        if is_loading:
            debug_logger.log_startup_phase("WebView开始加载")
            perf_monitor.start_timing("WebView渲染")
        else:
            debug_logger.log_startup_phase("WebView加载完成")
            perf_monitor.end_timing("WebView渲染")
            
            if not self._startup_complete:
                # 减少延迟时间，提高响应性
                self._startup_timer.start(50)  # 从200ms减少到50ms
                debug_logger.log_startup_phase("启动延迟处理", "50ms延迟确保渲染稳定")

    def _complete_startup(self) -> None:
        """完成启动过程"""
        try:
            self._startup_complete = True
            
            # 背景色保持不变
            
            debug_logger.log_startup_phase("应用启动完成", "渲染稳定，可以正常使用")
            
            # 记录启动总时间
            total_startup_time = perf_monitor.end_timing("应用总启动时间")
            debug_logger.log_performance("应用完整启动", total_startup_time)
            
            # 确保窗口完全可见
            self.show()
            self.raise_()
            self.activateWindow()
            
        except Exception as e:
            logging.error(f"启动完成处理错误: {e}")

    def start_progressive_loading(self, url: str, retry_count: int = 0) -> None:
        """优化的渐进式页面加载
        
        Args:
            url: 要加载的URL
            retry_count: 重试次数
        """
        logging.info(f"开始渐进式加载: {url} (重试次数: {retry_count})")
        
        # 限制最大重试次数
        max_retries = 3
        if retry_count >= max_retries:
            logging.warning(f"达到最大重试次数({max_retries})，直接加载页面")
            self.load_url(url)
            return
        
        def delayed_load():
            try:
                # 检查服务是否可用
                import urllib.request
                import urllib.error
                
                try:
                    # 减少超时时间，提高响应性
                    urllib.request.urlopen(url, timeout=1)
                    logging.info("服务连接测试成功，开始加载页面")
                    self.load_url(url)
                except urllib.error.URLError:
                    logging.warning(f"服务暂未就绪，第{retry_count + 1}次重试")
                    # 递减延迟时间，提高响应性
                    retry_delay = max(300, 1000 - retry_count * 200)  # 300-1000ms
                    QTimer.singleShot(retry_delay, lambda: self.start_progressive_loading(url, retry_count + 1))
                    
            except Exception as e:
                logging.error(f"渐进式加载失败: {e}")
                # 降级到直接加载
                self.load_url(url)
        
        # 首次加载时给WebEngine初始化时间，重试时立即执行
        initial_delay = 100 if retry_count == 0 else 0
        QTimer.singleShot(initial_delay, delayed_load)
    
    def _on_toggle_label(self, show: bool) -> None:
        """槽函数：在主线程中执行标签显示/隐藏操作
        
        Args:
            show: True显示，False隐藏
        """
        try:
            with QMutexLocker(self._gui_mutex):
                if self._is_updating:
                    return  # 正在更新中，跳过操作
                
                self._is_updating = True
                try:
                    if show:
                        self.label.show()
                    else:
                        self.label.hide()
                finally:
                    self._is_updating = False
        except Exception as e:
            error_msg = f"GUI标签操作失败: {e}"
            logging.error(error_msg)

    def safe_toggle_label(self, show: bool) -> bool:
        """线程安全的标签显示/隐藏操作
        
        Args:
            show: True显示，False隐藏
            
        Returns:
            bool: 操作是否成功
        """
        try:
            # 使用信号发射，确保GUI操作在主线程中执行
            self.toggle_label_signal.emit(show)
            return True
        except Exception as e:
            error_msg = f"GUI标签操作失败: {e}"
            logging.error(error_msg)
            return False

    def center_window(self):
        """将窗口移动到屏幕中心"""
        # 获取屏幕尺寸
        screen = QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        screen_center = screen_geometry.center()

        # 获取窗口尺寸
        window_size = self.size()

        # 计算窗口左上角的坐标
        x = screen_center.x() - window_size.width() // 2
        y = screen_center.y() - window_size.height() // 2

        # 移动窗口到计算出的坐标
        self.move(x, y)

    def dragEnterEvent(self, event) -> None:
        """dragEnterEvent函数。
        
        :param event: 拖拽进入事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    @database.atomic()
    def dropEvent(self, event) -> None:
        """dropEvent函数。
        
        :param event: 拖拽事件
        """
        result = []
        for url in event.mimeData().urls():
            dir_path = url.toLocalFile()
            if (not os.path.isdir(dir_path)):
                continue
            sku_path = None
            for file in os.listdir(dir_path):
                if ('SKU' in file.upper()):
                    sku_path = os.path.join(dir_path, file)
                    break
            if (not sku_path):
                continue
            Record.delete().where((Record.path == dir_path)).execute()
            sku_list = []
            file_list = (
                list_files(sku_path) if (
                    'ID' in os.path.basename(dir_path)) else list_files_2(sku_path))
            for sku_file in file_list:
                if (not sku_file.lower().endswith('.jpg')):
                    continue
                file_name = os.path.basename(sku_file).split('.')[0]
                dir_name = os.path.basename(os.path.dirname(sku_file))
                sku_list.append({'file_name': file_name, 'dir_name': dir_name, 'name': get_nick(
                    file_name, dir_name), 'path': sku_file, 'price': ''})
            if (len(sku_list) == 0):
                continue
            result.append({'name': os.path.basename(dir_path),
                           'path': dir_path,
                           'type': (2 if ('ID' in os.path.basename(dir_path)) else 1),
                           'status': 0,
                           'content': json.dumps(sku_list),
                           'update_time': time.now()})
        if (len(result) > 0):
            Record.insert_many(result).execute()
            self.load_url(f'http://127.0.0.1:{self.port}')

    @database.atomic()
    def _handle_file_drop(self, file_paths: list) -> None:
        """处理从WebView传递过来的拖放文件。
        
        :param file_paths: 文件路径列表
        """
        logging.info(f"🔧 处理拖放文件: {file_paths}")
        result = []
        for dir_path in file_paths:
            if (not os.path.isdir(dir_path)):
                continue
            sku_path = None
            for file in os.listdir(dir_path):
                if ('SKU' in file.upper()):
                    sku_path = os.path.join(dir_path, file)
                    break
            if (not sku_path):
                continue
            Record.delete().where((Record.path == dir_path)).execute()
            sku_list = []
            file_list = (
                list_files(sku_path) if (
                    'ID' in os.path.basename(dir_path)) else list_files_2(sku_path))
            for sku_file in file_list:
                if (not sku_file.lower().endswith('.jpg')):
                    continue
                file_name = os.path.basename(sku_file).split('.')[0]
                dir_name = os.path.basename(os.path.dirname(sku_file))
                sku_list.append({'file_name': file_name, 'dir_name': dir_name, 'name': get_nick(
                    file_name, dir_name), 'path': sku_file, 'price': ''})
            if (len(sku_list) == 0):
                continue
            result.append({'name': os.path.basename(dir_path),
                           'path': dir_path,
                           'type': (2 if ('ID' in os.path.basename(dir_path)) else 1),
                           'status': 0,
                           'content': json.dumps(sku_list),
                           'update_time': time.now()})
        if (len(result) > 0):
            Record.insert_many(result).execute()
            self.load_url(f'http://127.0.0.1:{self.port}')
            logging.info(f"✅ 成功导入 {len(result)} 个文件夹")

    def load_url(self, url) -> None:
        """load_url函数 - 专业级页面加载，避免闪烁。
        
        :param url: 加载的URL
        """
        try:
            logging.info(f"准备加载URL: {url}")
            
            # 🔧 URL验证和预处理
            if not url.startswith(('http://', 'https://', 'file://')):
                url = f"http://{url}"
            
            qurl = QUrl(url)
            if not qurl.isValid():
                logging.error(f"无效的URL: {url}")
                return
            
            # 🔧 检查WebView状态
            if self.webview.is_loading():
                logging.warning("WebView正在加载中，等待完成...")
                # 等待当前加载完成后再加载新URL
                def retry_load():
                    if not self.webview.is_loading():
                        self.load_url(url)
                    else:
                        QTimer.singleShot(100, retry_load)
                QTimer.singleShot(100, retry_load)
                return
            
            # 🔧 执行加载
            logging.debug(f"开始加载页面: {url}")
            self.webview.load(qurl)
            
        except Exception as e:
            logging.error(f"页面加载失败: {e}")
            # 降级处理：直接加载
            try:
                self.webview.load(QUrl(url))
            except Exception as fallback_error:
                logging.error(f"降级加载也失败: {fallback_error}")


class Gui():
    """Gui类。"""

    def __init__(
            self,
            title: str,
            logo: Optional[str],
            app,
            width: int = 800,
            height: int = 600,
            port: int = 5000) -> None:
        """__init__函数。
        
        :param title: 窗口标题
        :param logo: 窗口图标路径
        :param app: 应用实例
        :param width: 窗口宽度
        :param height: 窗口高度
        :param port: 端口号
        """
        self.title = title
        self.logo = logo
        self.app = app
        self.width = width
        self.height = height
        self.port = port
        self.window: Optional[MainWindow] = None
        self.page: Optional['ChromiumPage'] = None

    def run(self) -> None:
        """run函数。
        
        :return: None
        """
        try:
            # 🔧 优化Flask启动配置，提高启动速度
            self.app.run(
                port=self.port,
                debug=False,           # 禁用调试模式
                use_reloader=False,    # 禁用自动重载
                threaded=True,         # 启用多线程支持
                host='127.0.0.1',      # 明确指定主机
                processes=1,           # 单进程模式，减少资源消耗
                passthrough_errors=False  # 禁用错误传递，提高性能
            )
        except BaseException:
            logging.error('Exception occurred', exc_info=True)
            win32api.MessageBox(
                0, traceback.format_exc(), '提示', win32con.MB_OK)
            os._exit(0)

    def start(self) -> None:
        """start函数 - 专业级反闪烁启动流程。
        
        :return: None
        """
        try:
            # 🔧 开始总启动时间监控
            perf_monitor.start_timing("应用总启动时间")
            debug_logger.log_startup_phase("开始启动", "专业级反闪烁GUI应用")
            
            # 🔧 第一阶段：环境预配置
            perf_monitor.start_timing("环境配置")
            self._setup_environment()
            perf_monitor.end_timing("环境配置")
            
            # 🔧 第二阶段：创建Qt应用程序
            perf_monitor.start_timing("Qt应用创建")
            app = self._create_qt_application()
            perf_monitor.end_timing("Qt应用创建")
            
            # 🔧 第三阶段：启动后端服务
            perf_monitor.start_timing("后端服务启动")
            self._start_backend_service()
            perf_monitor.end_timing("后端服务启动")
            
            # 🔧 第四阶段：创建和配置主窗口
            perf_monitor.start_timing("主窗口创建")
            self._create_main_window()
            perf_monitor.end_timing("主窗口创建")
            
            # 🔧 第五阶段：渐进式启动
            perf_monitor.start_timing("渐进式启动")
            self._progressive_startup()
            perf_monitor.end_timing("渐进式启动")
            
            # 🔧 第六阶段：进入事件循环
            debug_logger.log_startup_phase("进入Qt事件循环", "应用准备就绪")
            sys.exit(app.exec_())
            
        except Exception as e:
            debug_logger.log_error(f"应用启动失败: {e}", "启动流程异常")
            import traceback
            traceback.print_exc()
            raise e

    def _setup_environment(self) -> None:
        """设置环境变量和系统配置"""
        debug_logger.log_startup_phase("配置环境变量", "设置反闪烁环境")
        
            # 🔧 环境变量：不再强制固定DPI/缩放，保留最小化的稳定性参数
        env_vars = {
                'QTWEBENGINE_DISABLE_SANDBOX': '0',
                'QTWEBENGINE_CHROMIUM_FLAGS': '--disable-background-timer-throttling'
            }
        
        for key, value in env_vars.items():
            os.environ[key] = value
            debug_logger.log_startup_phase("环境变量设置", f"{key}={value}")
        
        # 🔧 Qt应用程序属性（在创建QApplication之前设置）
        try:
            # 设置高DPI相关属性
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
            debug_logger.log_startup_phase("Qt属性设置", "AA_EnableHighDpiScaling=True")

            QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
            debug_logger.log_startup_phase("Qt属性设置", "AA_UseHighDpiPixmaps=True")
            
            # 尝试设置其他属性（如果存在）
            try:
                QApplication.setAttribute(Qt.ApplicationAttribute.AA_DisableWindowContextHelpButton, True)
                debug_logger.log_startup_phase("Qt属性设置", "AA_DisableWindowContextHelpButton=True")
            except AttributeError:
                debug_logger.log_startup_phase("Qt属性设置", "AA_DisableWindowContextHelpButton 不可用，跳过")
                
        except Exception as e:
            debug_logger.log_error(f"Qt属性设置失败: {e}", "Qt属性配置")

    def _create_qt_application(self) -> QApplication:
        """创建Qt应用程序实例"""
        debug_logger.log_startup_phase("创建Qt应用", "初始化QApplication")
        
        app = QApplication(sys.argv)
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{self.title}")
        except Exception:
            pass
        try:
            if self.logo and os.path.exists(self.logo):
                app.setWindowIcon(QIcon(self.logo))
        except Exception:
            pass
        
        # 🔧 设置应用程序样式表，完全避免影响标题栏
        stylesheet = """
            QMainWindow {
                background-color: #ffffff;
                font-family: "Microsoft YaHei", "SimHei", sans-serif;
            }
            QWebEngineView {
                background-color: #ffffff;
                border: none;
            }
            /* 移除所有标题栏相关样式，使用系统默认 */
        """
        app.setStyleSheet(stylesheet)
        debug_logger.log_startup_phase("样式表设置", "应用反闪烁样式")
        
        return app

    def _start_backend_service(self) -> None:
        """启动后端Flask服务"""
        debug_logger.log_startup_phase("启动后端服务", f"Flask服务端口: {self.port}")
        Thread(self.run).start()
        
        # 🔧 减少等待时间，提高启动速度
        time_module.sleep(0.1)  # 从0.5秒减少到0.1秒
        debug_logger.log_startup_phase("后端服务就绪", "Flask服务启动完成")

    def _create_main_window(self) -> None:
        """创建和配置主窗口"""
        debug_logger.log_startup_phase("创建主窗口", f"尺寸: {self.width}x{self.height}")
        
        self.window = MainWindow(self.port)
        
        # 🔧 设置窗口属性
        if self.logo and os.path.exists(self.logo):
            self.window.setWindowIcon(QIcon(self.logo))
            debug_logger.log_startup_phase("窗口图标", f"设置图标: {self.logo}")
        
        self.window.setWindowTitle(self.title)
        self.window.resize(self.width, self.height)
        self.window.center_window()
        
        # 🔧 设置窗口显示前的最后配置，完全避免影响标题栏
        self.window.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            /* 完全移除标题栏样式，使用系统默认 */
        """)
        debug_logger.log_startup_phase("主窗口配置", "窗口属性设置完成")

    def _progressive_startup(self) -> None:
        """渐进式启动流程"""
        debug_logger.log_startup_phase("渐进式启动", "开始分阶段显示")
        
        # 🔧 第一步：显示窗口
        self.window.show()
        debug_logger.log_startup_phase("窗口显示", "主窗口已显示")
        
        # 🔧 第二步：延迟加载页面，避免启动时的渲染冲突
        def delayed_page_load():
            url = f'http://127.0.0.1:{self.port}'
            debug_logger.log_startup_phase("延迟加载", f"准备加载: {url}")
            self.window.start_progressive_loading(url)
        
        # 大幅减少延迟时间，从1秒减少到200ms
        QTimer.singleShot(200, delayed_page_load)
        debug_logger.log_startup_phase("延迟定时器", "200ms后开始页面加载")

# 配置专业调试日志系统
class FlickerDebugLogger:
    """专业的闪烁问题调试日志系统"""
    
    def __init__(self):
        self.logger = logging.getLogger('FlickerDebug')
        self.logger.setLevel(logging.DEBUG)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        
        # 创建文件处理器
        file_handler = logging.FileHandler('flicker_debug.log', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 创建格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # 添加处理器
        if not self.logger.handlers:
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)
    
    def log_startup_phase(self, phase, details=""):
        """记录启动阶段"""
        # 禁用启动阶段日志输出
        # self.logger.info(f"启动阶段: {phase} - {details}")
        pass
    
    def log_webengine_event(self, event, details=""):
        """记录WebEngine事件"""
        # 禁用WebEngine事件日志输出
        # self.logger.debug(f"WebEngine事件: {event} - {details}")
        pass
    
    def log_performance(self, operation, duration):
        """记录性能数据"""
        # 禁用性能监控日志输出
        # self.logger.info(f"性能监控: {operation} 耗时 {duration:.3f}秒")
        pass
    
    def log_error(self, error, context=""):
        """记录错误"""
        self.logger.error(f"错误: {error} - 上下文: {context}")

# 全局调试器实例
debug_logger = FlickerDebugLogger()

class PerformanceMonitor:
    """轻量级性能监控器"""
    
    def __init__(self):
        self.start_times = {}
        self.enabled = False  # 默认禁用，减少开销
    
    def start_timing(self, operation):
        """开始计时"""
        if self.enabled:
            self.start_times[operation] = time_module.time()
    
    def end_timing(self, operation):
        """结束计时并记录"""
        if self.enabled and operation in self.start_times:
            duration = time_module.time() - self.start_times[operation]
            del self.start_times[operation]
            return duration
        return 0

# 全局性能监控器
perf_monitor = PerformanceMonitor()
