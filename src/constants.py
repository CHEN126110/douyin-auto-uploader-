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
    sys.stdout = open(os.path.join(root_path, 'stdout.log'), 'w')
    sys.stderr = open(os.path.join(root_path, 'stderr.log'), 'w')
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
