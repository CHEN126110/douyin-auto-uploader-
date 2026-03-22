import os
import sys

def _safe_add(path):
    try:
        if os.path.isdir(path):
            os.add_dll_directory(path)
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    internal_dir = os.path.join(base_dir, '_internal')
    _safe_add(base_dir)
    _safe_add(internal_dir)
    _safe_add(os.path.join(internal_dir, 'PySide6'))
    _safe_add(os.path.join(internal_dir, 'shiboken6'))
    os.environ['QT_PLUGIN_PATH'] = os.path.join(internal_dir, 'PySide6', 'plugins')
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(internal_dir, 'PySide6', 'plugins', 'platforms')
    os.environ['PATH'] = internal_dir + os.pathsep + os.path.join(internal_dir, 'PySide6') + os.pathsep + os.path.join(internal_dir, 'shiboken6') + os.pathsep + os.environ.get('PATH', '')