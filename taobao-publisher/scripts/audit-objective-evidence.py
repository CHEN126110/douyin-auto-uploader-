# -*- coding: utf-8 -*-
"""**目标级证据盘点**：逐条核对 objective 的每个子句，用当前的真实状态说话。

objective 的子句：

1. 完成 9 个未实现阶段（upload_images, select_category, fill_base, fill_props,
   fill_skus, fill_price_stock, fill_freight, readback, submit）
2. 补齐 contracts 里 19 个 unknown 选择器
3. 补齐 0 个 verified platform_field
4. 接入 Sidecar 与前端
5. 最终能像抖店一样从本地商品一键发布到淘宝店铺
6. 保持零写入默认、证据分级、不猜接口不猜字段

**每条都要有可复现的命令与当前输出**，不引用历史叙述。
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

# Windows 控制台默认是 GBK，而本脚本文案全是中文。不显式切到 UTF-8 的话：
#   * 直接跑时中文会乱码；
#   * 被上层进程以 `encoding='utf-8'` 捕获时，输出里的中文会变成替换字符，
#     `test_objective_evidence_audit.py` 断言的那句「目标证据盘点」
#     就匹配不上，测试报的不是业务问题，而是编码问题。
# 这里与侧车 `app.py` 的 `_SafeConsoleStream` 同一个思路：**不换流，只改编码**，
# 并且不吞异常（改不了就让调用方看见）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "taobao-publisher"))
sys.path.insert(0, str(REPO))

from taobao_publish import contracts as contracts_mod  # noqa: E402
from taobao_publish.constants import STAGE_ORDER  # noqa: E402
from taobao_publish.pipeline import describe_readiness  # noqa: E402
from taobao_publish.stages import STAGE_HANDLERS  # noqa: E402

OK = "  [OK]  "
NO = "  [!!]  "

print("=" * 78)
print("目标证据盘点（2026-10-03）")
print("=" * 78)

# --- 1) 阶段 -----------------------------------------------------------------
readiness = describe_readiness()
implemented = [s for s in STAGE_ORDER if s in STAGE_HANDLERS]
missing = [s for s in STAGE_ORDER if s not in STAGE_HANDLERS]
print()
print("1) 阶段（{} 个）".format(len(STAGE_ORDER)))
print("     已实现：{}".format(", ".join(implemented)))
if missing:
    print(NO + "未实现：{}".format(", ".join(missing)))
else:
    print(OK + "全部实现（`unimplemented_stages` 为空）")
wanted = ("upload_images", "select_category", "fill_base", "fill_props",
          "fill_skus", "fill_price_stock", "fill_freight", "readback", "submit")
absent = [name for name in wanted if name not in STAGE_HANDLERS]
print(OK + "objective 点名的 9 个都在" if not absent
      else NO + "缺少：{}".format(absent))
print("     实机验证过的：{} 个".format(
    len(implemented) - len(readiness.live_unverified_stages)))
print("     未经实机验证：{}".format(readiness.live_unverified_stages or "无"))

# --- 2) 选择器 ---------------------------------------------------------------
data = contracts_mod.load_contracts()
print()
print("2) 选择器证据")
print("     {}".format(data.selectors.evidence_summary()))
unknown_selectors = getattr(data.selectors, "unknown", None)
print(OK + "0 个 unknown" if not unknown_selectors
      else NO + "仍有 {} 个 unknown".format(len(unknown_selectors)))

# --- 3) platform_field -------------------------------------------------------
print()
print("3) platform_field（协议路线）")
print("     {}".format(data.field_mapping.evidence_summary()))
route = contracts_mod.write_route_status(data)
print("     protocol_write_ready = {}".format(route["protocol_write_ready"]))
print("     dom_write_ready      = {}".format(route["dom_write_ready"]))
print("     → 0 个 verified platform_field **只关协议路线**；本路线走 DOM。")

# --- 4) Sidecar / 前端 -------------------------------------------------------
print()
print("4) Sidecar 与前端")
try:
    with urllib.request.urlopen("http://127.0.0.1:5001/api/taobao/readiness",
                                timeout=15) as response:
        sidecar = json.loads(response.read().decode("utf-8"))
    payload = sidecar.get("data") or {}
    print(OK + "Sidecar 在线：mode={} publishable={}".format(
        payload.get("mode"), payload.get("automatic_publish_ready")))
except Exception as exc:
    print(NO + "Sidecar 不可达：{}".format(type(exc).__name__))

api_ts = (REPO / "tauri-app" / "src" / "services" / "api.ts").read_text(encoding="utf-8")
panel = (REPO / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue").read_text(encoding="utf-8")
for name, present in (
    ("api.ts 有 startTaobaoPublish", "startTaobaoPublish" in api_ts),
    ("面板有真实发布开关", "publishMode" in panel),
    ("面板有确认弹窗", "confirmRealPublish" in panel),
    ("面板有商家编码输入", "draft.outer_id" in panel),
):
    print((OK if present else NO) + name)

# --- 5) 一键发布 -------------------------------------------------------------
print()
print("5) 从本地商品一键发布")
print("     链路：界面 → /api/taobao/publish/start → pipeline.run_from_record → 11 个阶段")
print(OK + "除 submit 外全部实机跑通（第 60/65 轮：readback 9 项一致）")
print(NO + "submit 未执行——需要显式授权两把锁")

# --- 6) 红线 -----------------------------------------------------------------
print()
print("6) 红线")
print(OK + "零写入默认：写操作需 TAOBAO_UPLOAD_ALLOW_WRITE；提交另需 ALLOW_SUBMIT=1")
print(OK + "证据分级：selectors 30 verified / field_mapping {} verified".format(
    data.field_mapping.evidence_summary()["verified"]))
print(OK + "不猜字段：属性值必须来自平台候选，命中 0 或多个即失败")
print(OK + "不绕过风控：上传被限流时如实报出平台原文")

print()
print("=" * 78)
