# -*- coding: utf-8 -*-
"""商品链接采集接口（/api/capture/*）：启动 / 状态 / 历史 / 取消 / 导入。

``start_capture`` 一个函数 1100+ 行（里面的后台线程跑着整套采集流程），按「先机械搬迁、再拆」的原则原样保留；状态都在 ``CaptureService``。后台线程里没有 Flask 应用上下文，所以日志走 ``service.logger``（应用入口传入的 ``app.logger``），不能用 ``current_app``。"""
import json
import os
import time as system_time
import traceback
from datetime import datetime
from urllib.request import urlopen

from flask import Blueprint, jsonify, request

from src.capture_url_utils import normalize_capture_url
from .capture_helpers import (
    _build_1688_sku_info,
    _capture_failure_details,
    _capture_task_recovery_info,
    _capture_wait_seconds,
    _collect_1688_detail_images,
    _detect_local_proxy_risk,
    _extract_1688_context_snapshot,
    _extract_capture_product_id,
    _finalize_protocol_capture_record,
    _get_capture_browser_user_data_path,
    _is_1688_antibot_page,
    _is_1688_capture_url,
    _is_1688_login_url,
    _is_taobao_login_url,
    _is_taobao_tmall_capture_url,
    _is_taobao_tmall_store_url,
    _resolve_capture_redirect_url,
)


