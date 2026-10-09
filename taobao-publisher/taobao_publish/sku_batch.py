# -*- coding: utf-8 -*-
"""同一批量配图窗口内切换规格、回读预览、最后确认一次。

布局来自用户截图；具体 DOM 仍属 candidate。每次动作必须有唯一可见行、
实际选中状态和图片回读。批量窗口存在但不能识别时明确失败，不改走逐行重开。
"""
from __future__ import annotations

import json
import time
from .page import PageError, FieldMismatchError


def expression(names, action='read', target=''):
    return r'''(() => {
      const {names, action, target} = SPEC;
      const norm = value => String(value || '').normalize('NFC').replace(/\s+/g, ' ').trim();
      const visible = el => {
        if (!el || el.closest('[hidden],[aria-hidden="true"]')) return false;
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      const exact = (root, label) => Array.from(root.querySelectorAll('*'))
        .filter(el => visible(el) && norm(el.textContent) === norm(label)
          && !Array.from(el.children).some(child => norm(child.textContent) === norm(label)));
      const titles = exact(document.body, '批量填充规格主图');
      const headings = exact(document.body, '选择图片填充');
      if (!titles.length && !headings.length) return {ok:true, advertised:false, rows:[], confirms:0};
      if (titles.length > 1 || headings.length > 1)
        return {ok:false, advertised:true, reason:'batch_panel_not_unique'};
      const anchor = titles[0] || headings[0];
      const root = anchor.closest('.next-dialog,[role="dialog"],[class*="select_image"]') || document.body;
      const confirms = Array.from(root.querySelectorAll('button')).filter(visible)
        .filter(el => /^确定(?:[（(]\d+[）)])?$/.test(norm(el.textContent)));
      const selected = row => {
        const nodes = [row, ...row.querySelectorAll('*')];
        return nodes.some(el => el.getAttribute('aria-selected') === 'true'
          || el.getAttribute('aria-checked') === 'true'
          || el.getAttribute('data-selected') === 'true'
          || (el.matches('input[type="radio"],input[type="checkbox"]') && el.checked)
          || /(?:^|[ _-])(?:selected|active|checked)(?:$|[ _-])/i.test(String(el.className || '')));
      };
      let panel = headings[0] && headings[0].parentElement;
      while (panel && panel !== root && !names.every(name => exact(panel, name).length)) panel = panel.parentElement;
      const rows = [], nodes = [];
      if (headings.length) {
        if (!panel || !names.every(name => exact(panel, name).length))
          return {ok:false, advertised:true, reason:'batch_rows_missing'};
        for (const name of names) {
          const labels = exact(panel, name);
          if (labels.length !== 1) return {ok:false, advertised:true, reason:'batch_row_not_unique', name};
          let row = labels[0].parentElement;
          while (row && row !== panel) {
            const ownsOther = names.some(other => other !== name && exact(row, other).length);
            if (ownsOther) break;
            const slot = row.querySelector('img,svg,input[type="radio"],input[type="checkbox"],'
              + '[class*="image"],[class*="Image"],[class*="upload"],[class*="Upload"]');
            if (slot) break;
            row = row.parentElement;
          }
          if (!row || row === panel || names.some(other => other !== name && exact(row, other).length))
            return {ok:false, advertised:true, reason:'batch_row_boundary_unknown', name};
          const images = Array.from(row.querySelectorAll('img[src]')).map(img => String(img.src || ''))
            .filter(url => /^https?:\/\//.test(url) && !/\.(?:svg|ico)(?:[?#]|$)/i.test(url));
          nodes.push(row);
          rows.push({name, selected:selected(row), images:Array.from(new Set(images))});
        }
      }
      if (action === 'activate') {
        const matches = rows.map((row, index) => ({row,index})).filter(entry => entry.row.name === target);
        if (matches.length !== 1) return {ok:false, advertised:true, reason:'target_row_not_unique'};
        const row = nodes[matches[0].index];
        if (row.getAttribute('aria-disabled') === 'true' || row.disabled === true)
          return {ok:false, advertised:true, reason:'batch_row_disabled'};
        if (row.form && row.type !== 'button') return {ok:false, advertised:true, reason:'batch_row_may_submit'};
        if (!matches[0].row.selected) {
          row.scrollIntoView({block:'nearest',inline:'nearest'});
          row.click();
        }
      } else if (action === 'confirm') {
        if (confirms.length !== 1) return {ok:false, advertised:true, reason:'batch_confirm_not_unique'};
        const button = confirms[0];
        if (button.disabled || button.getAttribute('aria-disabled') === 'true')
          return {ok:false, advertised:true, reason:'batch_confirm_disabled'};
        if (button.form && button.type !== 'button') return {ok:false, advertised:true, reason:'batch_confirm_may_submit'};
        button.click();
      }
      return {ok:true, advertised:true, rows, confirms:confirms.length};
    })()'''.replace('SPEC', json.dumps({'names': list(names), 'action': action, 'target': target}, ensure_ascii=False), 1)


