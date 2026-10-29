# -*- coding: utf-8 -*-
"""链接采集服务：任务字典与互斥锁、淘宝 / 天猫店铺批量采集、单品 ICE → HTTP → DOM 三级提取、采集浏览器端口选择、采集结果入库。

任务字典 ``tasks``、互斥锁 ``lock``、正在运行的任务 id ``running_task_id``、mtop 商品缓存和浏览器 cookie 缓存原来是 ``app.py`` 的模块全局（靠 ``global`` 声明读写），现在是 ``CaptureService`` 实例的属性，由应用入口创建一次；``global`` 声明随之去掉。

这个类不导入 ``src.utils`` / DrissionPage / ``app.py``：浏览器相关能力、路径规则、端口占用检查都由应用入口注入；``logger`` 是应用入口传入的 ``app.logger``——后台线程里没有 Flask 应用上下文，不能用 ``current_app``。

与 app.py 旧函数名的对应：
  _start_protocol_capture_record             -> CaptureService.start_protocol_capture_record
  _select_capture_browser_port               -> CaptureService.select_capture_browser_port
  _capture_product_attributes                -> CaptureService.capture_product_attributes
  _cdp_get_cookies_and_token                 -> CaptureService._cdp_get_cookies_and_token
  _collect_store_products_via_mtop           -> CaptureService._collect_store_products_via_mtop
  _collect_taobao_tmall_store_product_urls   -> CaptureService._collect_taobao_tmall_store_product_urls
  _collect_taobao_desc_images_via_browser    -> CaptureService._collect_taobao_desc_images_via_browser
  _fetch_taobao_desc_images                  -> CaptureService._fetch_taobao_desc_images
  _extract_taobao_tmall_product_snapshot     -> CaptureService._extract_taobao_tmall_product_snapshot
  _download_capture_product_images           -> CaptureService._download_capture_product_images
  _get_browser_cookies_for_http              -> CaptureService._get_browser_cookies_for_http
  _capture_taobao_tmall_product_for_store    -> CaptureService.capture_taobao_tmall_product_for_store
  _run_taobao_tmall_store_capture            -> CaptureService.run_taobao_tmall_store_capture
  _import_capture_product_record             -> CaptureService.import_capture_product_record
  capture_tasks / _capture_lock / _capture_running_task_id -> tasks / lock / running_task_id
  _mtop_product_cache / _browser_cookie_str / _browser_cookie_ts -> mtop_product_cache / _browser_cookie_str / _browser_cookie_ts"""
import copy
import json
import os
import re
import threading
import time as system_time
from datetime import datetime
from typing import Optional

from .capture_helpers import (
    _detect_capture_source_platform,
    _extract_capture_product_id,
    _extract_taobao_ice_data,
    _extract_text_by_selectors,
    _finalize_protocol_capture_record,
    _get_capture_browser_user_data_path,
    infer_clazz_from_title,
)


