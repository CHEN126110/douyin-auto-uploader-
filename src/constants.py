# -*- coding: utf-8 -*-
import logging
import os
import sys
import uuid
from typing import Dict, Any
from .config import Config

is_pack = getattr(sys, 'frozen', False)
if is_pack:
    root_path = getattr(sys, '_MEIPASS', '')  # type: ignore
    # 必须显式指定 utf-8 + errors='replace'。
    # 这两行会把 app.py 装好的 _SafeConsoleStream 换掉，而 open() 默认用系统 ANSI
    # 编码（中文 Windows 上是 GBK）且严格报错，于是任何 print('⚠ ...') 都会抛
    # UnicodeEncodeError，被上层当成业务失败——2026-09-06 实测导致真实发布中断。
    sys.stdout = open(os.path.join(root_path, 'stdout.log'), 'w', encoding='utf-8', errors='replace')
    sys.stderr = open(os.path.join(root_path, 'stderr.log'), 'w', encoding='utf-8', errors='replace')
else:
    root_path = os.path.dirname(os.path.abspath(sys.argv[0]))
run_path = os.path.join(root_path, 'web')
mac = uuid.UUID(int=uuid.getnode()).hex[-12:]
secret = ('dEdJa2DksmU6ZFoi' + mac)
payload: Dict[str, Any] = {}
cfg = Config('cfg.yaml')
name = cfg.data['base']['name']
version = cfg.data['base']['version']
access_token = cfg.data['base']['access_token']
