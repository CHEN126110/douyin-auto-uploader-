# -*- coding: utf-8 -*-
"""故意改坏验证：逐个对新模块 / app.py 的装配做小改动，确认测试会变红，跑完恢复原文件。

“测试写完了”不等于“测试真的拦得住问题”。这个脚本把 MUTATIONS 里的每一条改动临时写进源码，
只跑对应的测试文件，收集哪些测试文件变红，然后无条件恢复原文件（并校验内容摘要）。

用法（仓库根执行；会**原地改动源码**，运行期间不要同时跑别的测试，也不要有别的会话在改这些文件）::

    python lab/sidecar_split/sabotage.py [名字里含这些关键词的改动，逗号分隔；缺省跑全部]

判定：
- 红✓   至少有一个测试文件失败，并且包含预期的那个新测试文件；
- 超时  测试卡死（被改坏后的代码死循环）。这比失败更糟，应该把测试改成快速失败（例如虚拟时钟限制睡眠次数）；
- 绿✗   改坏了测试还全绿，说明这块行为没人守着，要补测试。
任何一条不是“红✓”，脚本最后退出码非 0。

2026-10-19 店铺会话 + 调试浏览器这一轮的 52 条改动写在下面，可以当范例；换成别的域时照着写自己的 MUTATIONS。
一条改动是 ``M(名字, 文件, 旧文本, 新文本, 要跑的测试, nth=第几处, expect=预期抓住它的测试文件名)``，
旧文本必须在文件里出现 nth+1 次以上。
"""
import hashlib
import io
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.path.join(REPO, 'src', 'sidecar')
APP = os.path.join(REPO, 'tauri-app', 'python-sidecar', 'app.py')
TEST_TIMEOUT = 600      # 秒；单次 pytest 超过这个时间按“卡死”处理

SHOP_TESTS = ['tests/test_shop_accounts.py', 'tests/test_shop_routes.py', 'tests/test_shop_platform_api.py',
              'tests/test_taobao_desktop_api.py', 'tests/test_product_save_snapshot.py']
DEBUG_TESTS = ['tests/test_debug_browser_service.py', 'tests/test_debug_browser_routes.py']
SMOKE_TESTS = ['tests/test_sidecar_app_smoke.py']
IMPORT_TESTS = ['tests/test_import_routes.py']
XHS_TESTS = ['tests/test_xhs_batch.py', 'tests/test_xhs_task_prune.py']
CAPTURE_TESTS = ['tests/test_capture_routes.py', 'tests/test_capture_service.py', 'tests/test_capture_helpers.py',
                 'tests/test_capture_completeness.py', 'tests/test_capture_browser_connection.py',
                 'tests/test_capture_attribute_storage.py', 'tests/test_sidecar_service_attribute_refs.py']
# 淘宝发布这一轮：新模块的直接测试 + 重新指向新位置的老测试（接口 / 保存 / 账户门禁 / 更新器 / 装配接线）
TAOBAO_TESTS = ['tests/test_taobao_helpers.py', 'tests/test_taobao_service.py', 'tests/test_taobao_routes.py',
                'tests/test_sidecar_taobao_publish.py', 'tests/test_sidecar_taobao_concurrency.py',
                'tests/test_taobao_desktop_api.py', 'tests/test_product_save_snapshot.py', 'tests/test_shop_platform_api.py',
                'tests/test_sidecar_service_attribute_refs.py', 'taobao-publisher/tests/test_desktop_fill_entry.py']
# 抖店上传第一步：页面操作模块的边界测试 + 改指新位置的老测试（稳定性 / 价格库存 / 提交未确认 / 品牌 / 定位器）+ 装配接线
UPLOAD_STEPS_TESTS = ['tests/test_upload_steps.py', 'tests/test_publish_stability_fixes.py',
                      'tests/test_price_stock_virtual_scroll_fill.py', 'tests/test_submit_publish_unconfirmed.py',
                      'tests/test_upload_brand_safety.py', 'tests/test_upload_price_stock_locators.py',
                      'tests/test_select_text_brand_verification.py', 'tests/test_sidecar_app_smoke.py']


def M(name, path, old, new, tests, nth=0, expect=None):
    return dict(name=name, path=path, old=old, new=new, tests=tests, nth=nth, expect=expect)


def S(file):
    return os.path.join(SRC, file)


