# -*- coding: utf-8 -*-
"""只读探查抖店发布页"类目属性"区真实字段，作为 L3 属性补全的数据基础。
列出每个属性：名称 / 是否必填 / 控件类型 / 占位符 / 已有可选值。不修改、不提交。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.utils import attach_existing_debug_browser

DEBUG_ADDR = "127.0.0.1:9333"

def find_fxg_tab(browser):
    for tab in browser.get_tabs():
        try:
            if 'fxg.jinritemai.com/ffa/g/create' in (tab.url or ''):
                return tab
        except Exception:
            continue
    return browser.latest_tab

# 滚动到类目属性区（懒加载）
SCROLL_JS = r"""
return (function(){
  var t = [...document.querySelectorAll('*')].find(function(e){
    return e.children.length===0 && (e.textContent||'').trim()==='类目属性';
  });
  if(t){ t.scrollIntoView({behavior:'instant',block:'center'}); return {scrolled:true}; }
  var c = document.querySelector('[attr-field-id="类目属性"]');
  if(c){ c.scrollIntoView({behavior:'instant',block:'center'}); return {scrolled:'byField'}; }
  return {scrolled:false};
})()
"""

DUMP_JS = r"""
return (function(){
  // 类目属性容器：优先 attr-field-id=类目属性，否则全页
  var scope = document.querySelector('[attr-field-id="类目属性"]')
    || document.querySelector('#goodsEditScrollContainer-基础信息')
    || document.body;
  // 每个属性项：抖店属性项常带 attr-field-id 或 label+控件
  var fields = [...scope.querySelectorAll('[attr-field-id]')];
  var skip = new Set(['商品规格','类目属性','主图','主图视频','主图3:4','商品标题','商品类目']);
  var out = [];
  fields.forEach(function(f){
    var id = f.getAttribute('attr-field-id');
    if(!id || skip.has(id)) return;
    var required = !!f.querySelector('[class*="required"]')
      || /(^|[^a-zA-Z])\*/.test((f.querySelector('label,span')||{}).textContent||'');
    var hasCascader = !!f.querySelector('[class*="cascader"]');
    var hasSelect = !!f.querySelector('[class*="select-selector"],[role="combobox"]');
    var hasInput = !!f.querySelector('input:not([type=checkbox]):not([type=radio])');
    var hasRadio = !!f.querySelector('input[type=radio],[class*="radio"]');
    var hasCheckbox = !!f.querySelector('input[type=checkbox],[class*="checkbox"]');
    var inp = f.querySelector('input');
    var ph = inp ? (inp.placeholder||'') : '';
    // 已选/可见选项文字（radio/标签）
    var opts = [...f.querySelectorAll('[class*="radio"] span,[class*="tag"],label')]
      .map(function(e){return (e.textContent||'').trim();})
      .filter(function(s){return s && s.length<=12;}).slice(0,12);
    var ctrl = hasCascader?'cascader':hasSelect?'select':hasRadio?'radio':hasCheckbox?'checkbox':hasInput?'input':'other';
    out.push({id:id, required:required, control:ctrl, placeholder:ph, options:[...new Set(opts)].slice(0,10)});
  });
  return {count: out.length, fields: out, scopeFound: scope!==document.body};
})()
"""

report = {}
try:
    browser = attach_existing_debug_browser(DEBUG_ADDR)
    tab = find_fxg_tab(browser)
    url = (tab.url or "")
    print("attach:", url[:70])
    if 'fxg.jinritemai.com/ffa/g/create' not in url:
        print("!! 当前不在商品发布页，请在调试浏览器打开发布页后重试")
        report = {"ok": False, "reason": "not on create page", "url": url[:120]}
    else:
        tab.run_js(SCROLL_JS); time.sleep(0.8)
        data = tab.run_js(DUMP_JS)
        report = {"ok": True, **data}
        print(f"\n类目属性区字段数: {data.get('count')} (scopeFound={data.get('scopeFound')})")
        for fld in data.get("fields", []):
            req = "必填" if fld["required"] else "选填"
            print(f"  [{req}] {fld['id']}  控件={fld['control']}  占位={fld['placeholder']}  选项={fld['options']}")
except Exception as e:
    import traceback; traceback.print_exc()
    report = {"ok": False, "error": str(e)}

with open("tmp_runtime_probe_live/category-attrs.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("\n报告: tmp_runtime_probe_live/category-attrs.json")
