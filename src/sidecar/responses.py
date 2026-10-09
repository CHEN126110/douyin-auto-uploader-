# -*- coding: utf-8 -*-
"""桌面端沿用的 JSON 返回结构，不依赖 Flask 或浏览器工具库。"""


def api_ok(msg, data=None):
    return {'success': True, 'msg': msg, 'data': data}


def api_error(msg, data=None):
    return {'success': False, 'msg': msg, 'data': data}