MUTATIONS = [
    # ---------------------------------------------------------------- shop_accounts
    M('accounts: 当前账户不存在也不报错（回落到抖店）', S('shop_accounts.py'),
      "raise ValueError('当前账户不存在，请重新选择账户')", 'pass', SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 平台门禁判反', S('shop_accounts.py'),
      "if account['platform'] != expected:", "if account['platform'] == expected:", SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 不再校验账户快照是否过期', S('shop_accounts.py'),
      "if account_profile != account['profile_name']:", 'if False:', SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 装饰器不再持锁', S('shop_accounts.py'), 'with self._lock:', 'if True:', SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 有发布任务也允许切换账户', S('shop_accounts.py'), 'if running:', 'if False:', SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 读注册表失败返回 200', S('shop_accounts.py'), "msg=f'读取账户资料失败：{exc}'), 503",
      "msg=f'读取账户资料失败：{exc}'), 200", SHOP_TESTS, expect='test_shop_accounts'),
    M('accounts: 不校验注册表里的平台值', S('shop_accounts.py'),
      "'platform': self._shop_session.normalize_platform(entry.get('platform', 'douyin')),",
      "'platform': entry.get('platform', 'douyin'),", SHOP_TESTS, expect='test_shop_accounts'),
    # ---------------------------------------------------------------- shop_service
    M('service: 切换账户不丢弃旧浏览器句柄', S('shop_service.py'),
      'self._browser.page_state().page = None', 'pass', SHOP_TESTS, expect='test_shop_routes'),
    M('service: 切换账户不清调试浏览器实例', S('shop_service.py'),
      'self._browser.set_debug_browser_instance(None)', 'pass', SHOP_TESTS, expect='test_shop_routes'),
    M('service: 浏览器属于别的账户时不报冲突', S('shop_service.py'),
      'if owner != active_profile:', 'if False:', SHOP_TESTS, expect='test_shop_routes'),
    M('service: 实测身份记到当前账户而不是浏览器所属账户', S('shop_service.py'),
      "owner = self._shop_session.owning_profile_of(payload.get('browser_user_data_dir'))",
      'owner = active_profile', SHOP_TESTS, expect='test_shop_routes'),
    M('service: 淘宝卖家页来源标签错', S('shop_service.py'),
      "return candidate, browser, 'taobao_seller_page'", "return candidate, browser, 'taobao_page'", SHOP_TESTS,
      expect='test_shop_routes'),
    M('service: 小红书只扫第一个端口', S('shop_service.py'),
      'range(self._browser.shop_port_start, self._browser.shop_port_end + 1)',
      'range(self._browser.shop_port_start, self._browser.shop_port_start + 1)', SHOP_TESTS, expect='test_shop_routes'),
    M('service: 忽略 GUI 页面', S('shop_service.py'), "return address, info, 'gui_page'", "return '', {}, 'none'",
      SHOP_TESTS, expect='test_shop_routes'),
    M('service: 浏览器目录匹配判反', S('shop_service.py'),
      "return (profile_name or '').lower() in profile_text", "return (profile_name or '').lower() not in profile_text",
      SHOP_TESTS, expect='test_shop_routes'),
    M('service: 淘宝登录页地址写错', S('shop_service.py'),
      "_TAOBAO_SHOP_LOGIN_URL = 'https://item.upload.taobao.com/sell/ai/category.htm'",
      "_TAOBAO_SHOP_LOGIN_URL = 'https://www.taobao.com/'", SHOP_TESTS, expect='test_shop_routes'),
    M('service: 小红书用抖店登录页', S('shop_service.py'),
      "_xhs_login_url = 'https://ark.xiaohongshu.com/app-system/home'", '_xhs_login_url = _SHOP_LOGIN_URL', SHOP_TESTS,
      expect='test_shop_routes'),
    # ---------------------------------------------------------------- shop_routes
    M('routes: forget 默认连目录一起删', S('shop_routes.py'), "purge = data.get('purge', False)",
      "purge = data.get('purge', True)", SHOP_TESTS, expect='test_shop_routes'),
    M('routes: switch 不再要求账户已存在', S('shop_routes.py'),
      "if slug not in shop_session.load_registry()['profiles']:", 'if False:', SHOP_TESTS, expect='test_shop_routes'),
    M('routes: add 的 open_browser 不再严格校验', S('shop_routes.py'),
      'if not isinstance(open_browser, bool):', 'if False:', SHOP_TESTS, nth=0, expect='test_shop_routes'),
    M('routes: switch 不再加账户锁', S('shop_routes.py'),
      "    @routes.post('/api/shop/switch')\n    @accounts.with_lock\n", "    @routes.post('/api/shop/switch')\n",
      SHOP_TESTS, expect='test_shop_platform_api'),
    M('routes: 运费模板与登录店铺不一致时不报冲突', S('shop_routes.py'),
      "payload['shop_id'] != identity.get('shop_id')", "payload['shop_id'] == identity.get('shop_id')", SHOP_TESTS,
      expect='test_shop_routes'),
    M('routes: forget 不再被发布任务阻止', S('shop_routes.py'),
      "\n        error = accounts.account_change_blocked()", "\n        error = None", SHOP_TESTS, expect='test_shop_routes'),
    # ---------------------------------------------------------------- debug_browser_service
    M('debug: 会话上限 8 改 9', S('debug_browser_service.py'), '_BROWSER_DEBUG_MAX_SESSIONS = 8',
      '_BROWSER_DEBUG_MAX_SESSIONS = 9', DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 事件不再截断', S('debug_browser_service.py'),
      "session['events'] = session['events'][-_BROWSER_DEBUG_MAX_EVENTS:]", 'pass', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: 错误报告返回内部对象而不是副本', S('debug_browser_service.py'),
      'return copy.deepcopy(report) if report else None', 'return report if report else None', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: latest_error_after 边界 >= 改 >', S('debug_browser_service.py'),
      'captured_at >= started_at', 'captured_at > started_at', DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: attach 不再强制 existing_only', S('debug_browser_service.py'),
      'existing_only=existing_only or True', 'existing_only=existing_only', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: 显式端口不检查是否被占用', S('debug_browser_service.py'),
      'if not self._browser.is_port_available(self._browser.host, resolved_port):', 'if False:', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: 启动超时不杀进程', S('debug_browser_service.py'), 'process.kill()', 'pass', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: 重新打开浏览器后不清旧实例', S('debug_browser_service.py'),
      'self.set_browser_instance(None)', 'pass', DEBUG_TESTS, nth=0, expect='test_debug_browser_service'),
    M('debug: 会话事件数算错', S('debug_browser_service.py'), "'event_count': len(session.get('events', [])),",
      "'event_count': len(session.get('events', [])) + 1,", DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 记录自动化错误但不写 last_error', S('debug_browser_service.py'), 'self.set_last_error(report)', 'pass',
      DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 打包态产物目录判反', S('debug_browser_service.py'), "if getattr(sys, 'frozen', False):",
      "if not getattr(sys, 'frozen', False):", DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 等待间隔不限幅', S('debug_browser_service.py'),
      'sleep_interval = max(0.02, min(float(interval), 1.0))', 'sleep_interval = float(interval)', DEBUG_TESTS,
      expect='test_debug_browser_service'),
    M('debug: 截图失败不留痕', S('debug_browser_service.py'), "artifacts['screenshot_error'] = str(exc)", 'pass',
      DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 空标签的 slug 变成 none', S('debug_browser_service.py'), "raw = str(value or 'debug')",
      'raw = str(value)', DEBUG_TESTS, expect='test_debug_browser_service'),
    M('debug: 长文本不加省略号', S('debug_browser_service.py'), "return text[:limit] + '...'", 'return text[:limit]',
      DEBUG_TESTS, expect='test_debug_browser_service'),
    # ---------------------------------------------------------------- debug_browser_routes
    M('routes: query 默认包含不可见元素', S('debug_browser_routes.py'),
      "only_visible = debug_bool(data.get('only_visible'), True)", "only_visible = debug_bool(data.get('only_visible'), False)",
      DEBUG_TESTS, nth=0, expect='test_debug_browser_routes'),
    M('routes: wait 超时上限 30 改 300', S('debug_browser_routes.py'),
      'timeout = max(0.1, min(timeout, 30.0))', 'timeout = max(0.1, min(timeout, 300.0))', DEBUG_TESTS,
      expect='test_debug_browser_routes'),
    M('routes: action 失败不留证据', S('debug_browser_routes.py'),
      "artifacts = service.capture_artifacts(tab, label=f'action_{action}_failed', include_html=True)",
      'artifacts = None', DEBUG_TESTS, expect='test_debug_browser_routes'),
    M('routes: launch 默认不复用已运行的浏览器', S('debug_browser_routes.py'),
      "reuse_existing = debug_bool(data.get('reuse_existing'), True)",
      "reuse_existing = debug_bool(data.get('reuse_existing'), False)", DEBUG_TESTS, expect='test_debug_browser_routes'),
    M('routes: discover 默认不验证', S('debug_browser_routes.py'),
      "verify = debug_bool(request.args.get('verify'), True)", "verify = debug_bool(request.args.get('verify'), False)",
      DEBUG_TESTS, expect='test_debug_browser_routes'),
    M('routes: 改了 capture 的 URL', S('debug_browser_routes.py'), "@routes.post('/api/debug/browser/capture')",
      "@routes.post('/api/debug/browser/capture2')", DEBUG_TESTS + SMOKE_TESTS, expect='test_debug_browser_routes'),
    M('routes: query 失败证据的标签改了', S('debug_browser_routes.py'), "label='query_failed'", "label='query_ok'",
      DEBUG_TESTS, expect='test_debug_browser_routes'),
    M('routes: context 的 limit 下限改 0', S('debug_browser_routes.py'),
      "limit = debug_int(request.args.get('limit'), 5, minimum=1, maximum=20)",
      "limit = debug_int(request.args.get('limit'), 5, minimum=0, maximum=20)", DEBUG_TESTS,
      expect='test_debug_browser_routes'),
    # ---------------------------------------------------------------- app.py 装配
    M('app: 账户锁换成另一把', APP, '_shop_account_lock = shop_accounts.lock', '_shop_account_lock = threading.RLock()',
      SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 调试端口缓存了 gui 快照', APP, 'page_state=lambda: gui,\n        active_profile=_active_shop_profile,',
      'page_state=(lambda g: (lambda: g))(gui),\n        active_profile=_active_shop_profile,', SMOKE_TESTS,
      expect='test_sidecar_app_smoke'),
    M('app: 账户切换只看上传任务', APP,
      "    with taobao_service.lock:\n        running = running or any(task.get('status') in ('pending', 'running')\n"
      "                                 for task in taobao_service.tasks.values())\n    return running",
      '    return running', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 漏掉 _debug_bool 别名', APP, '_debug_bool = debug_bool\n', '', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 店铺端口的复用浏览器接错函数', APP, 'find_reusable_browser=_find_reusable_logged_in_fxg_browser,',
      'find_reusable_browser=_find_debug_browser_process,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    # ---------------------------------------------------------------- import_routes（2026-10-20）
    M('import: 没选文件夹也不报错', S('import_routes.py'),
      'if not isinstance(paths, list) or len(paths) == 0:', 'if False:', IMPORT_TESTS, expect='test_import_routes'),
    M('import: 路径不去重', S('import_routes.py'), 'if path_key not in seen:', 'if True:', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 路径去重不忽略大小写', S('import_routes.py'),
      "path_key = abs_path.lower() if os.name == 'nt' else abs_path", 'path_key = abs_path', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: SKU 不去重', S('import_routes.py'), 'sku_list, dedup_count = _dedup_sku_list(sku_list)',
      'dedup_count = 0', IMPORT_TESTS, expect='test_import_routes'),
    M('import: 去重区分大小写', S('import_routes.py'), "key = str(sku.get('name', '')).strip().lower()",
      "key = str(sku.get('name', '')).strip()", IMPORT_TESTS, expect='test_import_routes'),
    M('import: ID 文件夹不再记为 type 2', S('import_routes.py'), "'type': 2 if 'ID' in folder_name.upper() else 1,",
      "'type': 1,", IMPORT_TESTS, expect='test_import_routes'),
    M('import: 重复导入不替换旧记录', S('import_routes.py'),
      'Record.delete().where(Record.path.in_(paths_to_delete)).execute()', 'pass', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 入库不放进事务', S('import_routes.py'), 'with db.atomic():', 'if True:', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 单个文件夹出错中断整批', S('import_routes.py'),
      "errors.append(f'{os.path.basename(dir_path)}: {str(folder_error)}')", 'raise', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 括号里的名字不再优先', S('import_routes.py'), 'if arr:', 'if False:', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 自选备注规则失效', S('import_routes.py'),
      "if '自选备注' in dir_name or '/自选备注/' in normalized_path:", 'if False:', IMPORT_TESTS,
      expect='test_import_routes'),
    M('import: 不再跳过非图片文件', S('import_routes.py'), 'if name.lower().endswith(valid_ext):', 'if True:',
      IMPORT_TESTS, expect='test_import_routes'),
    M('import: 忽略注入的 split_number_prefix', S('import_routes.py'),
      '_, rest = split_number_prefix(file_name)', '_, rest = None, file_name', IMPORT_TESTS,
      expect='test_import_routes'),
    M('app: 导入接口漏接真实的 split_number_prefix', APP,
      'record_model=Record, split_number_prefix=split_number_prefix,',
      'record_model=Record, split_number_prefix=lambda text: (None, text),', SMOKE_TESTS,
      expect='test_sidecar_app_smoke'),
    # ---------------------------------------------------------------- xhs_batch（2026-10-20）
    M('xhs: 类目认不出时猜一个', S('xhs_batch_service.py'), "return _XHS_CATEGORY_LABELS.get(raw, '')",
      "return _XHS_CATEGORY_LABELS.get(raw, '中筒袜')", XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 目录里不存在的图也算', S('xhs_batch_service.py'), 'if os.path.isfile(p):', 'if True:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs: SKU 里不存在的图也算', S('xhs_batch_service.py'), 'if p and os.path.isfile(p):', 'if p:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs: worker 忽略取消', S('xhs_batch_service.py'), "if task and task.get('cancelled'):", 'if False:',
      XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 执行器说失败也记成功', S('xhs_batch_service.py'), "ok = bool(report.get('ok', False))", 'ok = True',
      XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 执行器异常中断整批', S('xhs_batch_service.py'), 'except Exception as exc:', 'except KeyError as exc:',
      XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 标题为空也调用执行器', S('xhs_batch_service.py'), 'if not title:', 'if False:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs: 上传默认放开（红线）', S('xhs_batch_service.py'), "allow_upload = bool(payload.get('allow_upload'))",
      'allow_upload = True', XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 清理连运行中的任务一起删', S('xhs_batch_service.py'), "terminal = ('succeeded', 'failed', 'cancelled')",
      "terminal = ('succeeded', 'failed', 'cancelled', 'running', 'pending')", XHS_TESTS,
      expect='test_xhs_task_prune'),
    M('xhs: 清理时时间戳损坏的任务也删', S('xhs_batch_service.py'),
      "except (TypeError, ValueError):\n                return None",
      "except (TypeError, ValueError):\n                return datetime.min", XHS_TESTS,
      expect='test_xhs_task_prune'),
    M('xhs: 显式端口不再优先', S('xhs_batch_service.py'), 'if payload_port:', 'if False:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs: 端口扫描不限页面类型', S('xhs_batch_service.py'), "target.get('type') == 'page' and", 'True and',
      XHS_TESTS, expect='test_xhs_batch'),
    M('xhs: 端口扫描少扫最后一个', S('xhs_batch_service.py'), 'range(self._port_start, self._port_end + 1)',
      'range(self._port_start, self._port_end)', XHS_TESTS, expect='test_xhs_batch'),
    M('xhs-routes: 账户门禁拦不住', S('xhs_batch_routes.py'), 'if error is not None:', 'if False:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs-routes: 取消不设标志', S('xhs_batch_routes.py'), "task['cancelled'] = True", 'pass', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs-routes: 已结束的任务也能被取消', S('xhs_batch_routes.py'),
      "if task.get('status') in ('succeeded', 'failed', 'cancelled'):", 'if False:', XHS_TESTS,
      expect='test_xhs_batch'),
    M('xhs-routes: 启动前不清理旧任务', S('xhs_batch_routes.py'), 'service.prune_finished_locked()', 'pass',
      XHS_TESTS, expect='test_xhs_batch'),
    M('xhs-routes: 非对象请求体不拒绝', S('xhs_batch_routes.py'), 'if not isinstance(data, dict):', 'if False:',
      XHS_TESTS, expect='test_xhs_batch'),
    M('app: 小红书服务接错端口段', APP,
      'host=_DEBUG_BROWSER_HOST, port_start=_SHOP_BROWSER_PORT_START, port_end=_SHOP_BROWSER_PORT_END,',
      'host=_DEBUG_BROWSER_HOST, port_start=_DEBUG_BROWSER_PORT_START, port_end=_DEBUG_BROWSER_PORT_END,',
      SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 小红书批量路由接了另一把门禁', APP, 'record_model=Record, service=xhs_batch, accounts=shop_accounts,',
      "record_model=Record, service=xhs_batch, accounts=type('G', (), {'require_publish_platform': staticmethod(lambda e: None)})(),",
      SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: fill-only 的端口不走批量服务', APP, "payload['port'] = xhs_batch.debug_port(payload.get('port'))",
      "payload['port'] = payload.get('port')", SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: status 体检的端口不走批量服务', APP, 'return _probe(port=xhs_batch.debug_port())', 'return _probe(port=None)',
      SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    # ---------------------------------------------------------------- capture（2026-10-20）
    M('capture-routes: 互斥锁不再拒绝第二个任务', S('capture_routes.py'), 'if service.running_task_id:', 'if False:', CAPTURE_TESTS,
      expect='test_capture_routes'),
    M('capture-routes: 启动时不记录占用互斥锁的任务 id', S('capture_routes.py'), 'service.running_task_id = task_id', 'pass', CAPTURE_TESTS,
      expect='test_capture_routes'),
    M('capture-routes: 线程结束不释放互斥锁', S('capture_routes.py'), 'service.running_task_id = None', 'pass', CAPTURE_TESTS,
      nth=0, expect='test_capture_routes'),
    M('capture-routes: 启动失败不释放互斥锁', S('capture_routes.py'), 'service.running_task_id = None', 'pass', CAPTURE_TESTS,
      nth=1, expect='test_capture_routes'),
    M('capture-routes: 取消不释放互斥锁', S('capture_routes.py'), 'service.running_task_id = None', 'pass', CAPTURE_TESTS,
      nth=2, expect='test_capture_routes'),
    M('capture-routes: 取消时连别人的互斥锁一起释放', S('capture_routes.py'), 'if service.running_task_id == task_id:', 'if True:',
      CAPTURE_TESTS, nth=1, expect='test_capture_routes'),
    M('capture-routes: 历史不按时间倒序', S('capture_routes.py'), "x.get('created_at') or '', reverse=True)",
      "x.get('created_at') or '', reverse=False)", CAPTURE_TESTS, expect='test_capture_routes'),
    M('capture-routes: 已结束的任务也能被取消', S('capture_routes.py'), "if task.get('status') in ('completed', 'failed'):", 'if False:',
      CAPTURE_TESTS, expect='test_capture_routes'),
    M('capture-routes: 取消不打 cancelled 标志', S('capture_routes.py'), "task['cancelled'] = True", 'pass', CAPTURE_TESTS,
      expect='test_capture_routes'),
    M('capture-routes: 下载开关失效（从不下载图片）', S('capture_routes.py'), "if options.get('download_images', True) and not download_path:",
      'if False:', CAPTURE_TESTS, expect='test_capture_routes'),
    M('capture-routes: 完成后不写协议采集结果', S('capture_routes.py'), "result=service.tasks[task_id]['result'],", 'result=None,',
      CAPTURE_TESTS, expect='test_capture_routes'),
    M('capture-service: cookie 缓存永不过期', S('capture_service.py'), '< 60', '< 6000000', CAPTURE_TESTS, expect='test_capture_service'),
    M('capture-service: cookie 缓存不记录时间', S('capture_service.py'), 'self._browser_cookie_ts = now', 'pass', CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: mtop 缓存不写入', S('capture_service.py'), 'self.mtop_product_cache[iid] = p', 'pass', CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: token 被拒绝后不刷新', S('capture_service.py'), "'TOKEN' in str(ret)", "'TOKEN_NEVER' in str(ret)", CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: 连续验证后不暂停', S('capture_service.py'), 'consecutive_verifications >= 3', 'consecutive_verifications >= 30',
      CAPTURE_TESTS, expect='test_capture_service'),
    M('capture-service: 店铺采集被取消后还接着采', S('capture_service.py'), "== 'failed':", "== 'failed_never':", CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: punish 类错误不计入验证次数', S('capture_service.py'), "'punish' in err_str.lower()", "'punish_never' in err_str.lower()",
      CAPTURE_TESTS, expect='test_capture_service'),
    M('capture-service: 没有商品链接也不报错', S('capture_service.py'), 'if not product_urls:', 'if False:', CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: 店铺商品全部失败也算完成', S('capture_service.py'), 'if not products:', 'if False:', CAPTURE_TESTS,
      expect='test_capture_service'),
    M('capture-service: 同一目录多条历史记录时也覆盖', S('capture_service.py'), 'if len(matches) > 1:', 'if False:', CAPTURE_TESTS,
      expect='test_capture_attribute_storage'),
    M('capture-service: 端口选择不比对资料目录', S('capture_service.py'),
      "if not browser_profile or os.path.normcase(os.path.abspath(browser_profile)) != profile_path:", 'if False:', CAPTURE_TESTS,
      expect='test_capture_browser_connection'),
    M('capture-service: 没有协议引擎也去初始化', S('capture_service.py'), 'if not self._protocol_capture_engine:', 'if False:',
      CAPTURE_TESTS, expect='test_capture_service'),
    M('capture-service: 读取 mtop 的 cookie 不过滤域名', S('capture_service.py'),
      "if 'taobao.com' not in domain and 'tmall.com' not in domain:", 'if False:', CAPTURE_TESTS, expect='test_capture_service'),
    M('capture-helpers: 淘宝登录页漏掉天猫', S('capture_helpers.py'), "'login.taobao.com' in lower or 'login.tmall.com' in lower",
      "'login.taobao.com' in lower", CAPTURE_TESTS, expect='test_capture_helpers'),
    M('capture-helpers: 资源耗尽只认 10048', S('capture_helpers.py'), '(10048, 10055, 10024)', '(10048,)', CAPTURE_TESTS,
      nth=1, expect='test_capture_helpers'),
    M('capture-helpers: 价格递归不限深度', S('capture_helpers.py'), 'depth > 4', 'depth > 400', CAPTURE_TESTS, expect='test_capture_helpers'),
    M('capture-helpers: 店铺判断把商品页也算进去', S('capture_helpers.py'),
      "if not _is_taobao_tmall_capture_url(lower_url) or _is_taobao_tmall_product_url(lower_url):",
      'if not _is_taobao_tmall_capture_url(lower_url):', CAPTURE_TESTS, expect='test_capture_helpers'),
    M('capture-helpers: 失败的任务不能重试', S('capture_helpers.py'),
      "'can_retry': bool(error_code in retryable_codes or (task or {}).get('status') == 'failed'),",
      "'can_retry': bool(error_code in retryable_codes),", CAPTURE_TESTS, expect='test_capture_helpers'),
    M('capture-helpers: ICE 商品 id 不一致也放行', S('capture_helpers.py'), 'if captured_id and current_id and captured_id != current_id:',
      'if False:', CAPTURE_TESTS, expect='test_capture_helpers'),
    M('capture-helpers: 短链落到别的域名也放行', S('capture_helpers.py'),
      "if not final_host.endswith(('.taobao.com', '.tmall.com')) and final_host not in {'taobao.com', 'tmall.com'}:", 'if False:',
      CAPTURE_TESTS, expect='test_capture_helpers'),
    M('app: 采集服务接错端口段', APP, 'capture_port_start=_CAPTURE_BROWSER_PORT_START, capture_port_end=_CAPTURE_BROWSER_PORT_END,',
      'capture_port_start=_DEBUG_BROWSER_PORT_START, capture_port_end=_DEBUG_BROWSER_PORT_END,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 采集服务的日志不是 app.logger', APP, 'record_model=Record, logger=app.logger, protocol_capture_engine=_PROTOCOL_CAPTURE_ENGINE,',
      "record_model=Record, logger=logging.getLogger('capture'), protocol_capture_engine=_PROTOCOL_CAPTURE_ENGINE,", SMOKE_TESTS,
      expect='test_sidecar_app_smoke'),
    M('app: 采集服务的 CDP 端口探测被换掉', APP, 'find_cdp_port=_find_cdp_port, load_capture_attributes=_load_capture_attributes,',
      'find_cdp_port=lambda: None, load_capture_attributes=_load_capture_attributes,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 采集路由接了另一份路径规则', APP, 'service=capture_service, normalize_save_path=normalize_save_path, get_app_root=get_app_root,',
      'service=capture_service, normalize_save_path=lambda path: path, get_app_root=get_app_root,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 更新器看不到采集任务', APP, 'capture = int(capture_service.running_task_id is not None)', 'capture = 0',
      SMOKE_TESTS + ['tests/test_update_readiness.py'], expect='test_update_readiness'),
    M('app: 采集状态在 app.py 又留了一份模块级字典', APP, 'capture_service = CaptureService(', 'capture_tasks = {}\ncapture_service = CaptureService(',
      SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    # ---------------------------------------------------------------- 淘宝发布（2026-10-20）
    # taobao_helpers
    M('taobao-helpers: 默认就往平台写（dry_run 默认值写反）', S('taobao_helpers.py'), "data.get('dry_run', True)", "data.get('dry_run', False)",
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 默认不停在提交前', S('taobao_helpers.py'), "data.get('stop_before_submit', True)", "data.get('stop_before_submit', False)",
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 默认就保存草稿', S('taobao_helpers.py'), "data.get('save_draft', False)", "data.get('save_draft', True)",
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 开关不再要求是布尔', S('taobao_helpers.py'), 'if not isinstance(value, bool):', 'if False:',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 上架方式不再校验', S('taobao_helpers.py'), 'if listing_mode not in TAOBAO_LISTING_MODES:', 'if False:',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 上架方式允许值多一个', S('taobao_helpers.py'), "('', '立刻上架', '定时上架', '放入仓库')",
      "('', '立刻上架', '定时上架', '放入仓库', '随便')", TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 请求白名单漏掉 product', S('taobao_helpers.py'), "'product', 'fill_only', ", "'fill_only', ",
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 整数类目不再映射成名称', S('taobao_helpers.py'), 'if isinstance(clazz_raw, int):', 'if False:',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 数字字符串类目不再映射成名称（批量发布的关键词变回 \'2\'）', S('taobao_helpers.py'),
      'if digits.isascii() and digits.isdigit():', 'if False:', TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 数字字符串类目不去首尾空白', S('taobao_helpers.py'), 'digits = clazz_raw.strip()', 'digits = clazz_raw',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 非 ASCII 的数字也当类目代码（上标数字会让 int() 抛异常）', S('taobao_helpers.py'),
      'if digits.isascii() and digits.isdigit():', 'if digits.isdigit():', TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 认不得的类目代码当成关键词', S('taobao_helpers.py'), "keyword = _CATEGORY_LABELS.get(clazz_raw, '')",
      'keyword = _CATEGORY_LABELS.get(clazz_raw, str(clazz_raw))', TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 价格为 0 的规格也放行', S('taobao_helpers.py'), 'if not name or price <= 0:', 'if not name or price < 0:',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 没有名字的规格也放行', S('taobao_helpers.py'), 'if not name or price <= 0:', 'if price <= 0:',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 库存不取记录里的库存', S('taobao_helpers.py'), 'stock = int(record.repo or 0)', 'stock = 0',
      TAOBAO_TESTS, expect='test_taobao_helpers'),
    M('taobao-helpers: 标题不回退到商品名', S('taobao_helpers.py'), "(record.title or '').strip() or (record.name or '').strip()",
      "(record.title or '').strip()", TAOBAO_TESTS, expect='test_taobao_helpers'),
    # taobao_service：翻译
    M('taobao-service: 标题超长不再拦', S('taobao_service.py'), 'if value and rule is not None and rule.hard:', 'if False:',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 标题为空不再拦', S('taobao_service.py'), 'if key == "title" and not value:', 'if False:',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 类目编号不再校验', S('taobao_service.py'), 'if not id_text.isascii() or not id_text.isdigit() or int(id_text) <= 0:',
      'if False:', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 价格为 0 也放行', S('taobao_service.py'), 'number_field == "price" and value <= 0', 'number_field == "price" and value < 0',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 库存允许小数', S('taobao_service.py'), 'int(value) != value', 'False', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: SKU 图片不再核对是不是登记过的', S('taobao_service.py'),
      'if not image_path.is_file() or os.path.normcase(str(image_path)) not in registered_images:', 'if not image_path.is_file():',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 类目路径分隔符错', S('taobao_service.py'), 'split(">")', 'split("<")', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: sku_mode 不再校验', S('taobao_service.py'), "if sku_mode not in ('standard', 'custom'):", 'if False:',
      TAOBAO_TESTS, expect='test_taobao_service'),
    # taobao_service：浏览器
    M('taobao-service: 取浏览器地址时平台写成抖音', S('taobao_service.py'), "resolve_active_browser(platform='taobao')",
      "resolve_active_browser(platform='douyin')", TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 非淘宝账户也去开浏览器', S('taobao_service.py'), "if account['platform'] != 'taobao':", 'if False:',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 不核对打开的是不是当前账户', S('taobao_service.py'), "if opened.get('active_profile') != account['profile_name']:",
      'if False:', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 打包运行也改 sys.path', S('taobao_service.py'), "if not getattr(sys, 'frozen', False):", 'if True:',
      TAOBAO_TESTS, expect='test_taobao_service'),
    # taobao_service：单品 worker
    M('taobao-service: 任务结束不还原环境变量', S('taobao_service.py'), "os.environ.pop('TAOBAO_MEDIA_ROUTE', None)", 'pass',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 流水线报已取消时记成失败', S('taobao_service.py'), "cancelled = (payload.get('error') or {}).get('code') == 'CANCELLED'",
      'cancelled = False', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 流水线跑完就当商品已上架', S('taobao_service.py'), "task['publish_confirmed'] = False", "task['publish_confirmed'] = True",
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 整页必填没确认也说完整填写', S('taobao_service.py'),
      "and whole_form_coverage_confirmed(verification.get('required_field_coverage'))):", 'and True):', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 回执自称 dry-run 也算完整填写', S('taobao_service.py'), "and payload.get('dry_run') is False and ", 'and ',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 做了保存草稿不说', S('taobao_service.py'), "draft_note = '；已在平台保存草稿' if saved_draft_step else ''", "draft_note = ''",
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 图片目录记录失败不报给界面', S('taobao_service.py'), "payload.setdefault('data', {})['media_record_error'] = media_record_error",
      'pass', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 图片目录记录失败不写启动日志', S('taobao_service.py'), 'self._bootstrap_log(media_record_error)', 'pass',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 填写任务拿到了提交授权', S('taobao_service.py'), 'authorization = WriteAuthorization.for_form_filling()',
      'authorization = WriteAuthorization.for_confirmed_publish()', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 取消钩子不读任务里的标志', S('taobao_service.py'), "return bool(task and task.get('cancelled'))", 'return False',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 上架方式不转发给流水线', S('taobao_service.py'), "listing_mode=options.get('listing_mode', ''),", "listing_mode='',",
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 保存草稿开关不转发给流水线', S('taobao_service.py'), "save_draft=options.get('save_draft', False),", 'save_draft=False,',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 素材准备没绑定任务的账户', S('taobao_service.py'),
      "media_profile = str((self.tasks.get(task_id) or {}).get('account_profile') or '')", "media_profile = ''",
      TAOBAO_TESTS, expect='test_taobao_service'),
    # taobao_service：批量 worker
    M('taobao-service: 批量发布不再检查取消', S('taobao_service.py'), 'if _should_cancel():', 'if False:', TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量全失败也算完成', S('taobao_service.py'), "'succeeded' if succeeded > 0 else 'failed'", "'succeeded'",
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量里抛异常的记录不计入失败', S('taobao_service.py'), 'failed += 1', 'pass', TAOBAO_TESTS, nth=1, expect='test_taobao_service'),
    M('taobao-service: 批量没有记录也不报错', S('taobao_service.py'), 'if total == 0:', 'if False:', TAOBAO_TESTS, expect='test_taobao_service'),
    # 2026-10-21 批量发布三个既有问题的修复：批量 worker 的状态与兜底、批量接口的准入、类目代码的映射
    M('taobao-service: 批量开始时不置 running', S('taobao_service.py'), "task['status'] = 'running'", 'pass', TAOBAO_TESTS, nth=1,
      expect='test_taobao_service'),
    M('taobao-service: 批量开始时不写 started_at', S('taobao_service.py'), "task['started_at'] = datetime.now().isoformat()", 'pass',
      TAOBAO_TESTS, nth=1, expect='test_taobao_service'),
    M('taobao-service: 批量里单条记录只拦 OSError（资料翻译抛 ValueError 会冒出来）', S('taobao_service.py'),
      'except Exception as exc:  # noqa: BLE001\n                failed += 1', 'except OSError as exc:  # noqa: BLE001\n                failed += 1',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量里资料翻译挪回 try 之外', S('taobao_service.py'),
      "            try:\n                # 资料翻译也在 try 里", "            product = _taobao_product_from_record(record)\n            row = dict(record.__data__)\n"
      "            _translated = self.product_request_payload(product, record=row)\n            try:\n                # 资料翻译也在 try 里",
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量外层不兜底（任务带着线程一起死）', S('taobao_service.py'),
      'except Exception as exc:\n            # 和单品 worker 同一口径', 'except ZeroDivisionError as exc:\n            # 和单品 worker 同一口径',
      TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量外层兜底后任务仍是 running', S('taobao_service.py'),
      "task['status'] = 'failed'\n                task['progress'] = 100\n                task['message'] = '淘宝批量发布失败'",
      "task['progress'] = 100\n                task['message'] = '淘宝批量发布失败'", TAOBAO_TESTS, expect='test_taobao_service'),
    M('taobao-service: 批量外层兜底不写结束时间', S('taobao_service.py'),
      "task['error'] = str(exc)\n                task['finished_at'] = datetime.now().isoformat()", "task['error'] = str(exc)",
      TAOBAO_TESTS, expect='test_taobao_service'),
    # 同日补：「未决问题」第 25 条，批量 worker 结束时还原进程级环境变量 TAOBAO_MEDIA_ROUTE（第 0 处是单品 worker 的）
    M('taobao-service: 批量结束不还原环境变量（TAOBAO_MEDIA_ROUTE 留在进程里）', S('taobao_service.py'),
      "os.environ.pop('TAOBAO_MEDIA_ROUTE', None)", 'pass', TAOBAO_TESTS, nth=1, expect='test_taobao_service'),
    M('taobao-service: 批量的环境变量还原只在没抛异常时做（finally 改成 else）', S('taobao_service.py'),
      "        finally:\n            # ⚠️ **必须还原 `TAOBAO_MEDIA_ROUTE`**（理由同 ``run_publish_task``）",
      "        else:\n            # ⚠️ **必须还原 `TAOBAO_MEDIA_ROUTE`**（理由同 ``run_publish_task``）", TAOBAO_TESTS, expect='test_taobao_service'),
    # taobao_routes
    M('taobao-routes: 填写任务可以不在提交前停止', S('taobao_routes.py'), "if options_raw['fill_only'] and (", 'if False and (',
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 已有任务在进行中也放行', S('taobao_routes.py'), 'if in_flight:', 'if False:', TAOBAO_TESTS, expect='test_sidecar_taobao_concurrency'),
    M('taobao-routes: 409 不说是哪个任务占着', S('taobao_routes.py'), "busy.get('task_id')", "''", TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 商品资料版本不再核对', S('taobao_routes.py'), "if 'expected_record_revision' in data:", 'if False:',
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 填写前不再检查账户切换互斥', S('taobao_routes.py'), 'error = accounts.account_change_blocked()', 'error = None',
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 填写任务不拉起素材中心浏览器', S('taobao_routes.py'), 'cdp_list_url = service.ensure_fill_browser()',
      'cdp_list_url = service.cdp_list_url()', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 任务不记录商品编号', S('taobao_routes.py'), "'record_id': record_id,", "'record_id': None,", TAOBAO_TESTS, nth=1,
      expect='test_taobao_routes'),
    M('taobao-routes: 任务一开始就当作已上架', S('taobao_routes.py'), "'publish_confirmed': False,", "'publish_confirmed': True,",
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 翻译结果不带商品编号', S('taobao_routes.py'), "translated['record_id'] = record_id", 'pass', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 翻译时不传商品记录（不核对图片来源）', S('taobao_routes.py'), 'service.product_request_payload(product, record=row)',
      'service.product_request_payload(product)', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 批量发布不校验平台门禁', S('taobao_routes.py'), "error = accounts.require_publish_platform('taobao', data.get('account_profile'))",
      'error = None', TAOBAO_TESTS, nth=2, expect='test_taobao_routes'),
    M('taobao-routes: 批量任务一开始就是已取消', S('taobao_routes.py'), "'cancelled': False", "'cancelled': True", TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 批量账户标识取成空', S('taobao_routes.py'), "account_profile = data.get('account_profile') or ''", "account_profile = ''",
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 查不到任务也返回 200', S('taobao_routes.py'), "return jsonify(success=False, msg='任务不存在，请重新发起'), 404",
      "return jsonify(success=False, msg='任务不存在，请重新发起'), 200", TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 已结束的任务也能被取消', S('taobao_routes.py'), "if task['status'] in ('succeeded', 'failed', 'cancelled'):", 'if False:',
      TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 取消不打标志', S('taobao_routes.py'), "task['cancelled'] = True", 'pass', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 任务列表不按时间倒序', S('taobao_routes.py'), 'reverse=True', 'reverse=False', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 批量发布有任务在跑也去拉起浏览器（不过账户切换互斥）', S('taobao_routes.py'), 'error = accounts.account_change_blocked()', 'error = None',
      TAOBAO_TESTS, nth=1, expect='test_taobao_routes'),
    M('taobao-routes: 批量发布已有任务在进行中也放行', S('taobao_routes.py'), 'if in_flight:', 'if False:', TAOBAO_TESTS, nth=1,
      expect='test_taobao_routes'),
    M('taobao-routes: 批量发布 409 不说是哪个任务占着', S('taobao_routes.py'), "busy.get('task_id')", "''", TAOBAO_TESTS, nth=1,
      expect='test_taobao_routes'),
    M('taobao-routes: 就绪度检查把缺依赖当成未预期错误', S('taobao_routes.py'), 'except (ImportError, OSError, ValueError) as exc:',
      'except (OSError, ValueError) as exc:', TAOBAO_TESTS, expect='test_taobao_routes'),
    M('taobao-routes: 资料检查的资料问题报成 503', S('taobao_routes.py'), 'return jsonify(success=False, msg=str(exc)), 400',
      'return jsonify(success=False, msg=str(exc)), 503', TAOBAO_TESTS, expect='test_taobao_routes'),
    # app.py 里读淘宝任务字典的几处 + 装配
    M('app: 保存商品的编辑保护看不到淘宝任务', APP, '(taobao_service.tasks, taobao_service.lock)', '({}, taobao_service.lock)',
      TAOBAO_TESTS + ['tests/test_whitebg_selection.py'], expect='test_product_save_snapshot'),
    M('app: 更新器不数淘宝任务', APP, "taobao = sum(t.get('status') in ('pending', 'running') for t in taobao_service.tasks.values())", 'taobao = 0',
      SMOKE_TESTS + ['tests/test_update_readiness.py'], expect='test_update_readiness'),
    M('app: 保存时不校验淘宝标题', APP, "taobao_service.product_request_payload({'title': updates['title']})", 'pass',
      TAOBAO_TESTS, expect='test_product_save_snapshot'),
    M('app: 淘宝服务接错仓库根目录', APP, 'record_model=Record, repo_root=repo_root, accounts=shop_accounts, shop_service=shop_session_service,',
      "record_model=Record, repo_root='.', accounts=shop_accounts, shop_service=shop_session_service,", SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 淘宝路由接了另一份版本校验', APP, 'resolve_data_file=resolve_data_file, require_product_revision=_require_product_revision,',
      'resolve_data_file=resolve_data_file, require_product_revision=lambda row, expected: None,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 淘宝服务的启动日志换成别的函数', APP, 'bootstrap_log=_bootstrap_log,', 'bootstrap_log=print,', SMOKE_TESTS, expect='test_sidecar_app_smoke'),

    # ---------------------------------------------------------------- upload_steps（2026-10-21 抖店上传第一步）
    # 边界契约：不依赖服务层 / 不碰服务状态 / 导入无副作用
    M('upload-steps: 页面操作导入了 flask', S('upload_steps.py'), 'import json\nimport os\nimport re\n',
      'import json\nimport os\nimport re\nfrom flask import request\n', UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 页面操作导入了设置管理器', S('upload_steps.py'), 'import json\nimport os\nimport re\n',
      'import json\nimport os\nimport re\nfrom src.config import settings_manager\n', UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 页面操作读了任务字典', S('upload_steps.py'), "return str(main_tab.url or '')", "return str(_upload_tasks or main_tab.url or '')",
      UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 页面操作读了 gui', S('upload_steps.py'), "return str(main_tab.url or '')", "return str(gui or main_tab.url or '')",
      UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 导入时就打印（模块级语句）', S('upload_steps.py'), "_SUBMIT_RESULT_BUTTONS = ('继续发布', '返回商品列表', '编辑商品')",
      "_SUBMIT_RESULT_BUTTONS = ('继续发布', '返回商品列表', '编辑商品')\nprint('upload_steps loaded')", UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 常量右值里调函数', S('upload_steps.py'), '_SUBMIT_CONFIRM_TIMEOUT = 60.0', '_SUBMIT_CONFIRM_TIMEOUT = float(60.0)',
      UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    # 装配：app.py 里的同名是同一个对象，钩子注册的是那里的弹层清理函数
    M('app: 交互恢复钩子没有注册', APP, 'register_interaction_recovery_hook(_dismiss_interfering_overlays)',
      'register_interaction_recovery_hook(None)', UPLOAD_STEPS_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 交互恢复钩子注册成别的函数', APP, 'register_interaction_recovery_hook(_dismiss_interfering_overlays)',
      'register_interaction_recovery_hook(lambda tab, context=None: None)', UPLOAD_STEPS_TESTS, expect='test_sidecar_app_smoke'),
    M('app: 页面步骤在 app.py 里被换成副本', APP, '    _wait_login_complete,\n)\n',
      '    _wait_login_complete,\n)\n_open_publish_page = lambda *a, **k: None\n', UPLOAD_STEPS_TESTS, expect='test_sidecar_app_smoke'),
    # 搬过去的代码本身仍被老测试守着（这些测试现在读 upload_steps.py）
    M('upload-steps: 数字规整不再去千分位', S('upload_steps.py'), ".replace(',', '')", ".replace(';', '')",
      UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 句柄失效不再认「元素对象已失效」', S('upload_steps.py'), "'元素对象已失效' in text", "'元素对象已失效!' in text",
      UPLOAD_STEPS_TESTS, expect='test_upload_steps'),
    M('upload-steps: 标题填写的重试次数变了', S('upload_steps.py'), 'for attempt in range(1, 4):', 'for attempt in range(1, 5):',
      UPLOAD_STEPS_TESTS, expect='test_publish_stability_fixes'),
    M('upload-steps: 品牌调用点的写法变了', S('upload_steps.py'), 'ensure_no_brand(main_tab)', 'ensure_no_brand(main_tab, True)',
      UPLOAD_STEPS_TESTS, nth=2, expect='test_select_text_brand_verification'),
    M('upload-steps: 价格库存不再跳过空白行', S('upload_steps.py'), "print(f'跳过价格库存空白行：{blank_rows} 行')", "print(f'空白行：{blank_rows} 行')",
      UPLOAD_STEPS_TESTS, expect='test_upload_price_stock_locators'),
    M('upload-steps: 提交未确认不再抛异常', S('upload_steps.py'), 'raise PublishUnconfirmedError(', 'return False; raise PublishUnconfirmedError(',
      UPLOAD_STEPS_TESTS, expect='test_submit_publish_unconfirmed'),
    M('upload-steps: 提交未确认不再标记待确认', S('upload_steps.py'), '    record.status = 2\n    record.save()\n    current_url = _get_current_tab_url(main_tab)',
      '    record.save()\n    current_url = _get_current_tab_url(main_tab)', UPLOAD_STEPS_TESTS, expect='test_submit_publish_unconfirmed'),
]


def md5(path):
    with open(path, 'rb') as fp:
        return hashlib.md5(fp.read()).hexdigest()


def apply_mutation(text, mutation):
    """返回改坏后的文本；旧文本出现次数不够时返回 None。"""
    count = text.count(mutation['old'])
    if count == 0 or mutation['nth'] >= count:
        return None
    pos = -1
    for _ in range(mutation['nth'] + 1):
        pos = text.index(mutation['old'], pos + 1)
    return text[:pos] + mutation['new'] + text[pos + len(mutation['old']):]


def run_tests(tests):
    """返回 (退出码或 'timeout', 失败的测试文件名集合)。"""
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    try:
        done = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--no-header', '--tb=no', '-W', 'ignore']
            + tests, cwd=REPO, env=env, capture_output=True, text=True, encoding='utf-8', timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'timeout', set()
    failed_files = set()
    for line in done.stdout.splitlines():
        if line.startswith(('FAILED ', 'ERROR ')):
            failed_files.add(line.split()[1].split('::')[0].split('/')[-1][:-3])
    return done.returncode, failed_files


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else 'all'
    selected = [m for m in MUTATIONS if wanted == 'all' or any(k in m['name'] for k in wanted.split(','))]
    originals = {}
    for m in selected:
        originals.setdefault(m['path'], md5(m['path']))
    problems = []
    try:
        for index, m in enumerate(selected, 1):
            with io.open(m['path'], encoding='utf-8', newline='') as fp:
                text = fp.read()
            mutated = apply_mutation(text, m)
            if mutated is None:
                print('!! 改动无法应用（旧文本出现次数不够）: %s' % m['name'], flush=True)
                problems.append(m['name'] + '（未应用）')
                continue
            try:
                with io.open(m['path'], 'w', encoding='utf-8', newline='') as fp:
                    fp.write(mutated)
                code, failed = run_tests(m['tests'])
            finally:
                with io.open(m['path'], 'w', encoding='utf-8', newline='') as fp:
                    fp.write(text)
            if code == 'timeout':
                verdict = '超时'
            else:
                verdict = '红✓' if code != 0 else '绿✗'
            print('%2d/%d %-4s %s\n        失败的测试文件: %s' % (
                index, len(selected), verdict, m['name'], ', '.join(sorted(failed)) or '-'), flush=True)
            if verdict != '红✓' or (m['expect'] and m['expect'] not in failed):
                problems.append('%s [%s]' % (m['name'], verdict))
    finally:
        for path, digest in originals.items():
            assert md5(path) == digest, '文件没有恢复: ' + path
    print('\n改动总数 %d，需要关注 %d' % (len(selected), len(problems)))
    for name in problems:
        print('  -', name)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
