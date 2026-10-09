"""把采集事实用于当前类目的必填属性；不猜别名、枚举 ID 或复合控件含义。"""
from __future__ import annotations

import json
import re

from .captured_attributes import normalize, SOURCE
from .models import PropEntry, EvidenceRef
from . import page

# 来源字段不允许覆盖售价、库存、物流、销售规格或用户选择的品牌。
AUTO_REQUIRED_NAMES = frozenset({'上市年份季节', '适用季节', '适用年龄', '适用性别', '适用场景'})


def _expression(label, *, action='', value=''):
    source = r'''(() => {
      const name=__LABEL__, action=__ACTION__, desired=__VALUE__;
      const profiles=[['.sell-component-info-wrapper-wrap','.sell-component-info-wrapper-label'],
                      ['.sell-catProp-item-common','label']];
      const selector=profiles.map(p=>p[0]).join(',');
      const visible=el=>el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden';
      const rows=new Set();
      for (const [rowSelector,labelSelector] of profiles) {
        for (const row of document.querySelectorAll(rowSelector)) {
          const label=Array.from(row.querySelectorAll(labelSelector)).find(n=>n.closest(selector)===row);
          if (label && label.textContent.trim()===name) rows.add(row);
        }
      }
      if (rows.size===0) return {ok:true,found:false};
      if (rows.size!==1) return {ok:false,reason:'目标行不唯一'};
      const row=Array.from(rows)[0];
      if (!visible(row)) return {ok:true,found:false};
      const own=sel=>Array.from(row.querySelectorAll(sel)).filter(n=>n.closest(selector)===row && visible(n));
      const controls=own('input:not([type=hidden]),textarea,select,[role=combobox]');
      const labels=own('label,.sell-component-info-wrapper-label-wrap');
      const required=controls.some(n=>n.required || n.getAttribute('aria-required')==='true')
        || labels.some(n=>n.matches('label.required') || /[*＊]/.test(n.textContent));
      if (!required) return {ok:true,found:true,required:false};
      if (controls.length!==1) return {ok:false,reason:'包含多个或未知控件'};
      const control=controls[0];
      const kind=control.getAttribute('role')==='combobox' ? 'combobox'
        : control.tagName==='SELECT' ? 'select'
        : control.tagName==='TEXTAREA' || (control.tagName==='INPUT' && ['text','search','number'].includes(control.type))
          ? 'text' : 'unsupported';
      if (action==='guard') {
        if (kind!=='combobox') return {ok:false,reason:'下拉控件已改变'};
        return {ok:true,found:true,required:true,kind};
      }
      if (action==='write') {
        if (!['text','select'].includes(kind)) return {ok:false,reason:'控件无法直接填写'};
        let next=desired;
        if (kind==='select') {
          const matches=Array.from(control.options).filter(n=>n.textContent.trim()===desired
            && !n.disabled && !n.closest('optgroup[disabled]') && n.value!=='');
          if (matches.length!==1) return {ok:false,reason:'没有唯一且可用的下拉选项'};
          next=matches[0].value;
        }
        if ((control.disabled || control.readOnly) && control.value!==next)
          return {ok:false,reason:'控件不可编辑'};
        if (control.value!==next) {
          const proto=control.tagName==='SELECT' ? HTMLSelectElement.prototype
            : control.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(control,next);
          control.dispatchEvent(new Event('input',{bubbles:true}));
          control.dispatchEvent(new Event('change',{bubbles:true}));
        }
      }
      const value=kind==='select' ? (control.selectedOptions[0]?.textContent || '').trim() : control.value;
      return {ok:true,found:true,required:true,kind,value,
              valid:control.validity ? control.validity.valid : true};
    })()'''
    values = {'LABEL': label, 'ACTION': action, 'VALUE': value}
    return re.sub(r'__(LABEL|ACTION|VALUE)__', lambda match: json.dumps(values[match[1]], ensure_ascii=False), source)


class _ExactComboboxClient:
    """每次动作与行检查在同一次 JS 求值内执行，防止页面重绘后串行。"""
    def __init__(self, client, label):
        self.client, self.label = client, label

    def evaluate(self, expression):
        guard = _expression(self.label, action='guard')
        return self.client.evaluate('(() => {const guard=' + guard + ';'
            'if (!guard.ok) return guard;'
            'if (!guard.found || !guard.required) return {ok:false,reason:"采集属性目标已改变"};'
            'return (' + expression + ');})()')


def _checked(client, label, **options):
    result = client.evaluate(_expression(label, **options))
    if not isinstance(result, dict) or result.get('ok') is not True:
        reason = result.get('reason', '无有效结果') if isinstance(result, dict) else '无有效结果'
        raise page.PageError('采集属性「{}」：{}'.format(label, reason))
    return result


def read(client, label):
    shape = _checked(client, label)
    if not shape.get('found') or not shape.get('required'):
        raise page.FieldMismatchError('采集属性目标已改变：' + label)
    if shape.get('kind') == 'combobox':
        return page.read_prop_value(_ExactComboboxClient(client, label), label, exact_only=True)
    if shape.get('kind') not in ('text', 'select') or shape.get('valid') is not True:
        raise page.FieldMismatchError('采集属性控件回读无效：' + label)
    return shape.get('value')


def fill(client, item):
    captured = normalize(item.captured_attributes)
    if not captured or not captured['attributes']:
        return [], []
    explicit = {prop.prop_name for prop in item.props}
    results, skipped = [], []
    for entry in captured['attributes']:
        name, value = entry['name'], entry['value']
        if name in explicit or name not in AUTO_REQUIRED_NAMES:
            skipped.append({'label': name, 'reason': 'explicit_value' if name in explicit else 'no_automatic_mapping'})
            continue
        shape = _checked(client, name)
        if not shape.get('found') or not shape.get('required'):
            skipped.append({'label': name, 'reason': 'not_current_required_field'})
            continue
        if shape.get('kind') == 'combobox':
            outcome = page.pick_prop_value(_ExactComboboxClient(client, name), name, value, exact_only=True)
            read_back = outcome['read_back']
        else:
            _checked(client, name, action='write', value=value)
            read_back = read(client, name)
        if read_back != value:
            raise page.FieldMismatchError('采集属性填写后回读不一致：' + name)
        item.props.append(PropEntry(name, value, evidence=EvidenceRef(level='candidate', source=SOURCE)))
        results.append({'label': name, 'written': value, 'read_back': read_back, 'how': 'captured_required_attribute'})
    return results, skipped
