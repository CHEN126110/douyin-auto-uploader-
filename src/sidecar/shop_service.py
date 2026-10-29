# -*- coding: utf-8 -*-
"""店铺会话服务：找出「发布流程这一刻会用到的浏览器」、实测当前登录的店铺、切换账户时丢弃旧浏览器句柄并打开登录页。

设计前提：应用自己不存 cookie，登录态全部寄生在 Chrome 用户数据目录里。所以「当前登录哪个店」只能从真正会被
发布流程用到的那个浏览器上实测，不能从 profile 名字推断——名字是意图，cookie 才是事实。

浏览器能力经 ``ShopBrowserPort`` 注入，账户门禁来自 ``ShopAccountGuard``；本模块不导入浏览器自动化库，
也不反向导入 app.py。

与 app.py 旧函数名的对应：
  _resolve_active_shop_browser -> ShopSessionService.resolve_active_browser
  _build_shop_current_payload  -> ShopSessionService.build_current_payload
  _activate_shop_profile       -> ShopSessionService.activate_profile"""
import json
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from flask import current_app


# 切换店铺后落地页：用后台首页而不是发布页，登录完成后能直接看到店铺名
_SHOP_LOGIN_URL = 'https://fxg.jinritemai.com/ffa/mshop/homepage/index'
# 淘宝/天猫：登录后打开的落点。用发布工作台而不是通用首页——它既是卖家身份的
# 真实入口（未登录会 302 到 login.taobao.com），也是后续发布流程要用的页面。
# 已实证（2026-10-03）：未登录访问该 URL 会在 URL 层重定向到登录页。
_TAOBAO_SHOP_LOGIN_URL = 'https://item.upload.taobao.com/sell/ai/category.htm'


@dataclass(frozen=True)
class ShopBrowserPort:
    """店铺会话需要的浏览器能力，由应用入口一次性注入；本模块不导入浏览器自动化库。

    ``page_state`` 是无参函数，每次调用返回当前的共享页面状态（带 ``page`` 属性的对象），含义同
    ``DebugBrowserPort.page_state``。``host`` / ``shop_port_start`` / ``shop_port_end`` 是店铺浏览器的
    调试地址与端口段（与 src/utils.py 的 _SHOP_BROWSER_PORT_* 必须一致），其它业务域也在用，所以留在 app.py。
    """

    page_state: Callable[[], Any]
    open_page: Callable[..., Any]
    normalize_address: Callable[[str], str]
    gui_page_debug_address: Callable[[], str]
    find_browser_process: Callable[[str], Any]
    find_reusable_browser: Callable[..., Any]
    set_debug_browser_instance: Callable[[Any], None]
    host: str
    shop_port_start: int
    shop_port_end: int


def _shop_profile_matches(browser_info, profile_name):
    """浏览器的用户数据目录是否属于指定 profile。

    返回 True / False / None（信息不足，无法判断）。
    None 和 False 是两回事：前者是「不知道」，不该被当成「不匹配」去报警。
    """
    profile_text = '{} {}'.format(
        (browser_info or {}).get('user_data_dir') or '',
        (browser_info or {}).get('profile_directory') or '',
    ).strip().lower()
    if not profile_text:
        return None
    return (profile_name or '').lower() in profile_text


