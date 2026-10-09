# -*- coding: utf-8 -*-
"""任务执行成功与完整填写验证分开判断；纯函数，不触碰浏览器或账户。"""
from __future__ import annotations

from collections.abc import Mapping

WHOLE_FORM_SCOPE = 'whole_publish_form_required_fields'


def whole_form_coverage_confirmed(coverage):
    if not isinstance(coverage, Mapping):
        return False
    if (coverage.get('known') is not True or coverage.get('completePage') is not True
            or coverage.get('scope') != WHOLE_FORM_SCOPE):
        return False
    row_count = coverage.get('rowCount')
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 1:
        return False
    required, checked = coverage.get('required'), coverage.get('checked')
    if not isinstance(required, list) or not isinstance(checked, list):
        return False
    # 发布页已有标题等必填项，空回执或必填数大于所读行数是缺失/矛盾证据。
    if not required or len(required) > row_count:
        return False
    def labels(entries, is_required):
        result = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                return None
            label = entry.get('label')
            if not isinstance(label, str) or not label.strip() or label != label.strip():
                return None
            if is_required:
                if type(entry.get('hitCount')) is not int or entry.get('hitCount') != 1 or entry.get('supportedReader') is not True:
                    return None
            else:
                value = entry.get('value')
                if not isinstance(value, str) or not value.strip():
                    return None
            result.append(label)
        return result if len(set(result)) == len(result) else None
    wanted, actual = labels(required, True), labels(checked, False)
    count = coverage.get('checkedCount')
    return (wanted is not None and actual is not None and set(wanted) == set(actual)
            and not isinstance(count, bool) and isinstance(count, int)
            and count == len(actual) == len(wanted))


def visible_requirements_have_no_failures(facts):
    """新增局部事实只用于否决；没有这份附加回执也不能据此证明完整填写。"""
    if facts is None:
        return True
    if (not isinstance(facts, Mapping) or facts.get('known') is not True
            or facts.get('scope') != 'visible_publish_rows_required' or facts.get('completePage') is not False
            or type(facts.get('rowCount')) is not int or facts['rowCount'] < 1
            or type(facts.get('unownedRequiredCount')) is not int or facts['unownedRequiredCount'] != 0
            or not isinstance(facts.get('required'), list) or len(facts['required']) > facts['rowCount']):
        return False
    labels=set()
    for field in facts['required']:
        if not isinstance(field, Mapping):
            return False
        label=field.get('label')
        if (not isinstance(label,str) or not label.strip() or label!=label.strip() or label in labels
                or type(field.get('hitCount')) is not int or field['hitCount'] != 1
                or field.get('supportedReader') is not True or field.get('filled') is not True
                or field.get('valid') is not True):
            return False
        labels.add(label)
    return True


def summarize_form_verification(runs, *, success, dry_run, stopped_before_submit):
    """只有完整、可解析的整页必填回读才可声明完整填写；无证据保持未验证。"""
    result = {'status': 'not_verified', 'complete': False,
              'required_field_coverage': None, 'visible_form_requirements': None,
              'reason': '没有完成本次写入的最终回读'}
    if dry_run is not False:
        result['reason'] = '校对模式未填写平台表单'
        return result
    readbacks = [run for run in runs if run.name == 'readback']
    if len(readbacks) != 1:
        return result
    outcome = readbacks[0].outcome
    native = outcome.data.get('visible_form_requirements')
    result['visible_form_requirements'] = dict(native) if isinstance(native, Mapping) else native
    if outcome.status != 'ok' or outcome.ok is not True or success is not True:
        result['status'] = 'failed' if outcome.status == 'failed' else 'not_verified'
        result['reason'] = '最终回读未通过，不能声明完整填写'
        return result
    coverage = outcome.data.get('required_field_coverage')
    result['required_field_coverage'] = dict(coverage) if isinstance(coverage, Mapping) else None
    result['status'] = 'partial'
    result['reason'] = '本次已执行字段的回读通过，整页必填覆盖尚未确认'
    if stopped_before_submit is not True:
        result['reason'] = '执行范围未停在提交前，不能作为提交前填写完成'
        return result
    if not visible_requirements_have_no_failures(native):
        result['reason'] = '可见发布表单必填控件仍有未通过或未知项，不能声明完整填写'
        return result
    if whole_form_coverage_confirmed(coverage):
        if isinstance(native, Mapping):
            covered_labels = {entry['label'] for entry in coverage['required']}
            if any(entry['label'] not in covered_labels for entry in native['required']):
                result['reason'] = '整页必填清单遗漏了本次可见的必填字段，不能声明完整填写'
                return result
        result.update(status='complete', complete=True, reason='整页必填及本次写入回读已确认，停在提交前')
    return result