def create_capture_blueprint(*, service, normalize_save_path, get_app_root, settings_manager):
    """``service`` 是 ``CaptureService``（任务状态、日志、提取逻辑）；``normalize_save_path`` / ``get_app_root`` 留在应用入口（路径规则依赖入口文件的位置，别的业务域也在用）；``settings_manager`` 提供用户保存的采集方式偏好。"""
    routes = Blueprint('capture', __name__)

    @routes.route('/api/capture/start', methods=['POST'])
    def start_capture():
        """启动商品采集任务"""
        try:
            service.logger.info("=" * 80)
            service.logger.info("📥 收到采集请求")
        
            data = request.get_json()
            if not data:
                service.logger.error("❌ 无效的请求数据")
                return jsonify({'success': False, 'message': '无效的请求数据'})
        
            raw_url = str(data.get('url', '') or '').strip()
            url = normalize_capture_url(raw_url)
            options = data.get('options', {
                'download_images': True,
                'extract_sku': True,
                'extract_params': True
            })

            service.logger.info(f"🔗 采集URL: {url}")
            service.logger.info(f"⚙️ 采集选项: {options}")

            # 验证URL
            if not url:
                service.logger.error("❌ URL为空")
                return jsonify({'success': False, 'message': '请输入商品或店铺链接'})

            try:
                resolved_url, short_url = _resolve_capture_redirect_url(url)
                if short_url:
                    service.logger.info(f"🔁 淘宝短链已解析: {short_url} -> {resolved_url}")
                url = resolved_url
            except ValueError as resolve_error:
                service.logger.error(f"❌ 短链解析失败: {resolve_error}")
                return jsonify({'success': False, 'message': str(resolve_error)})

            is_1688 = _is_1688_capture_url(url)
            is_taobao_tmall = _is_taobao_tmall_capture_url(url)
            if not is_1688 and not is_taobao_tmall:
                service.logger.error(f"❌ 不支持的URL: {url}")
                return jsonify({'success': False, 'message': '仅支持淘宝/天猫/1688商品链接，或淘宝/天猫店铺链接'})

            # 平台 + 采集方式由后端按 URL 自动识别，并从用户设置读取每平台的偏好。
            # 1688 与 淘宝/天猫 是两个独立平台，从 capture_preferences 分别取对应字段，不跨用。
            platform_choice = '1688' if is_1688 else 'taobao'
            try:
                _ms = settings_manager.get_settings()
                _ac = settings_manager.normalize_automation_config(_ms.automation_config)
                _prefs = _ac.get('capture_preferences') or {}
                if platform_choice == '1688':
                    capture_mode = str(_prefs.get('alibaba_1688_mode') or 'dom').strip().lower()
                else:
                    capture_mode = str(_prefs.get('taobao_tmall_mode') or 'dom').strip().lower()
                if capture_mode not in {'dom', 'protocol'}:
                    capture_mode = 'dom'
            except Exception as _pref_err:
                service.logger.warning(f"⚠️ 读取采集偏好失败，回退默认 dom: {_pref_err}")
                capture_mode = 'dom'

            service.logger.info(f"🎯 平台: {platform_choice} | 采集方式: {capture_mode}（按用户设置自动选择）")

            product_id = _extract_capture_product_id(url)

            # 生成任务ID
            import hashlib
            task_id = f"capture_{int(system_time.time())}_{hashlib.md5(url.encode()).hexdigest()[:8]}"
            service.logger.info(f"🆔 生成任务ID: {task_id}")

            # 并发互斥：同一时刻只允许一个采集任务在跑，避免共享 capture-browser-profile 时
            # Chrome 单 user_data_dir 限制导致两个任务互相打断对方的页面状态。
            with service.lock:
                if service.running_task_id:
                    running = service.running_task_id
                    service.logger.warning(f"❌ 已有采集任务在跑: {running}，拒绝新请求 {task_id}")
                    return jsonify({
                        'success': False,
                        'message': f'已有采集任务正在运行 ({running})，请等待完成或先取消后再试'
                    })
                service.running_task_id = task_id
                service.logger.info(f"🔒 已占用采集互斥锁: {task_id}")

            protocol_capture_runtime = service.start_protocol_capture_record(
                source_url=url,
                task_id=task_id,
                options=options,
                product_id=product_id,
            )
        
            # 创建任务
            task = {
                'task_id': task_id,
                'url': url,
                'original_url': raw_url if raw_url and raw_url != url else '',
                'options': options,
                'platform': platform_choice,
                'capture_mode': capture_mode,
                'status': 'pending',
                'progress': 0,
                'message': '任务创建成功',
                'created_at': datetime.now().isoformat(),
                'result': None,
                'error_code': '',
                'cancelled': False,
                'protocol_capture_root': protocol_capture_runtime.get('root') if protocol_capture_runtime else '',
            }
        
            service.tasks[task_id] = task
            service.logger.info(f"✅ 任务已创建: {task_id}")
        
            # 在后台线程中启动采集
            def run_capture_task():
                # 在函数开头导入所需模块，避免作用域问题
                import traceback
                import re
                task_url = service.tasks.get(task_id, {}).get('url', url)
                # 读取本任务的平台/采集方式（默认 auto + dom，保证旧调用兼容）
                task_platform = service.tasks.get(task_id, {}).get('platform', 'auto')
                task_capture_mode = service.tasks.get(task_id, {}).get('capture_mode', 'dom')

                try:
                    service.logger.info(f"🚀 开始执行采集任务: {task_id}")
                    service.logger.info(f"🎯 任务平台: {task_platform} | 采集方式: {task_capture_mode}")

                    # 采集方式分发说明：
                    #   - dom（默认）：当前已实现的两套独立提取路径
                    #       · 1688  → JS 注入读取 window.context（不跨用淘宝协议）
                    #       · 淘宝/天猫 → 浏览器内 mtop 客户端调用（不跨用 1688 协议）
                    #   - protocol（预览版）：基于 CDP Network 域被动抓接口响应。
                    #       完整实现需要枚举每个平台的关键接口并解析响应，工作量较大；
                    #       本版本先把请求/响应原文落到 protocol_capture_root 目录便于离线复盘，
                    #       数据提取仍走 DOM 路径以保证用户能拿到产品数据，不会出现"功能空转"。
                    if task_capture_mode == 'protocol':
                        service.logger.warning(
                            "⚠️ 协议采集为预览版：本次仍按 DOM 路径完成数据提取，"
                        "协议层网络快照将被记录到 protocol_capture_root 供后续抓包分析"
                        )
                        service.tasks[task_id]['message'] = '协议采集（预览版）：本次走 DOM 提取并记录协议层网络快照...'
                    else:
                        service.logger.info("📋 采集方式: DOM 采集（读浏览器渲染数据）")

                    # 更新任务状态
                    service.tasks[task_id]['status'] = 'running'
                    service.tasks[task_id]['progress'] = 10
                    if not service.tasks[task_id].get('message', '').startswith('协议采集'):
                        service.tasks[task_id]['message'] = '正在启动浏览器...'
                    service.logger.info(f"📊 进度: 10% - 正在启动浏览器...")
                
                    # 使用DrissionPage进行采集（因为项目已经有了这个依赖）
                    try:
                        from DrissionPage import ChromiumPage, ChromiumOptions
                        service.logger.info("✅ DrissionPage 导入成功")
                    except ImportError as e:
                        service.logger.error(f"❌ DrissionPage 导入失败: {e}")
                        raise Exception(f"缺少依赖库 DrissionPage，请安装: pip install DrissionPage")
                
                    # 配置浏览器（添加反爬虫策略）
                    service.logger.info("⚙️ 配置浏览器选项...")
                    co = ChromiumOptions()
                    co.headless(False)  # 显示浏览器，方便用户登录
                    capture_port = service.select_capture_browser_port()
                    capture_user_data_path = _get_capture_browser_user_data_path()
                    co.set_paths(local_port=capture_port, user_data_path=capture_user_data_path)
                    co.set_user('Default')
                    service.logger.info(f"✅ 采集浏览器配置: port={capture_port}, user_data={capture_user_data_path}")
                    co.set_load_mode('eager')  # 采集页常驻长连接资源，避免 page.get() 长时间等待 complete
                
                    # 🛡️ 反爬虫策略配置
                    # 1. 设置真实的User-Agent
                    co.set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

                    # 2. 禁用自动化检测特征

                    # 3. 添加更多反检测参数
                    co.set_argument('--disable-dev-shm-usage')
                    # co.set_argument('--no-sandbox')  # 已移除：会显示警告提示
                    co.set_argument('--disable-gpu')

                    # 4. 设置窗口大小（模拟真实用户）
                    co.set_argument('--window-size=1920,1080')

                    # 5. webdriver 标记由 addScriptToEvaluateOnNewDocument 里的 JS 覆盖处理。
                    # --disable-blink-features=AutomationControlled 在 Chrome 120+ 已废弃，
                    # 加了反而显示"不受支持的命令行标记"警告，不加。

                    # 6. 强制不走系统代理（关键！）
                    # 现场实测：用户机器开启 Clash 类本地代理(127.0.0.1:7897)时，规则集会拦截
                    #   - g.alicdn.com/AWSC/...baxia*.js（阿里风控"八仙"脚本）
                    #   - gm.mmstat.com / log.mmstat.com（阿里埋点）
                    # 阿里登录页依赖 baxia.js 获取风控 token 才会调用 qrcode/generate.do 生成二维码，
                    # baxia 被掐就会出现"二维码框存在但永远空白"的现象。
                    # 1688/淘宝/天猫都是国内站点，采集浏览器直连即可，不需要也不应走系统代理。
                    co.set_argument('--no-proxy-server')
                    # 备用兜底：即便上面被某些场景忽略，bypass-list 也会强制绕过阿里域名
                    co.set_argument(
                        '--proxy-bypass-list=<-loopback>;'
                    '*.taobao.com;*.tmall.com;*.alibaba.com;*.alibabagroup.com;'
                    '*.1688.com;*.alicdn.com;*.aliyun.com;*.alipay.com;'
                    '*.mmstat.com;*.alipayobjects.com'
                    )

                    service.logger.info("✅ 反爬虫策略已配置（含强制直连绕过本地代理）")
                
                    # 更新进度
                    service.tasks[task_id]['progress'] = 20
                    service.tasks[task_id]['message'] = '正在启动采集浏览器...'
                    service.logger.info(f"📊 进度: 20% - 正在启动采集浏览器...")
                
                    # 创建页面
                    service.logger.info("🌐 正在启动浏览器...")
                    page = ChromiumPage(co)

                    # ============== 持久化注入：反检测 + mmstat 埋点短路 ==============
                    # 用 Page.addScriptToEvaluateOnNewDocument，每个新 document 加载前自动注入。
                    # 旧的 page.run_js 只对当前空白页生效，page.get(商品页) 之后就失效了。
                    #
                    # mmstat 短路（关键）：
                    #   现场实测：用户机器开 Clash / verge-mihomo / Mihomo 等本地代理工具时，
                    #   规则集常把 *.mmstat.com（阿里埋点）加入 REJECT 名单，导致请求 SSL 失败。
                    #   1688 详情页的初始化 JS 依赖埋点上报，埋点失败会触发 launch_regist_error
                    #   并 abort 整个主框架，所有商品模块 JS 被级联取消，最终页面只剩空骨架。
                    #   `--no-proxy-server` 启动参数对 TUN 模式代理无效（TUN 在网卡层接管）。
                    #   这里在浏览器内 hook fetch / XHR / sendBeacon / Image，让所有 *.mmstat.com
                    #   请求立即返回 fake 200，业务 JS 以为埋点成功，正常继续渲染。
                    init_script = r'''
                (function () {
                  // 反检测
                  try {
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                    if (window.navigator.permissions && window.navigator.permissions.query) {
                      const origQuery = window.navigator.permissions.query;
                      window.navigator.permissions.query = function (p) {
                        return p && p.name === 'notifications'
                          ? Promise.resolve({ state: Notification.permission })
                          : origQuery(p);
                      };
                    }
                  } catch (e) {}

                  // mmstat 短路 —— 绕过本地代理拦截阿里埋点导致的页面渲染中断
                  var BLOCK_PATTERNS = [ /mmstat\.com/i ];
                  function shouldFake(url) {
                    if (typeof url !== 'string') return false;
                    for (var i = 0; i < BLOCK_PATTERNS.length; i++) {
                      if (BLOCK_PATTERNS[i].test(url)) return true;
                    }
                    return false;
                  }

                  if (window.fetch) {
                    var origFetch = window.fetch;
                    window.fetch = function (input, init) {
                      var url = typeof input === 'string' ? input : (input && input.url) || '';
                      if (shouldFake(url)) {
                        return Promise.resolve(new Response('', { status: 200, headers: { 'Content-Type': 'text/plain' } }));
                      }
                      return origFetch.apply(this, arguments);
                    };
                  }

                  if (window.XMLHttpRequest) {
                    var origOpen = XMLHttpRequest.prototype.open;
                    var origSend = XMLHttpRequest.prototype.send;
                    XMLHttpRequest.prototype.open = function (method, url) {
                      try { this.__fakeUrl = shouldFake(url) ? url : null; } catch (e) {}
                      return origOpen.apply(this, arguments);
                    };
                    XMLHttpRequest.prototype.send = function () {
                      var self = this;
                      if (self.__fakeUrl) {
                        setTimeout(function () {
                          try {
                            Object.defineProperty(self, 'readyState',   { configurable: true, get: function () { return 4; } });
                            Object.defineProperty(self, 'status',       { configurable: true, get: function () { return 200; } });
                            Object.defineProperty(self, 'statusText',   { configurable: true, get: function () { return 'OK'; } });
                            Object.defineProperty(self, 'responseText', { configurable: true, get: function () { return ''; } });
                            Object.defineProperty(self, 'response',     { configurable: true, get: function () { return ''; } });
                            if (typeof self.onreadystatechange === 'function') self.onreadystatechange();
                            if (typeof self.onload === 'function') self.onload();
                            self.dispatchEvent(new Event('readystatechange'));
                            self.dispatchEvent(new Event('load'));
                            self.dispatchEvent(new Event('loadend'));
                          } catch (e) {}
                        }, 0);
                        return;
                      }
                      return origSend.apply(this, arguments);
                    };
                  }

                  if (navigator.sendBeacon) {
                    var origBeacon = navigator.sendBeacon.bind(navigator);
                    navigator.sendBeacon = function (url, data) {
                      if (shouldFake(url)) return true;
                      return origBeacon(url, data);
                    };
                  }

                  try { console.log('[capture-init] anti-detect + mmstat-shim installed'); } catch (e) {}
                })();
                '''
                    try:
                        page.add_init_js(init_script)
                        service.logger.info("✅ init 脚本已持久化注入（反检测 + mmstat 短路）")
                    except Exception as init_err:
                        # add_init_js 不可用时降级为 run_js（只对当前页面生效，但聊胜于无）
                        service.logger.warning(f"⚠️ add_init_js 失败，降级为 run_js: {init_err}")
                        try:
                            page.run_js(init_script)
                        except Exception as run_err:
                            service.logger.error(f"❌ 反检测/mmstat 脚本注入失败: {run_err}")
                
                    # 从任务中获取URL
                    is_1688 = _is_1688_capture_url(task_url)
                    is_taobao_tmall = _is_taobao_tmall_capture_url(task_url)
                    is_taobao_tmall_store = (not is_1688) and _is_taobao_tmall_store_url(task_url)
                    service.tasks[task_id]['message'] = '正在访问商品页面...'
                    service.logger.info(f"📊 进度: 20% - 正在访问商品页面...")
                
                    # 🛡️ 首页导航：建立浏览轨迹（1688 跳过避免触发风控）
                    if not is_taobao_tmall_store and not is_1688:
                        try:
                            if 'tmall.com' in task_url:
                                page.get('https://www.tmall.com', timeout=15)
                            else:
                                page.get('https://www.taobao.com', timeout=15)
                            system_time.sleep(1)
                        except Exception as e:
                            service.logger.warning(f"⚠️ 首页访问失败: {e}")

                    # 访问目标页面
                    service.logger.info(f"🔗 正在访问: {task_url}")
                    if is_1688:
                        # 1688: DrissionPage page.get 会因登录重定向触发刷新检测而崩溃，用 CDP 导航
                        # 关键：必须用本任务自己启动的 capture_port，不能用 _find_cdp_port() —
                        # 否则会扫到系统里其他 Chrome（如 DrissionPage 默认 9222），把别人的 Chrome
                        # 强制导航到 1688 商品页，而真正的采集浏览器还停在空白页。
                        try:
                            import websocket as _ws1688nav
                            cdp_port = capture_port
                            targets1688 = json.loads(urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
                            # 优先选 DrissionPage 当前控制的那个 tab，避免误导航到其他 tab
                            current_tab_id = ''
                            try:
                                current_tab_id = str(getattr(page, 'tab_id', '') or '')
                            except Exception:
                                current_tab_id = ''
                            page_targets = [t for t in targets1688 if t.get('type') == 'page']
                            target_for_nav = None
                            if current_tab_id:
                                for t in page_targets:
                                    if t.get('id') == current_tab_id:
                                        target_for_nav = t
                                        break
                            if target_for_nav is None and page_targets:
                                target_for_nav = page_targets[0]
                            if target_for_nav:
                                ws1688 = _ws1688nav.create_connection(target_for_nav['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
                                ws1688.settimeout(5)
                                # 双保险：在 Page.navigate 之前通过同一个 WebSocket 直接注册
                                # Page.addScriptToEvaluateOnNewDocument，确保 mmstat 短路脚本
                                # 在本次导航的新 document 加载前生效。
                                # add_init_js 依赖 DrissionPage API 是否可用；旧版 API 不可用时
                                # 会降级为 run_js（只对当前空白页生效），CDP 导航后就失效。
                                # 这里直接通过 CDP 再注册一次，不依赖 DrissionPage 版本。
                                try:
                                    ws1688.send(json.dumps({
                                        'id': 0,
                                        'method': 'Page.addScriptToEvaluateOnNewDocument',
                                        'params': {'source': init_script},
                                    }))
                                except Exception as _reg_err:
                                    service.logger.warning(f"⚠️ 1688 CDP addScriptToEvaluateOnNewDocument 注册失败（不影响采集）: {_reg_err}")
                                ws1688.send(json.dumps({'id': 1, 'method': 'Page.enable'}))
                                ws1688.send(json.dumps({'id': 2, 'method': 'Page.navigate', 'params': {'url': task_url}}))
                                # 等待页面加载：基础 5 秒 + 轮询等 window.context 商品数据就绪
                                # （window.context 就绪 ≈ 1688 SPA 主框架渲染完成）
                                system_time.sleep(5)
                                for _w1688 in range(5):
                                    try:
                                        if page.run_js(
                                            "return !!(window.context?.result?.global"
                                        "?.globalData?.model?.offerDetail?.subject)"
                                        ):
                                            service.logger.info(f"✅ 1688 window.context 就绪（约 {5 + _w1688 * 2}s）")
                                            break
                                    except Exception:
                                        pass
                                    system_time.sleep(2)
                                ws1688.close()
                        except Exception as _cdp_nav_err:
                            service.logger.warning(f"1688 CDP导航失败({_cdp_nav_err})，尝试DrissionPage")
                            try:
                                page.get(task_url, timeout=30)
                            except Exception as _dr_err:
                                service.logger.warning(f"1688导航异常，等待页面稳定: {_dr_err}")
                                system_time.sleep(5)
                    else:
                        try:
                            page.get(task_url, timeout=30)
                        except Exception as nav_err:
                            err_str = str(nav_err)
                            if '刷新' in err_str or 'refresh' in err_str.lower():
                                service.logger.warning(f"页面刷新/重定向 ({err_str[:80]})，等待页面稳定...")
                                system_time.sleep(5)
                            else:
                                raise
                    current_url = page.url
                    service.logger.info(f"📍 当前URL: {current_url[:100]}")

                    if is_1688 and _is_1688_antibot_page(page):
                        antibot_wait_seconds = _capture_wait_seconds('CAPTURE_ANTIBOT_WAIT_SECONDS', 120)
                        service.logger.warning(f"⚠️ 1688 触发风控验证页，等待用户处理（最多{antibot_wait_seconds}秒）...")
                        service.tasks[task_id]['message'] = '⏳ 1688 触发访问验证，请在采集浏览器中完成验证...'
                        wait_deadline = system_time.time() + antibot_wait_seconds
                        while system_time.time() < wait_deadline:
                            if service.tasks.get(task_id, {}).get('cancelled'):
                                return
                            system_time.sleep(2)
                            if not _is_1688_antibot_page(page):
                                service.logger.info("✅ 1688 验证通过，重新进入商品页")
                                try:
                                    page.get(task_url, timeout=30)
                                except Exception:
                                    pass
                                system_time.sleep(3)
                                break
                        else:
                            service.logger.error("❌ 1688 风控验证等待超时")
                            service.tasks[task_id]['status'] = 'failed'
                            service.tasks[task_id]['progress'] = 0
                            service.tasks[task_id]['error_code'] = '1688_antibot_verification'
                            service.tasks[task_id]['message'] = (
                                f'1688 触发访问验证，{antibot_wait_seconds} 秒内未完成验证。请在采集浏览器中完成验证后重新采集；'
                            '如果反复触发，先使用普通浏览器打开同一商品链接确认账号/网络环境正常。'
                            )
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=service.tasks[task_id]['message'],
                                error='1688_antibot_verification',
                            )
                            return

                    if not is_1688 and ('punish' in current_url or 'sec.taobao.com' in current_url or 'bixi.alicdn.com' in current_url):
                        service.logger.warning("⚠️ 触发安全验证，等待用户处理（最多120秒）...")
                        service.tasks[task_id]['message'] = '⏳ 触发安全验证，请在浏览器中完成验证...'
                        wait_count = 0
                        while wait_count < 60:
                            if service.tasks.get(task_id, {}).get('cancelled'):
                                return
                            system_time.sleep(2)
                            wait_count += 1
                            current_url = page.url
                            if 'punish' not in current_url and 'sec.taobao.com' not in current_url and 'bixi.alicdn.com' not in current_url:
                                service.logger.info("✅ 验证通过，继续采集")
                                page.get(task_url, timeout=30)
                                system_time.sleep(3)
                                break
                        else:
                            service.logger.error("❌ 验证等待超时")
                            service.tasks[task_id]['status'] = 'failed'
                            service.tasks[task_id]['progress'] = 0
                            service.tasks[task_id]['error_code'] = 'triggered_antibot_verification'
                            service.tasks[task_id]['message'] = '验证等待超时，请手动完成验证后重新采集'
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=service.tasks[task_id]['message'],
                                error='triggered_antibot_verification',
                            )
                            return
                
                    service.logger.info("✅ 页面访问成功，未被拦截")
                
                    # 等待页面完全加载
                    system_time.sleep(3)  # 等待3秒，确保页面完全渲染
                
                    # 检查是否需要登录（通过URL判断，更快更准确）
                    service.tasks[task_id]['progress'] = 30
                    service.tasks[task_id]['message'] = '检测登录状态...'
                    service.logger.info(f"📊 进度: 30% - 检测登录状态...")
                
                    login_detected = False
                    try:
                        # 获取当前页面URL
                        current_url = page.url
                        service.logger.info(f"🔍 当前URL: {current_url}")
                    
                        # 通过 URL 判断是否需要登录。
                        # 关键：1688 和淘宝/天猫是两个独立平台，登录页也是两套独立实体：
                        #   - 1688 任务：当前 URL 可能是 1688 自己的登录页（_is_1688_login_url），
                        #     也可能是淘宝"会员通"统一登录页（_is_taobao_login_url）；
                        #     只要 cookie 写到对应域名上，回到 detail.1688.com 后 **协议提取永远走 1688 的 window.context**，
                        #     绝不会因为登录页是淘宝域名就改用淘宝的 mtop 协议。
                        #   - 淘宝/天猫任务：只识别 _is_taobao_login_url，不会去看 1688 的登录页。
                        if is_1688:
                            on_login_page = (
                                _is_1688_login_url(current_url)
                                or _is_taobao_login_url(current_url)
                            )
                            login_hint_msg = (
                                '需要登录 1688，请在浏览器中完成登录（建议使用账号密码，扫码登录可能被风控）...'
                            )
                        else:
                            on_login_page = _is_taobao_login_url(current_url)
                            login_hint_msg = '需要登录淘宝/天猫，请在浏览器中完成登录...'

                        # 检测到登录页时，主动诊断本地代理/TUN 环境（二维码空白的常见根因），
                        # 把根因和解决办法直接推给用户，避免对着空白二维码干等到超时。
                        proxy_risk_hint = _detect_local_proxy_risk()

                        if on_login_page:
                            login_detected = True
                            service.logger.warning(f"⚠️ 检测到登录页面: {current_url[:120]}")
                            if proxy_risk_hint:
                                login_hint_msg = login_hint_msg + ' ' + proxy_risk_hint
                                service.logger.warning(f"🛑 代理环境风险: {proxy_risk_hint}")
                            service.tasks[task_id]['message'] = login_hint_msg

                            # 等待用户登录（最多等待 120 秒）
                            wait_count = 0
                            service.logger.info("⏳ 等待用户完成登录（最多120秒）...")
                            while wait_count < 60 and login_detected:
                                if service.tasks.get(task_id, {}).get('cancelled'):
                                    return
                                system_time.sleep(2)
                                wait_count += 1

                                # 检查 URL 是否已离开登录页
                                current_url = page.url
                                if is_1688:
                                    still_on_login = (
                                        _is_1688_login_url(current_url)
                                        or _is_taobao_login_url(current_url)
                                    )
                                else:
                                    still_on_login = _is_taobao_login_url(current_url)

                                if not still_on_login:
                                    if is_taobao_tmall_store:
                                        login_detected = False
                                        service.logger.info(f"✅ 店铺登录完成，回到店铺链接: {task_url[:100]}")
                                        page.get(task_url, timeout=30)
                                        system_time.sleep(2)
                                        break
                                    # 确认已经跳转回商品页面
                                    if (
                                        (is_1688 and ('detail.1688.com' in current_url or 'offer.1688.com' in current_url or '/offer/' in current_url))
                                        or (not is_1688 and ('detail.tmall.com' in current_url or 'item.taobao.com' in current_url))
                                    ):
                                        login_detected = False
                                        service.logger.info(f"✅ 登录完成，当前URL: {current_url[:100]}")
                                        # 等待页面稳定加载
                                        system_time.sleep(2)
                                        break
                                    # 已经离开登录页但没回到商品页（1688 登录后常停在首页或中转页），
                                    # 主动导航回原始商品链接
                                    service.logger.info(
                                        f"✅ 已离开登录页但未跳回商品页，主动重新导航: {current_url[:80]}"
                                    )
                                    try:
                                        page.get(task_url, timeout=30)
                                        system_time.sleep(3)
                                        login_detected = False
                                        break
                                    except Exception as _renav_err:
                                        service.logger.warning(f"⚠️ 登录后重新导航失败: {_renav_err}")
                                        # 继续等下一轮检测，不立刻判失败
                        
                            if login_detected:
                                service.logger.warning("⏰ 登录等待超时")
                                service.tasks[task_id]['status'] = 'failed'
                                service.tasks[task_id]['progress'] = 0
                                service.tasks[task_id]['error_code'] = 'login_timeout'
                                timeout_msg = (
                                    '1688 登录等待超时，当前会话仍停留在登录页，请先在浏览器中完成登录后再重试'
                                    if is_1688
                                    else '淘宝/天猫登录等待超时，当前会话仍停留在登录页，请先在浏览器中完成登录后再重试'
                                )
                                if proxy_risk_hint:
                                    timeout_msg = timeout_msg + ' ' + proxy_risk_hint
                                service.tasks[task_id]['message'] = timeout_msg
                                _finalize_protocol_capture_record(
                                    protocol_capture_runtime,
                                    task_id=task_id,
                                    source_url=task_url,
                                    status='failed',
                                    progress=0,
                                    message=service.tasks[task_id]['message'],
                                    error='login_timeout',
                                )
                                return
                        else:
                            service.logger.info("✅ 无需登录或已登录")
                    except Exception as e:
                        service.logger.warning(f"⚠️ 登录检测异常: {e}")

                    if is_taobao_tmall_store:
                        service.logger.info("🏪 检测到淘宝/天猫店铺链接，进入店铺批量采集分支")
                        service.run_taobao_tmall_store_capture(page, task_id, task_url, options, protocol_capture_runtime)
                        return
                
                    # 🔧 提取商品ID
                    extracted_product_id = ''
                    try:
                        extracted_product_id = _extract_capture_product_id(task_url)
                        if extracted_product_id:
                            service.logger.info(f"✅ 商品ID: {extracted_product_id}")
                        else:
                            service.logger.warning("⚠️ 未能从URL提取商品ID")
                            extracted_product_id = f"product_{int(system_time.time())}"
                    except Exception as e:
                        service.logger.error(f"❌ 提取商品ID失败: {e}")
                        extracted_product_id = f"product_{int(system_time.time())}"
                
                    # 🔧 协议采集单品
                    service.tasks[task_id]['progress'] = 50
                    service.tasks[task_id]['message'] = '正在提取商品信息...'
                    service.logger.info(f"📊 进度: 50% - 正在提取商品信息...")

                    if is_1688:
                        # ==== 1688 协议提取：window.context 数据 ====
                        service.logger.info("🔍 1688协议提取: 读取 window.context")
                        product_data = {
                            'product_id': _extract_capture_product_id(task_url),
                            'title': '',
                            'price': {'current': 0, 'original': None, 'currency': 'CNY'},
                            'main_images': [],
                            'detail_images': [],
                            'sku_info': [],
                            'parameters': [],
                        }

                        # ============================================================
                        # 关键校验：浏览器实际跳到的 offerId 必须等于 task_url 的 offerId
                        # ------------------------------------------------------------
                        # 之前的 CDP Page.navigate 只 sleep(5) 不等导航完成回调；如果导航被
                        # 1688 风控阻塞/CDP tab 选错/旧 profile 残留，浏览器可能还停在上一次
                        # 采集留下的商品页 (例如 1031073754824)，但 task_url 是另一个商品
                        # (例如 9999999)。此时 sidecar 会拿"上一次商品的 window.context 数据"
                        # 但 product_id 用"新商品的 offerId"算出来，结果就是"输入 A 链接，
                        # 采集到 B 商品数据"——这是严重的数据错配 bug，必须在提取前堵住。
                        # ============================================================
                        expected_pid = (_extract_capture_product_id(task_url) or '').strip()

                        def _current_page_pid():
                            try:
                                return (_extract_capture_product_id(page.url or '') or '').strip()
                            except Exception:
                                return ''

                        if expected_pid:
                            actual_pid = _current_page_pid()
                            if actual_pid != expected_pid:
                                service.logger.warning(
                                    f"⚠️ 浏览器 URL 与目标商品不一致: expected={expected_pid} actual={actual_pid} "
                                f"current_url={(page.url or '')[:140]}；强制重新导航 1 次"
                                )
                                try:
                                    page.get(task_url, timeout=30)
                                    system_time.sleep(4)
                                except Exception as _renav_err:
                                    service.logger.warning(f"重新导航异常: {_renav_err}")
                                actual_pid = _current_page_pid()
                                if actual_pid != expected_pid:
                                    service.logger.error(
                                        f"❌ 重新导航后 URL 仍不匹配: expected={expected_pid} actual={actual_pid} "
                                    f"current_url={(page.url or '')[:200]}"
                                    )
                                    service.tasks[task_id]['status'] = 'failed'
                                    service.tasks[task_id]['progress'] = 0
                                    service.tasks[task_id]['error_code'] = '1688_url_mismatch'
                                    service.tasks[task_id]['message'] = (
                                        f'浏览器未能跳转到目标商品 (期望 offerId={expected_pid}，'
                                    f'实际停在 {actual_pid or "未知页面"})。可能原因：1688 反爬拦截/页面跳转被本地代理阻断。'
                                    f'请关闭代理工具的 TUN 模式或在浏览器中手动访问 {task_url} 后重试。'
                                    )
                                    _finalize_protocol_capture_record(
                                        protocol_capture_runtime,
                                        task_id=task_id,
                                        source_url=task_url,
                                        status='failed',
                                        progress=0,
                                        message=service.tasks[task_id]['message'],
                                        error='1688_url_mismatch',
                                    )
                                    return
                            service.logger.info(f"✅ URL 一致性校验通过: offerId={expected_pid}")

                        # 显式等待 window.context.result.global.globalData.model.offerDetail 填充
                        # 1688 用 eager load mode + set_load_mode('eager')，page.get() 提前返回，
                        # 此时 model 可能还没由 launch JS 写入。最多等 18s。
                        # 同时校验 offerDetail.offerId 等于 expected_pid，防止页面正在切换但 ctx
                        # 还是上一个商品的残留值。
                        wait_ready_start = system_time.time()
                        ready_ok = False
                        last_observed_offer_id = ''
                        while system_time.time() - wait_ready_start < 18:
                            try:
                                ready_info = page.run_js('''
                                return (() => {
                                    const od = window.context?.result?.global?.globalData?.model?.offerDetail;
                                    if (!od || !od.subject || od.subject.length === 0) return null;
                                    return { offer_id: String(od.offerId || '') };
                                })()
                            ''')
                                if ready_info:
                                    observed_oid = str((ready_info or {}).get('offer_id') or '').strip()
                                    last_observed_offer_id = observed_oid
                                    # 双重校验：URL 一致 + offerDetail.offerId 也要一致
                                    if not expected_pid or observed_oid == expected_pid:
                                        ready_ok = True
                                        break
                            except Exception:
                                pass
                            system_time.sleep(0.5)
                        elapsed = system_time.time() - wait_ready_start
                        if ready_ok:
                            service.logger.info(
                                f"✅ 1688 window.context.offerDetail 已就绪（等待 {elapsed:.1f}s, offerId={last_observed_offer_id}）"
                            )
                        else:
                            # offerDetail 未填充，或填充的 offerId 跟 task_url 不符
                            if expected_pid and last_observed_offer_id and last_observed_offer_id != expected_pid:
                                service.logger.error(
                                    f"❌ window.context.offerDetail.offerId={last_observed_offer_id} 与目标 {expected_pid} 不符，"
                                f"采集会拿到错误商品；直接失败而不是吐错数据"
                                )
                                service.tasks[task_id]['status'] = 'failed'
                                service.tasks[task_id]['progress'] = 0
                                service.tasks[task_id]['error_code'] = '1688_offerid_mismatch'
                                service.tasks[task_id]['message'] = (
                                    f'window.context 数据与目标商品不一致 (期望 offerId={expected_pid}，'
                                f'页面里是 {last_observed_offer_id})。可能浏览器残留了上次的页面状态。'
                                f'请手动刷新页面或重启采集浏览器后重试。'
                                )
                                _finalize_protocol_capture_record(
                                    protocol_capture_runtime,
                                    task_id=task_id,
                                    source_url=task_url,
                                    status='failed',
                                    progress=0,
                                    message=service.tasks[task_id]['message'],
                                    error='1688_offerid_mismatch',
                                )
                                return
                            service.logger.warning(
                                f"⚠️ 1688 window.context.offerDetail 未在 18s 内填充（last_observed_offer_id={last_observed_offer_id or '空'}），继续尝试提取"
                            )

                        try:
                            snapshot = _extract_1688_context_snapshot(page)
                            if snapshot and snapshot.get('title'):
                                product_data['title'] = str(snapshot['title']).strip()

                                # 主图
                                main_imgs = snapshot.get('main_images') or snapshot.get('offer_images') or []
                                product_data['main_images'] = [
                                    u if u.startswith('http') else ('https:' + u)
                                    for u in main_imgs[:12]
                                ]

                                # 价格
                                current_prices = snapshot.get('current_prices') or []
                                if current_prices:
                                    try:
                                        price_val = float(current_prices[0].get('price', '0'))
                                        product_data['price']['current'] = price_val
                                    except (ValueError, TypeError, KeyError):
                                        pass

                                # SKU
                                default_price = product_data['price']['current']
                                from urllib.request import urlopen as _urlopen_1688
                                sku_info = _build_1688_sku_info(snapshot, None, default_price)
                                if sku_info:
                                    product_data['sku_info'] = sku_info
                                elif not product_data['sku_info']:
                                    product_data['sku_info'].append({
                                        'type': '规格', 'name': '默认', 'image': '',
                                        'price': default_price, 'index': 1,
                                    })

                                # 详情图
                                detail_url = snapshot.get('detail_url', '')
                                if detail_url:
                                    detail_imgs = _collect_1688_detail_images(detail_url)
                                    if detail_imgs:
                                        product_data['detail_images'] = detail_imgs

                                service.capture_product_attributes(page, product_data, options)

                                service.logger.info(
                                    f"1688协议提取成功: title={bool(product_data['title'])} "
                                f"price={product_data['price']['current']} "
                                f"images={len(product_data['main_images'])} "
                                f"skus={len(product_data['sku_info'])} "
                                f"details={len(product_data['detail_images'])}"
                                )
                            else:
                                # 关键：1688 提取失败时不能回退到淘宝 mtop 协议（两个平台独立）。
                                # 直接报清晰的失败信息，让用户知道根因。
                                service.logger.error("❌ 1688 window.context 数据不可用，且不能跨用淘宝协议；本次采集失败。")
                                service.tasks[task_id]['status'] = 'failed'
                                service.tasks[task_id]['progress'] = 0
                                service.tasks[task_id]['error_code'] = '1688_context_empty'
                                service.tasks[task_id]['message'] = (
                                    '1688 商品页 window.context 数据未填充，可能是页面没加载完整。'
                                '常见原因：本地代理工具（Clash / verge-mihomo 等）的 TUN 模式拦截了 mmstat 之外的关键资源；'
                                '请暂时关闭代理或在规则中放行 *.alicdn.com / *.1688.com / *.mmstat.com 后重试。'
                                )
                                _finalize_protocol_capture_record(
                                    protocol_capture_runtime,
                                    task_id=task_id,
                                    source_url=task_url,
                                    status='failed',
                                    progress=0,
                                    message=service.tasks[task_id]['message'],
                                    error='1688_context_empty',
                                )
                                return
                        except Exception as e:
                            # 同上：不跨协议回退。让错误信息明确指出根因。
                            service.logger.error(f"❌ 1688 协议提取异常: {e}")
                            service.tasks[task_id]['status'] = 'failed'
                            service.tasks[task_id]['progress'] = 0
                            service.tasks[task_id]['error_code'] = '1688_extract_exception'
                            service.tasks[task_id]['message'] = f'1688 协议提取失败: {str(e)[:120]}'
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=service.tasks[task_id]['message'],
                                error='1688_extract_exception',
                            )
                            return
                    else:
                        # ==== 淘宝/天猫: ICE+HTTP+DOM 三级回退 ====
                        product_data = service.capture_taobao_tmall_product_for_store(page, task_url, options)

                    extracted_product_id = product_data.get('product_id', f"product_{int(system_time.time())}")
                    platform_context = {}
                    # 🔧 下载图片（改进版：按文件夹分类）
                    service.tasks[task_id]['progress'] = 70
                    service.tasks[task_id]['message'] = '正在下载图片...'
                    service.logger.info(f"📊 进度: 70% - 正在下载图片...")
                
                    # 淘宝/天猫共用提取器已下载过图片，单品入口直接使用同一份结果。
                    download_path = product_data.get('download_path')
                    if options.get('download_images', True) and not download_path:
                        # 从配置获取基础保存路径，默认为 'uploads/products'
                        base_save_path = options.get('save_path', 'uploads/products')
                    
                        # 规范化路径（支持相对路径和绝对路径，支持打包后的可执行文件）
                        base_save_path = normalize_save_path(base_save_path)
                    
                        service.logger.info(f"📂 基础保存路径: {base_save_path}")
                        service.logger.info(f"📂 程序根目录: {get_app_root()}")
                    
                        # 使用ID-{商品ID}作为父文件夹名称（符合ID模式）
                        parent_dir = os.path.join(base_save_path, f'ID-{extracted_product_id}')
                        os.makedirs(parent_dir, exist_ok=True)
                    
                        service.logger.info(f"✅ 文件将保存到: {parent_dir}")
                    
                        # 创建子文件夹
                        main_img_dir = os.path.join(parent_dir, '主图')
                        sku_img_dir = os.path.join(parent_dir, 'SKU')
                        detail_img_dir = os.path.join(parent_dir, '详情页')
                    
                        os.makedirs(main_img_dir, exist_ok=True)
                        os.makedirs(sku_img_dir, exist_ok=True)
                        os.makedirs(detail_img_dir, exist_ok=True)
                    
                        service.logger.info(f"📁 创建文件夹结构: {parent_dir}")
                    
                        import requests
                        from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                        session = requests.Session()
                        session.headers.update({
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                    
                        total_images = len(product_data['main_images']) + len(product_data['detail_images']) + len([s for s in product_data['sku_info'] if s.get('image')])
                        downloaded = 0
                    
                        # 定义并行下载函数
                        def download_image(img_url, filepath, img_type, index):
                            """并行下载单张图片"""
                            try:
                                if img_url.startswith('//'):
                                    img_url = 'https:' + img_url
                            
                                response = session.get(img_url, timeout=15)
                            
                                if response.status_code == 200:
                                    # 检查图片大小，过滤1px占位图
                                    if len(response.content) < 100:
                                        return {'success': False, 'reason': 'small_size', 'size': len(response.content)}
                                
                                    with open(filepath, 'wb') as f:
                                        f.write(response.content)
                                
                                    return {'success': True, 'size': len(response.content), 'type': img_type, 'index': index}
                                else:
                                    return {'success': False, 'reason': 'http_error', 'status': response.status_code}
                            except Exception as e:
                                return {'success': False, 'reason': 'exception', 'error': str(e)}
                    
                        # 并行下载主图
                        service.logger.info(f"📥 开始并行下载主图: {len(product_data['main_images'])} 张")
                        main_download_count = 0
                        with ThreadPoolExecutor(max_workers=8) as executor:
                            futures = []
                            for i, img_url in enumerate(product_data['main_images']):
                                ext = _get_image_ext(img_url, '')
                                filename = f"主图_{i+1:02d}{ext}"
                                filepath = os.path.join(main_img_dir, filename)
                                future = executor.submit(download_image, img_url, filepath, 'main', i+1)
                                futures.append(future)
                        
                            # 等待所有任务完成
                            for future in as_completed(futures):
                                result = future.result()
                                if result['success']:
                                    downloaded += 1
                                    main_download_count += 1
                                    progress = 70 + (downloaded / total_images) * 20
                                    service.tasks[task_id]['progress'] = int(progress)
                    
                        service.logger.info(f"✅ 主图下载完成: {main_download_count}/{len(product_data['main_images'])} 张")
                    
                        # 并行下载SKU图片
                        sku_with_image = [s for s in product_data['sku_info'] if s.get('image')]
                        service.logger.info(f"📥 开始并行下载SKU图片: {len(sku_with_image)} 张")
                        sku_download_count = 0
                        with ThreadPoolExecutor(max_workers=10) as executor:
                            futures = []
                            for sku in product_data['sku_info']:
                                if not sku.get('image'):
                                    continue
                            
                                img_url = sku['image']
                                ext = _get_image_ext(img_url, '')
                                safe_name = re.sub(r'[\\/:*?"<>|]', '_', sku['name'][:50])
                                filename = f"{sku['index']:02d}_{safe_name}{ext}"
                                filepath = os.path.join(sku_img_dir, filename)
                                future = executor.submit(download_image, img_url, filepath, 'sku', sku['index'])
                                futures.append(future)
                        
                            # 等待所有任务完成
                            for future in as_completed(futures):
                                result = future.result()
                                if result['success']:
                                    downloaded += 1
                                    sku_download_count += 1
                                    progress = 70 + (downloaded / total_images) * 20
                                    service.tasks[task_id]['progress'] = int(progress)
                    
                        service.logger.info(f"✅ SKU图片下载完成: {sku_download_count}/{len(sku_with_image)} 张")
                    
                        # 并行下载详情页图片
                        service.logger.info(f"📥 开始并行下载详情页图片: {len(product_data['detail_images'])} 张")
                        detail_download_count = 0
                        with ThreadPoolExecutor(max_workers=10) as executor:
                            futures = []
                            for i, img_url in enumerate(product_data['detail_images']):
                                ext = _get_image_ext(img_url, '')
                                filename = f"详情_{i+1:03d}{ext}"
                                filepath = os.path.join(detail_img_dir, filename)
                                future = executor.submit(download_image, img_url, filepath, 'detail', i+1)
                                futures.append(future)
                        
                            # 等待所有任务完成
                            for future in as_completed(futures):
                                result = future.result()
                                if result['success']:
                                    downloaded += 1
                                    detail_download_count += 1
                                    progress = 70 + (downloaded / total_images) * 20
                                    service.tasks[task_id]['progress'] = int(progress)
                    
                        service.logger.info(f"✅ 详情图下载完成: {detail_download_count}/{len(product_data['detail_images'])} 张")
                    
                        download_path = parent_dir
                        service.logger.info(f"✅ 图片下载完成：共 {downloaded}/{total_images} 张")
                
                    # 保持浏览器打开（用户可能需要继续浏览或验证其他商品）
                    service.logger.info("✅ 采集完成，浏览器保持打开状态")
                    service.logger.info("💡 提示：您可以在浏览器中继续浏览商品，或手动关闭浏览器")
                    # page.quit()  # 已注释：不再自动关闭浏览器
                
                    # 更新任务状态
                    service.tasks[task_id]['status'] = 'completed'
                    service.tasks[task_id]['progress'] = 100
                    service.tasks[task_id]['message'] = '采集完成'
                    service.tasks[task_id]['result'] = {
                        **product_data,
                        'download_path': download_path,
                        'task_id': task_id,
                        'url': task_url,
                        'captured_at': datetime.now().isoformat()
                    }
                    _finalize_protocol_capture_record(
                        protocol_capture_runtime,
                        task_id=task_id,
                        source_url=task_url,
                        status='completed',
                        progress=100,
                        message='采集完成',
                        result=service.tasks[task_id]['result'],
                    )
                
                    service.logger.info("=" * 80)
                    service.logger.info(f"✅✅✅ 采集任务完成: {task_id}")
                    service.logger.info(f"📝 商品ID: {extracted_product_id}")
                    service.logger.info(f"📝 标题: {product_data['title']}")
                    service.logger.info(f"💰 价格: ¥{product_data['price']['current']}")
                    service.logger.info(f"🖼️ 主图: {len(product_data['main_images'])} 张")
                    service.logger.info(f"📸 详情图: {len(product_data['detail_images'])} 张")
                    service.logger.info(f"📦 SKU: {len(product_data['sku_info'])} 个")
                    service.logger.info(f"💾 下载目录: {download_path}")
                    service.logger.info("=" * 80)
                
                except Exception as e:
                    service.logger.error("=" * 80)
                    service.logger.error(f"❌❌❌ 采集任务失败: {task_id}")
                    service.logger.error(f"错误类型: {type(e).__name__}")
                    service.logger.error(f"错误信息: {str(e)}")
                    service.logger.error("详细堆栈:")
                    service.logger.error(traceback.format_exc())
                    service.logger.error("=" * 80)
                
                    service.tasks[task_id]['status'] = 'failed'
                    service.tasks[task_id]['progress'] = 0
                    service.tasks[task_id].update(_capture_failure_details(e))
                    _finalize_protocol_capture_record(
                        protocol_capture_runtime,
                        task_id=task_id,
                        source_url=task_url,
                        status='failed',
                        progress=0,
                        message=service.tasks[task_id]['message'],
                        error=str(e),
                    )
        
            # 辅助函数：获取图片扩展名
            def _get_image_ext(url, content_type=''):
                """根据URL和Content-Type确定图片扩展名"""
                # 优先从Content-Type判断
                if 'image/png' in content_type:
                    return '.png'
                elif 'image/gif' in content_type:
                    return '.gif'
                elif 'image/webp' in content_type:
                    return '.webp'
                elif 'image/jpeg' in content_type or 'image/jpg' in content_type:
                    return '.jpg'
            
                # 从URL判断
                if '.png' in url.lower():
                    return '.png'
                elif '.gif' in url.lower():
                    return '.gif'
                elif '.webp' in url.lower():
                    return '.webp'
                elif '.jpg' in url.lower() or '.jpeg' in url.lower():
                    return '.jpg'
            
                # 默认
                return '.jpg'
        
            # 在后台线程中运行，外层 wrapper 负责释放互斥锁，无论成功/失败/异常都会清零
            def _run_capture_task_with_lock_release():
                try:
                    run_capture_task()
                finally:
                    with service.lock:
                        if service.running_task_id == task_id:
                            service.running_task_id = None
                            service.logger.info(f"🔓 已释放采集互斥锁: {task_id}")

            import threading
            thread = threading.Thread(target=_run_capture_task_with_lock_release, daemon=True)
            thread.start()
            service.logger.info(f"🧵 后台线程已启动")
        
            # 构建响应
            response_data = {
                'success': True,
                'task_id': task_id,
                'data': {
                    'task_id': task_id,
                    'url': url,
                },
                'message': '采集任务已启动'
            }
            service.logger.info(f"📤 准备返回响应: {response_data}")
        
            response = jsonify(response_data)
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            service.logger.info(f"✅ 响应已返回，状态码: 200")
        
            return response
        
        except Exception as e:
            service.logger.error("=" * 80)
            service.logger.error("❌❌❌ 启动采集任务失败")
            service.logger.error(f"错误类型: {type(e).__name__}")
            service.logger.error(f"错误信息: {str(e)}")
            service.logger.error("详细堆栈:")
            service.logger.error(traceback.format_exc())
            service.logger.error("=" * 80)

            # 如果在"占锁之后、启动线程之前"挂了，必须释放锁，避免后续永远拒绝新任务
            # 注：任务 id 和互斥锁现在是 service 的属性（原来的 global 声明随搬迁去掉了）
            _task_id_local = locals().get('task_id')
            if _task_id_local:
                with service.lock:
                    if service.running_task_id == _task_id_local:
                        service.running_task_id = None
                        service.logger.info(f"🔓 启动失败已释放采集互斥锁: {_task_id_local}")

            return jsonify({
                'success': False,
                'message': f'启动任务失败: {str(e)}'
            })

    @routes.route('/api/capture/status/<task_id>', methods=['GET'])
    def get_capture_status(task_id: str):
        """获取采集任务状态"""
        task = service.tasks.get(task_id)
    
        if not task:
            return jsonify({
                'success': False,
                'message': '任务不存在'
            })
    
        recovery_info = _capture_task_recovery_info(task)
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': task['status'],
            'progress': task['progress'],
            'message': task['message'],
            'error_code': task.get('error_code', ''),
            **recovery_info,
            'platform': task.get('platform'),
            'capture_mode': task.get('capture_mode'),
            'result': task.get('result'),
            'created_at': task['created_at']
        })

    @routes.route('/api/capture/history', methods=['GET'])
    def get_capture_history():
        tasks = []
        for task in service.tasks.values():
            recovery_info = _capture_task_recovery_info(task)
            tasks.append({
                'task_id': task.get('task_id'),
                'url': task.get('url', ''),
                'status': task.get('status', 'pending'),
                'progress': task.get('progress', 0),
                'message': task.get('message', ''),
                'error_code': task.get('error_code', ''),
                **recovery_info,
                'platform': task.get('platform'),
                'capture_mode': task.get('capture_mode'),
                'created_at': task.get('created_at')
            })
        tasks.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        return jsonify({
            'success': True,
            'data': {
                'tasks': tasks
            }
        })

    @routes.route('/api/capture/cancel/<task_id>', methods=['POST'])
    def cancel_capture(task_id: str):
        task = service.tasks.get(task_id)
        if not task:
            return jsonify({
                'success': False,
                'message': '任务不存在'
            }), 404

        if task.get('status') in ('completed', 'failed'):
            return jsonify({
                'success': True,
                'message': '任务已结束',
                'task_id': task_id
            })

        task['status'] = 'failed'
        task['progress'] = 0
        task['cancelled'] = True
        task['error_code'] = 'cancelled'
        task['message'] = '任务已取消'

        # 同步释放互斥锁，否则后续新任务会一直被"已有采集任务正在运行"拒绝
        with service.lock:
            if service.running_task_id == task_id:
                service.running_task_id = None
                service.logger.info(f"🔓 取消任务时释放采集互斥锁: {task_id}")

        return jsonify({
            'success': True,
            'message': '已取消采集任务',
            'task_id': task_id
        })

    @routes.route('/api/capture/import', methods=['POST'])
    def import_capture_result():
        """导入采集结果到待上传列表"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': '无效的请求数据'})
        
            task_id = data.get('task_id')
            product_data = data.get('product_data')
            task = service.tasks.get(task_id) if task_id else None
            if task and task.get('result'):
                product_data = task.get('result')
        
            if not task_id or not product_data:
                return jsonify({
                    'success': False,
                    'message': '缺少必要参数'
                })

            if isinstance(product_data, dict) and product_data.get('capture_type') == 'store':
                imported_records = []
                import_errors = []
                for index, item in enumerate(product_data.get('products') or [], start=1):
                    try:
                        imported_records.append(service.import_capture_product_record(item))
                    except Exception as item_error:
                        import_errors.append({
                            'index': index,
                            'url': item.get('url') if isinstance(item, dict) else '',
                            'error': str(item_error),
                        })

                if not imported_records:
                    return jsonify({
                        'success': False,
                        'message': f"店铺商品导入失败，失败数量: {len(import_errors)}",
                        'data': {'errors': import_errors}
                    })

                return jsonify({
                    'success': True,
                    'message': f"店铺商品已添加到待上传列表：成功 {len(imported_records)} 个，失败 {len(import_errors)} 个",
                    'record_id': imported_records[0]['record_id'],
                    'record_name': imported_records[0]['record_name'],
                    'data': {
                        'imported_count': len(imported_records),
                        'records': imported_records,
                        'errors': import_errors,
                    }
                })
        
            imported = service.import_capture_product_record(product_data)
            return jsonify({'success': True, 'message': '商品已添加到待上传列表',
                            'record_id': imported['record_id'], 'record_name': imported['record_name'],
                            'data': imported})

        except Exception as e:
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'导入失败: {str(e)}'
            })

    return routes