class ShopSessionService:
    """一个应用一个实例。``accounts`` 是 ``ShopAccountGuard``，``browser`` 是 ``ShopBrowserPort``，
    ``shop_session`` 是账户注册表模块（测试里换成假件）。"""

    def __init__(self, *, accounts, browser, shop_session):
        self._accounts = accounts
        self._browser = browser
        self._shop_session = shop_session

    def _resolve_taobao_shop_browser(self):
        """淘宝分支：找一个带着淘宝/天猫页面的调试浏览器。

        与抖店分支的唯一区别是「认哪个域名的页面」。刻意**不做**「已登录验证」：
        登录与否由 ``shop_session.read_taobao_identity`` 直接从 cookie 判定，
        比「页面上有某个域名」准得多。

        仍复用 ``_find_reusable_logged_in_fxg_browser`` 里那套
        **按 profile 双向过滤**的逻辑——多店铺同时开着时，复用了别家店铺的浏览器
        会静默发错店，每一步都成功、事后查不出来。
        """

        try:
            reusable = self._browser.find_reusable_browser(verify=False)
        except Exception:
            reusable = {}
        targets_by_address = reusable.get('targets_by_address') or {}
        fallback = None
        for browser in reusable.get('eligible_browsers') or []:
            candidate = self._browser.normalize_address(browser.get('debug_address') or '')
            if not candidate:
                continue
            for target in targets_by_address.get(candidate) or []:
                if target.get('type') != 'page':
                    continue
                url = str(target.get('url') or '')
                if url.startswith('devtools://'):
                    continue
                if not any(domain in url for domain in self._shop_session.TAOBAO_DOMAINS):
                    continue
                # 卖家页优先于普通淘宝页：停在登录页只说明「需要登录」，说明不了身份。
                if any(hint in url for hint in self._shop_session.TAOBAO_SELLER_PAGE_HINTS):
                    return candidate, browser, 'taobao_seller_page'
                if fallback is None:
                    fallback = (candidate, browser, 'taobao_page')
        if fallback is not None:
            return fallback
        return '', {}, 'none'

    def _resolve_xiaohongshu_shop_browser(self):
        """小红书分支：在账户浏览器端口段里找带着千帆页面的调试实例。

        刻意**不走** ``_find_reusable_logged_in_fxg_browser``：那条链会按抖店
        登录态筛选，千帆浏览器会被滤掉（真机实测 shop/current 报 no_browser，
        而 9500 上千帆首页明明白白开着）。这里直接扫
        ``_SHOP_BROWSER_PORT_START..END``，用页面域名判定，不做登录验证
        （登录态由 ``shop_session.read_xiaohongshu_identity`` 实测）。
        """
        from urllib.error import URLError
        from urllib.request import urlopen

        fallback = None
        for port in range(self._browser.shop_port_start, self._browser.shop_port_end + 1):
            address = '{}:{}'.format(self._browser.host, port)
            try:
                with urlopen('http://{}/json/list'.format(address), timeout=0.4) as resp:
                    targets = json.loads(resp.read().decode('utf-8', errors='replace'))
            except (URLError, OSError, ValueError):
                continue
            for target in targets:
                if target.get('type') != 'page':
                    continue
                url = str(target.get('url') or '')
                if url.startswith('devtools://'):
                    continue
                if not any(domain in url for domain in self._shop_session.XHS_DOMAINS):
                    continue
                info = self._browser.find_browser_process(address) or {'debug_address': address}
                if 'ark.xiaohongshu.com' in url:
                    return address, info, 'xhs_ark_page'
                if fallback is None:
                    fallback = (address, info, 'xhs_page')
        if fallback is not None:
            return fallback
        return '', {}, 'none'

    def resolve_active_browser(self, platform='douyin'):
        """找出「发布流程这一刻会用到的浏览器」的调试地址。

        只观察，不启动任何浏览器：这个接口会被前端轮询，
        顺手拉起 Chrome 会变成用户没点过的副作用。

        :param platform: 按平台挑页面。抖音认 ``jinritemai.com``；
            淘宝认 ``taobao.com`` / ``tmall.com``。两个平台是互不相通的账号体系，
            拿抖店的页面去证明淘宝的登录态是错的。

        返回 ``(debug_address, browser_info, source)``；找不到时地址为空字符串。
        """
        address = self._browser.normalize_address(self._browser.gui_page_debug_address())
        if address:
            info = self._browser.find_browser_process(address) or {}
            return address, info, 'gui_page'

        if self._shop_session.normalize_platform(platform) == 'taobao':
            return self._resolve_taobao_shop_browser()

        if self._shop_session.normalize_platform(platform) == 'xiaohongshu':
            return self._resolve_xiaohongshu_shop_browser()

        try:
            reusable = self._browser.find_reusable_browser(verify=True)
        except Exception:
            reusable = {}
        selected = reusable.get('selected_browser') or {}
        address = self._browser.normalize_address(selected.get('debug_address') or '')
        if address:
            return address, selected, 'reusable_browser'

        # 还没登录时上一步找不到（它只认已登录的页面），但浏览器可能正停在登录页，
        # 这时也该把它当成「当前会话」，好把「未登录」如实报出来。
        #
        # 这里刻意不用 _find_cdp_port_with_jinritemai()：那个函数要逐个探 169 个端口，
        # 本机实测要 68 秒，而这个接口是前端定时轮询的。进程枚举已经能从命令行拿到
        # 真实的调试端口，0.03 秒就够，没有必要扫端口。
        targets_by_address = reusable.get('targets_by_address') or {}
        for browser in reusable.get('eligible_browsers') or []:
            candidate = self._browser.normalize_address(browser.get('debug_address') or '')
            if not candidate:
                continue
            for target in targets_by_address.get(candidate) or []:
                url = target.get('url') or ''
                if target.get('type') == 'page' and 'jinritemai.com' in url and not url.startswith('devtools://'):
                    return candidate, browser, 'open_browser'

        return '', {}, 'none'

    def build_current_payload(self):
        account = self._accounts.active_account()
        active_profile = account['profile_name']
        registry_entry = next(
            (item for item in self._shop_session.list_profiles() if item.get('profile_name') == active_profile),
            None,
        )

        payload = {
            'platform': account['platform'],
            'active_profile': active_profile,
            'active_profile_label': (registry_entry or {}).get('label') or account['label'] or '默认抖音账户',
            'profile_dir': self._shop_session.profile_dir(active_profile),
            # 注册表里的记录只是「上次看到的店铺」，与本次实测严格分开，
            # 免得界面把历史值当成当前登录的店。
            'last_seen_shop_id': (registry_entry or {}).get('shop_id'),
            'last_seen_shop_name': (registry_entry or {}).get('shop_name'),
            'status': 'no_browser',
            'shop_id': None,
            'shop_name': None,
            'debug_address': None,
            'browser_source': 'none',
            'page_url': None,
            'profile_match': None,
            'warning': None,
            'error': None,
            # 技术细节只写日志，不展示给用户
            'detail': None,
            'checked_at': datetime.now().isoformat(timespec='seconds'),
        }

        # 两个平台走同一条链路：解析浏览器 → 按平台读身份 → 实测结果写回注册表。
        #
        # 早先这里对淘宝是硬编码早退（status='manual'、永远不验证），那是当时
        # 「淘宝只做本地资料准备」的产品决策。现在淘宝也走真实登录与身份验证，
        # 所以不再有平台分支——差异全部收在 shop_session 里按平台分派。
        platform = account['platform']
        debug_address, browser_info, source = self.resolve_active_browser(platform=platform)
        payload['browser_source'] = source
        if not debug_address:
            # 文案必须指向真实存在的东西：界面上没有「切换店铺」按钮，
            # 登录入口是左上角那个账户菜单。
            payload['error'] = '尚未登录，点左上角账户菜单选择该账户即可打开登录页'
            return payload

        payload['debug_address'] = debug_address
        payload['browser_user_data_dir'] = (browser_info or {}).get('user_data_dir') or None

        # 这个接口会被前端每 15 秒轮询一次，超时必须明显短于轮询间隔，
        # 否则慢响应会一直叠在一起。本地 CDP 往返正常在 1 秒内。
        identity = self._shop_session.read_account_identity(debug_address, platform=platform, timeout=6.0)
        payload['status'] = identity.get('status')
        payload['shop_id'] = identity.get('shop_id')
        payload['shop_name'] = identity.get('shop_name')
        payload['page_url'] = identity.get('page_url')
        payload['error'] = identity.get('error')
        payload['detail'] = identity.get('detail')

        payload['profile_match'] = _shop_profile_matches(browser_info, active_profile)

        has_measured_identity = any(
            identity.get(field) for field in ('shop_id', 'shop_name', 'account_id')
        )
        if identity.get('status') == 'logged_in' and has_measured_identity:
            # 千帆目前只有店铺名、淘宝可能只有账户 ID，都不能被 shop_id 门槛挡在注册表外。
            # 实测结果要记到「这次是从哪个 profile 读出来的」，不是「当前选中哪个」。
            # 记错了注册表就会声称 A 目录是甲店，而甲店其实在 B 目录里。
            owner = self._shop_session.owning_profile_of(payload.get('browser_user_data_dir'))
            payload['owner_profile'] = owner
            if owner:
                if owner != active_profile:
                    payload.update({
                        'status': 'conflict', 'shop_id': None, 'shop_name': None,
                        'error': '浏览器登录账户与当前所选账户不一致，请重新选择账户',
                    })
                    return payload
                owner_entry = self._shop_session.load_registry()['profiles'].get(owner, {})
                owner_platform = self._shop_session.normalize_platform(owner_entry.get('platform', 'douyin'))
                if owner_platform != platform:
                    # 拿抖店的读法去证明淘宝的登录态（或反过来）会得出错误身份，
                    # 必须让用户看见，而不是凑合记下来。
                    payload.update({
                        'status': 'conflict', 'shop_id': None, 'shop_name': None,
                        'error': '浏览器所属账户的平台与当前发布平台不一致，请重新选择账户',
                    })
                    return payload
                try:
                    observation = self._shop_session.observe_identity(
                        owner,
                        identity.get('shop_id'),
                        identity.get('shop_name'),
                        platform=platform,
                        # 淘宝的账户 ID（unb）与店铺 ID 是两个字段，必须分别记。
                        account_id=identity.get('account_id'),
                    )
                except (OSError, ValueError) as exc:
                    current_app.logger.exception('保存账户实测身份失败')
                    payload['warning'] = f'登录已实测，但账户资料保存失败：{exc}'
                    observation = {'status': 'unknown'}
                payload['observation'] = observation.get('status')

        entry = next(
            (item for item in self._shop_session.list_profiles() if item.get('profile_name') == active_profile),
            None,
        )
        if entry:
            payload['active_profile_label'] = entry.get('label') or active_profile
            payload['last_seen_shop_id'] = entry.get('shop_id')
            payload['last_seen_shop_name'] = entry.get('shop_name')

        return payload

    def restore_active_browser(self):
        """按需恢复当前账户的浏览器，再以实测身份收尾。

        已经实测登录时不重开页面；`no_browser` / 平台页面缺失 / 调试地址不可达
        只说明缺少检测入口，允许恢复一次。真正的 `logged_out`、账户冲突不自动重开，
        避免把用户重新登录或选择账户的动作交给程序代替。
        """

        initial = self.build_current_payload()
        if initial.get('status') == 'logged_in':
            return {'recovery_attempted': False, 'browser_opened': False,
                    'browser_error': None, 'shop': initial}
        recoverable = {'no_browser', 'no_fxg_tab', 'no_taobao_tab', 'no_xhs_tab', 'unreachable'}
        if initial.get('status') not in recoverable:
            return {'recovery_attempted': False, 'browser_opened': False,
                    'browser_error': None, 'shop': initial}
        opened = self.activate_profile(initial['active_profile'], open_browser=True)
        return {
            'recovery_attempted': True,
            'browser_opened': opened.get('browser_opened') is True,
            'browser_error': opened.get('browser_error'),
            'debug_address': opened.get('debug_address'),
            # 打开浏览器不等于登录恢复：这里仍只返回实测结果，不拿历史店铺名顶替。
            'shop': self.build_current_payload(),
        }

    def activate_profile(self, target_profile, open_browser=True, browser_url=None):
        """把某个店铺目录设为当前，并按需打开登录页。

        旧的浏览器句柄属于上一个店铺，必须丢弃，否则下一次发布会继续用它。
        这里只断开引用，不关掉用户的浏览器窗口——里面可能有没保存的东西。
        """
        account = self._accounts.active_account()
        if account['profile_name'] != target_profile:
            raise ValueError('当前账户与切换目标不一致')
        previous_address = self._browser.normalize_address(self._browser.gui_page_debug_address())
        self._browser.page_state().page = None
        self._browser.set_debug_browser_instance(None)

        result = {
            'platform': account['platform'],
            'active_profile': target_profile,
            'profile_dir': self._shop_session.profile_dir(target_profile),
            'previous_debug_address': previous_address or None,
            'browser_opened': False,
            'browser_error': None,
        }

        if open_browser:
            # 三个平台各开各自的登录页（原写法是"淘宝 else 抖店"两分支，新平台会被打开抖店后台 ✗）。
            #
            # ⚠️ 这里**不能**写 `shop_session.XHS_HOME_URL` ✗：测试注入的 `shop_session` 是假件，
            # 没有这个属性，会在 open_browser=True 分支上抛 AttributeError。
            # 共享库里的 `shop_session.XHS_HOME_URL` 仍是应用其它位置的唯一来源 ✓，两处需保持一致。
            _xhs_login_url = 'https://ark.xiaohongshu.com/app-system/home'
            login_url = browser_url or {
                'douyin': _SHOP_LOGIN_URL,
                'taobao': _TAOBAO_SHOP_LOGIN_URL,
                'xiaohongshu': _xhs_login_url,
            }.get(account['platform'], _SHOP_LOGIN_URL)
            try:
                self._browser.page_state().page = self._browser.open_page(login_url, profile_name=target_profile)
                result['browser_opened'] = True
                result['debug_address'] = self._browser.normalize_address(self._browser.gui_page_debug_address()) or None
            except Exception as exc:
                # 打不开浏览器不该让「已切换」这件事回滚：目录已经选好了，
                # 用户手动开浏览器同样能登录。
                traceback.print_exc()
                result['browser_error'] = str(exc)

        return result
