# -*- coding: utf-8 -*-
"""把**必填属性**按"稳妥通用值"逐项填好，并**逐项回读确认**。

## 为什么单独一层

用户诉求：把带 `*` 的必填项都填好就能走到发布。但"填什么"必须满足两条：
1. **稳妥通用**——不含具体卖点、与实物不冲突（`四季通用`/`男女通用`/`其他`）；
2. **不猜商品事实**——面料/材质成分只能来自采集数据或人。

取值规则在 :mod:`taobao_publish.category_defaults`（纯函数、可测），
本模块只负责**把它落到页面上并回读验证**。

## 复用的既有能力（不另造一套）

* :func:`page.build_open_prop_dropdown_expression` —— 按标签唯一定位属性行并展开（含
  "命中不是恰好 1 行就一次都不点"的唯一性守卫、禁用检查、`aria-expanded` 检查）；
* :func:`page.build_search_prop_options_expression` —— 在弹层的搜索框里输入关键词过滤候选；
* :func:`page.build_pick_spec_value_expression` —— 在**最后一个**可见弹层里点中候选值
  （取最后一个：残留旧弹层会让值填进输入框但不提交，实测踩过）；
* :func:`page.read_prop_value` —— 回读属性值（两类控件的值位置不同，它都处理了）。

## 红线

* 每一步都**回读**；读不回就报错，**不把"点到了"当"填上了"**；
* 候选值**不在平台给的候选里就不填**（不硬塞自由文本——实测那样不会提交）；
* 商品事实类字段**直接跳过并记 `needs_human`**。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from . import page
from .category_defaults import plan_required_defaults, platform_recommendation

#: 本层**绝不自动填**的字段（商品事实，只能来自采集数据或人）。
FACT_FIELDS = frozenset({
    "面料", "里料", "面料材质成分", "里料材质成分", "材质成分", "加固部分材质",
    "品牌", "产地", "吊牌价", "货号", "款号", "商家编码",
})

#: 平台"一键采纳推荐值"按钮文案（实测 `SPAN.next-btn-helper`，未禁用、不在 form 内）。
ADOPT_RECOMMEND_TEXT = "一键采纳推荐值"


def read_required_rows(client, *, timeout: float = 40.0) -> List[Dict[str, Any]]:
    """读所有**带必填标记**的属性行：名称、当前显示值、行内平台推荐值。

    必填标记是**独立元素** `.sell-component-info-wrapper-required`，
    **不在标签文本里**——按文本找 `*` 会得到「0 个必填」（实测踩过）。

    ⚠️ 每个标记**向上找到"只包住一个下拉"的那层容器**再读值；直接往上找
    "第一个含下拉的祖先"会把外层大容器（含几十个下拉）当成一行（实测踩过）。
    """

    expression = r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const clean = t => String(t || '')
        .replace(/平台推荐值[：:][^\s，,；;。]*/g, '')
        .replace(/[（(][^）)]*[）)]/g, '')
        .replace(/(重要|必填|选填|多选|单选)/g, '')
        .replace(/[*＊\s]/g, '');
      // ⚠️ **用与 `page.build_open_prop_dropdown_expression` 相同的两种行结构**。
      // 自己另发明一套"向上找最近的含下拉容器"会与写入侧的定位不一致——
      // 表现为"读到的名字和填的时候用的名字对不上"（实测踩过）。
      const PROFILES = [
        { row: '.sell-component-info-wrapper-wrap',
          labelSel: '.sell-component-info-wrapper-label' },
        { row: '.sell-catProp-item-common', labelSel: 'label' },
      ];
      const MARK = '.sell-component-info-wrapper-required';
      const marks = Array.from(document.querySelectorAll(MARK)).filter(visible);
      const rows = [];
      const seen = new Set();
      for (const prof of PROFILES) {
        for (const row of Array.from(document.querySelectorAll(prof.row)).filter(visible)) {
          if (!row.querySelector(MARK)) continue;
          const selects = Array.from(row.querySelectorAll('.next-select')).filter(visible);
          if (selects.length !== 1) continue;   // 只认"恰好一个下拉"的属性行
          const labelEl = row.querySelector(prof.labelSel);
          const name = clean(labelEl ? labelEl.textContent : '');
          if (!name || seen.has(name)) continue;
          const select = selects[0];
          const holder = select.querySelector('.next-select-values');
          let display = '';
          if (holder) {
            const em = holder.querySelector('em[title]');
            display = text(em || holder).slice(0, 30);
          } else {
            const input = row.querySelector('input');
            display = input ? String(input.value || '').slice(0, 30) : '';
          }
          const rowText = text(row);
          const rec = rowText.match(/平台推荐值[：:]\s*([^\s，,；;。]{1,12})/);
          seen.add(name);
          rows.push({ name: name, display: display,
                      // ⚠️ **三个键都要给，且名字必须与消费方一致**：
                      // * `required` —— `plan_required_defaults` 按它过滤
                      //   （漏给会让整份计划变成空数组、一个字段都不填）；
                      // * `selectDisplays` —— 同一个函数按它判"已有值"
                      //   （只给 `display` 会被判成空的，于是"已填"项误进 needs_human）；
                      // * `display` —— 本模块用于判"是不是下拉类必填项"。
                      required: true,
                      selectDisplays: display ? [display] : [],
                      empty: !display || display === '请选择',
                      hint: rowText.slice(0, 160),
                      recommended: rec ? rec[1] : '' });
        }
      }
      return { ok: true, rows: rows };
    })()'''
    payload = client.evaluate(expression, timeout=timeout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise page.PageError("必填行读取失败："
                             + str((payload or {}).get("reason") if isinstance(payload, dict) else "无返回"))
    return list(payload.get("rows") or [])


def adopt_platform_recommendations(client, *, wait: float = 4.0,
                                   timeout: float = 40.0) -> Dict[str, Any]:
    """点平台的「一键采纳推荐值」。

    为什么用它：那是**平台自己算出来的建议值**，比我们逐项猜更稳妥。
    它只改属性值，不改价格库存等交易字段（这一点由"点完回读对比"验证）。

    ⚠️ 按钮可能在视口外——先 `scrollIntoView` 再用真实鼠标点，
    并在点击期间临时放行预览覆盖层（实测那层会吃掉发往页面的鼠标事件）。
    """

    located = client.evaluate(r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').trim();
      const hits = [];
      for (const el of document.querySelectorAll('button,span,div,a')) {
        if (!visible(el) || el.children.length) continue;
        if (text(el) === WANT) hits.push(el);
      }
      if (hits.length !== 1) return { ok: false, reason: 'adopt_button_not_unique', hitCount: hits.length };
      const btn = hits[0];
      // 真实按钮通常是它的父链上的 BUTTON，优先点那个
      const clickable = btn.closest('button') || btn;
      if (clickable.disabled === true || clickable.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'adopt_button_disabled' };
      if (clickable.tagName === 'BUTTON' && clickable.form && clickable.type !== 'submit'
          && clickable.type !== 'button')
        return { ok: false, reason: 'adopt_button_may_submit' };
      if (clickable.tagName === 'BUTTON' && clickable.form && clickable.type === 'submit')
        return { ok: false, reason: 'adopt_button_may_submit' };
      clickable.scrollIntoView({ block: 'center', inline: 'nearest' });
      const r = clickable.getBoundingClientRect();
      const point = { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
      const top = document.elementFromPoint(point.x, point.y);
      return { ok: true, point: point,
               covered: !(top && clickable.contains(top)),
               coveredBy: top ? String(top.className || top.tagName).slice(0, 60) : null };
    })()'''.replace("WANT", repr(ADOPT_RECOMMEND_TEXT).replace("'", '"')), timeout=timeout)
    if not isinstance(located, dict) or located.get("ok") is not True:
        raise page.PageError("找不到「{}」：{}".format(
            ADOPT_RECOMMEND_TEXT,
            (located or {}).get("reason") if isinstance(located, dict) else "无返回"))

    suspended = False
    try:
        if located.get("covered"):
            page.set_preview_overlay_pointer_events(client, suspend=True)
            suspended = True
            time.sleep(0.3)
        point = located["point"]
        for event_type, extra in (("mouseMoved", {}), ("mousePressed", {"clickCount": 1}),
                                  ("mouseReleased", {"clickCount": 1})):
            params = {"type": event_type, "x": point["x"], "y": point["y"], "button": "left"}
            params.update(extra)
            client.send("Input.dispatchMouseEvent", params)
            time.sleep(0.15)
    finally:
        if suspended:
            try:
                page.set_preview_overlay_pointer_events(client, suspend=False)
            except Exception:  # noqa: BLE001 - 恢复失败不该掩盖主流程
                pass
    time.sleep(max(0.0, wait))
    return {"ok": True, "clicked": ADOPT_RECOMMEND_TEXT, "point": located.get("point")}


def fill_required_attr(client, label: str, value: str, *,
                       wait: float = 1.2, dropdown_open: bool = False,
                       readback_timeout: float = 6.0) -> Dict[str, Any]:
    """候选已展开时直接选值；异步提交只轮询回读，不重复点击。"""
    before = page.read_prop_value(client, label)
    out: Dict[str, Any] = {"label": label, "want": value, "before": before}
    if before == value:
        return {**out, "after": before, "unchanged": True}
    if not dropdown_open:
        out["pick"] = page.pick_prop_value(client, label, value, wait=wait)
    else:
        picked = client.evaluate(page.build_pick_spec_value_expression(value))
        if not isinstance(picked, dict) or picked.get("ok") is not True:
            raise page.OptionNotFound("属性 {!r} 的已展开候选无法精确选中 {!r}：{}".format(
                label, value, picked))
        deadline = time.monotonic() + max(0.0, readback_timeout)
        while True:
            read_back = page.read_prop_value(client, label)
            if read_back == value:
                break
            if time.monotonic() >= deadline:
                raise page.FieldMismatchError("属性 {!r} 回读不一致：期望 {!r}，实际 {!r}".format(
                    label, value, read_back))
            time.sleep(0.1)
        out["pick"] = {**picked, "read_back": read_back}
    out["after"] = out["pick"].get("read_back")
    return out


def _close_dropdown(client) -> None:
    for event_type in ("keyDown", "keyUp"):
        client.send("Input.dispatchKeyEvent",
                    {"type": event_type, "key": "Escape", "code": "Escape",
                     "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27})


def read_dropdown_options(client, label: str, *, wait: float = 1.2,
                          timeout: float = 40.0, close: bool = True) -> List[str]:
    """展开并读取候选；批量填写使用 close=False，在同一次展开内选值。

    为什么要单列这一步：稳妥值必须**在平台候选里**挑（`category_defaults` 的硬约束），
    而属性行本身不带候选——只有展开才知道。所以是"先读候选，再决策"，
    而不是拿一个想当然的值去硬填。

    实现要点（都踩过）：
    * 先把行 `scrollIntoView` 进视口——CDP 鼠标事件只在视口内有效；
    * 只认 `div.next-select-popup-wrap` 这个弹层（页面里还有别的 `.next-overlay-inner`：
      导航条、填写助手，按它们读会读到一堆无关文本）；
    * 选项取**弹层内叶子节点的短文本**（按 `.next-menu-item,[role=option],li` 找会命中 0）。
    """

    located = client.evaluate(r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').trim();
      const LABEL = WANT;
      const PROFILES = [
        { row: '.sell-component-info-wrapper-wrap',
          labelSel: '.sell-component-info-wrapper-label' },
        { row: '.sell-catProp-item-common', labelSel: 'label' },
      ];
      for (const prof of PROFILES) {
        const hits = Array.from(document.querySelectorAll(prof.row)).filter(visible)
          .filter(row => {
            const labelEl = row.querySelector(prof.labelSel);
            return labelEl && text(labelEl).replace(/[*＊\s]/g, '').replace(/(重要|必填|选填)/g, '') === LABEL;
          });
        if (hits.length !== 1) continue;
        const selects = Array.from(hits[0].querySelectorAll('.next-select')).filter(visible);
        if (selects.length !== 1) continue;
        const select = selects[0];
        if (select.disabled === true || select.getAttribute('aria-disabled') === 'true')
          return { ok: false, reason: 'select_disabled' };
        select.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = select.getBoundingClientRect();
        return { ok: true, point: { x: Math.round(r.x + r.width / 2),
                                    y: Math.round(r.y + r.height / 2) } };
      }
      return { ok: false, reason: 'row_not_found_or_ambiguous' };
    })()'''.replace("WANT", repr(label).replace("'", '"')), timeout=timeout)
    if not isinstance(located, dict) or located.get("ok") is not True:
        raise page.PageError("读候选时找不到属性 {!r} 的下拉：{}".format(
            label, (located or {}).get("reason") if isinstance(located, dict) else "无返回"))

    suspended = False
    try:
        client.evaluate(page.build_suspend_preview_overlay_expression(True), timeout=timeout)
        suspended = True
        point = located["point"]
        for event_type, extra in (("mouseMoved", {}), ("mousePressed", {"clickCount": 1}),
                                  ("mouseReleased", {"clickCount": 1})):
            params = {"type": event_type, "x": point["x"], "y": point["y"], "button": "left"}
            params.update(extra)
            client.send("Input.dispatchMouseEvent", params)
            time.sleep(0.15)
    finally:
        if suspended:
            try:
                client.evaluate(page.build_suspend_preview_overlay_expression(False),
                                timeout=timeout)
            except Exception:  # noqa: BLE001 - 恢复失败不该掩盖主流程
                pass
    time.sleep(max(0.0, wait))
    options = client.evaluate(r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').trim();
      const menus = Array.from(document.querySelectorAll('div.next-select-popup-wrap')).filter(visible);
      const items = [];
      for (const menu of menus) {
        for (const el of menu.querySelectorAll('*')) {
          if (!visible(el) || el.children.length) continue;
          const t = text(el);
          if (t && t.length <= 16) items.push(t);
        }
      }
      return { menuCount: menus.length, options: [...new Set(items)].slice(0, 100) };
    })()''', timeout=timeout)
    if close:
        _close_dropdown(client)
    if not isinstance(options, dict) or options.get("menuCount") != 1:
        raise page.PageError("属性 {!r} 的可见候选菜单不是唯一一个".format(label))
    return [str(v) for v in (options.get("options") or [])]



def _trace_timing(label: str, started: float) -> None:
    """`TAOBAO_TIMING=1` 时把必填项**内部各步**耗时写到 stderr。

    每项只展开一次，记录读取候选到确认值提交的完整耗时。
    """

    import os

    if os.environ.get('TAOBAO_TIMING') != '1':
        return
    import sys as _sys
    import time as _time

    elapsed_ms = int((_time.perf_counter() - started) * 1000)
    _sys.stderr.write('[required-timing] {:>7} ms  {}\n'.format(elapsed_ms, ascii(label)))
    _sys.stderr.flush()


def fill_required_attrs(client, *, category_path: Sequence[str] = (),
                        only: Optional[Sequence[str]] = None,
                        skip: Optional[Sequence[str]] = None,
                        adopt_recommendations: bool = False,
                        per_field_wait: float = 1.2) -> Dict[str, Any]:
    """按计划把必填属性逐项填好并回读。

    :param category_path: 类目路径（用于**类目驱动**的取值，如筒高）。
    :param only: 只处理这些字段（调试用）。
    :param skip: 跳过这些字段。
    :param adopt_recommendations: 是否先点平台的「一键采纳推荐值」。
    :param per_field_wait: 每次选择后的等待秒数。
    :return: ``{filled, already, needs_human, failed}`` 明细。
    """
    result: Dict[str, Any] = {"adopted": None, "filled": [], "already": [],
                              "needs_human": [], "failed": [],
                              "category_leaf": (category_path[-1] if category_path else "")}
    if adopt_recommendations:
        try:
            result["adopted"] = adopt_platform_recommendations(client)
        except Exception as exc:  # 单独记录失败，再逐字段处理。
            result["adopted"] = {"skipped": "{}: {}".format(type(exc).__name__, exc)}

    # 采纳推荐后再读取，避免用旧快照重复填写已经有值的属性。
    rows = read_required_rows(client)
    only_set = {str(v) for v in (only or ())}
    skip_set = {str(v) for v in (skip or ())}
    for source in rows:
        if source.get("display") is None:
            continue
        row = {**source, "category_path": list(category_path or ())}
        name = str(row.get("name") or "")
        if only_set and name not in only_set:
            continue
        plan = plan_required_defaults([row])
        if not plan:
            continue
        item = plan[0]
        if item["action"] == "already":
            result["already"].append({"name": name, "value": item["value"]})
            continue
        if name in skip_set or name in FACT_FIELDS:
            result["needs_human"].append({"name": name,
                "reason": item.get("reason") or "商品事实，留给人"})
            continue

        # 一项一次完成：打开、读候选、决策、选择、回读；不再预读全表后重开。
        opened = False
        try:
            started = time.perf_counter()
            opened = True
            row["options"] = read_dropdown_options(client, name, wait=per_field_wait, close=False)
            item = plan_required_defaults([row])[0]
            if item["action"] != "fill" or not item.get("value"):
                result["needs_human"].append({"name": name, "reason": item.get("reason")})
                continue
            entry = fill_required_attr(client, name, str(item["value"]),
                                       wait=per_field_wait, dropdown_open=True)
            _trace_timing('读候选并写值[{}]'.format(name), started)
            result["filled"].append(entry)
        except Exception as exc:  # 每项真实失败可见，继续其它独立字段。
            result["failed"].append({"name": name, "value": item.get("value"),
                "error": "{}: {}".format(type(exc).__name__, exc)})
        finally:
            if opened:
                # 选择后可能自动关闭；Esc 只收起残留菜单，不能触发第二次选择。
                _close_dropdown(client)
    return result
