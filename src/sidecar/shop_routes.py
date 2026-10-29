# -*- coding: utf-8 -*-
"""店铺会话接口（/api/shop/*）：当前登录的店铺、运费模板、账户列表、添加 / 切换 / 移除账户。

这些接口只做 HTTP 适配；账户门禁在 ``ShopAccountGuard``，浏览器会话在 ``ShopSessionService``。"""
import os

from flask import Blueprint, current_app, jsonify, request

from .responses import api_error, api_ok


def create_shop_blueprint(*, accounts, service, shop_session):
    """``accounts`` 是 ``ShopAccountGuard``（账户锁与平台门禁），``service`` 是 ``ShopSessionService``
    （浏览器会话与身份实测），``shop_session`` 是账户注册表模块（测试里换成假件）。"""
    routes = Blueprint('shop', __name__)

    def platform_label(platform):
        """平台的中文名。面向用户的提示统一从这里取，避免各处硬编码「抖音/淘宝」。

        ⚠️ 测试（`tests/test_shop_routes.py`、`tests/test_shop_platform_api.py`）注入的 `shop_session` 是**假件**，
        只提供 normalize_platform 等少量属性 ✗
        —— 所以**不能**读 `shop_session.PLATFORM_LABELS`（实测：改成读它之后 5 条接口测试失败 ✗）。
        映射写在这里，并与共享库 `shop_session.PLATFORM_LABELS` 保持一致 ✓
        （两处都有回归/测试盯着；加平台时两处一起补）。
        """

        labels = {'douyin': '抖音 / 抖店', 'taobao': '淘宝', 'xiaohongshu': '小红书千帆'}
        try:
            normalized = shop_session.normalize_platform(platform)
        except ValueError:
            return str(platform)
        return labels.get(normalized, normalized)

    @routes.get('/api/shop/current')
    @accounts.with_lock
    def shop_current():
        """当前发布会话实测登录的店铺。"""
        try:
            return api_ok('店铺状态已刷新', data=service.build_current_payload())
        except Exception as exc:
            return api_error('读取店铺状态失败: {}'.format(exc))

    @routes.post('/api/shop/restore')
    @accounts.with_lock
    def shop_restore():
        """启动或人工恢复时调用一次；普通 /current 轮询仍然只观察。"""
        error = accounts.account_change_blocked()
        if error is not None:
            return error
        try:
            return api_ok('店铺浏览器恢复流程已结束', data=service.restore_active_browser())
        except Exception as exc:
            return api_error('恢复店铺浏览器失败: {}'.format(exc))

    @routes.get('/api/shop/freight-templates')
    @accounts.with_lock
    def shop_freight_templates():
        """当前登录店铺的运费模板，实时读，不用本地维护的列表。

        运费模板是每家店自己的。让用户手工维护一份名单，名字打错或换了店
        就会在发布时选错模板甚至失败，而且不会有任何报错。

        两个平台都支持这个接口，但**淘宝侧尚未实证接口名**，所以淘宝会如实返回
        ``status='not_captured'``。空列表绝不等于「该店铺没有模板」——
        前端必须把这两种情况区分开。
        """
        account = accounts.active_account()
        platform = account['platform']
        debug_address, browser_info, source = service.resolve_active_browser(platform=platform)
        payload = {
            'platform': platform,
            'status': 'no_browser',
            'templates': [],
            'shop_id': None,
            'shop_name': None,
            'current': None,
            'browser_source': source,
            'error': '尚未登录，先在左上角登录店铺',
            'detail': None,
        }
        if not debug_address:
            return api_ok('运费模板已刷新', data=payload)

        if platform == 'taobao':
            result = shop_session.read_taobao_freight_templates(debug_address, timeout=8.0)
        else:
            result = shop_session.read_freight_templates(debug_address, timeout=8.0)
        payload.update({
            'status': result.get('status'),
            'templates': result.get('templates') or [],
            'shop_id': result.get('shop_id'),
            # 当前挂着的模板。淘宝那条 DOM 路线能读到（`page.read_freight_template`），
            # 抖店那条读不到就是 None——**不做兜底**，前端按 None 显示「未知」。
            'current': result.get('current'),
            'error': result.get('error'),
            'detail': result.get('detail'),
        })

        # 顺带带上店铺名，让前端能说清「这是哪家店的模板」
        try:
            identity = shop_session.read_account_identity(debug_address, platform=platform, timeout=6.0)
            payload['shop_name'] = identity.get('shop_name')
            if (
                payload['shop_id']
                and identity.get('shop_id')
                and payload['shop_id'] != identity.get('shop_id')
            ):
                # 模板自带 shop_id，和当前登录店铺对不上说明会话串了，
                # 这时候拿这批模板去发布就是按别人店铺的运费规则发货。
                payload['status'] = 'conflict'
                payload['error'] = '运费模板与当前登录店铺对不上，请重新登录后再试'
                payload['detail'] = '模板 shop_id={} 实测登录 shop_id={}'.format(
                    payload['shop_id'], identity.get('shop_id')
                )
                payload['templates'] = []
        except Exception:
            pass

        return api_ok('运费模板已刷新', data=payload)

    @routes.get('/api/shop/profiles')
    @accounts.with_lock
    def shop_profiles():
        """已登记的店铺列表。"""
        try:
            profiles = shop_session.list_profiles()
            for item in profiles:
                item['profile_dir'] = shop_session.profile_dir(item['profile_name'])
            return api_ok('店铺列表已加载', data={
                'active_profile': accounts.active_profile(),
                'platform': accounts.active_account()['platform'],
                'profiles': profiles,
                'registry_path': shop_session.registry_path(),
            })
        except Exception as exc:
            return api_error('读取店铺列表失败: {}'.format(exc))

    @routes.post('/api/shop/add')
    @accounts.with_lock
    def shop_add():
        """添加时绑定平台；名称仅作为账户备注，平台店铺身份仍需实测。"""
        data = request.get_json(silent=True)
        if data is None and not request.data:
            data = {}
        if not isinstance(data, dict) or set(data) - {'platform', 'label', 'open_browser'}:
            return jsonify(success=False, msg='添加账户需要有效的 JSON 对象'), 400
        label = data.get('label')
        if label is not None and (not isinstance(label, str) or len(label.strip()) > 60):
            return jsonify(success=False, msg='账户名称必须是60字以内的文本'), 400
        open_browser = data.get('open_browser', True)
        if not isinstance(open_browser, bool):
            return jsonify(success=False, msg='open_browser 必须是布尔值'), 400

        try:
            platform = shop_session.normalize_platform(data.get('platform', 'douyin'))
            error = accounts.account_change_blocked()
            if error is not None:
                return error
            target_profile = shop_session.create_profile(platform=platform, label=label)
            shop_session.set_active_profile(target_profile)
            result = service.activate_profile(target_profile, open_browser=open_browser)
        except ValueError as exc:
            return jsonify(success=False, msg=f'添加账户失败：{exc}'), 400
        except Exception as exc:
            return api_error('添加店铺失败: {}'.format(exc))

        message = '{}账户已添加，登录后会自动显示店铺名'.format(platform_label(platform)) if open_browser else '{}账户已添加'.format(platform_label(platform))
        if result['browser_error']:
            message = '店铺已添加，但登录页面没能自动打开，请手动打开{}后台登录'.format(platform_label(platform))
        return api_ok(message, data=result)

    @routes.post('/api/shop/switch')
    @accounts.with_lock
    def shop_switch():
        """切换到某个已有店铺，并按需打开浏览器让用户登录。

        请求体：
          - ``profile_name``  要切换到的店铺目录名
          - ``open_browser``  是否顺带打开浏览器，默认 true
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) - {'profile_name', 'open_browser'}:
            return jsonify(success=False, msg='切换账户需要有效的 JSON 对象'), 400
        profile_name = data.get('profile_name')
        if not isinstance(profile_name, str) or not profile_name.strip():
            return jsonify(success=False, msg='请先选择要切换的账户'), 400
        open_browser = data.get('open_browser', True)
        if not isinstance(open_browser, bool):
            return jsonify(success=False, msg='open_browser 必须是布尔值'), 400

        try:
            error = accounts.account_change_blocked()
            if error is not None:
                return error
            slug = shop_session.slugify_profile_name(profile_name.strip())
            if slug not in shop_session.load_registry()['profiles']:
                return jsonify(success=False, msg='账户不存在，请刷新账户列表'), 404
            target_profile = shop_session.set_active_profile(profile_name)
            result = service.activate_profile(target_profile, open_browser=open_browser)
        except ValueError as exc:
            return jsonify(success=False, msg=f'切换账户失败：{exc}'), 400
        except Exception as exc:
            return api_error('切换店铺失败: {}'.format(exc))

        message = '已切换，请在打开的页面完成登录' if open_browser else '已切换到{}账户'.format(platform_label(result['platform']))
        if result['browser_error']:
            message = '已切换，但登录页面没能自动打开，请手动打开{}后台登录'.format(platform_label(result['platform']))
        return api_ok(message, data=result)

    @routes.post('/api/shop/forget')
    @accounts.with_lock
    def shop_forget():
        """从列表里移除一个店铺记录；``purge=true`` 时**连浏览器登录资料一起删除**。

        两档语义必须由调用方明确选一个，不能默认删磁盘：

          - ``purge=false``（默认）—— 只摘记录，登录态留在磁盘上；
          - ``purge=true`` —— 记录与 ``profile_dir`` 一起删。这才是用户说的「删除」：
            下次重新添加同一个账户时是全新未登录状态。

        允许移除当前账户：删完会把 active 交接给另一个仍然存在的账户（响应里
        ``active_profile`` 会给出交接结果）。早先这里返回 409 要求「先切换」，
        但「登录错了账户」场景下那个错账户就是当前账户，等于把人卡住。
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('profile_name'), str) or not data['profile_name'].strip():
            return jsonify(success=False, msg='缺少要移除的账户'), 400
        purge = data.get('purge', False)
        if not isinstance(purge, bool):
            return jsonify(success=False, msg='purge 必须是布尔值'), 400
        profile_name = shop_session.slugify_profile_name(data['profile_name'].strip())
        error = accounts.account_change_blocked()
        if error is not None:
            return error
        try:
            entry = shop_session.load_registry()['profiles'].get(profile_name)
            if profile_name == shop_session.DEFAULT_PROFILE_NAME and entry is not None:
                if not shop_session.is_empty_default_profile(profile_name, entry):
                    return jsonify(success=False, msg='该历史账户已有店铺身份、备注或观测记录，不能作为默认空账户移除'), 409
            directory = shop_session.profile_dir(profile_name)
            had_directory = os.path.isdir(directory)
            if not shop_session.remove_profile(profile_name, purge_directory=purge):
                return jsonify(success=False, msg='账户不存在，请刷新账户列表'), 404
        except (OSError, ValueError) as exc:
            current_app.logger.exception('移除本地账户记录失败')
            return jsonify(success=False, msg=f'移除账户失败：{exc}'), 503

        purged = purge and had_directory and not os.path.isdir(directory)
        if purge and had_directory and not purged:
            # 记录已摘掉，但目录没删干净。必须如实说，不能报成「已彻底删除」。
            message = '已从列表移除，但浏览器登录资料未能完全删除，请手动检查'
        elif purged:
            message = '已彻底删除该账户，包括本地浏览器登录资料'
        else:
            message = '已从列表移除，本地浏览器登录资料仍保留'
        return api_ok(message, data={
            'purged': purged,
            'removed_profile': profile_name,
            'active_profile': accounts.active_profile(),
            'profiles': shop_session.list_profiles(),
        })

    return routes
