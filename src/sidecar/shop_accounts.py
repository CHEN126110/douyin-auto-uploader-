# -*- coding: utf-8 -*-
"""账户门禁：当前账户及其绑定平台、账户锁，以及发布入口与账户切换之间的互斥检查。

登录态全部寄生在 Chrome 用户数据目录里，应用只在本地注册表（``shop_session``）里记「当前账户」和它绑定的平台。
上传 / 淘宝 / 小红书 / 保存等入口都要先过这里的门：平台对得上、账户没被换掉，才允许继续；
账户切换与这些入口共用同一把锁，避免「校验通过之后账户被另一个请求换成别的」。

与 app.py 旧函数名的对应：
  _shop_account_lock        -> ShopAccountGuard.lock
  _active_shop_profile      -> ShopAccountGuard.active_profile
  _active_shop_account      -> ShopAccountGuard.active_account
  _with_shop_account_lock   -> ShopAccountGuard.with_lock（装饰器）
  _require_publish_platform -> ShopAccountGuard.require_publish_platform
  _account_change_blocked   -> ShopAccountGuard.account_change_blocked"""
import threading
from functools import wraps

from flask import jsonify


class ShopAccountGuard:
    """由应用入口创建一次；锁属于实例，不同实例互不影响。

    ``shop_session`` 与 ``has_running_publish_tasks`` 由调用方注入：前者是账户注册表（测试里换成假件），
    后者回答「现在有没有发布任务在跑」——任务字典属于上传 / 淘宝业务域，本类不碰它们。"""

    def __init__(self, *, shop_session, has_running_publish_tasks):
        self._shop_session = shop_session
        self._has_running_publish_tasks = has_running_publish_tasks
        # 账户切换与发布入口共享锁，避免校验后被另一个请求换成其他账户。
        self._lock = threading.RLock()

    @property
    def lock(self):
        """账户锁本体。媒体 / 白底图等 Blueprint 要拿同一把锁，所以对外暴露。"""
        return self._lock

    def active_profile(self):
        """当前账户目录；注册表异常必须让调用方感知，不能误选默认账户。"""
        return self._shop_session.get_active_profile()

    def active_account(self):
        """仅从本地账户注册表读取绑定平台，不推测登录状态。"""
        registry = self._shop_session.load_registry()
        active_profile = self._shop_session.slugify_profile_name(registry['active_profile'])
        entry = registry['profiles'].get(active_profile)
        if entry is None and (active_profile != self._shop_session.DEFAULT_PROFILE_NAME or registry['profiles']):
            raise ValueError('当前账户不存在，请重新选择账户')
        entry = entry or {}
        return {
            'profile_name': active_profile,
            'platform': self._shop_session.normalize_platform(entry.get('platform', 'douyin')),
            'label': entry.get('label'),
        }

    def with_lock(self, handler):
        @wraps(handler)
        def locked(*args, **kwargs):
            with self._lock:
                return handler(*args, **kwargs)
        return locked

    def require_publish_platform(self, expected, account_profile=None):
        """在访问商品、浏览器或创建任务前校验当前账户的平台。"""
        try:
            account = self.active_account()
        except (OSError, ValueError) as exc:
            return jsonify(success=False, msg=f'读取账户资料失败：{exc}'), 503
        if account['platform'] != expected:
            # 提示语里的平台短名内联在这里，与 shop_routes 里 platform_label 的完整名不是同一份映射。
            label = {'douyin': '抖音', 'taobao': '淘宝', 'xiaohongshu': '小红书千帆'}.get(expected, expected)
            return jsonify(
                success=False, code='ACCOUNT_PLATFORM_MISMATCH',
                msg=f'当前账户不属于{label}，请先切换到{label}账户',
            ), 409
        if account_profile is not None:
            if not isinstance(account_profile, str) or not account_profile.strip():
                return jsonify(success=False, msg='账户标识必须是非空文本'), 400
            if account_profile != account['profile_name']:
                return jsonify(
                    success=False, code='ACCOUNT_CHANGED',
                    msg='当前账户已改变，请刷新账户后重新检查发布资料',
                ), 409
        return None

    def account_change_blocked(self):
        running = self._has_running_publish_tasks()
        if running:
            return jsonify(success=False, msg='发布任务运行中，请完成或取消后再切换账户'), 409
        return None
