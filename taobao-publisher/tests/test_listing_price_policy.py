# -*- coding: utf-8 -*-
from decimal import Decimal
import pytest
from taobao_publish.price_policy import listing_price
from taobao_publish import models, stages


@pytest.mark.parametrize('values, expected', [
    ([9.9], 20), ([9.1], 19), ([9.0], 18), ([9.5], 19), ([19.9,9.9],20),
    ([Decimal('0.29')], 1), ([Decimal('10.000000001')],21),
])
def test_twice_minimum_rounded_up_to_whole_yuan(values, expected):
    assert listing_price(values) == expected


@pytest.mark.parametrize('values', [[], [float('inf')], [float('nan')]])
def test_missing_or_nonfinite_prices_are_rejected(values):
    with pytest.raises(ValueError):
        listing_price(values)


def test_expected_listing_price_does_not_change_sku_prices():
    skus=[models.SkuEntry({'颜色':'黑'}, price=9.9, stock=1), models.SkuEntry({'颜色':'白'}, price=12.8, stock=1)]
    ctx=stages.PipelineContext(item=models.PublishItem(record_id=1, record_name='价格测试', skus=skus), dry_run=False)
    fields={entry['label']:entry['value'] for entry in stages.expected_field_values(ctx)}
    assert fields['一口价'] == '20.00'
    assert [sku.price for sku in skus] == [9.9,12.8]
