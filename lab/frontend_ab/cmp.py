# -*- coding: utf-8 -*-
"""对比两次验证运行（例如 before / after）留下的快照、事件和请求日志。

用法：cmp.py <A阶段> <B阶段> [文件名片段过滤]
快照文件按「阶段_名称.txt」命名；请求日志按 *_requests.jsonl 命名。
"""
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("AB_WORK") or os.path.join(HERE, ".work")
NOGEO = "--nogeo" in sys.argv
CAP = os.path.join(WORK, "captures")


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fp:
        return fp.read()


# 这些流程里「轮询了几次」取决于脚本点击的时机（进度卡住 / 外部任务），不代表逻辑差异，比较时折叠
LOOSE_POLL_FLOWS = ("stuck_cancel", "external_discovery", "capture_cancel")
MOCK_ID = re.compile(r"mock-(douyin|taobao|xhs|cap)-\d+")


def norm_log(text, collapse=False):
    """请求日志：去掉随时间 / 序号变化的字段后返回条目列表。"""
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        e.pop("status", None)
        s = json.dumps(e, ensure_ascii=False, sort_keys=True)
        s = MOCK_ID.sub(r"mock-\1-N", s)
        if collapse and entries and entries[-1] == s and "/status/" in s:
            continue
        entries.append(s)
    return entries


STATUS_RUN = re.compile(r"(GET /api/[a-z/]+/status/[^ ,]+)( , \1)+")


def normalize_events(text):
    """事件文件：任务编号归一；宽松流程的 `[requests <flow>]` 行折叠连续相同的状态轮询。"""
    out = []
    for line in text.split("\n"):
        if line.startswith("[requests ") and any(f in line.split("]")[0] for f in LOOSE_POLL_FLOWS):
            line = STATUS_RUN.sub(r"\1", line)
        out.append(MOCK_ID.sub(r"mock-\1-N", line))
    return "\n".join(out)


def load_props():
    """从 harness.js 读取 STYLE_PROPS，保证与快照字段顺序一致。"""
    h = read(os.path.join(HERE, "harness.js"))
    m = re.search(r"const STYLE_PROPS = \[(.*?)\];", h, re.S)
    return re.findall(r'"([A-Za-z]+)"', m.group(1))


PROPS = load_props()
# 受设备像素比（DPR）取整影响的数值：边框 / 轮廓宽度、尺寸；用容差比较，其余属性必须完全一致
TOLERANT = {p for p in PROPS if p in ("width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight", "outlineWidth",
                                      "top", "right", "bottom", "left")
            or (p.startswith("border") and p.endswith("Width"))}
TOL = 1.01
LINE_RE = re.compile(r"^(.*) rect=([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+) css=(.*)$")


def num(v):
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(px)?", v)
    return float(m.group(1)) if m else None


GEO_LENIENT = {"marginLeft", "marginRight", "marginTop", "marginBottom", "gridTemplateColumns", "flexBasis", "transform"}
LENIENT_TOL = 8.0


def numbers_close(x, y, tol):
    nx = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", x)]
    ny = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", y)]
    return len(nx) == len(ny) and re.sub(r"-?\d+(?:\.\d+)?", "#", x) == re.sub(r"-?\d+(?:\.\d+)?", "#", y)         and all(abs(i - j) <= tol for i, j in zip(nx, ny))


def lines_equal(a, b, lenient=False):
    """逐行比较；元素行的 rect 与受 DPR 影响的样式允许 1px 以内误差。
    lenient=True（运行环境 DPR 不同）时不比 rect，几何相关的样式允许 8px 以内误差，其余属性仍须完全一致。"""
    if a == b:
        return True
    ma, mb = LINE_RE.match(a), LINE_RE.match(b)
    if not ma or not mb or ma.group(1) != mb.group(1):
        return False
    if not lenient:
        for i in range(2, 6):  # rect 四个数
            if abs(float(ma.group(i)) - float(mb.group(i))) > TOL:
                return False
    ca, cb = ma.group(6).split("|"), mb.group(6).split("|")
    if len(ca) != len(cb):
        return False
    for idx, (x, y) in enumerate(zip(ca, cb)):
        if x == y:
            continue
        name = PROPS[idx] if idx < len(PROPS) else ""
        if lenient and (name in TOLERANT or name in GEO_LENIENT) and numbers_close(x, y, LENIENT_TOL):
            continue
        if name in TOLERANT:
            nx, ny = num(x), num(y)
            if nx is not None and ny is not None and abs(nx - ny) <= TOL:
                continue
        return False
    return True


