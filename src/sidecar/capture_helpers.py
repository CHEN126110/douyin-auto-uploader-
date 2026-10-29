# -*- coding: utf-8 -*-
"""链接采集的无状态函数：URL 识别与归一、价格 / SKU 解析、1688 页面快照、淘宝 ICE 数据提取、失败原因归类、协议采集产物写入等。

这里的函数只依赖入参和标准库 / 轻量库，不碰任务字典、锁、浏览器单例和 Flask 请求上下文；需要这些的函数在 ``capture_service.CaptureService``。

搬迁时发现下面 6 个函数在整个仓库里没有任何调用方，先原样保留：``_extract_taobao_tmall_item_id``、``_normalize_taobao_tmall_item_url``、``_append_query_params``、``_mtop_post_fetch``、``_infer_capture_image_ext``、``_parse_ice_from_html``。"""
import html
import json
import os
import re
import time as system_time
from datetime import datetime
from typing import Optional

from src.capture_url_utils import capture_url_host, is_taobao_short_link, normalize_capture_url


def _detect_capture_source_platform(url: str) -> str:
    if _is_1688_capture_url(url):
        return '1688'
    if 'tmall.com' in str(url or '').lower():
        return 'tmall'
    if _is_taobao_tmall_capture_url(url):
        return 'taobao'
    return 'unknown'


def _write_protocol_capture_artifact_json(protocol_runtime, stage, name, payload, artifact_type='json'):
    if not protocol_runtime:
        return None
    try:
        return protocol_runtime['store'].write_json(stage, name, payload, artifact_type=artifact_type)
    except Exception as exc:
        print(f'协议化采集产物写入失败，已跳过: stage={stage} name={name} error={exc}')
        return None


def _finalize_protocol_capture_record(
    protocol_runtime,
    *,
    task_id: str,
    source_url: str,
    status: str,
    progress: int,
    message: str,
    error: str = '',
    result: Optional[dict] = None,
):
    if not protocol_runtime:
        return
    _write_protocol_capture_artifact_json(
        protocol_runtime,
        'session',
        'task-summary',
        {
            'task_id': task_id,
            'source_url': source_url,
            'status': status,
            'progress': progress,
            'message': message,
            'error': error,
            'artifact_root': protocol_runtime.get('root'),
            'finished_at': datetime.now().isoformat(),
        },
        artifact_type='task-summary',
    )
    if result:
        _write_protocol_capture_artifact_json(
            protocol_runtime,
            'import_manifest',
            'capture-result',
            result,
            artifact_type='capture-result',
        )


def _get_capture_browser_user_data_path():
    from src.runtime_paths import get_data_dir, get_runtime_root

    data_dir = get_data_dir(create=True)
    base_dir = data_dir if data_dir is not None else (get_runtime_root() / 'runtime')
    profile_dir = base_dir / 'capture-browser-profile'
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


def infer_clazz_from_title(t: str) -> int:
    try:
        s = (t or '').lower()
        if '船袜' in s:
            return 0
        if ('短筒' in s) or ('短袜' in s):
            return 1
        if '中筒' in s:
            return 2
        if '长筒' in s:
            return 3
        if '袜套' in s:
            return 4
        return 2
    except Exception:
        return 2


def _capture_wait_seconds(env_name: str, default_seconds: int = 120) -> int:
    try:
        value = int(os.environ.get(env_name, str(default_seconds)))
    except (TypeError, ValueError):
        value = default_seconds
    return max(2, min(value, 600))


def _capture_failure_details(error: Exception) -> dict:
    # DrissionPage 会将底层 socket 错误包装成“浏览器未启动”。沿异常链保留
    # 真正的网络资源错误；端口预检返回的文本也可能包含原始 WinError。
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        winerror = getattr(current, 'winerror', None)
        if winerror not in (10048, 10055, 10024):
            match = re.search(r'\bWinError (10048|10055|10024)\b', str(current))
            winerror = int(match.group(1)) if match else None
        if winerror in (10048, 10055, 10024):
            return {
                'error_code': 'capture_network_resources_exhausted',
                'message': (
                    f'采集失败：本机网络连接资源不足（WinError {winerror}），无法建立采集所需连接。'
                    '请暂停异常占用连接的程序或代理请求，等待连接释放后重试采集。'
                ),
            }
        for related in (current.__cause__, current.__context__, getattr(current, 'reason', None), *current.args):
            if isinstance(related, BaseException):
                pending.append(related)
    return {'error_code': type(error).__name__, 'message': f'采集失败: {error}'}


