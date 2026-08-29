# -*- coding: utf-8 -*-
"""用调试浏览器(9333)新开标签读取小米 MiMo 文档，提取 API base_url / 模型 / 鉴权方式。
不影响发布页标签。绕过故障的内置 WebFetch。"""
import sys, os, time, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.utils import attach_existing_debug_browser

DEBUG_ADDR = "127.0.0.1:9333"
DOC_URLS = [
    "https://mimo.mi.com/docs/welcome",
    "https://mimo.mi.com/docs/quickstart",
    "https://mimo.mi.com/docs/api",
    "https://mimo.mi.com/docs/chat",
]

report = {}
try:
    browser = attach_existing_debug_browser(DEBUG_ADDR)
    tab = browser.new_tab("https://mimo.mi.com/docs/welcome")
    time.sleep(4)  # 等 SPA 渲染

    # 1. welcome 页全文 + 所有导航链接
    body = tab.run_js("return document.body ? document.body.innerText : ''") or ""
    links = tab.run_js(
        "return [...document.querySelectorAll('a')].map(a=>({t:(a.innerText||'').trim().slice(0,40), h:a.href})).filter(x=>x.t && x.h)"
    ) or []
    report["welcome_text_head"] = body[:1500]
    report["links"] = [l for l in links if "mimo.mi.com" in str(l.get("h", ""))][:40]

    # 2. 在全文里搜 base_url / endpoint / 模型 / openai 关键信息
    def find_signals(text):
        sig = {}
        urls = re.findall(r"https?://[a-zA-Z0-9./_\-]+", text)
        sig["urls"] = sorted(set(u for u in urls if "mimo" in u or "api" in u or "/v1" in u))[:20]
        sig["has_chat_completions"] = "chat/completions" in text
        sig["has_openai"] = "openai" in text.lower() or "OpenAI" in text
        sig["models"] = sorted(set(re.findall(r"mimo[\w.\-]*", text, flags=re.IGNORECASE)))[:20]
        sig["bearer"] = "Bearer" in text or "Authorization" in text
        return sig
    report["welcome_signals"] = find_signals(body)

    # 3. 逐个尝试可能的 API 文档子页
    sub_results = {}
    for url in DOC_URLS[1:]:
        try:
            t2 = browser.new_tab(url)
            time.sleep(3)
            txt = t2.run_js("return document.body ? document.body.innerText : ''") or ""
            sub_results[url] = {
                "len": len(txt),
                "signals": find_signals(txt),
                "text_head": txt[:1200],
            }
            t2.close()
        except Exception as e:
            sub_results[url] = {"error": str(e)}
    report["sub_pages"] = sub_results

    report["ok"] = True
except Exception as e:
    import traceback; traceback.print_exc()
    report = {"ok": False, "error": str(e)}

with open("tmp_runtime_probe_live/mimo-docs.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# 控制台精简输出
print("=== welcome signals ===")
print(json.dumps(report.get("welcome_signals", {}), ensure_ascii=False, indent=2))
print("\n=== 导航链接 ===")
for l in report.get("links", [])[:20]:
    print(f"  {l.get('t')}  ->  {l.get('h')}")
print("\n=== 子页 signals ===")
for url, r in (report.get("sub_pages") or {}).items():
    print(f"\n[{url}] len={r.get('len')}")
    print("  ", json.dumps(r.get("signals", r.get("error")), ensure_ascii=False))
print("\n报告: tmp_runtime_probe_live/mimo-docs.json")
