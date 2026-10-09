# -*- coding: utf-8 -*-
"""命令行入口::

    python -m taobao_publish readiness
    python -m taobao_publish dry-run --record-id 1 --sku-price 9.9 --sku-stock 100
    python -m taobao_publish sanitize tmp/raw-probe.json captures/tb_probe_20261002.json

设计约束：**不引入任何第三方依赖**（sqlite3 用标准库），这样即使 sidecar 的
依赖没装齐，也能先跑只读检查。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contracts import SUBPROJECT_ROOT
from .errors import TaobaoPublishError
from .local_source import local_product_from_record
from .pipeline import describe_readiness, run
from .sanitize import assert_capture_ready, assert_clean, sanitize_payload


def _resolve_project_root() -> Path:
    """仓库根 = 子项目根的上一级。"""

    return SUBPROJECT_ROOT.parent


def _default_db_path() -> Path:
    return _resolve_project_root() / "sqlite.db"


def _read_record(db_path: Path, record_id: int) -> Dict[str, Any]:
    """从 SQLite 读一行 ``record``。用标准库，不依赖 Peewee。"""

    if not db_path.is_file():
        raise SystemExit(f"数据库不存在：{db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id, name, path, title, clazz, remark, shipping_template, source_url, content "
            "FROM record WHERE id = ?",
            (record_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise SystemExit(f"record id={record_id} 不存在")
    return dict(row)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    """跑一遍自检。六道门，全部只读。"""

    from .selfcheck import main as selfcheck_main

    argv = ["--json"] if getattr(args, "json", False) else []
    return selfcheck_main(argv)


def cmd_readiness(args: argparse.Namespace) -> int:
    readiness = describe_readiness()
    payload = readiness.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if readiness.publish_route_ready else 1

    print("=" * 72)
    print("淘宝发布子项目就绪度")
    print("=" * 72)
    print(f"契约自检问题：{len(readiness.contract_problems)} 条")
    for problem in readiness.contract_problems:
        print(f"  [!] {problem}")
    print()
    print(f"mtop 协议写路线可用：{'是' if readiness.protocol_write_ready else '否'}")
    print(f"DOM 写路线可用：      {'是' if readiness.dom_write_ready else '否'}")
    print(f"是否存在可用发布路线：{'是' if readiness.publish_route_ready else '否'}")
    # 「路线存在」与「现在能发布」是两件事。只报前者会让人以为已经可以一键发布，
    # 而实际上未实现阶段一定会让流水线中途失败。
    print(f"现在能否一键发布：    {'是' if readiness.publishable else '否'}")
    if not readiness.publishable and readiness.publish_route_ready:
        reasons = []
        if readiness.unimplemented_stages:
            reasons.append("尚未实现：{}".format("、".join(readiness.unimplemented_stages)))
        if readiness.incomplete_stages:
            reasons.append("已注册但走不到成功：{}".format("、".join(readiness.incomplete_stages)))
        if readiness.contract_problems:
            reasons.append("契约自检有 {} 条问题".format(len(readiness.contract_problems)))
        print("  理由：{}".format("；".join(reasons) or "未知"))
    if readiness.live_unverified_stages:
        # 「写完了」与「真的跑通过」是两件事，别让前者看起来像后者。
        print("  ⚠️ 以下阶段**尚未在真实页面上跑通完整链路**：{}".format(
            "、".join(readiness.live_unverified_stages)))
        print("     它们有实现也有单测，但成功路径没有实机验证过；"
              "首次真跑请盯紧每一步。")
    print()
    print(f"已实现阶段（{len(readiness.implemented_stages)}）：{', '.join(readiness.implemented_stages)}")
    print(f"未实现阶段（{len(readiness.unimplemented_stages)}）：{', '.join(readiness.unimplemented_stages)}")
    if readiness.incomplete_stages:
        # 「注册了」和「能走完」是两件事，必须分开列。
        print(f"已注册但走不到成功（{len(readiness.incomplete_stages)}）："
              f"{', '.join(readiness.incomplete_stages)}")
    print()
    # ⚠️ **下面两段只关 mtop 协议路线。**
    #
    # 原先的标签是「必填但不可写的字段（真实发布前必须补齐）」——而它
    # **只卡 protocol_write_ready**（见 write_route_status），
    # 与 dom_write_ready 无关。于是输出变成自相矛盾：
    # 上面写「现在能否一键发布：是」，下面写「真实发布前必须补齐 10 个」。
    #
    # 这与第 25 轮修过的「success: True 底下挂 10 条阻塞项」是同一类：
    # **把「另一条路线的待办」说成了「本次的阻塞」。**
    print("mtop 协议路线的字段证据分布（**DOM 路线不依赖它**）：")
    for level, count in readiness.field_evidence.items():
        print(f"  {level:<10} {count}")
    print()
    if readiness.blocked_required_fields:
        print("协议路线缺的字段映射（要用协议路线才需要补齐；"
              "**本次走 DOM 路线，不依赖它们**）：")
        for intent in readiness.blocked_required_fields:
            print(f"  - {intent}")
    else:
        print("协议路线缺的字段映射：无")
    print()
    selectors = readiness.blocked_write_critical_selectors
    if selectors:
        # 这一条是**真的**会挡住 DOM 路线——它归 dom_write_ready。
        print(f"写关键但未取证的选择器：{len(selectors)} 个"
              "（**这一条会挡住 DOM 路线**）")
        for key in selectors:
            print(f"  - {key}")
    else:
        print("写关键但未取证的选择器：0 个（DOM 路线不缺选择器）")
    return 0 if readiness.publish_route_ready else 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    row = _read_record(Path(args.db), args.record_id)
    local = local_product_from_record(row, product_dir=str(row.get("path") or ""))

    skus: List[Dict[str, Any]] = []
    spec_values: Dict[str, str] = {}
    if args.spec_values:
        try:
            parsed = json.loads(args.spec_values)
        except ValueError as exc:
            raise SystemExit(f"--spec-values 不是合法 JSON：{exc}") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("--spec-values 必须是 JSON 对象，例如 '{\"颜色\":\"白\"}'")
        spec_values = {str(k): str(v) for k, v in parsed.items()}

    if args.sku_price is not None or args.sku_stock is not None:
        if args.sku_price is None or args.sku_stock is None:
            # 本地没有库存字段，只有一个不给就没法构造合法 SKU——直接拒绝，不猜。
            raise SystemExit("--sku-price 与 --sku-stock 必须成对提供（本地无库存字段，禁止默认值）")
        skus.append(
            {
                "spec_values": spec_values,
                "price": args.sku_price,
                "stock": args.sku_stock,
            }
        )

    request: Dict[str, Any] = {"record_id": local.record_id, "record_name": local.record_name}
    if args.title:
        request["title"] = args.title
    if skus:
        request["skus"] = skus

    # 指到应用管理的那个浏览器——不传就是研究环境的 9334（那里通常没有浏览器）。
    cdp_list_url = args.cdp_list_url.strip()
    if not cdp_list_url and args.cdp_address.strip():
        cdp_list_url = "http://{}/json/list".format(args.cdp_address.strip())

    result = run(
        local,
        request,
        dry_run=True,
        stop_before_submit=True,
        **({"cdp_list_url": cdp_list_url} if cdp_list_url else {}),
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print(f"dry-run 结果：{'成功' if result.success else '失败'}")
        print("=" * 72)
        print(f"停在阶段：{result.stage}")
        print(f"dry-run：{result.dry_run}    提交前截停：{result.stopped_before_submit}")
        print()
        for step in result.steps:
            marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]", "running": "[..]  "}.get(
                step.status, "[?]   "
            )
            print(f"{marker} {step.label:<16} {step.elapsed_ms:>6}ms  {step.summary}")
        if result.error:
            print()
            print(f"错误：{result.error.get('code')} — {result.error.get('message')}")
        if result.blockers:
            print()
            print(f"阻塞项（{len(result.blockers)}）：")
            for blocker in result.blockers[: args.max_blockers]:
                field = blocker.get("field") or "-"
                print(f"  [{blocker.get('code')}] {field}: {blocker.get('detail')}")
            if len(result.blockers) > args.max_blockers:
                print(f"  ...另有 {len(result.blockers) - args.max_blockers} 条，用 --json 看全量")
        readiness = result.data.get("readiness") or {}
        print()
        print(f"发布路线可用：{'是' if readiness.get('publish_route_ready') else '否'}")
        # 同理：路线可用不等于现在能发布。
        print(f"现在能否一键发布：{'是' if readiness.get('publishable') else '否'}")
    return 0 if result.success else 1


def cmd_sanitize(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        raise SystemExit(f"输入文件不存在：{source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"输入不是合法 JSON：{exc}") from exc

    cleaned = sanitize_payload(raw)
    text = json.dumps(cleaned, ensure_ascii=False, indent=2)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)

    # captures/ 是要**进仓库**的目录，tmp/ 不是。写 captures 时加一道更严的守卫：
    # 光靠 README 里的手工约定不足以保证「原始产物不经脱敏不会进仓库」，
    # 而此前唯一的自动守卫 assert_clean 对头名字与 JSON 引号键是无感的
    # （对抗性审查 2026-10-02，F1/F2 与流程风险）。
    in_captures = "captures" in target.resolve().parts
    if in_captures:
        assert_capture_ready(text, context=str(target))
    else:
        assert_clean(text, context=str(target))

    target.write_text(text, encoding="utf-8")
    scope = "captures（严格守卫）" if in_captures else "普通产物"
    print(f"已脱敏写出：{target}  [{scope}]")
    return 0


def cmd_contracts(args: argparse.Namespace) -> int:
    """打印契约里的证据清单，便于人工巡检。"""

    from .contracts import iter_evidence_rows

    rows = list(iter_evidence_rows())
    if args.json:
        print(json.dumps([{"kind": k, "id": i, "level": l, "source": s} for k, i, l, s in rows], ensure_ascii=False, indent=2))
        return 0
    for kind, identifier, level, source in rows:
        print(f"{kind:<9} {level:<10} {identifier:<32} {source}")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m taobao_publish",
        description="淘宝商品发布流水线（只读预检与契约工具）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    readiness = subparsers.add_parser("readiness", help="打印就绪度：两条写路线到底能不能用")
    readiness.add_argument("--json", action="store_true", help="以 JSON 输出")
    readiness.set_defaults(func=cmd_readiness)

    dry_run = subparsers.add_parser("dry-run", help="对一条本地记录跑 dry-run（不触碰平台）")
    dry_run.add_argument("--record-id", type=int, required=True, help="record 表主键")
    dry_run.add_argument("--db", default=str(_default_db_path()), help="sqlite.db 路径")
    dry_run.add_argument("--title", default="", help="覆盖标题")
    dry_run.add_argument("--sku-price", type=float, default=None, help="SKU 价格（本地无此数据，必须显式给）")
    dry_run.add_argument("--sku-stock", type=int, default=None, help="SKU 库存（本地无此数据，必须显式给）")
    dry_run.add_argument("--spec-values", default="", help='销售属性 JSON，例如 \'{"颜色":"白"}\'')
    dry_run.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    dry_run.add_argument("--max-blockers", type=int, default=12, help="文本模式下最多打印多少条阻塞项")
    # ⚠️ **必须有这个参数。**
    #
    # `pipeline.run` 的默认是研究环境的 9334，而应用管理的浏览器在 9500-9599
    # 端口段（Sidecar 的注释写得很明确：两者登录态不同，
    # 「流水线跑到错误的浏览器上会什么都找不到」）。
    # 没有它的话，这条命令实际上只能在 9334 上跑——那里通常没有浏览器。
    dry_run.add_argument(
        "--cdp-address",
        default="",
        help="应用管理的调试浏览器地址，形如 127.0.0.1:9502"
        "（不传则用默认的 9334，那是研究环境，登录态不同）",
    )
    dry_run.add_argument(
        "--cdp-list-url",
        default="",
        help="完整覆盖 /json/list URL（优先于 --cdp-address）",
    )
    dry_run.set_defaults(func=cmd_dry_run)

    sanitize = subparsers.add_parser("sanitize", help="把 tmp 下的原始探针产物脱敏后写入 captures")
    sanitize.add_argument("input", help="原始 JSON 路径")
    sanitize.add_argument("output", help="脱敏后输出路径")
    sanitize.set_defaults(func=cmd_sanitize)

    check = subparsers.add_parser(
        "check",
        help="跑一遍自检：契约 / 构造器冒烟 / 错误目录 / hard 规则覆盖")
    check.add_argument("--json", action="store_true", help="以 JSON 输出")
    check.set_defaults(func=cmd_check)

    contracts = subparsers.add_parser("contracts", help="列出契约证据清单")
    contracts.add_argument("--json", action="store_true", help="以 JSON 输出")
    contracts.set_defaults(func=cmd_contracts)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except TaobaoPublishError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
