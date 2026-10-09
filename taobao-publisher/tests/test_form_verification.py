from copy import deepcopy
import pytest

from taobao_publish.verification import summarize_form_verification, whole_form_coverage_confirmed
from taobao_publish.stages import StageOutcome, StageRun


def coverage():
    return {'known': True, 'completePage': True, 'scope': 'whole_publish_form_required_fields',
            'rowCount': 8, 'required': [{'label': '品牌', 'hitCount': 1, 'supportedReader': True}],
            'checked': [{'label': '品牌', 'value': '调用方明确提供的品牌'}], 'checkedCount': 1}


def result(facts, **options):
    run = StageRun('readback', StageOutcome(data={'required_field_coverage': facts}))
    return summarize_form_verification([run], success=options.get('success', True),
                                      dry_run=options.get('dry_run', False),
                                      stopped_before_submit=options.get('stopped', True))


def test_complete_requires_an_explicit_whole_form_scope_and_checked_values():
    assert whole_form_coverage_confirmed(coverage())
    assert result(coverage())['complete'] is True


@pytest.mark.parametrize('patch', [
    {'required': [], 'checked': [], 'checkedCount': 0},
    {'rowCount': 1, 'required': [{'label': '品牌', 'hitCount': 1, 'supportedReader': True},
        {'label': '标题', 'hitCount': 1, 'supportedReader': True}],
        'checked': [{'label': '品牌', 'value': '无品牌'}, {'label': '标题', 'value': '模型标题'}], 'checkedCount': 2},
    {'known': False}, {'known': 'true'}, {'completePage': False},
    {'scope': 'visible_property_label_required'}, {'scope': 'unknown'},
    {'rowCount': 0}, {'rowCount': True}, {'checkedCount': True}, {'checkedCount': 2},
    {'required': None}, {'checked': []}, {'checked': [{'label': '品牌', 'value': ' '}]},
    {'required': [{'label': '品牌', 'hitCount': 2, 'supportedReader': True}]},
    {'required': [{'label': '品牌', 'hitCount': 1.0, 'supportedReader': True}]},
    {'required': [{'label': '品牌', 'hitCount': 1, 'supportedReader': False}]},
    {'checked': [{'label': '其它属性', 'value': '不应匹配'}]},
    {'checked': [{'label': '品牌', 'value': 'A'}, {'label': '品牌', 'value': 'A'}], 'checkedCount': 2},
])
def test_partial_or_malformed_coverage_is_not_full_completion(patch):
    facts = deepcopy(coverage()); facts.update(patch)
    assert not whole_form_coverage_confirmed(facts)
    summary = result(facts)
    assert summary['status'] == 'partial' and summary['complete'] is False


@pytest.mark.parametrize('facts', [None, {}, 'complete'])
def test_absent_coverage_cannot_be_assumed_complete(facts):
    assert not result(facts)['complete']


@pytest.mark.parametrize('options', [{'dry_run': True}, {'success': False}, {'stopped': False}])
def test_execution_mode_and_outcome_are_part_of_completion(options):
    assert not result(coverage(), **options)['complete']


def test_readback_not_run_or_failed_is_explicitly_unverified():
    assert summarize_form_verification([], success=True, dry_run=False, stopped_before_submit=True)['complete'] is False
    failed = StageRun('readback', StageOutcome.failed('READBACK_FAILED', '有必填缺值'))
    assert summarize_form_verification([failed], success=False, dry_run=False, stopped_before_submit=True)['status'] == 'failed'


def test_duplicate_readback_results_are_not_a_unique_proof():
    run = StageRun('readback', StageOutcome(data={'required_field_coverage': coverage()}))
    assert not summarize_form_verification([run, run], success=True, dry_run=False, stopped_before_submit=True)['complete']


@pytest.mark.parametrize('patch',[
    {'known':False}, {'unownedRequiredCount':1},
    {'required':[{'label':'发货时间','hitCount':1,'supportedReader':True,'filled':False,'valid':True}]},
    {'required':[{'label':'一口价','hitCount':1,'supportedReader':True,'filled':True,'valid':False}]},
])
def test_native_required_failures_veto_a_contradictory_complete_claim(patch):
    facts={'known':True,'scope':'visible_publish_rows_required','completePage':False,
           'rowCount':1,'unownedRequiredCount':0,'required':[]}
    facts.update(patch)
    run=StageRun('readback',StageOutcome(data={'required_field_coverage':coverage(),'visible_form_requirements':facts}))
    summary=summarize_form_verification([run],success=True,dry_run=False,stopped_before_submit=True)
    assert summary['status']=='partial' and summary['complete'] is False
    assert summary['visible_form_requirements']==facts


def test_failed_readback_preserves_native_required_diagnostics():
    facts={'known':False,'reason':'控件事实读取失败'}
    outcome=StageOutcome.failed('READBACK_FAILED','未验证')
    outcome.data={'visible_form_requirements':facts}
    summary=summarize_form_verification([StageRun('readback',outcome)],success=False,dry_run=False,stopped_before_submit=True)
    assert summary['status']=='failed' and summary['visible_form_requirements']==facts


def test_whole_form_list_cannot_omit_an_observed_required_field_even_when_it_has_value():
    native={'known':True,'scope':'visible_publish_rows_required','completePage':False,
        'rowCount':1,'unownedRequiredCount':0,'required':[{'label':'发货时间','hitCount':1,
        'supportedReader':True,'filled':True,'valid':True}]}
    run=StageRun('readback',StageOutcome(data={'required_field_coverage':coverage(),'visible_form_requirements':native}))
    summary=summarize_form_verification([run],success=True,dry_run=False,stopped_before_submit=True)
    assert not summary['complete'] and '遗漏' in summary['reason']
    native['required'][0]['label']='品牌'
    summary=summarize_form_verification([run],success=True,dry_run=False,stopped_before_submit=True)
    assert summary['complete'] is True
