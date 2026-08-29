# -*- coding: utf-8 -*-
"""只读探查关键类目属性的真实可选值（点开下拉读选项，不选、不提交）。
用于确认 L1 画像的词能否匹配抖店预设选项，是 L3 不臆造的依据。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.utils import attach_existing_debug_browser

DEBUG_ADDR = "127.0.0.1:9333"
ATTRS = ["适用性别", "筒高", "厚度", "图案", "功能", "适用季节", "风格"]

def find_fxg_tab(browser):
    for tab in browser.get_tabs():
        try:
            if 'fxg.jinritemai.com/ffa/g/create' in (tab.url or ''):
                return tab
        except Exception:
            continue
    return browser.latest_tab

# 点开指定属性的 select，dump 下拉选项，再关闭
OPEN_DUMP_JS = r"""
return (function(){
  var NAME = "%s";
  var field = document.querySelector('[attr-field-id="'+NAME+'"]');
  if(!field) return {ok:false, reason:'no field'};
  // 找 select 触发器
  var trigger = field.querySelector('[class*="select-selector"],[role="combobox"],[class*="select-selection"]')
    || field.querySelector('[class*="select"]');
  if(!trigger) return {ok:false, reason:'no trigger'};
  trigger.scrollIntoView({block:'center'});
  ['mousedown','mouseup','click'].forEach(function(t){
    trigger.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));
  });
  return {ok:true};
})()
"""

DUMP_OPTIONS_JS = r"""
return (function(){
  // 可见的下拉选项（ecom-g-select-item / cascader-menu-item / li）
  var dd = document.querySelector('[class*="select-dropdown"]:not([class*="hidden"])')
    || document.querySelector('[class*="cascader-menus"]:not([class*="hidden"])');
  if(!dd) {
    // 兜底：全页找可见 select-item
    var items = [...document.querySelectorAll('[class*="select-item-option"],[class*="select-item"]')]
      .filter(function(e){return e.offsetParent!==null;});
    return {found: items.length>0, options: items.map(function(e){return (e.textContent||'').trim();}).slice(0,40)};
  }
  var items = [...dd.querySelectorAll('[class*="select-item-option"],[class*="cascader-menu-item"],li,[role="option"]')];
  var opts = [...new Set(items.map(function(e){return (e.textContent||'').trim();}))]
    .filter(function(s){return s && !/^\d+$/.test(s) && s.length<=12;});
  return {found:true, options: opts.slice(0,40)};
})()
"""

CLOSE_JS = "document.body.click();"

report = {}
try:
    browser = attach_existing_debug_browser(DEBUG_ADDR)
    tab = find_fxg_tab(browser)
    url = (tab.url or "")
    print("attach:", url[:60])
    if 'ffa/g/create' not in url:
        print("!! 不在发布页"); report = {"ok": False, "reason": "not on create page"}
    else:
        results = {}
        for name in ATTRS:
            # 确保旧下拉彻底关闭
            tab.run_js(CLOSE_JS); time.sleep(0.5)
            opened = tab.run_js(OPEN_DUMP_JS % name)
            if not opened.get("ok"):
                results[name] = {"error": opened.get("reason")}
                print(f"  {name}: 打不开 ({opened.get('reason')})")
                continue
            # 轮询等下拉稳定（最多 2s）
            opts = []
            for _ in range(10):
                time.sleep(0.2)
                dump = tab.run_js(DUMP_OPTIONS_JS)
                cur = dump.get("options", [])
                if cur and cur == opts:  # 连续两次相同视为稳定
                    break
                opts = cur
            results[name] = {"options": opts}
            print(f"  {name} ({len(opts)}项): {opts[:15]}")
            tab.run_js(CLOSE_JS); time.sleep(0.4)
        report = {"ok": True, "attrs": results}
except Exception as e:
    import traceback; traceback.print_exc()
    report = {"ok": False, "error": str(e)}

with open("tmp_runtime_probe_live/attr-options.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("\n报告: tmp_runtime_probe_live/attr-options.json")
