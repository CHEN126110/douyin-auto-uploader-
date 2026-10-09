"""采集商品参数的存储契约。只收显式名称和值，不把埋点字典当商品属性。"""
from __future__ import annotations

import json

SOURCE = 'visible_product_parameters_v1'


def normalize(raw):
    """旧记录没有属性时返回空值；损坏资料明确报错，不静默降级。"""
    if raw is None or raw == '':
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw is None:
        return None
    if (not isinstance(raw, dict) or type(raw.get('version')) is not int
            or raw['version'] != 1 or raw.get('source') != SOURCE
            or raw.get('status') not in ('captured', 'not_found', 'disabled')):
        raise ValueError('采集商品属性的来源或版本无效')
    entries = raw.get('attributes')
    if not isinstance(entries, list) or len(entries) > 200:
        raise ValueError('采集商品属性必须是最多 200 项的列表')
    values = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'name', 'value'}:
            raise ValueError('采集商品属性必须明确提供 name 和 value')
        name, value = entry['name'], entry['value']
        if (not isinstance(name, str) or not isinstance(value, str)
                or not name.strip() or not value.strip()
                or len(name) > 80 or len(value) > 1000
                or any(ord(char) < 32 and char not in '\n\t\r' for char in name + value)):
            raise ValueError('采集商品属性的名称或值无效')
        name, value = name.strip(), value.strip()
        if name in values and values[name] != value:
            raise ValueError('采集商品属性存在冲突：' + name)
        values[name] = value
    if (raw['status'] == 'captured') != bool(values):
        raise ValueError('采集商品属性的状态与内容不一致')
    return {'version': 1, 'source': SOURCE, 'status': raw['status'],
            'attributes': [{'name': name, 'value': values[name]} for name in sorted(values)]}


def dumps(raw):
    value = normalize(raw)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) if value else None


def read_expression():
    """只读可见参数区中的结构化表格/dl/旧参数列表；未识别时如实返回空。

    这是有结构校验的候选 DOM 适配，不宣称涵盖所有平台页面。
    不读 window 上的业务/埋点对象，也不提取账号资料、隐藏区或整页文本。
    """
    return r'''(() => {
      const visible = el => {
        if (!el || !el.getClientRects().length) return false;
        for (let node=el; node; node=node.parentElement) {
          const style=getComputedStyle(node);
          if (node.hidden || style.display==='none' || style.visibility==='hidden') return false;
        }
        return true;
      };
      const text = el => (el?.innerText || '').trim();
      const titles = new Set(['商品参数', '产品参数', '规格参数', '商品属性']);
      const roots = new Set();
      for (const el of document.querySelectorAll('table,dl,section,[role="region"]')) {
        const ownHeading = Array.from(el.children).find(n=>n.matches('caption,h1,h2,h3,h4,h5,h6'));
        if (visible(el) && (titles.has(el.getAttribute('aria-label')) || titles.has(text(ownHeading)))) roots.add(el);
      }
      for (const heading of document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')) {
        const next = heading.nextElementSibling;
        if (visible(heading) && titles.has(text(heading)) && visible(next)
            && next.matches('table,dl,section,[role="region"]')) roots.add(next);
      }
      // 旧商品页显式参数列表；仅解析自身 li 内的首个冒号。
      for (const el of document.querySelectorAll('#J_AttrUL,#attributes .attributes-list')) {
        if (visible(el)) roots.add(el);
      }
      const attributes=[], seen=new Set();
      const add=(name,value,node)=>{
        if (!visible(node) || seen.has(node)) return;
        seen.add(node);
        name=name.trim(); value=value.trim();
        if (!name || !value) throw new Error('商品参数行缺少名称或值');
        attributes.push({name,value});
      };
      for (const root of roots) {
        const tables = root.matches('table') ? [root] : root.querySelectorAll('table');
        for (const table of tables) for (const row of table.rows) {
          if (!visible(row)) continue;
          const cells=Array.from(row.cells);
          if (cells.length===2 && cells[1].tagName==='TD') add(text(cells[0]),text(cells[1]),row);
        }
        const lists = root.matches('dl') ? [root] : root.querySelectorAll('dl');
        for (const list of lists) for (const key of list.querySelectorAll(':scope > dt')) {
          const value=key.nextElementSibling;
          if (value?.matches('dd') && visible(value)) add(text(key),text(value),key);
        }
        if (root.matches('#J_AttrUL,#attributes .attributes-list')) {
          for (const li of root.querySelectorAll(':scope > li')) {
            const match=text(li).match(/^([^:：]+)[:：]([\s\S]+)$/);
            if (match) add(match[1],match[2],li);
          }
        }
      }
      return {version:1, source:'visible_product_parameters_v1',
              status:attributes.length ? 'captured' : 'not_found', attributes};
    })()'''


def capture(page, *, enabled=True):
    if not enabled:
        return {'version': 1, 'source': SOURCE, 'status': 'disabled', 'attributes': []}
    raw = page.run_js('return ' + read_expression())
    if not isinstance(raw, dict):
        raise ValueError('商品参数读取没有返回可识别的结果')
    return normalize(raw)