class CaptureService:
    """一个应用一个实例，持有采集任务的全部进程内状态。

    ``record_model`` 是商品表；``logger`` 是 ``app.logger``；``protocol_capture_engine`` 是可选的协议采集引擎（没有就是 None）；
    ``find_cdp_port`` / ``load_capture_attributes`` 与上传、淘宝域共用，``normalize_save_path`` 与白底图服务共用，``is_local_port_available`` 与调试浏览器共用，所以都留在应用入口；
    ``normalize_debug_address`` / ``verify_debug_browser`` / ``discover_browsers`` 在 src.utils 里（会连带导入浏览器库），所以注入；
    ``debug_host`` / ``capture_port_start`` / ``capture_port_end`` 是采集浏览器的调试地址和端口段。"""

    def __init__(
            self, *,
            record_model,
            logger,
            protocol_capture_engine,
            find_cdp_port,
            load_capture_attributes,
            normalize_save_path,
            is_local_port_available,
            normalize_debug_address,
            verify_debug_browser,
            discover_browsers,
            debug_host,
            capture_port_start,
            capture_port_end,
    ):
        self._record_model = record_model
        self.logger = logger
        self._protocol_capture_engine = protocol_capture_engine
        self._find_cdp_port = find_cdp_port
        self._load_capture_attributes = load_capture_attributes
        self._normalize_save_path = normalize_save_path
        self._is_local_port_available = is_local_port_available
        self._normalize_debug_address = normalize_debug_address
        self._verify_debug_browser = verify_debug_browser
        self._discover_debuggable_browsers = discover_browsers
        self._debug_host = debug_host
        self._capture_port_start = capture_port_start
        self._capture_port_end = capture_port_end
        # 全局任务存储
        self.tasks = {}
        # DOM 采集互斥锁：同一时刻只允许一个采集任务在跑，避免共享 capture-browser-profile
        # 时 Chrome 同一 user_data_dir 只能挂一个实例的并发冲突。
        self.lock = threading.Lock()
        # 标记当前是否有采集任务在运行（task_id 形式）；释放时清零
        self.running_task_id: Optional[str] = None
        # mtop 产品数据缓存 (itemId → {title, price, skuList...})，供单品采集复用
        self.mtop_product_cache: dict = {}
        # 浏览器 cookies 缓存，避免重复 CDP 请求
        self._browser_cookie_str: str = ''
        self._browser_cookie_ts: float = 0.0

    def start_protocol_capture_record(self, *, source_url: str, task_id: str, options: Optional[dict] = None, product_id: str = ''):
        if not self._protocol_capture_engine:
            return None
        try:
            platform = _detect_capture_source_platform(source_url)
            context, store = self._protocol_capture_engine.build_run_context(
                source_url=source_url,
                source_platform=platform,
                product_id=product_id,
                metadata={
                    'task_id': task_id,
                    'options': copy.deepcopy(options or {}),
                },
            )
            store.write_json('session', 'plan', self._protocol_capture_engine.export_plan(), artifact_type='protocol-plan')
            store.write_json(
                'session',
                'platform-profiles',
                self._protocol_capture_engine.export_platform_profiles(),
                artifact_type='platform-profiles',
            )
            store.write_json(
                'session',
                'task-meta',
                {
                    'task_id': task_id,
                    'source_url': source_url,
                    'source_platform': platform,
                    'product_id': product_id,
                    'options': copy.deepcopy(options or {}),
                    'started_at': context.started_at,
                },
                artifact_type='task-meta',
            )
            runtime = {'context': context, 'store': store, 'root': str(store.root)}
            print(f'协议化采集调试目录: {runtime["root"]}')
            return runtime
        except Exception as exc:
            print(f'协议化采集调试运行初始化失败，已跳过: {exc}')
            return None

    def select_capture_browser_port(self):
        # 同一资料目录只能有一个 Chrome 实例。先按目录找到原端口，不能因为一次
        # HTTP 探测失败就换端口重启，也不能接管恰好位于采集端口段的其它浏览器。
        profile_path = os.path.normcase(os.path.abspath(_get_capture_browser_user_data_path()))
        occupied_ports = set()
        for browser in self._discover_debuggable_browsers(verify=False):
            address = self._normalize_debug_address(browser.get('debug_address') or '')
            host, separator, port_text = address.rpartition(':')
            if not separator or host != self._debug_host or not port_text.isdigit():
                continue
            port = int(port_text)
            if not 1 <= port <= 65535:
                continue
            occupied_ports.add(port)
            browser_profile = browser.get('user_data_dir') or ''
            if not browser_profile or os.path.normcase(os.path.abspath(browser_profile)) != profile_path:
                continue
            verification = self._verify_debug_browser(address, timeout=2.0)
            if not verification.get('ok'):
                raise RuntimeError(
                    f'采集浏览器已启动，但调试端口 {address} 无法连接：'
                f'{verification.get("error") or "未返回有效响应"}。'
                '请先处理连接故障；如该浏览器已失去响应，请关闭采集浏览器后重试。'
                )
            return port

        for port in range(self._capture_port_start, self._capture_port_end + 1):
            if port not in occupied_ports and self._is_local_port_available(self._debug_host, port):
                return port
        raise RuntimeError('未找到可用的采集浏览器调试端口')

    def capture_product_attributes(self, page, product_data, options):
        attributes = self._load_capture_attributes().capture(page, enabled=options.get('extract_params', True))
        product_data['captured_attributes'] = attributes
        product_data['parameters'] = attributes['attributes']
        if attributes['status'] == 'not_found':
            self.logger.warning('未识别到可见的结构化商品参数区；本次采集不提供自动属性值')

    def _cdp_get_cookies_and_token(self, cdp_port: int) -> tuple:
        """通过 CDP WebSocket 获取所有 cookies 和 mtop token。
        返回 (cookies_header, mtop_token)，失败返回 ('', '')。"""
        try:
            import websocket
            import time
            from urllib.request import urlopen as _urlopen

            targets = json.loads(_urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
            target = next(
                (t for t in targets if t.get('type') == 'page' and 'taobao' in (t.get('url') or '').lower()),
                targets[0] if targets else None,
            )
            if not target:
                return '', ''

            ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
            _msg_id = [0]

            def _cdp(method, params=None):
                _msg_id[0] += 1
                ws.send(json.dumps({'id': _msg_id[0], 'method': method, 'params': params or {}}))
                deadline = time.time() + 10
                while time.time() < deadline:
                    raw = ws.recv()
                    msg = json.loads(raw)
                    if msg.get('id') == _msg_id[0]:
                        return msg
                raise TimeoutError(method)

            _cdp('Network.enable')
            r = _cdp('Network.getAllCookies')
            ws.close()

            all_cookies = (r.get('result') or {}).get('cookies') or []
            parts = []
            mtop_token = ''
            for c in all_cookies:
                domain = c.get('domain', '')
                if 'taobao.com' not in domain and 'tmall.com' not in domain:
                    continue
                name = c.get('name', '')
                value = c.get('value', '')
                if name and value:
                    parts.append(f'{name}={value}')
                    if name == '_m_h5_tk':
                        mtop_token = value.split('_')[0]
            return '; '.join(parts), mtop_token
        except Exception as e:
            self.logger.warning(f"⚠️ CDP cookie 提取失败: {e}")
            return '', ''

    def _collect_store_products_via_mtop(self, page, max_products: int = 1000,
                                         cat_id: int = 0, keyword: str = '',
                                         order_type: str = 'popular', decode_price: bool = True) -> list:
        """纯协议采集：CDP 提取 token + Python MD5 签名 + 浏览器 fetch() 发送 mtop API。
        零 DOM 操作、零滚动、零导航。请求通过浏览器 TLS 指纹，不触发反爬。
        返回 [{itemId, title, image, price, soldCount, itemUrl, skuList, ...}, ...]"""

        # 1. 获取 shopId/sellerId
        try:
            info = page.run_js(r"""
            var gc = window.g_config || {};
            var seller = gc.seller || {};
            return {
                shopId: String(seller.shopId || ''),
                sellerId: String(seller.userId || seller.sellerId || ''),
            };
        """)
            if not info or not info.get('shopId'):
                system_time.sleep(5)
                info = page.run_js(r"""
                var gc = window.g_config || {};
                var seller = gc.seller || {};
                return {shopId: String(seller.shopId||''), sellerId: String(seller.userId||seller.sellerId||'')};
            """)
                if not info or not info.get('shopId'):
                    return []
            shop_id = info['shopId']
            seller_id = info.get('sellerId', '')
        except Exception:
            return []

        # 2. CDP 提取 mtop token
        cdp_port = self._find_cdp_port()
        if not cdp_port:
            system_time.sleep(5)
            cdp_port = self._find_cdp_port()
        if not cdp_port:
            return []

        cookies_header, mtop_token = self._cdp_get_cookies_and_token(cdp_port)
        if not mtop_token:
            return []

        self.logger.info("📡 纯协议: shopId=%s, token=%s...", shop_id, mtop_token[:8])

        # 3. Python 签名 + 浏览器 fetch() 分页
        import hashlib
        from urllib.parse import urlencode as _urlencode

        all_products = []
        seen_ids = set()
        page_no = 1
        consecutive_errors = 0
        app_key = '12574478'
        api_path = 'mtop.taobao.shop.simple.item.fetch'

        while page_no <= 50 and len(all_products) < max_products:
            data_obj = {'shopId': shop_id, 'sellerId': seller_id, 'page': str(page_no), 'pageSize': '30'}
            data_str = json.dumps(data_obj, separators=(',', ':'))
            ts = str(int(system_time.time() * 1000))
            sign = hashlib.md5((mtop_token + '&' + ts + '&' + app_key + '&' + data_str).encode()).hexdigest()

            query = _urlencode({
                'jsv': '2.6.2', 'appKey': app_key, 't': ts, 'sign': sign,
                'api': api_path, 'v': '1.0', 'type': 'originaljson',
                'timeout': '10000', 'dataType': 'json',
            })
            api_url = 'https://h5api.m.taobao.com/h5/' + api_path + '/1.0/?' + query + '&data=' + _urlencode({'data': data_str})[5:]

            # 浏览器 fetch() 发送（浏览器 TLS + 自动 Cookie）
            js_code = (
                'return (async function() {'
            'try {'
            'var resp = await fetch(' + json.dumps(api_url) + ', {credentials: "include"});'
            'var text = await resp.text();'
            'return text;'
            '} catch(e) {'
            'return "ERROR: " + (e.message || String(e));'
            '}'
            '})();'
            )
            result = page.run_js(js_code, timeout=20) or ''

            if not result or result.startswith('ERROR'):
                self.logger.warning("📡 page %d: %s", page_no, str(result)[:100])
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                system_time.sleep(2)
                continue

            try:
                resp_data = json.loads(result)
            except json.JSONDecodeError:
                self.logger.warning("📡 page %d: JSON解析失败", page_no)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                continue

            ret = resp_data.get('ret', [])
            if 'SUCCESS' not in str(ret):
                self.logger.warning("📡 page %d: %s", page_no, str(ret)[:80])
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                if 'TOKEN' in str(ret) or 'ILLEGAL' in str(ret) or 'RGV587' in str(ret):
                    cookies_header, mtop_token = self._cdp_get_cookies_and_token(cdp_port)
                    if not mtop_token:
                        break
                system_time.sleep(1)
                continue

            consecutive_errors = 0
            data = resp_data.get('data', {})
            items = data.get('data', [])
            total = data.get('totalCnt', 0)
            has_next = data.get('hasNext', False)
            new_count = 0

            for item in items:
                item_id = str(item.get('itemId', ''))
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    sku_list = []
                    for sku in (item.get('skuInfoList') or []):
                        sku_list.append({
                            'skuId': str(sku.get('skuId', '')),
                            'skuImageUrl': sku.get('skuImageUrl', ''),
                            'skuUrl': sku.get('itemSkuUrl', ''),
                            'skuText': sku.get('skuPropertyText', ''),
                        })
                    all_products.append({
                        'itemId': item_id,
                        'title': item.get('title', ''),
                        'image': item.get('image', ''),
                        'price': item.get('discountPrice', ''),
                        'priceEncoded': item.get('priceEncoded', True),
                        'soldCount': item.get('vagueSold365', ''),
                        'itemUrl': item.get('itemUrl', ''),
                        'skuList': sku_list,
                        'icons': item.get('itemIconUrlList') or [],
                        'benefits': item.get('benefitPointList') or [],
                    })
                    new_count += 1

            self.logger.info("📡 page %d: +%d, 累计 %d/%d", page_no, new_count, len(all_products), total)

            if not has_next or not items:
                break
            page_no += 1
            system_time.sleep(0.3)

        self.logger.info("📡 纯协议完成: %d 个商品", len(all_products))

        for p in all_products:
            iid = str(p.get('itemId', ''))
            if iid:
                self.mtop_product_cache[iid] = p

        return all_products[:max_products]

    def _collect_taobao_tmall_store_product_urls(self, page, store_url: str, max_products: int = 1000, max_pages: int = 50) -> list:
        """从店铺页面收集商品详情链接。
        优先级: 1) mtop 纯协议 (不碰 DOM)  2) 传统 <a href> 兜底。"""
        product_urls = []
        seen_ids = set()
        store_url_norm = store_url if re.match(r'^https?://', store_url) else f'https://{store_url}'

        # ---------- 第一阶段: mtop 纯协议采集 (不碰 DOM) ----------
        # 检查是否已在店铺页（调用方已导航），避免冗余刷新
        current_url = (page.url or '').strip()
        if 'taobao.com' not in current_url and 'tmall.com' not in current_url:
            try:
                self.logger.info("📡 导航到店铺页...")
                page.get(store_url_norm, timeout=25)
                system_time.sleep(5)
            except Exception as nav_err:
                self.logger.warning(f"⚠️ 店铺页访问失败: {nav_err}")
        else:
            self.logger.info(f"📡 已在店铺页，跳过重复导航: {current_url[:80]}")

        mtop_products = self._collect_store_products_via_mtop(page, max_products=max_products)
        if mtop_products:
            from urllib.parse import urlparse
            parsed = urlparse(store_url_norm)
            host = parsed.netloc or ''
            is_tmall = 'tmall.com' in host
            detail_host = 'detail.tmall.com' if is_tmall else 'item.taobao.com'
            for item in mtop_products:
                item_id = str(item.get('itemId', ''))
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                raw_item_url = str(item.get('itemUrl', '') or '').strip()
                if raw_item_url:
                    if raw_item_url.startswith('//'):
                        raw_item_url = 'https:' + raw_item_url
                    elif not raw_item_url.startswith('http'):
                        raw_item_url = 'https://' + raw_item_url
                    product_urls.append(raw_item_url)
                else:
                    product_urls.append(f'https://{detail_host}/item.htm?id={item_id}')
                if len(product_urls) >= max_products:
                    break
            self.logger.info(f"📡 mtop 协议采集完成，共 {len(product_urls)} 个商品链接")
            return product_urls

        # mtop 未获取到数据时，直接返回空列表（新版店铺无传统 <a href>）
        self.logger.warning("mtop 未获取到数据，请确保已登录淘宝且页面加载完整")
        return product_urls

    def _collect_taobao_desc_images_via_browser(self, page, max_images: int = 80) -> list:
        """在当前商品页内分段滚动，触发宝贝描述懒加载后从 DOM 收集详情图。

        背景：天猫/淘宝详情描述是纯 JS 渲染 + 懒加载，pcDescUrl 的裸 HTML 里只有
        <script> 标签，HTTP 抓取拿不到图（2026-08 实证）。采集流程的页面会话是有效的，
        直接在页内滚动等描述模块渲染完毕再收图即可。

        只返回阿里 CDN 的真图片 URL（带图片扩展名），调用方负责去重/下载。
        """
        import re as _re

        # 分段滚动到底部，触发描述区懒加载
        try:
            page.run_js('window.scrollTo(0, 0)')
            for _ in range(16):
                page.run_js('window.scrollBy(0, 900)')
                system_time.sleep(0.6)
            page.run_js('window.scrollTo(0, document.body.scrollHeight)')
            system_time.sleep(1.5)
        except Exception as e:
            self.logger.warning(f"详情图滚动加载异常: {e}")

        collected = page.run_js(r'''
        var urls = [];
        var sels = [
            '#description img',
            '#container .descV8-singleImage img',
            '#container .descV8-container img',
            '.detail-content img',
            '.desc-root img',
            '[class*="descV8"] img',
            '[class*="detailDesc"] img',
            '[class*="detail-desc"] img'
        ];
        sels.forEach(function (s) {
            document.querySelectorAll(s).forEach(function (im) {
                var u = im.getAttribute('data-src') || im.getAttribute('data-ks-lazyload') || im.getAttribute('src') || '';
                if (!u) return;
                u = String(u).trim();
                if (u.indexOf('//') === 0) u = 'https:' + u;
                urls.push(u);
            });
        });
        return urls;
    ''') or []

        result = []
        for u in collected:
            if 'alicdn.com' not in u and 'taobaocdn' not in u:
                continue
            if 's.gif' in u or 'placeholder' in u.lower():
                continue
            if not _re.search(r'\.(?:jpg|jpeg|png|webp)(?:[_.?#]|$)', u, _re.IGNORECASE):
                continue
            if u not in result:
                result.append(u)
            if len(result) >= max_images:
                break

        # 回滚到顶部，避免影响后续 DOM 兜底提取的视口判断
        try:
            page.run_js('window.scrollTo(0, 0)')
        except Exception:
            pass
        return result

    def _fetch_taobao_desc_images(self, page, pc_desc_url: str) -> list:
        """从淘宝 PC 详情页 URL 提取详情图列表（二次HTTP请求）。"""
        import requests as _requests
        try:
            if not pc_desc_url.startswith('http'):
                pc_desc_url = 'https:' + pc_desc_url
            resp = _requests.get(pc_desc_url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
                'Referer': 'https://item.taobao.com/',
            })
            html = resp.text
            # 详情页的图片通常在 <img> 标签或 JSON 数据中
            import re as _re
            img_urls = _re.findall(r'(?:src|data-src)=["\']([^"\']*(?:alicdn|taobaocdn|gw\.alicdn)[^"\']*)["\']', html)
            # 补充 JSON 内嵌图片 URL（desc 页常把图放在 "url":"//..." 这类字段里）
            img_urls += _re.findall(r'"((?:https?:)?//[^"\']*(?:alicdn|taobaocdn)[^"\']*)"', html)
            result = []
            for u in img_urls[:120]:
                u = u.strip()
                if not u or 's.gif' in u or 'placeholder' in u.lower():
                    continue
                # 只保留真图片：路径必须带图片扩展名（允许 _尺寸/_裁剪 等 CDN 后缀）。
                # 否则 <script src="https://g.alicdn.com/....js"> 会被误当详情图下载，
                # 存成 .jpg 后内容是 JS（现场实证：详情_001.jpg 文件头是 !function...）。
                if not _re.search(r'\.(?:jpg|jpeg|png|webp)(?:[_.?#]|$)', u, _re.IGNORECASE):
                    continue
                if not u.startswith('http'):
                    u = 'https:' + u
                if u not in result:
                    result.append(u)
            return result
        except Exception as e:
            self.logger.warning(f"详情图提取失败: {e}")
            return []

    def _extract_taobao_tmall_product_snapshot(self, page, product_url: str, *, include_skus: bool = True) -> dict:
        product_id = _extract_capture_product_id(product_url)
        product_data = {
            'product_id': product_id,
            'title': '',
            'price': {'current': 0, 'original': None, 'currency': 'CNY'},
            'main_images': [],
            'detail_images': [],
            'sku_info': [],
            'parameters': [],
        }

        # 优先从 mtop 缓存获取已采集数据（避免重复 DOM 提取）
        cached = self.mtop_product_cache.get(product_id) if product_id else None
        if cached:
            # 标题
            if cached.get('title'):
                product_data['title'] = str(cached['title'])
            # 价格（优先使用解码后的价格）
            decoded_price = cached.get('priceDecoded')
            if decoded_price:
                try:
                    product_data['price']['current'] = float(int(str(decoded_price)) / 100)
                except (ValueError, TypeError):
                    pass
            # 店铺列表缓存不是完整的可售 SKU 表，不与商品页规格拼接。
            # 主图（mtop 返回首图，作为兜底）
            if cached.get('image'):
                product_data['main_images'] = [str(cached['image'])]

        product_data['title'] = _extract_text_by_selectors(page, [
            '.mainTitle--R75fTcZL',
            '[class*="mainTitle"]',
            '[class*="Title--"]',
            'h1',
        ]) or '未能获取标题'

        price_value = page.run_js(r'''
        function parsePriceText(raw) {
            if (raw === null || raw === undefined) return 0;
            var match = String(raw).replace(/[,，]/g, '').match(/(\d+(?:\.\d+)?)/);
            return match ? parseFloat(match[1]) : 0;
        }
        var selectors = [
            '.highlightPrice--asfw5V1e',
            '.tb-rmb-num',
            '[class*="highlightPrice"]',
            '[class*="priceText"]',
            '[class*="PriceText"]',
            '[class*="salesPrice"]',
            '[class*="mainPrice"]',
            '[class*="price--"]',
            '[class*="Price--"]',
            '[data-testid*="price"]',
            '.price-value',
            '.tb-property-cont .price'
        ];
        for (var i = 0; i < selectors.length; i++) {
            var node = document.querySelector(selectors[i]);
            var price = parsePriceText(node ? (node.textContent || node.innerText || '') : '');
            if (price > 0) return price;
        }
        return 0;
    ''')
        if price_value:
            product_data['price']['current'] = float(price_value)

        image_payload = page.run_js(r'''
        function cleanList(values) {
            var result = [];
            values.forEach(function(value) {
                if (!value) return;
                value = String(value).trim();
                if (!value || value.indexOf('s.gif') !== -1 || value.indexOf('O1CN01CYtPWu1MUBqQAUK9D') !== -1) return;
                if (value.indexOf('//') === 0) value = 'https:' + value;
                if (value.indexOf('alicdn.com') === -1 && value.indexOf('alicdn.net') === -1) return;
                if (result.indexOf(value) === -1) result.push(value);
            });
            return result;
        }
        function srcOf(img) {
            return img.getAttribute('data-src') || img.getAttribute('src') || img.getAttribute('data-ks-lazyload') || '';
        }
        var main = [];
        [
            '.thumbnailPic--QasTmWDm',
            '.thumbnailWrap--TikzqD8l img',
            '.thumbnailList--T63jJ6eM img',
            '[class*="thumbnail"] img',
            '[class*="PicGallery"] img'
        ].forEach(function(selector) {
            document.querySelectorAll(selector).forEach(function(img) { main.push(srcOf(img)); });
        });
        if (!main.length) {
            document.querySelectorAll('img').forEach(function(img) {
                var rect = img.getBoundingClientRect();
                if (rect.width >= 80 && rect.height >= 80 && rect.top < 900) main.push(srcOf(img));
            });
        }
        var detail = [];
        [
            '#container .descV8-singleImage img',
            '#container .descV8-container img',
            '#description img',
            '.detail-content img',
            '.desc-root img',
            '[class*="desc"] img',
            '[class*="detail"] img'
        ].forEach(function(selector) {
            document.querySelectorAll(selector).forEach(function(img) { detail.push(srcOf(img)); });
        });
        return { main: cleanList(main).slice(0, 12), detail: cleanList(detail).slice(0, 80) };
    ''') or {}

        product_data['main_images'] = image_payload.get('main') or []
        product_data['detail_images'] = [url for url in (image_payload.get('detail') or []) if url not in product_data['main_images']]

        if include_skus:
            from src.taobao_capture import DOM_GROUPS_JS, from_dom_groups
            product_data['sku_info'] = from_dom_groups(page.run_js(DOM_GROUPS_JS))
            product_data['sku_source'] = 'dom_groups'

        return product_data

    def _download_capture_product_images(self, product_data: dict, product_url: str, options: dict) -> str:
        from src.taobao_capture import download_assets
        base = self._normalize_save_path((options or {}).get('save_path', 'uploads/products'))
        return download_assets(product_data, product_url, base, extract_sku=(options or {}).get('extract_sku', True))

    def _get_browser_cookies_for_http(self) -> str:
        """获取浏览器 cookies 用于 Python HTTP 请求（缓存60秒）"""
        now = system_time.time()
        if self._browser_cookie_str and (now - self._browser_cookie_ts) < 60:
            return self._browser_cookie_str

        cdp_port = self._find_cdp_port()
        if not cdp_port:
            return ''

        import websocket as _ws
        from urllib.request import urlopen as _uopen
        try:
            targets = json.loads(_uopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
            target = next((t for t in targets if t.get('type') == 'page'), None)
            if not target:
                return ''
            ws = _ws.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
            mid = [0]
            def _cdp(m, p=None):
                mid[0] += 1
                ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
                dl = system_time.time() + 10
                while system_time.time() < dl:
                    raw = ws.recv()
                    msg = json.loads(raw)
                    if msg.get('id') == mid[0]:
                        return msg
                return {}
            _cdp('Network.enable')
            r = _cdp('Network.getAllCookies')
            ws.close()
            parts = []
            for c in (r.get('result') or {}).get('cookies', []):
                if 'taobao.com' in (c.get('domain', '')) or 'tmall.com' in (c.get('domain', '')):
                    parts.append(f"{c['name']}={c['value']}")
            self._browser_cookie_str = '; '.join(parts)
            self._browser_cookie_ts = now
            return self._browser_cookie_str
        except Exception:
            return ''

    def capture_taobao_tmall_product_for_store(self, page, product_url: str, options: dict, mtop_cache: dict = None) -> dict:
        """协议优先采集：ICE SSR数据 → HTTP正则 → DOM 三级回退。

        Tier 1: _extract_taobao_ice_data() — 读 __ICE_APP_CONTEXT__ JSON (最稳定)
        Tier 2: Python HTTP + 正则 — 不依赖浏览器页面状态
        Tier 3: DOM snapshot — 浏览器 CSS 选择器 (兜底)
        """

        product_id = _extract_capture_product_id(product_url)
        # 店铺批次复用标签页时，必须先进入本件商品，不能读取上一件商品的 ICE。
        if _extract_capture_product_id(str(getattr(page, 'url', '') or '')) != product_id:
            page.get(product_url, timeout=30)
            system_time.sleep(1.5)
            if _extract_capture_product_id(str(getattr(page, 'url', '') or '')) != product_id:
                raise ValueError('采集浏览器尚未进入目标商品页，请完成页面登录或验证后重试。')
        cached = (mtop_cache or {}).get(product_id) if product_id else None

        product_data = {
            'product_id': product_id,
            'title': '',
            'price': {'current': 0, 'original': None, 'currency': 'CNY'},
            'main_images': [],
            'detail_images': [],
            'sku_info': [],
            'parameters': [],
        }

        # ==== Tier 1: ICE 协议提取 (优先，不依赖 DOM 选择器) ====
        ice_data = _extract_taobao_ice_data(page)

        if ice_data and ice_data.get('title'):
            product_data.update(ice_data)
            # 详情读取统一放到资料补全之后，避免只在 ICE 成功时执行。
            self.logger.info(f"ICE提取成功: title={product_data['title'][:30]} price={product_data['price']['current']} imgs={len(product_data['main_images'])} skus={len(product_data['sku_info'])} details={len(product_data['detail_images'])}")
        else:
            self.logger.info(f"ICE提取数据不完整，回退到HTTP正则+DOM")

        # ==== Tier 2: HTTP 正则 (ICE 失败时回退) ====
        if not product_data['price']['current']:
            import re as _re
            from urllib.request import Request as _Req, urlopen as _urlopen

            cookie_str = self._get_browser_cookies_for_http()
            html = ''
            if cookie_str:
                try:
                    req = _Req(product_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
                        'Cookie': cookie_str,
                        'Accept': 'text/html,application/xhtml+xml',
                        'Referer': 'https://www.taobao.com/',
                    })
                    resp = _urlopen(req, timeout=15)
                    html = resp.read().decode('utf-8', errors='replace')
                except Exception as e:
                    self.logger.warning(f"HTTP请求失败: {e}")

            if html and len(html) > 10000:
                title_m = _re.search(r'<title>([^<]+)</title>', html)
                if title_m and title_m.group(1) != '商品详情':
                    product_data['title'] = title_m.group(1)

                pm_m = _re.search(r'"priceMoney"\s*:\s*"(\d+)"', html)
                if pm_m:
                    try:
                        product_data['price']['current'] = float(int(pm_m.group(1)) / 100)
                    except (ValueError, TypeError):
                        pass

                img_m = _re.search(r'"images"\s*:\s*\[(.*?)\]', html)
                if img_m:
                    img_urls = _re.findall(r'"((?:https?:)?//[^"]+)"', img_m.group(1))
                    for u in img_urls:
                        url = u if u.startswith('http') else ('https:' + u)
                        if url not in product_data['main_images']:
                            product_data['main_images'].append(url)

                self.logger.info(f"REGEX: html={len(html)}b price={product_data['price']['current']} imgs={len(product_data['main_images'])} title={bool(title_m)}")

        # 标题、价格、图片与规格分别判断完整性。HTTP 正则拿到价格并不代表 SKU 已采集。
        needs_sku = (options or {}).get('extract_sku', True)
        needs_snapshot = (
            not product_data['title'] or not product_data['price']['current']
            or not product_data['main_images'] or (needs_sku and not product_data['sku_info'])
        )
        if needs_snapshot:
            self.logger.info('商品资料尚不完整，读取当前商品页补充缺失字段')
            snapshot = self._extract_taobao_tmall_product_snapshot(page, product_url,
                include_skus=needs_sku and not bool(product_data['sku_info']))
            if not product_data['title'] and snapshot.get('title') != '未能获取标题':
                product_data['title'] = snapshot.get('title') or ''
            if not product_data['price']['current']:
                product_data['price']['current'] = (snapshot.get('price') or {}).get('current') or 0
            for field in ('main_images', 'detail_images', 'sku_info'):
                if not product_data[field] and snapshot.get(field):
                    product_data[field] = snapshot[field]

        # 4. mtop 缓存补充
        if cached:
            if cached.get('title') and not product_data['title']:
                product_data['title'] = str(cached['title'])
            if cached.get('image') and not product_data['main_images']:
                product_data['main_images'] = [str(cached['image'])]
            if cached.get('soldCount'):
                product_data['sold_count'] = str(cached['soldCount'])

        if needs_sku and not product_data['sku_info']:
            raise ValueError('已读取商品基础信息，但未能提取SKU规格；采集尚未完成，请待商品规格区域加载后重试。')
        if not product_data['title'] or not product_data['main_images']:
            raise ValueError('商品标题或主图未能完整读取，采集尚未完成，请检查商品页面。')
        # HTTP 基础字段成功时也要读取详情，不能只在 ICE 成功分支执行。
        pc_desc_url = product_data.pop('_pc_desc_url', '')
        if not product_data['detail_images']:
            product_data['detail_images'] = self._collect_taobao_desc_images_via_browser(page)
            if not product_data['detail_images'] and pc_desc_url:
                product_data['detail_images'] = self._fetch_taobao_desc_images(page, pc_desc_url)
        self.capture_product_attributes(page, product_data, options)
        download_path = (self._download_capture_product_images(product_data, product_url, options)
                         if (options or {}).get('download_images', True) else None)
        product_data.update({
            'download_path': download_path,
            'url': product_url,
            'captured_at': datetime.now().isoformat(),
        })
        return product_data

    def run_taobao_tmall_store_capture(self, page, task_id: str, task_url: str, options: dict, protocol_capture_runtime):
        max_products = int((options or {}).get('max_store_products') or 1000)
        max_pages = int((options or {}).get('max_store_pages') or 50)

        self.tasks[task_id]['progress'] = 35
        self.tasks[task_id]['message'] = '正在读取店铺商品列表...'
        product_urls = self._collect_taobao_tmall_store_product_urls(
            page,
            task_url,
            max_products=max_products,
            max_pages=max_pages,
        )

        if not product_urls:
            raise Exception('未从店铺页面找到商品链接，请确认店铺页已登录且商品列表可见')

        # 采集间隔：避免频繁 page.get() 触发验证码（默认3秒，可配置）
        request_interval = float((options or {}).get('request_interval_seconds') or 3.0)

        products = []
        errors = []
        total = len(product_urls)
        consecutive_verifications = 0

        for index, product_url in enumerate(product_urls, start=1):
            if self.tasks.get(task_id, {}).get('status') == 'failed':
                return

            # 连续验证码过多 → 暂停等待用户处理
            if consecutive_verifications >= 3:
                self.logger.warning(f"⏸️ 连续 {consecutive_verifications} 次验证码，暂停30秒...")
                self.tasks[task_id]['message'] = f'触发验证码过多，暂停等待中 ({index}/{total})...'
                system_time.sleep(30)
                consecutive_verifications = 0

            self.tasks[task_id]['progress'] = 35 + int((index - 1) / total * 60)
            self.tasks[task_id]['message'] = f'正在采集店铺商品 {index}/{total}'
            self.logger.info(f"🏪 店铺商品采集 {index}/{total}: {product_url}")
            try:
                products.append(self.capture_taobao_tmall_product_for_store(
                    page, product_url, options, mtop_cache=self.mtop_product_cache))
                consecutive_verifications = 0
            except Exception as product_error:
                err_str = str(product_error)
                self.logger.warning(f"⚠️ 店铺商品采集失败: {product_url}, error={err_str}")
                errors.append({'url': product_url, 'error': err_str})
                if '验证' in err_str or 'punish' in err_str.lower() or 'sec.taobao' in err_str:
                    consecutive_verifications += 1

            # 请求间隔
            if index < total:
                system_time.sleep(request_interval)

        if not products:
            raise Exception(f'店铺商品采集全部失败，失败数量: {len(errors)}')

        result = {
            'capture_type': 'store',
            'title': f'店铺采集 {len(products)} 个商品',
            'store_url': task_url,
            'product_urls': product_urls,
            'products': products,
            'errors': errors,
            'sku_count': sum(len(product.get('sku_info') or []) for product in products),
            'task_id': task_id,
            'url': task_url,
            'captured_at': datetime.now().isoformat(),
        }

        self.tasks[task_id]['status'] = 'completed'
        self.tasks[task_id]['progress'] = 100
        self.tasks[task_id]['message'] = f'店铺采集完成：成功 {len(products)} 个，失败 {len(errors)} 个'
        self.tasks[task_id]['result'] = result
        _finalize_protocol_capture_record(
            protocol_capture_runtime,
            task_id=task_id,
            source_url=task_url,
            status='completed',
            progress=100,
            message=self.tasks[task_id]['message'],
            result=result,
        )

    def import_capture_product_record(self, product_data: dict) -> dict:
        """单品和店铺批次共用同一条 SKU 清单导入路径。重复导入保留记录 ID。"""
        from src.taobao_capture import bind_local_files
        captured_attributes = self._load_capture_attributes().dumps(product_data.get('captured_attributes'))
        download_path = os.path.normpath(product_data.get('download_path') or '')
        if not product_data.get('download_path') or not os.path.isdir(download_path):
            raise ValueError('图片目录不存在：' + download_path)
        sku_list = bind_local_files(product_data)
        folder_name = os.path.basename(download_path)
        title = str(product_data.get('title') or '采集的商品')
        values = dict(name=folder_name, path=download_path, type=2, status=0, repo=100,
                      title=title, clazz=infer_clazz_from_title(title),
                      content=json.dumps(sku_list, ensure_ascii=False), update_time=datetime.now(),
                      import_source='capture', source_url=str(product_data.get('url') or ''),
                      captured_attributes=captured_attributes, managed_files=True)
        # 写锁先于查找，两个完成通知同时导入也只产生一条记录。
        with self._record_model._meta.database.atomic('IMMEDIATE'):
            matches = list(self._record_model.select().where(self._record_model.path == download_path).limit(2))
            if len(matches) > 1:
                raise ValueError('同一商品目录存在多条历史记录，未自动覆盖')
            if matches:
                record = matches[0]
                self._record_model.update(**values).where(self._record_model.id == record.id).execute()
            else:
                record = self._record_model.create(**values, remark='')
        return {'record_id': record.id, 'record_name': folder_name, 'sku_count': len(sku_list), 'title': title}
