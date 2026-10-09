# -*- coding: utf-8 -*-
"""对比**抖店**与**淘宝**的发布启动接口：守卫是否对得上。

objective 要求「交互逻辑与抖店一致」。所以把两边的入口校验逐条列出来比。

⚠️ 两边**本来就不该完全一样**（抖店走协议、淘宝走 DOM），
所以这份对比是**清单，不是结论**——每条差异都要人工看是「有意的」还是「漏的」。
"""

from __future__ import annotations

import ast
import pathlib
import re

APP = (pathlib.Path(__file__).resolve().parents[2]
       / "tauri-app" / "python-sidecar" / "app.py")
source = APP.read_text(encoding="utf-8")
lines = source.splitlines()


def handler_for(route: str):
    """找到路由对应的处理函数名与行范围。"""

    pattern = re.compile(r"@app\.(?:route|get|post)\('" + re.escape(route) + r"'")
    for index, line in enumerate(lines):
        if pattern.search(line):
            for offset in range(index, min(len(lines), index + 8)):
                match = re.match(r"def (\w+)\(", lines[offset])
                if match:
                    start = offset
                    end = offset + 1
                    while end < len(lines) and (not lines[end].startswith("def ")
                                                and not lines[end].startswith("@app.")):
                        end += 1
                    return match.group(1), start, end
    return None, None, None


def guards(name: str, start: int, end: int):
    """把处理函数里的**校验语句**抽出来。"""

    body = "\n".join(lines[start:end])
    found = []
    for pattern, label in (
        (r"set\(data\)\s*-\s*\{([^}]*)\}", "允许的请求字段白名单"),
        (r"request\.get_json\(silent=True\)", "JSON 解析"),
        (r"isinstance\(data,\s*dict\)", "必须是 JSON 对象"),
        (r"_require_publish_platform\(", "账户平台校验"),
        (r"account_profile", "账户标识（一致性校验）"),
        (r"isinstance\([^,]+,\s*bool\)", "布尔值显式校验"),
        (r"record_id", "record_id 校验"),
        (r"_account_change_blocked\(", "账户变更互斥锁"),
        (r"Record\.get_by_id\(", "记录存在性"),
        (r"dry_run", "dry-run 开关"),
        (r"stop_before_submit", "提交前截停开关"),
        (r"WriteAuthorization", "写授权对象"),
        (r"taobao_upload|upload_tasks", "任务登记表"),
    ):
        if re.search(pattern, body):
            found.append(label)
    return found


PAIRS = (
    ("/api/upload/start", "/api/taobao/publish/start", "启动发布"),
    ("/api/upload/status/<task_id>", "/api/taobao/publish/status/<task_id>", "查询进度"),
    ("/api/upload/cancel/<task_id>", "/api/taobao/publish/cancel/<task_id>", "取消任务"),
)

print("=" * 78)
print("抖店 vs 淘宝：同类接口的守卫对比")
print("=" * 78)

for douyin_route, taobao_route, label in PAIRS:
    print()
    print("### {}（{}）".format(label, douyin_route))
    for route, side in ((douyin_route, "抖店"), (taobao_route, "淘宝")):
        name, start, end = handler_for(route)
        if name is None:
            print("  {:<4} {} → **找不到路由**".format(side, route))
            continue
        items = guards(name, start, end)
        print("  {:<4} {}（{}，第 {}~{} 行）".format(side, route, name, start + 1, end))
        for item in items:
            print("        · {}".format(item))
        if not items:
            print("        （没抽到校验语句——可能是命名不同，需人工看）")

print()
print("=" * 78)
print("**这是清单，不是结论。** 两边本来就不该完全一样")
print("（抖店走协议、淘宝走 DOM），每条差异都要人工判断是「有意」还是「漏的」。")
