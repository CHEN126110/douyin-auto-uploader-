# -*- coding: utf-8 -*-
"""淘宝发布的无状态部分：发布开关的解析与校验、从商品记录构造请求载荷，以及它们用到的常量。

这里的函数只依赖入参和标准库，不碰任务字典、锁、账户、浏览器和 Flask 请求上下文——所以能脱离账户状态直接单测。需要这些的逻辑在 ``taobao_service.TaobaoPublishService``。

函数名保持 app.py 里的原名（含下划线前缀），便于新旧对照。"""
import json


#: 上架方式只允许页面上**实测存在**的三个选项；空串表示"用流水线默认值"。
TAOBAO_LISTING_MODES = ('', '立刻上架', '定时上架', '放入仓库')
_CATEGORY_LABELS = {0: '船袜', 1: '短袜', 2: '中筒袜', 3: '长筒袜', 4: '袜套'}


def _parse_taobao_publish_options(data):
    """解析并校验 `/api/taobao/publish/start` 的开关参数。

    抽成**纯函数**的理由：这段校验原来是内联在路由里的，于是它的行为**只有登录
    淘宝账户时才测得到**（前面还有 `_require_publish_platform` 那道账户门）。
    而这里恰恰是几条一旦写错就静默出错的不变量——默认值写反、字符串 `"false"`
    被当成真值——所以必须能脱离账户状态直接验证。

    :return: ``(options_dict, error_message)``；``error_message`` 非空表示应当 400。
    """

    if not isinstance(data, dict):
        return None, '请求必须是 JSON 对象'
    unknown = set(data) - {
        'record_id', 'platform', 'account_profile', 'dry_run', 'stop_before_submit',
        'product', 'fill_only', 'expected_record_revision', 'listing_mode', 'save_draft',
    }
    if unknown:
        return None, '请求包含不支持的参数'

    # 布尔值必须**显式是布尔**：字符串 "false" 在 Python 里是真值，
    # 不校验就会绕过 dry-run / save_draft 的默认值。
    flags = {
        'dry_run': data.get('dry_run', True),
        'stop_before_submit': data.get('stop_before_submit', True),
        'fill_only': data.get('fill_only', False),
        # 保存草稿是写入，**默认必须 False**：授权只是白名单，这个开关才决定点不点按钮。
        'save_draft': data.get('save_draft', False),
    }
    for key, value in flags.items():
        if not isinstance(value, bool):
            return None, '{} 必须是布尔值'.format(key)

    # 上架方式：取值必须来自页面实测的三个选项。
    # **危险的那个（立刻上架）绝不能是默认值**——默认落到空串 = 流水线用「放入仓库」。
    listing_mode = data.get('listing_mode', '')
    if listing_mode is None:
        listing_mode = ''
    if not isinstance(listing_mode, str):
        return None, 'listing_mode 必须是字符串'
    listing_mode = listing_mode.strip()
    if listing_mode not in TAOBAO_LISTING_MODES:
        return None, 'listing_mode 只能是 {} 之一'.format(
            '、'.join(TAOBAO_LISTING_MODES[1:]))

    return {**flags, 'listing_mode': listing_mode}, None


def _taobao_product_from_record(record):
    """从 Record 构建淘宝商品请求载荷。纯函数，供批量发布使用。"""
    try:
        sku_list = json.loads(record.content) if record.content else []
    except (ValueError, TypeError):
        sku_list = []

    clazz_raw = record.clazz
    # ``Record.clazz`` 是 CharField：整数 2 存进去、从库里读出来是字符串 ``'2'``。去掉首尾空白后全是数字的字符串
    # 就是类目代码，和整数走同一个映射（以前只认整数，批量发布给流水线的类目关键词因此是 ``'2'``）。
    # 认不得的代码给空串（不猜）；本来就是文字的类目（``'短袜'``）原样使用。
    if isinstance(clazz_raw, str):
        digits = clazz_raw.strip()
        if digits.isascii() and digits.isdigit():
            clazz_raw = int(digits)
    if isinstance(clazz_raw, int):
        keyword = _CATEGORY_LABELS.get(clazz_raw, '')
    else:
        keyword = str(clazz_raw or '').strip()

    stock = int(record.repo or 0)
    skus = []
    for s in sku_list:
        if not isinstance(s, dict):
            continue
        name = str(s.get('name') or '').strip()
        try:
            price = float(s.get('price', 0))
        except (ValueError, TypeError):
            price = 0
        if not name or price <= 0:
            continue
        raw_specs = s.get('spec_values') or {}
        if not isinstance(raw_specs, dict):
            raise ValueError('第{}条 SKU 的 spec_values 必须是对象'.format(len(skus) + 1))
        # 保留采集/编辑得到的附加规格；当前编辑的 SKU 名称始终覆盖主规格。
        entry = {'spec_values': {**raw_specs, '颜色分类': name}, 'price': price, 'stock': stock}
        img = str(s.get('path') or '').strip()
        if img:
            entry['image_path'] = img
        skus.append(entry)

    return {
        'title': (record.title or '').strip() or (record.name or '').strip(),
        'category_keyword': keyword,
        'sku_mode': 'custom',
        'outer_id': (record.name or '').strip(),
        'skus': skus,
    }
