# -*- coding: utf-8 -*-
"""完整填写不得忽略调用方明确提供的 SKU 图、详情图；不连接平台。"""
from unittest.mock import Mock

import pytest

from taobao_publish.models import ImageSet, PublishItem, SkuEntry
from taobao_publish import stages


@pytest.mark.parametrize('images,skus,field', [
    (ImageSet(sku=['SKU图.jpg']), [], 'images.sku'),
    (ImageSet(), [SkuEntry(image_path='SKU图.jpg')], 'images.sku'),
    (ImageSet(detail=['详情图.jpg']), [], 'images.detail'),
])
def test_unimplemented_media_intent_cannot_be_reported_as_readback_success(monkeypatch, images, skus, field):
    item = PublishItem(record_id=1, record_name='商品一', title='袜子', images=images, skus=skus)
    opener = Mock(side_effect=AssertionError('不能为未消费的媒体意图假造回读结果'))
    monkeypatch.setattr(stages, '_open_publish_page', opener)
    result = stages.stage_readback(stages.PipelineContext(item=item, dry_run=False))
    assert not result.ok and result.error_code == 'EVIDENCE_INSUFFICIENT'
    assert any(blocker.field == field for blocker in result.blockers)
    assert '未完成' in result.summary
    opener.assert_not_called()


def test_dry_run_is_still_a_skip_and_does_not_claim_media_was_written():
    item = PublishItem(record_id=1, record_name='商品一', images=ImageSet(sku=['sku.jpg'], detail=['detail.jpg']))
    result = stages.stage_readback(stages.PipelineContext(item=item, dry_run=True))
    assert result.status == 'skipped' and '不写平台' in result.summary