class BatchSkuPicker:
    def __init__(self, client, names, row_context, confirm_context):
        self.client, self.names = client, list(names)
        self.row_context, self.confirm_context = row_context, confirm_context

    @staticmethod
    def _check(payload):
        if not isinstance(payload, dict) or payload.get('ok') is not True:
            reason = payload.get('reason', 'invalid_result') if isinstance(payload, dict) else 'invalid_result'
            raise PageError('批量规格配图窗口无法确认：' + str(reason))
        return payload

    @classmethod
    def discover(cls, client, names, context_ids):
        observations = [(context, client.evaluate(expression(names), context_id=context))
                        for context in dict.fromkeys(context_ids)]
        advertised = [(context, payload) for context, payload in observations
                      if isinstance(payload, dict) and payload.get('advertised')]
        if not advertised:
            if any(not isinstance(payload, dict) or payload.get('ok') is not True for _, payload in observations):
                raise PageError('无法判断当前 SKU 选图窗口类型')
            return None
        row_contexts, confirm_contexts = [], []
        for context, payload in advertised:
            cls._check(payload)
            if len(payload.get('rows', [])) == len(names): row_contexts.append(context)
            if payload.get('confirms') == 1: confirm_contexts.append(context)
            elif payload.get('confirms', 0) > 1: raise PageError('批量规格配图确认按钮不唯一')
        if len(row_contexts) != 1 or len(confirm_contexts) != 1:
            raise PageError('批量规格配图的规格列表或确认按钮不唯一')
        return cls(client, names, row_contexts[0], confirm_contexts[0])

    def read(self):
        state = self._check(self.client.evaluate(expression(self.names), context_id=self.row_context))
        if not state.get('advertised') or [row.get('name') for row in state.get('rows', [])] != self.names:
            raise PageError('批量规格配图窗口已关闭或规格列表发生变化')
        return state['rows']

    def _wait(self, predicate, message, timeout=3.0):
        deadline = time.monotonic() + timeout
        while True:
            rows = self.read()
            if predicate(rows): return rows
            if time.monotonic() >= deadline: raise FieldMismatchError(message)
            time.sleep(0.1)

    def activate(self, name):
        self._check(self.client.evaluate(expression(self.names, 'activate', name), context_id=self.row_context))
        self._wait(lambda rows: [row['name'] for row in rows if row.get('selected')] == [name],
                   '批量配图未选中唯一目标规格：' + name)

    def verify_image(self, name, url, matches):
        self._wait(lambda rows: any(row['name'] == name and len(row['images']) == 1
                   and matches(row['images'][0], url) for row in rows),
                   '批量配图预览与目标规格图片不一致：' + name)

    def confirm(self, expected, matches):
        rows = {row['name']: row for row in self.read()}
        for name, url in expected.items():
            if len(rows[name]['images']) != 1 or not matches(rows[name]['images'][0], url):
                raise FieldMismatchError('确认前规格图片发生变化：' + name)
        self._check(self.client.evaluate(expression(self.names, 'confirm'), context_id=self.confirm_context))
