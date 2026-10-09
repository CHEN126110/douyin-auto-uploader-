# -*- coding: utf-8 -*-
"""阶段级实机冒烟：用真实页面跑一遍 ``fill_base``。

**这是写操作**，所以必须显式传 ``--allow-write``。写入**不会保存草稿、不会提交**，
值只停留在页面表单里，脚本结束前会**恢复原值**。

跑的是真正的阶段处理器（``stages.stage_fill_base``），不是自己拼的表达式——
这样验证的是「阶段能不能驱动页面」，而不是「定位表达式对不对」。

用法::

    python taobao-publisher/scripts/smoke-fill-base-live.py --address 127.0.0.1:9502 --allow-write
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
from taobao_publish.models import PublishItem  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 冒烟用的标题。刻意用带中文与数字的短串，且**不写满 60 字符**。
SMOKE_TITLE = "冒烟测试标题DSH001"

#: 导购标题的冒烟串。**选填字段**——第 38 轮才接进流水线，这里补实机验证。
SMOKE_GUIDE_TITLE = "导购冒烟DSH001"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--title", default=SMOKE_TITLE)
    args = parser.parse_args()

    if not args.allow_write:
        print("这是写操作，必须显式加 --allow-write。")
        print("（不保存草稿、不提交；脚本会恢复原值）")
        return 2

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    target = next(
        (t for t in targets
         if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")),
        None,
    )
    if target is None:
        print("没有找到发布工作台页面")
        return 1

    ws_url = target["webSocketDebuggerUrl"]
    with page.PageClient.connect(ws_url) as client:
        original = page.read_text_field(client, "宝贝标题")
        original_guide = page.read_text_field(client, "导购标题")
    print("原始标题：{!r}".format(original))
    print("原始导购标题：{!r}".format(original_guide))
    print()

    item = PublishItem(record_id=0, record_name="实机冒烟", title=args.title,
                       guide_title=SMOKE_GUIDE_TITLE)
    ctx = stages.PipelineContext(item=item, dry_run=False)

    # 让阶段连到我们已知的那个页面：cdp_list_url 指向本机调试端口
    ctx.cdp_list_url = "http://{}/json/list".format(args.address)

    print("==== 直接调用阶段处理器 {} ====".format("fill_base"))
    outcome = stages.STAGE_HANDLERS["fill_base"].run(ctx)
    print("  ok      : {}".format(outcome.ok))
    print("  status  : {}".format(outcome.status))
    print("  summary : {}".format(outcome.summary))
    if outcome.error_code:
        print("  error   : {} {}".format(outcome.error_code, outcome.data))

    restored = None
    try:
        with page.PageClient.connect(ws_url) as client:
            written = page.read_text_field(client, "宝贝标题")
            written_guide = page.read_text_field(client, "导购标题")
            print()
            print("  页面上的标题：    {!r}".format(written))
            print("  页面上的导购标题：{!r}".format(written_guide))
            print("  阶段报告的对象：{}".format(json.dumps(outcome.data, ensure_ascii=False)[:200]))
            print()
            print("==== 恢复原值 ====")
            page.fill_text_field(client, "宝贝标题", original or "")
            restored = page.read_text_field(client, "宝贝标题")
            page.fill_text_field(client, "导购标题", original_guide or "")
            restored_guide = page.read_text_field(client, "导购标题")
            print("  恢复后标题：    {!r}".format(restored))
            print("  恢复后导购标题：{!r}".format(restored_guide))
    except Exception as exc:  # noqa: BLE001
        print("恢复过程出错：{}: {}".format(type(exc).__name__, exc))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-fill-base-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": target.get("url"),
        "wrote": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "title_before": original,
        "title_smoke": args.title,
        "title_restored": restored,
        "guide_title_before": original_guide,
        "guide_title_smoke": SMOKE_GUIDE_TITLE,
        "guide_title_written": written_guide,
        "guide_title_restored": restored_guide,
        "stage": {
            "name": "fill_base",
            "ok": outcome.ok,
            "status": outcome.status,
            "summary": outcome.summary,
            "error_code": outcome.error_code,
            "data": outcome.data,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    # 三条都必须成立：阶段报成功、导购标题真的写进去了、两个字段都恢复了原值。
    title_ok = restored == (original or "")
    guide_ok = restored_guide == (original_guide or "")
    guide_written = written_guide == SMOKE_GUIDE_TITLE
    ok = outcome.ok and title_ok and guide_ok and guide_written
    print()
    print("  阶段 ok                : {}".format(outcome.ok))
    print("  导购标题真的写进去了    : {}（{!r}）".format(guide_written, written_guide))
    print("  标题已恢复              : {}".format(title_ok))
    print("  导购标题已恢复          : {}".format(guide_ok))
    print("结论：{}".format("阶段驱动页面成功，现场已恢复" if ok else "未通过，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
