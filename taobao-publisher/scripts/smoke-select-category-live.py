# -*- coding: utf-8 -*-
"""阶段级实机冒烟：跑一遍 ``select_category``。

**这是交互动作**，所以必须显式传 ``--allow-interact``：它会搜索类目、点击候选、
可能选择品牌并点「确认，下一步」。**不保存草稿、不上架、不提交。**

用法::

    python taobao-publisher/scripts/smoke-select-category-live.py --address 127.0.0.1:9502 \
        --allow-interact --leaf 一次性袜子 [--brand 无品牌/无注册商标]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.models import PropEntry, PublishItem  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

DEFAULT_PATH = ("女士内衣/男士内衣/家居服", "短袜/打底袜/丝袜/美腿袜（新）", "一次性袜子")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-interact", action="store_true")
    parser.add_argument("--leaf", default="", help="只跑以该文本结尾的三级路径")
    parser.add_argument("--brand", default="", help="要选的品牌名（留空则验证 BRAND_REQUIRED 阻断）")
    args = parser.parse_args()

    if not args.allow_interact:
        print("这是交互动作（会点页面），必须显式加 --allow-interact。")
        print("（不保存草稿、不上架、不提交）")
        return 2

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    target = next(
        (t for t in targets
         if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")),
        None,
    )
    if target is None:
        print("没有发布工作台页面")
        return 1

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("起始页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))

    path = DEFAULT_PATH
    if args.leaf:
        path = tuple(DEFAULT_PATH[:-1]) + (args.leaf,)

    props = []
    if args.brand:
        props.append(PropEntry(prop_name="品牌", value_name=args.brand))

    item = PublishItem(
        record_id=0, record_name="实机冒烟", title="冒烟测试标题",
        props=props,
    )
    item.category.path = path

    ctx = stages.PipelineContext(item=item, dry_run=False)
    ctx.cdp_list_url = "http://{}/json/list".format(args.address)

    print("目标类目：{}".format(">".join(path)))
    print("品牌    ：{!r}".format(args.brand or "（未提供）"))
    print()
    print("==== 调用阶段处理器 select_category ====")
    outcome = stages.STAGE_HANDLERS["select_category"].run(ctx)
    print("  ok      : {}".format(outcome.ok))
    print("  status  : {}".format(outcome.status))
    print("  summary : {}".format(outcome.summary))
    if outcome.error_code:
        print("  error   : {}".format(outcome.error_code))
    for blocker in outcome.blockers:
        print("  blocker : [{}] {}".format(blocker.code, blocker.detail[:90]))

    print()
    print("  scratch : {}".format(json.dumps(ctx.scratch.get("select_category"), ensure_ascii=False)[:300]))

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        where = str(client.evaluate("location.href") or "")
        selected = page.read_selected_category(client)
        confirm = page.read_confirm_button_state(client)
    print()
    print("  结束页面：{}".format(where[:100]))
    print("  已选类目：{}".format(json.dumps(selected, ensure_ascii=False)))
    print("  确认按钮：{}".format(json.dumps(confirm, ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-select-category-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "interacted": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "target_path": list(path),
        "brand": args.brand,
        "outcome": {
            "ok": outcome.ok, "status": outcome.status, "summary": outcome.summary,
            "error_code": outcome.error_code,
            "blockers": [{"code": b.code, "detail": b.detail} for b in outcome.blockers],
            "data": outcome.data,
        },
        "final_href": where,
        "selected_category": selected,
        "confirm_button": confirm,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
