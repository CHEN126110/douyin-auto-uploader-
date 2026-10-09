# -*- coding: utf-8 -*-
"""从**素材中心页面的 DOM** 读图片空间目录（ID + 名称）——只读。

## 为什么走 DOM 而不是 mtop

`mtop.taobao.picturecenter.console.dir.query` 的调用形态已被完整取证
（GET + `data` 在 query + `jsv=2.6.1` + `type/dataType=originaljsonp` + `ttid`），
但**自己发**任何形态（POST/GET/JSONP/带 ttid）实测一律返回
``FAIL_SYS_ILLEGAL_ACCESS::非法请求``——网关层拒绝，疑与 appKey 权限有关，
未取证。而**目录名与目录 ID 就明文渲染在页面上**，DOM 路线不需要任何签名。

本脚本只读页面文本，产出 ``[{"name": ..., "folder_id": ...}]``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "taobao-publisher"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from taobao_publish.cdp_ws import CdpBrowser, CdpClientError  # noqa: E402

PAGE_URL = "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu"

#: 读目录树的表达式。素材中心的目录树是 Ant Design 的 ``.next-tree``。
#:
#: ⚠️ **folderId 就在节点的 `value` 属性上**（2026-10-06 实测，E-282）：
#:
#: .. code-block:: html
#:
#:     <li role="presentation" class="next-tree-node"
#:         value="1114918855143810805" name="ID-1074582642352" level="1">
#:
#: 早先只找 ``data-id`` / ``data-key``（**两者在真实页面上都是空**），于是
#: ``id`` 一直读不出来，只能回目录名——**不是拿不到，是找错了属性**。
#: 协议上传需要的是数字 folderId（``upload.api?folderId=…``），所以这里必须读 `value`。
TREE_EXPRESSION = r"""
(() => {
  const visible = el => !!(el.getBoundingClientRect().width && el.getBoundingClientRect().height);
  const out = { trees: 0, nodes: [] };
  const trees = Array.from(document.querySelectorAll('.next-tree, [role="tree"]')).filter(visible);
  out.trees = trees.length;
  for (const tree of trees) {
    const nodes = Array.from(tree.querySelectorAll('.next-tree-node, [role="treeitem"]')).filter(visible);
    for (const node of nodes) {
      // 目录名优先取 label；``data-label`` 也是实测存在的属性。
      const label = node.querySelector('.next-tree-node-label, [data-label]') || node;
      const name = ((label.getAttribute && label.getAttribute('data-label'))
                    || label.textContent || '').trim().slice(0, 80);
      if (!name) continue;
      // ⚠️ 顺序有讲究：`value` 是**实测的 folderId**，放最前；
      // 其余是历史猜测，保留为回退但不优先。
      const id = node.getAttribute('value')
        || node.getAttribute('data-id')
        || node.getAttribute('data-key')
        || '';
      const level = node.getAttribute('level') || '';
      out.nodes.push({ name: name, id: String(id || ''), level: String(level || '') });
    }
  }
  // 页面上还可能直接写着 ID-xxxx 这样的目录名（拿不到树时的兜底，**id 为空**）
  if (!out.nodes.length && document.body) {
    const text = document.body.innerText || '';
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (/^(ID-\d+|全部素材|全部图片|回收站|官方)$/.test(trimmed)) {
        out.nodes.push({ name: trimmed, id: '', level: '' });
      }
    }
  }
  return out;
})()
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从素材中心 DOM 读图片空间目录（只读）")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--url", default=PAGE_URL)
    parser.add_argument("--wait", type=float, default=9.0)
    parser.add_argument("--out", default="")
    arguments = parser.parse_args(argv)

    browser = CdpBrowser(port=arguments.port, timeout=25.0)
    try:
        browser.version()
    except CdpClientError as exc:
        sys.stderr.write(f"调试端口不可达：{exc}\n")
        return 1
    target = browser.new_page(arguments.url)
    session_id = browser.attach(target.target_id)
    time.sleep(max(3.0, arguments.wait))
    try:
        result = browser.evaluate(TREE_EXPRESSION, session_id=session_id, await_promise=False, timeout=25.0)
    except CdpClientError as exc:
        result = {"error": str(exc)}
    browser.close_target(target.target_id)
    browser.close()

    raw_nodes: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        raw_nodes = [item for item in (result.get("nodes") or []) if isinstance(item, dict)]
    # ⚠️ **按名字聚合 folderIds，而不是按 (name, id, level) 去重。**
    #
    # 实测发现两种节点混在一起：
    #   * 真实目录节点：有 `value`（folderId）与 `level`；
    #   * 树的外层渲染节点：**名字相同但没有任何属性**（Ant Design 的虚拟列表
    #     会同时渲染包装层与真实层，所以同一目录会在"有属性"和"无属性"各出现一次）。
    #
    # 早先按 (name, id, level) 去重，结果是：明明同一个目录被当成两条，
    # 而真实的同名目录（图省里真有两个同名文件夹，folderId 不同）又被当成渲染重复。
    # 名字是页面上唯一可读的键，所以按名字聚合、把 folderIds 收成列表，
    # **不猜哪个才是"对的"**——两个 ID 就如实列两个。
    grouped: "OrderedDict[str, List[str]]" = OrderedDict()
    levels: Dict[str, str] = {}
    for item in raw_nodes:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        folder_id = str(item.get("id") or "").strip()
        grouped.setdefault(name, [])
        if folder_id and folder_id not in grouped[name]:
            grouped[name].append(folder_id)
        level = str(item.get("level") or "").strip()
        if level and name not in levels:
            levels[name] = level
    nodes: List[Dict[str, Any]] = [
        {"name": name, "folder_ids": ids, "level": levels.get(name, "")}
        for name, ids in grouped.items()
    ]
    ambiguous = [item for item in nodes if len(item["folder_ids"]) > 1]
    missing_ids = [item for item in nodes if not item["folder_ids"]]
    payload = {
        "url": arguments.url,
        "tree_count": (result or {}).get("trees") if isinstance(result, dict) else None,
        "folder_count": len(nodes),
        "nodes": nodes[:80],
        "with_id": len(nodes) - len(missing_ids),
        "missing_id": len(missing_ids),
        "ambiguous_names": [item["name"] for item in ambiguous],
        "note": ("folderId 取自节点 `value` 属性（E-282）。"
                 "`missing_id` 非 0 说明有目录没暴露 ID；"
                 "`ambiguous_names` 非空说明**页面上确实存在同名目录**，"
                 "调用方必须显式选一个，不要按名字猜。"),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    out = arguments.out or str(
        _ROOT / "taobao-publisher" / "tmp"
        / f"picture-center-folders-dom-{time.strftime('%Y%m%d%H%M%S')}.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(f"[已写入产物] {out}\n")
    return 0 if nodes else 2


if __name__ == "__main__":
    raise SystemExit(main())