def snapshots_equal(la, lb, lenient=False):
    # 环境头（dpr / 视口）只提示不比较
    la = [x for x in la if not x.startswith("#env ")]
    lb = [x for x in lb if not x.startswith("#env ")]
    return len(la) == len(lb) and all(lines_equal(x, y, lenient) for x, y in zip(la, lb))


def short(line, n=260):
    return line if len(line) <= n else line[:n] + "…"


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    a, b = args[0], args[1]
    only = args[2] if len(args) > 2 else ""
    files = sorted(f for f in os.listdir(CAP) if f.startswith(a + "_") and only in f)
    same = diff = missing = env_mismatch = 0
    for fa in files:
        fb = b + fa[len(a):]
        pa, pb = os.path.join(CAP, fa), os.path.join(CAP, fb)
        if not os.path.exists(pb):
            print(f"MISSING  {fb}")
            missing += 1
            continue
        ta, tb = read(pa), read(pb)
        if fa.endswith("_requests.jsonl"):
            loose = any(f in fa for f in LOOSE_POLL_FLOWS)
            la, lb = norm_log(ta, loose), norm_log(tb, loose)
            if la == lb:
                same += 1
                print(f"same     {fa}  ({len(la)} 条请求，顺序一致)")
            elif sorted(la) == sorted(lb):
                same += 1
                print(f"same*    {fa}  ({len(la)} 条请求，内容一致、仅顺序不同)")
            else:
                diff += 1
                print(f"DIFF     {fa}")
                for line in difflib.unified_diff(la, lb, "A", "B", lineterm="", n=0):
                    print("   ", short(line))
            continue
        # 事件 / 快照文本里的阶段前缀、文件名统一成占位符再比较
        ta = normalize_events(ta.replace(a + "_", "PHASE_"))
        tb = normalize_events(tb.replace(b + "_", "PHASE_"))
        la0, lb0 = ta.splitlines(), tb.splitlines()
        env_a = next((x for x in la0 if x.startswith("#env ")), "")
        env_b = next((x for x in lb0 if x.startswith("#env ")), "")
        if env_a != env_b:
            if not NOGEO:
                env_mismatch += 1
                print(f"ENV      {fa}  ({env_a} vs {env_b}) —— 运行环境不同，结果不可比，需重跑")
                continue
            if snapshots_equal(la0, lb0, lenient=True):
                same += 1
                print(f"same-nogeo {fa}  (DPR 不同：结构 / 文本 / 非几何样式一致，几何不比)")
                continue
        if ta == tb:
            same += 1
            print(f"same     {fa}")
        elif snapshots_equal(la0, lb0):
            same += 1
            print(f"same~    {fa}  (仅 DPR 取整级别的 ≤1px 差异)")
        else:
            diff += 1
            la, lb = ta.splitlines(), tb.splitlines()
            print(f"DIFF     {fa}  (A {len(la)} 行 / B {len(lb)} 行)")
            shown = 0
            for line in difflib.unified_diff(la, lb, "A", "B", lineterm="", n=0):
                if line.startswith(("---", "+++")):
                    continue
                print("   ", short(line))
                shown += 1
                if shown >= 16:
                    print("    …（差异过多，已截断）")
                    break
    print(f"\n汇总：相同 {same}，不同 {diff}，缺失 {missing}")
    return 1 if diff or missing else 0


if __name__ == "__main__":
    sys.exit(main())