def _capture_task_recovery_info(task: dict) -> dict:
    error_code = str((task or {}).get('error_code') or '')
    retryable_codes = {
        '1688_antibot_verification',
        'triggered_antibot_verification',
        'login_timeout',
        'capture_network_resources_exhausted',
    }
    action_hints = {
        '1688_antibot_verification': '请先在采集浏览器里完成 1688 访问验证，再点击重试采集。',
        'triggered_antibot_verification': '请先在浏览器里完成平台安全验证，再点击重试采集。',
        'login_timeout': '请先在浏览器里完成平台登录，再点击重试采集。',
        'capture_network_resources_exhausted': str((task or {}).get('message') or '本机网络连接资源不足，请暂停异常占用连接的程序，等待连接释放后重试采集。'),
    }
    return {
        'can_retry': bool(error_code in retryable_codes or (task or {}).get('status') == 'failed'),
        'user_action_required': error_code in retryable_codes,
        'action_hint': action_hints.get(error_code, ''),
    }


def _is_1688_capture_url(url: str) -> bool:
    return '1688.com' in (url or '').lower()


def _is_taobao_tmall_capture_url(url: str) -> bool:
    lower_url = (url or '').lower()
    return 'taobao.com' in lower_url or 'tmall.com' in lower_url


def _resolve_capture_redirect_url(url: str):
    normalized_url = normalize_capture_url(url)
    if not normalized_url:
        return '', ''
    if not is_taobao_short_link(normalized_url):
        return normalized_url, ''

    try:
        import requests
        response = requests.get(
            normalized_url,
            allow_redirects=True,
            timeout=8,
            stream=True,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
            },
        )
        final_url = normalize_capture_url(response.url)
        response.close()
    except Exception as exc:
        raise ValueError(f'解析淘宝短链失败：{exc}。请打开短链后复制最终的淘宝/天猫商品链接再试') from exc

    final_host = capture_url_host(final_url)
    if not final_host.endswith(('.taobao.com', '.tmall.com')) and final_host not in {'taobao.com', 'tmall.com'}:
        raise ValueError(f'淘宝短链解析后的域名不受支持：{final_host or "未知域名"}')
    return final_url, normalized_url


def _is_1688_login_url(url: str) -> bool:
    """1688 平台自己的登录页。属于 1688 平台，与淘宝登录页是不同实体。"""
    lower = (url or '').lower()
    return 'login.1688.com' in lower or 'login.alibaba.com' in lower


def _is_taobao_login_url(url: str) -> bool:
    """淘宝/天猫平台的登录页（也是阿里"会员通"统一登录入口）。属于淘宝平台，与 1688 登录页是不同实体。"""
    lower = (url or '').lower()
    return 'login.taobao.com' in lower or 'login.tmall.com' in lower


