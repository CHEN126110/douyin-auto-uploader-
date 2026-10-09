"""用户指定的淘宝商品一口价规则；SKU 售价不在此修改。"""
from decimal import Decimal, ROUND_CEILING


def listing_price(prices):
    values = [Decimal(str(value)) for value in prices]
    if not values or any(not value.is_finite() for value in values):
        raise ValueError('一口价需要有效的 SKU 单价')
    return int((min(values) * 2).to_integral_value(rounding=ROUND_CEILING))