def _detect_local_proxy_risk() -> str:
    """检测本地代理 / TUN 环境，返回面向用户的诊断+解决提示（无风险返回空串）。

    淘宝/1688 的二维码登录依赖阿里风控脚本（baxia.js）向风控服务器换取 token。
    若本地代理（Clash / Mihomo 等）开启 TUN 模式，会在网卡层接管全部流量、把阿里
    请求绕到海外节点，风控按"海外数据中心 IP"判高风险拒发 token，二维码框就永远空白；
    或规则集直接 REJECT 阿里域名（如 *.mmstat.com）。这两种情况都不是浏览器代码能
    单方面修复的（流量在系统网络层就被接管），只能引导用户调整代理。

    所有检测异常一律吞掉返回空串，绝不阻断采集主流程。
    """
    reasons = []
    # 1) Windows 系统代理开关
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            try:
                enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            except FileNotFoundError:
                enable = 0
            if enable:
                try:
                    server = winreg.QueryValueEx(key, "ProxyServer")[0]
                except FileNotFoundError:
                    server = ""
                reasons.append(f"系统代理开启({server or '未知地址'})")
    except Exception:
        pass
    # 2) 代理软件进程 + TUN 虚拟网卡
    try:
        import psutil
        names = ('clash', 'mihomo', 'verge', 'v2ray', 'xray', 'sing-box', 'trojan', 'shadowsocks')
        found = set()
        for p in psutil.process_iter(['name']):
            nm = (p.info.get('name') or '').lower()
            for k in names:
                if k in nm:
                    found.add('Clash/Mihomo' if k in ('clash', 'mihomo', 'verge') else k)
                    break
        if found:
            reasons.append("代理软件运行中(" + "、".join(sorted(found)) + ")")
        try:
            import socket as _sock
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            tun_keys = ('meta', 'tun', 'tap', 'wintun', 'clash', 'mihomo', 'wireguard')
            for ifname, addr_list in addrs.items():
                low = ifname.lower()
                if not any(k in low for k in tun_keys):
                    continue
                # 关键：Windows 上 psutil 对 TUN 虚拟网卡的 isup 常误报 False，
                # 改用"是否分到 IPv4 地址"判断是否真正启用
                # （Clash/Mihomo TUN 默认 fake-ip 网关 198.18.x.x）。
                has_ipv4 = any(getattr(a, 'family', None) == _sock.AF_INET for a in addr_list)
                is_up = getattr(stats.get(ifname), 'isup', False)
                if has_ipv4 or is_up:
                    reasons.append(f"TUN 虚拟网卡启用({ifname})")
                    break
        except Exception:
            pass
    except Exception:
        pass

    if not reasons:
        return ""
    return (
        "⚠️ 检测到本地代理可能导致登录二维码空白：" + "；".join(reasons) + "。"
        "代理(尤其 TUN 模式)会把淘宝流量绕到海外节点，阿里风控因此拒发二维码。"
        "解决任选其一：① 在 Clash/代理软件中临时关闭 TUN 模式或系统代理后重试；"
        "② 在代理规则里把 *.taobao.com、*.tmall.com、*.alicdn.com、*.mmstat.com 设为直连(DIRECT)；"
        "③ 直接用登录页右侧的『账号密码登录』(不依赖二维码)。"
    )


def _is_taobao_tmall_product_url(url: str) -> bool:
    """判断淘宝/天猫商品详情链接，避免店铺页被当成单品页。"""
    from urllib.parse import urlparse

    lower_url = (url or '').strip().lower()
    if not _is_taobao_tmall_capture_url(lower_url):
        return False

    parsed = urlparse(lower_url if re.match(r'^https?://', lower_url) else f'https://{lower_url}')
    host = parsed.netloc
    path = parsed.path
    if 'item.taobao.com' in host and ('/item.htm' in path or '/item_' in path):
        return True
    if 'detail.tmall.com' in host and ('/item.htm' in path or '/item_' in path):
        return True
    if re.search(r'(^|\.)detail\.tmall\.', host) and '/item' in path:
        return True
    if re.search(r'(^|\.)item\.taobao\.', host) and '/item' in path:
        return True
    return False


def _is_taobao_tmall_store_url(url: str) -> bool:
    """判断淘宝/天猫店铺链接。商品详情页必须排除，否则会破坏现有单品采集。"""
    from urllib.parse import urlparse

    raw_url = (url or '').strip()
    lower_url = raw_url.lower()
    if not _is_taobao_tmall_capture_url(lower_url) or _is_taobao_tmall_product_url(lower_url):
        return False

    parsed = urlparse(lower_url if re.match(r'^https?://', lower_url) else f'https://{lower_url}')
    host = parsed.netloc
    path = parsed.path or '/'

    if 'tmall.com' in host:
        tmall_store_hosts = {'brand.tmall.com', 'store.tmall.com', 'chaoshi.tmall.com', 'temai.tmall.com'}
        if host in tmall_store_hosts or re.match(r'(^|\.)shop\d*\.tmall\.com$', host):
            return True
    if re.match(r'(^|\.)shop\d*\.taobao\.com$', host):
        return True
    if host in {'store.taobao.com', 'shop.taobao.com', 'shop.m.taobao.com'}:
        return True
    if path.endswith('/search.htm') or path.endswith('/category.htm') or 'view_shop' in path:
        return True
    return False


def _extract_taobao_tmall_item_id(url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    raw_url = (url or '').strip()
    parsed = urlparse(raw_url if re.match(r'^https?://', raw_url) else f'https://{raw_url}')
    query = parse_qs(parsed.query)
    for key in ('id', 'item_id', 'itemId'):
        value = query.get(key)
        if value and str(value[0]).strip():
            return str(value[0]).strip()
    match = re.search(r'item[_/-](\d+)', raw_url, flags=re.IGNORECASE)
    return match.group(1) if match else ''


def _normalize_taobao_tmall_item_url(url: str) -> str:
    """归一化商品链接，保留商品 id，减少店铺翻页时的重复链接。"""
    from urllib.parse import parse_qs, urlparse

    raw_url = html.unescape(str(url or '')).strip()
    if not raw_url:
        return ''
    if raw_url.startswith('//'):
        raw_url = 'https:' + raw_url
    if raw_url.startswith('/'):
        return ''
    if not re.match(r'^https?://', raw_url, flags=re.IGNORECASE):
        raw_url = 'https://' + raw_url

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    path = parsed.path
    if 'taobao.com' not in host and 'tmall.com' not in host:
        return ''

    query = parse_qs(parsed.query)
    item_id = ''
    for key in ('id', 'item_id', 'itemId'):
        if query.get(key):
            item_id = str(query[key][0]).strip()
            break
    if not item_id:
        match = re.search(r'item[_/-](\d+)', raw_url, flags=re.IGNORECASE)
        item_id = match.group(1) if match else ''
    if not item_id:
        return ''

    if 'tmall.com' in host:
        return f'https://detail.tmall.com/item.htm?id={item_id}'
    return f'https://item.taobao.com/item.htm?id={item_id}'


def _extract_capture_product_id(url: str) -> str:
    url = (url or '').strip()
    patterns = [
        r'[?&]id=(\d+)',
        r'/offer/(\d+)\.html',
        r'/offer/(\d+)(?:[/?#]|$)',
        r'offerId=(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return f"product_{int(system_time.time())}"


def _parse_capture_price(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r'(\d+(?:\.\d+)?)', str(value))
    return float(match.group(1)) if match else 0.0


def _extract_capture_price_from_mapping(item, default: float = 0.0) -> float:
    """Extract a positive price from nested capture payloads."""
    if not isinstance(item, dict):
        return default

    preferred_keys = (
        'price',
        'discountPrice',
        'promotionPrice',
        'salePrice',
        'skuPrice',
        'consignPrice',
        'specQuotePrice',
        'priceWithTax',
        'currentPrice',
        'finalPrice',
    )

    disallowed_key_fragments = (
        'stock',
        'count',
        'quantity',
        'qty',
        'book',
        'inventory',
    )

    def _looks_like_price_key(key) -> bool:
        key_text = str(key or '').strip().lower()
        if not key_text:
            return False
        if key_text in {str(name).lower() for name in preferred_keys}:
            return True
        if any(fragment in key_text for fragment in disallowed_key_fragments):
            return False
        return 'price' in key_text

    for key in preferred_keys:
        price = _parse_capture_price(item.get(key))
        if price > 0:
            return price

    seen = set()

    def walk(value, depth: int = 0, allow_scalar: bool = False) -> float:
        if depth > 4 or value is None:
            return 0.0
        value_id = id(value)
        if value_id in seen:
            return 0.0
        seen.add(value_id)

        if isinstance(value, (int, float, str)):
            return _parse_capture_price(value) if allow_scalar else 0.0

        if isinstance(value, dict):
            for key in preferred_keys:
                price = _parse_capture_price(value.get(key))
                if price > 0:
                    return price
            for nested_key, nested_value in value.items():
                if _looks_like_price_key(nested_key):
                    price = walk(nested_value, depth + 1, allow_scalar=True)
                    if price > 0:
                        return price
            return 0.0

        if isinstance(value, (list, tuple)):
            for nested_value in value:
                if not isinstance(nested_value, (dict, list, tuple)):
                    continue
                price = walk(nested_value, depth + 1, allow_scalar=allow_scalar)
                if price > 0:
                    return price
        return 0.0

    nested_price = walk(item)
    return nested_price if nested_price > 0 else default


def _extract_1688_context_snapshot(page):
    """读取 1688 页面 window.context 提取完整商品数据。

    数据路径 (2026-05 验证):
      title       → globalModel.offerDetail.subject
      main_images → globalModel.offerDetail.mainImageList  (注意：对象数组 {fullPathImageURI, imageURI})
      all_images  → globalModel.offerDetail.imageList      (同样是对象数组)
      price       → globalModel.tradeModel.offerPriceModel.currentPrices[].price
      sku_props   → globalModel.offerDetail.skuProps
      sku_map     → globalModel.tradeModel.skuMap
      detail_url  → data.description.fields.detailUrl

    JS 侧负责把图片对象数组扁平化为 URL 字符串数组，避免上层代码 startswith('http') 在
    dict 上抛 AttributeError 并被 except 吃掉导致"未找到图片文件"。
    """
    return page.run_js(
        '''
        return (() => {
            const ctx = window.context || {};
            const data = ctx?.result?.data || {};
            const globalModel = ctx?.result?.global?.globalData?.model || {};
            const offerDetail = globalModel?.offerDetail || {};
            const tradeModel = globalModel?.tradeModel || {};

            // 把 mainImageList / imageList 的对象数组扁平化为 URL 字符串数组
            function pickImageUrl(item) {
                if (!item) return '';
                if (typeof item === 'string') return item;
                if (typeof item === 'object') {
                    // 优先级：完整 URL > 尺寸 URL > 相对路径
                    return item.fullPathImageURI
                        || item.imageURI
                        || item.size310x310ImageURI
                        || item.size220x220ImageURI
                        || item.searchImageURI
                        || item.summImageURI
                        || '';
                }
                return '';
            }
            function flattenImages(list) {
                if (!Array.isArray(list)) return [];
                const result = [];
                const seen = new Set();
                for (const item of list) {
                    const u = pickImageUrl(item);
                    if (u && !seen.has(u)) {
                        seen.add(u);
                        result.push(u);
                    }
                }
                return result;
            }

            const mainImages = flattenImages(offerDetail?.mainImageList);
            const allImages  = flattenImages(offerDetail?.imageList);
            // 价格
            const currentPrices = Array.isArray(tradeModel?.offerPriceModel?.currentPrices)
                ? tradeModel.offerPriceModel.currentPrices
                : [];
            // SKU 属性定义
            const skuProps = Array.isArray(offerDetail?.skuProps)
                ? offerDetail.skuProps
                : [];
            // SKU 价格映射
            const skuMap = Array.isArray(tradeModel?.skuMap)
                ? tradeModel.skuMap
                : [];
            // 详情图
            const detailUrl = (data?.description?.fields && data.description.fields.detailUrl)
                || offerDetail?.detailUrl
                || '';

            return {
                title: offerDetail?.subject || '',
                main_images: mainImages,
                offer_images: allImages,
                current_prices: currentPrices,
                price_display: tradeModel?.priceDisplay || '',
                sku_props: skuProps,
                sku_map: skuMap,
                detail_url: detailUrl,
                offer_id: offerDetail?.offerId || tradeModel?.offerId || '',
            };
        })()
        '''
    ) or {}


def _is_1688_antibot_page(page) -> bool:
    """检测当前页是否为 1688 风控/验证页。

    避免对"正常商品页"误判为验证页：1688 商品页渲染过程中，body 文本或外层 HTML
    可能瞬时包含 "验证"/"punish" 等子串（埋点脚本、商家详情、压缩 JS 变量名），若据此
    判为验证页，任务会卡在 120s 验证等待循环，而实际页面完全正常。

    判定优先级：1) 已有 offerDetail.subject → 正常商品页，直接 False；
    2) 无商品上下文时再看强风控标记 + 验证关键词。真验证页会整页替换、offerDetail 不填充。
    红线：本函数只做"区分正常页 vs 真验证页"，不绕过任何真实风控/验证码。
    """
    try:
        marker = page.run_js(
            '''
            return (() => {
                const href = location.href || '';
                const html = document.documentElement?.outerHTML || '';
                const text = document.body?.innerText || '';
                // 1) 已有商品标题 → 正常商品页，绝不判为验证页（避免渲染过程瞬时误判）
                const od = window.context?.result?.global?.globalData?.model?.offerDetail;
                if (od && od.subject && String(od.subject).length > 0) return false;
                // 2) 强风控特征：收紧 bare 'punish'，避免误匹配压缩 JS 变量名
                if (/_____tmd_____|x5sec|sufei-punish|punishpage|baxia-punish/i.test(href + html)) {
                    return true;
                }
                // 3) 文本验证关键词：仅在无商品上下文时才采信，避免商品详情文本误命中
                return /验证码|安全验证|访问验证/.test(text);
            })()
            '''
        )
        return bool(marker)
    except Exception:
        return False


def _collect_1688_detail_images(detail_url: str):
    detail_url = (detail_url or '').strip()
    if not detail_url:
        return []

    try:
        import requests

        response = requests.get(
            detail_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            timeout=20
        )
        response.raise_for_status()
        detail_html = response.text
    except Exception:
        return []

    image_urls = []
    seen = set()
    for match in re.finditer(r'((?:https?:)?//[^"\'<>\s]+(?:alicdn|tbcdn)\.com[^"\'<>\s]+)', detail_html, flags=re.IGNORECASE):
        image_url = html.unescape(match.group(1) or '').replace('\\/', '/').strip().rstrip('\\')
        if image_url not in seen:
            seen.add(image_url)
            image_urls.append(image_url)
    return image_urls


def _build_1688_sku_info(snapshot: dict, clean_url_fn, default_price: float):
    sku_props = snapshot.get('sku_props') or []
    sku_map = snapshot.get('sku_map') or []
    prop_titles = []
    value_image_map = {}

    # clean_url_fn 允许为 None：调用方有时不需要 URL 清洗逻辑，给个 no-op fallback
    def _clean(u):
        u = (u or '').strip()
        if not u:
            return ''
        if callable(clean_url_fn):
            try:
                return clean_url_fn(u) or ''
            except Exception:
                pass
        # 内置回退清洗：补全协议
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http'):
            return u
        return ''

    for prop in sku_props:
        prop_name = str(prop.get('prop') or prop.get('name') or '').strip()
        if prop_name:
            prop_titles.append(prop_name)
        for value in prop.get('value') or []:
            value_name = str(value.get('name') or '').strip()
            raw_image = value.get('imageUrl') or value.get('image') or value.get('imgUrl') or ''
            cleaned_image = _clean(raw_image)
            if value_name and cleaned_image:
                value_image_map[value_name] = cleaned_image

    sku_info = []
    if sku_map:
        for index, item in enumerate(sku_map, start=1):
            spec_attrs = html.unescape(str(item.get('specAttrs') or '')).replace('&gt;', '>')
            spec_parts = [part.strip() for part in spec_attrs.split('>') if part and part.strip()]
            name = ' / '.join(spec_parts) if spec_parts else f'SKU{index}'
            image_url = ''
            for part in spec_parts:
                if part in value_image_map:
                    image_url = value_image_map[part]
                    break

            price = _extract_capture_price_from_mapping(item, default_price)
            stock = item.get('canBookCount') or item.get('stock') or item.get('quantity')
            sku_info.append({
                'type': ' / '.join(prop_titles) if prop_titles else '规格',
                'name': name,
                'vid': str(item.get('skuId') or item.get('specId') or index),
                'image': image_url,
                'price': price,
                'stock': stock,
                'index': index,
            })

    if sku_info:
        return sku_info

    flattened_values = []
    for prop in sku_props:
        prop_name = str(prop.get('prop') or prop.get('name') or '').strip() or '规格'
        for value in prop.get('value') or []:
            value_name = str(value.get('name') or '').strip()
            if not value_name:
                continue
            flattened_values.append({
                'type': prop_name,
                'name': value_name,
                'image': value_image_map.get(value_name, ''),
            })

    for index, item in enumerate(flattened_values, start=1):
        sku_info.append({
            'type': item['type'],
            'name': item['name'],
            'vid': f'1688_{index}',
            'image': item['image'],
            'price': default_price,
            'index': index,
        })

    return sku_info


def _append_query_params(url: str, params: dict) -> str:
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _mtop_post_fetch(cookies_header: str, mtop_token: str, shop_id: str, seller_id: str, page_no: int,
                     cat_id: int = 0, keyword: str = '', order_type: str = 'popular',
                     sort_type: str = '', filter_type: str = '') -> dict:
    """纯 HTTP POST 调用 mtop API，不经过浏览器。
    支持筛选参数: cat_id(类目), keyword(搜索), order_type(排序), sort_type, filter_type。"""
    import hashlib
    import time
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode

    app_key = '12574478'
    api = 'mtop.taobao.shop.simple.item.fetch'
    data_obj = {
        'shopId': shop_id, 'sellerId': seller_id,
        'page': str(page_no), 'pageSize': '30',
        'orderType': order_type, 'sortType': sort_type,
        'catId': cat_id, 'keyword': keyword, 'filterType': filter_type,
    }
    data_str = json.dumps(data_obj, separators=(',', ':'))
    ts = str(int(time.time() * 1000))
    sign = hashlib.md5(f'{mtop_token}&{ts}&{app_key}&{data_str}'.encode()).hexdigest()

    query = urlencode({
        'jsv': '2.6.2', 'appKey': app_key, 't': ts, 'sign': sign,
        'api': api, 'v': '1.0', 'type': 'originaljson', 'timeout': '10000',
        'dataType': 'json', 'antiCreep': 'true',
    })
    url = f'https://h5api.m.taobao.com/h5/{api}/1.0/?{query}'
    body = urlencode({'data': data_str}).encode('utf-8')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://shop{shop_id}.taobao.com/',
        'Origin': f'https://shop{shop_id}.taobao.com',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie': cookies_header,
    }

    with urlopen(Request(url, data=body, headers=headers, method='POST'), timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _extract_text_by_selectors(page, selectors: list) -> str:
    selector_script = json.dumps(selectors, ensure_ascii=False)
    try:
        return str(page.run_js(f'''
            var selectors = {selector_script};
            for (var i = 0; i < selectors.length; i++) {{
                var node = document.querySelector(selectors[i]);
                var text = node ? (node.textContent || node.innerText || '') : '';
                if (text && text.trim()) return text.trim();
            }}
            return '';
        ''') or '').strip()
    except Exception:
        return ''


def _extract_taobao_ice_data(page) -> dict:
    """读结构化真实 SKU 组合，按 pid:vid 关联属性图，不按名称丢弃规格。"""
    from src.taobao_capture import from_ice
    result = page.run_js(r'''return (() => {
        const home=(((window.__ICE_APP_CONTEXT__||{}).loaderData||{}).home||{}).data;
        if(!home||!home.res)return JSON.stringify({error:'no_ice_data'});
        const res=home.res;
        return JSON.stringify({item:res.item||{},skuBase:res.skuBase||null,skuCore:res.skuCore||{}});
    })()''')
    payload = json.loads(result) if isinstance(result, str) else result
    if isinstance(payload, dict):
        captured_id = str((payload.get('item') or {}).get('itemId') or '')
        current_id = _extract_capture_product_id(str(getattr(page, 'url', '') or ''))
        if captured_id and current_id and captured_id != current_id:
            raise ValueError('页面结构化SKU仍属于上一件商品，不能混入本件采集结果')
    return from_ice(payload)


def _infer_capture_image_ext(url: str, content_type: str = '') -> str:
    lower_type = (content_type or '').lower()
    lower_url = (url or '').lower()
    if 'image/png' in lower_type or '.png' in lower_url:
        return '.png'
    if 'image/gif' in lower_type or '.gif' in lower_url:
        return '.gif'
    if 'image/webp' in lower_type or '.webp' in lower_url:
        return '.webp'
    return '.jpg'


def _parse_ice_from_html(html: str) -> dict:
    """从单品页 SSR HTML 中提取 __ICE_APP_CONTEXT__ JSON"""
    import re as _re
    idx = html.find('__ICE_APP_CONTEXT__')
    if idx < 0:
        return {}
    # 在 ICE 之后的 200 字符内找 var b = {
    rest = html[idx:idx+200]
    bm = _re.search(r'var\s+b\s*=\s*\{', rest)
    if not bm:
        return {}
    start = idx + bm.end() - 1
    depth = 0
    in_str = False
    esc = False
    for i in range(start, min(start+200000, len(html))):
        ch = html[i]
        if esc:
            esc = False
            continue
        if ch == chr(92):
            esc = True
            continue
        if ch == chr(34) and not esc:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i+1])
                except json.JSONDecodeError:
                    return {}
    return {}
