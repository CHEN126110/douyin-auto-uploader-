# -*- coding: utf-8 -*-
"""按**标签文本**定位表单行与控件。

## 为什么需要这个模块

淘宝发布填写页里，控件的 ``placeholder`` 大量重复（「请选择」出现 20+ 次，
「请输入」同理），按钮也没有唯一属性。**CSS 选择器无法按文本匹配**，
所以只有两条路：

* 按 ``nth-child`` / 「第 N 个 input」定位 —— **禁止**。页面增删一个字段就整体错位，
  而且每一步都会「成功」，事后完全查不出来。
* 按**行的标签文本**定位 —— 本模块。

## 已实证的行结构（2026-10-03，真实登录态）

``.next-form-item`` 在这个页面**不存在**（实测 0 个），不能套 Fusion 的标准结构。
真实结构是：

.. code-block:: text

    div.sell-component-info-wrapper-wrap            ← 行容器
      ├── div.sell-component-info-wrapper-label-wrap
      │     └── span.sell-component-info-wrapper-label   ← 标签文本
      └── input / [role=combobox] / …               ← 控件

实测：页面 70 行，其中 8 行无标签，**62 个标签互不重复**；22 个业务字段
（材质成分、面料、上市年份季节、宝贝标题、一口价、总库存……）按标签精确匹配
**全部恰好命中 1 行**（唯一 22 / 多重 0 / 缺失 0）。

## 一条必须守住的规则

契约里写着：「禁止使用会匹配到多个元素的选择器去驱动写操作；
写入前必须校验唯一命中的元素数量。」

本模块把这条规则**做进 API**：定位函数返回命中数，`require_unique` 在命中数
不为 1 时直接抛错。**调用方拿不到「可能写错」的选项**——这是有意的，
因为写错行的后果是商品信息串行，比直接失败难查得多。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: 行容器。实测 70 行 / 22 个业务字段全部命中。
ROW_SELECTOR = ".sell-component-info-wrapper-wrap"

#: 标签元素。文本即字段名（必填会以 ``*`` 兄弟节点出现，不进入本元素的 textContent）。
LABEL_SELECTOR = ".sell-component-info-wrapper-label"

#: 行内可能承载值的控件。
CONTROL_SELECTOR = "input,textarea,select,[role=\"combobox\"]"


@dataclass(frozen=True)
class RowProfile:
    """一个页面上的「行容器 + 标签」结构。

    为什么需要它：**淘宝不同页面的表单结构不一样**。

    ==================  ==========================================  ==================================
    页面                 行容器                                       标签
    ==================  ==========================================  ==================================
    发布填写页            ``.sell-component-info-wrapper-wrap``        ``.sell-component-info-wrapper-label``
    类目搜索页            ``.sell-catProp-item-common``                ``label``（必填带 ``required`` 类）
    ==================  ==========================================  ==================================

    两套结构都靠「先按标签唯一定位行、再取行内控件」工作，只是选择器不同。
    把差异收进这个数据结构，而不是在各处写死其中一个。
    """

    name: str
    row_selector: str
    label_selector: str
    note: str = ""


#: 发布填写页（item.upload.taobao.com/sell/v2/publish.htm）。实测 70 行 / 62 个互不重复的标签。
PUBLISH_FORM = RowProfile(
    name="publish_form",
    row_selector=ROW_SELECTOR,
    label_selector=LABEL_SELECTOR,
    note="实测 70 行，22 个业务字段按标签精确匹配全部恰好命中 1 行",
)

#: 类目搜索页（item.upload.taobao.com/sell/ai/category.htm）。
#:
#: 实测这一页只有 **1 个** ``.sell-catProp-item-common``：品牌（必填）。
#: 标签是行内直接嵌的 ``label``，必填时类名含 ``required``。
CATEGORY_PAGE = RowProfile(
    name="category_page",
    row_selector=".sell-catProp-item-common",
    label_selector="label",
    note="实测该页只有 1 个属性项：品牌（required），控件为 input[role=combobox]",
)

#: 两个页面的结构。键是 profile 名，供调用方按页面选择。
#: 类目属性行的组合。**发布页上的「商品属性」块也用这套结构。**
#:
#: 实测（2026-10-03）：`publish_form` 组合定位到 21 个标签，
#: **类目属性行一个都没有**；换成这套组合，「品牌 / 上市年份季节 / 适用季节 /
#: 适用性别」4 个立刻定位到，且都是 ``input[role=combobox]``。
PROPERTY_ROW = RowProfile(
    name="property_row",
    row_selector=".sell-catProp-item-common",
    label_selector="label",
    note="类目属性行；实测控件为 input[role=combobox]（可搜索下拉）",
)

ROW_PROFILES: Dict[str, RowProfile] = {
    PUBLISH_FORM.name: PUBLISH_FORM,
    CATEGORY_PAGE.name: CATEGORY_PAGE,
    PROPERTY_ROW.name: PROPERTY_ROW,
}

#: 按标签定位时**依次尝试**的组合。
#:
#: ⚠️ **顺序有讲究**：发布页上的普通字段要用 `publish_form`；
#: 类目属性行（「商品属性」块里那些）用的是 `property_row` 那套结构。
#: 实测只试前者的话，属性行**一个都定位不到**。
ROW_PROFILE_ORDER = (PUBLISH_FORM, PROPERTY_ROW)


class LabelNotFound(LookupError):
    """按标签没有定位到任何行。"""


class LabelAmbiguous(LookupError):
    """按标签定位到多行——**绝不允许**在这种情况下写值。"""


@dataclass(frozen=True)
class LocatedRow:
    """一次定位的结果。只有 ``unique`` 为真时调用方才可以写值。"""

    label: str
    hit_count: int
    match_mode: str
    control_count: int
    row_class: str
    reason: str = ""

    @property
    def unique(self) -> bool:
        return self.hit_count == 1


def _js_string(value: str) -> str:
    """把 Python 字符串安全地嵌进 JS 字面量。

    用 ``json.dumps`` 而不是手工加引号：中文、引号、反斜杠、``</script>``
    都能正确转义。标签名来自本项目的契约常量，但**不因此放松**——
    一旦将来有人把它接到用户输入上，这里就是注入点。
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("标签必须是非空字符串")
    return json.dumps(value, ensure_ascii=False)


def locate_row_expression(label: str, profile: "RowProfile" = PUBLISH_FORM) -> str:
    """生成一段 JS：按标签精确定位行，返回命中数与控件画像。

    返回的是**描述**而不是元素引用——元素引用过不了 CDP 的 ``returnByValue``。
    需要操作元素时用 :func:`operate_row_expression`。

    页面端**只读**：不点击任何东西。

    :param profile: 目标页面的行结构。默认发布填写页；类目页传 :data:`CATEGORY_PAGE`。
    """

    literal = _js_string(label)
    return """
(() => {{
  const LABEL = {label_literal};
  const ROW = {row};
  const LABEL_SEL = {label_sel};
  const CONTROL = {control};

  const labelOf = (row) => {{
    const el = row.querySelector(LABEL_SEL);
    return el ? (el.textContent || '').trim() : '';
  }};

  const rows = Array.from(document.querySelectorAll(ROW));
  let hits = rows.filter(r => labelOf(r) === LABEL);
  let mode = 'exact';
  if (hits.length === 0) {{
    // 退化：标签区文本以字段名开头（例如带自定义后缀时）
    hits = rows.filter(r => labelOf(r).startsWith(LABEL));
    mode = hits.length ? 'prefix' : 'none';
  }}

  const first = hits[0];
  const controls = first
    ? Array.from(first.querySelectorAll(CONTROL)).filter(el => {{
        const b = el.getBoundingClientRect();
        return b.width > 0 && b.height > 0;
      }})
    : [];

  return {{
    label: LABEL,
    hitCount: hits.length,
    matchMode: mode,
    rowClass: first && typeof first.className === 'string' ? first.className.slice(0, 120) : '',
    controlCount: controls.length,
    controls: controls.slice(0, 5).map(el => ({{
      tag: el.tagName.toLowerCase(),
      // ⚠️ **`type` 不能省。**
      //
      // 实测（2026-10-03）：「发货时间」那一行是**两组单选**
      // （按商品统一设置/按规格单独设置 + 四档发货时效），6 个 `input[value='on']`。
      // 但画像里没有 `type` 时，radio 与文本框长得一模一样，
      // `classify_row` 于是把它判成 `text`——
      // 而拿 `fill_text_field` 去写一个 radio 是**毫无意义**的。
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      placeholder: el.getAttribute('placeholder') || '',
      disabled: el.disabled === true,
      readOnly: el.readOnly === true,
    }})),
  }};
}})()
""".format(
        label_literal=literal,
        row=json.dumps(profile.row_selector),
        label_sel=json.dumps(profile.label_selector),
        control=json.dumps(CONTROL_SELECTOR),
    )


def describe_located_row(payload: Any) -> LocatedRow:
    """把页面返回的描述转成 :class:`LocatedRow`，并判定是否可用。"""

    if not isinstance(payload, dict):
        return LocatedRow("", 0, "none", 0, "", reason="页面没有返回可解析的定位结果")

    hit_count = payload.get("hitCount")
    if not isinstance(hit_count, int) or hit_count < 0:
        hit_count = 0
    control_count = payload.get("controlCount")
    if not isinstance(control_count, int) or control_count < 0:
        control_count = 0

    reason = ""
    if hit_count == 0:
        reason = "按标签没有定位到行；字段可能被折叠、在别的类目下、或页面结构已变"
    elif hit_count > 1:
        reason = "按标签定位到多行；写入会串行，必须先补限定条件"

    return LocatedRow(
        label=str(payload.get("label") or ""),
        hit_count=hit_count,
        match_mode=str(payload.get("matchMode") or "none"),
        control_count=control_count,
        row_class=str(payload.get("rowClass") or ""),
        reason=reason,
    )


def require_unique(row: LocatedRow) -> LocatedRow:
    """命中数不为 1 时抛错。**写值之前必须调用它。**

    :raises LabelNotFound: 命中 0 行
    :raises LabelAmbiguous: 命中多行
    """

    if row.hit_count == 0:
        raise LabelNotFound("{}（标签 {!r}）".format(row.reason or "未定位到行", row.label))
    if row.hit_count > 1:
        raise LabelAmbiguous("{}（标签 {!r} 命中 {} 行）".format(row.reason, row.label, row.hit_count))
    return row


def operate_row_expression(
    label: str, action_js: str, profile: "RowProfile" = PUBLISH_FORM
) -> str:
    """生成一段 JS：定位到唯一一行后，对该行执行 ``action_js``。

    ``action_js`` 里可用变量：

      - ``row``     该行元素
      - ``control`` 行内第一个可见控件（可能为 ``null``）

    **仍然先落唯一性判定**：命中数不为 1 时直接返回失败描述，不执行 ``action_js``。
    这比「先查一次、再操作一次」可靠——两次查询之间页面可能变了。

    :param profile: 目标页面的行结构。默认发布填写页；类目页传 :data:`CATEGORY_PAGE`。
    """

    literal = _js_string(label)
    if not isinstance(action_js, str) or not action_js.strip():
        raise ValueError("action_js 不能为空")

    return """
(() => {{
  const LABEL = {label_literal};
  const ROW = {row};
  const LABEL_SEL = {label_sel};
  const CONTROL = {control};

  const labelOf = (row) => {{
    const el = row.querySelector(LABEL_SEL);
    return el ? (el.textContent || '').trim() : '';
  }};

  const rows = Array.from(document.querySelectorAll(ROW));
  let hits = rows.filter(r => labelOf(r) === LABEL);
  if (hits.length === 0) hits = rows.filter(r => labelOf(r).startsWith(LABEL));
  if (hits.length !== 1) {{
    return {{ ok: false, reason: hits.length === 0 ? 'label_not_found' : 'label_ambiguous',
              label: LABEL, hitCount: hits.length }};
  }}

  const row = hits[0];
  const control = Array.from(row.querySelectorAll(CONTROL)).find(el => {{
    const b = el.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  }}) || null;

  {action}

  return {{ ok: true, label: LABEL }};
}})()
""".format(
        label_literal=literal,
        row=json.dumps(profile.row_selector),
        label_sel=json.dumps(profile.label_selector),
        control=json.dumps(CONTROL_SELECTOR),
        action=action_js,
    )


#: 只有这些字段的标签经过实测确认（见模块注释）。实现阶段只允许用这些。
VERIFIED_LABELS: Dict[str, List[str]] = {
    "fill_base": ["宝贝标题", "导购标题", "商家编码"],
    "fill_props": [
        "材质成分", "面料", "上市年份季节", "编织工艺", "吊牌价", "防滑设计",
        "风格", "缝头工艺", "厚薄", "抗菌处理", "款式细节", "里料",
        "是否商场同款", "图案", "袜口弹性材质", "款号",
    ],
    "fill_price_stock": ["一口价", "总库存", "购买须知"],
}

#: 实测确认的行标签全集（2026-10-03 页面全貌勘察）。
#:
#: 这份名单是**页面地图**，不是「可以随便写的字段」。其中带 ``*`` 的是必填，
#: 而必填项里有一部分（上架时间 / 发货时间 / 提取方式 / 宝贝详情）还没有实证的写入方式，
#: 属于 `fill_freight` 与 `submit` 阶段的待办。
MEASURED_ROW_LABELS: Dict[str, Dict[str, Any]] = {
    "当前类目": {"required": True, "controls": 0},
    "宝贝类型": {"required": True, "controls": 0, "visible": False},
    "1:1主图": {"required": True, "controls": 0},
    "宝贝标题": {"required": True, "controls": 1},
    "导购标题": {"required": False, "controls": 1},
    "商品属性": {"required": True, "controls": 21, "note": "所有属性的父行，内含子行"},
    "材质成分": {"required": False, "controls": 0, "important": True,
               "note": "行内无可见控件，用「添加材质成分」按钮"},
    "里料材质成分": {"required": False, "controls": 0},
    "适用场景": {"required": True, "controls": 1},
    "适用季节": {"required": True, "controls": 1},
    "适用年龄": {"required": True, "controls": 1},
    "适用性别": {"required": True, "controls": 1},
    "功能": {"required": False, "controls": 1},
    "品牌": {"required": False, "controls": 1},
    "面料": {"required": False, "controls": 1},
    "上市年份季节": {"required": True, "controls": 1},
    "编织工艺": {"required": False, "controls": 1},
    "吊牌价": {"required": False, "controls": 1},
    "防滑设计": {"required": False, "controls": 1},
    "风格": {"required": False, "controls": 1},
    "缝头工艺": {"required": False, "controls": 1},
    "厚薄": {"required": False, "controls": 1},
    "抗菌处理": {"required": False, "controls": 1},
    "款式细节": {"required": False, "controls": 1},
    "里料": {"required": False, "controls": 1},
    "是否商场同款": {"required": False, "controls": 1},
    "图案": {"required": False, "controls": 1},
    "袜口弹性材质": {"required": False, "controls": 1},
    "款号": {"required": False, "controls": 1},
    "销售规格": {"required": False, "controls": 0, "note": "用「+ 创建规格」按钮"},
    "一口价": {"required": True, "controls": 1},
    "总库存": {"required": True, "controls": 1},
    "购买须知": {"required": False, "controls": 1},
    "商家编码": {"required": False, "controls": 1},
    "多件优惠": {"required": False, "controls": 3},
    "上架时间": {"required": True, "controls": 3},
    "商品预检": {"required": False, "controls": 1},
    "发货时间": {"required": True, "controls": 6, "note": "物流服务；尚无写入方式"},
    "提取方式": {"required": True, "controls": 4, "note": "物流服务；尚无写入方式"},
    "3:4主图": {"required": False, "controls": 0},
    "商品视频": {"required": False, "controls": 0},
    "白底图": {"required": False, "controls": 0},
    "宝贝长图": {"required": False, "controls": 0},
    "卖点图": {"required": False, "controls": 0},
    "宝贝详情": {"required": True, "controls": 0, "note": "图文描述；尚无写入方式"},
    "店铺中分类": {"required": False, "controls": 1},
}

#: 实测确认的按钮文本（2026-10-03）。
MEASURED_BUTTONS: Dict[str, Dict[str, Any]] = {
    "提交宝贝信息": {"write": True, "note": "提交发布——最后一道人工确认的对象"},
    "保存草稿": {"write": True, "note": "保存草稿"},
    "切换类目": {"write": False},
    "+ 创建规格": {"write": True, "note": "打开销售规格创建，fill_skus 的入口"},
    "添加材质成分": {"write": True, "note": "材质成分专用入口（该行无内联控件）"},
    "批量导入": {"write": True},
    "从1:1主图裁剪": {"write": False},
    "从3:4主图裁剪": {"write": False},
    "从主图生成": {"write": False},
    "预览": {"write": False},
    "保存为模板": {"write": True, "disabled": True},
    "设置批次库存发货时效": {"write": True},
}


def verified_labels_for(stage: str) -> List[str]:
    """该阶段已实测确认的标签。未确认的阶段返回空列表——**不允许猜**。"""

    return list(VERIFIED_LABELS.get(stage, []))


def locate_button_expression(text: str) -> str:
    """生成一段 JS：按**按钮文本**定位按钮，返回命中数与状态。

    按钮和输入框一样没有唯一属性——「提交宝贝信息」与「保存草稿」的区别**只在文本**，
    类名只差 ``next-btn-primary`` / ``next-btn-normal`` 这一位，靠它区分太脆。
    而 CSS 无法按文本匹配，所以同样要按文本定位。
    """

    literal = _js_string(text)
    return """
(() => {{
  const TEXT = {text_literal};
  const all = Array.from(document.querySelectorAll('button'));
  const norm = (b) => (b.textContent || '').trim();
  let hits = all.filter(b => norm(b) === TEXT);
  let mode = 'exact';
  if (hits.length === 0) {{
    hits = all.filter(b => norm(b).includes(TEXT));
    mode = hits.length ? 'contains' : 'none';
  }}
  const usable = hits.filter(b => {{
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }});
  const first = usable[0] || hits[0];
  return {{
    text: TEXT,
    hitCount: hits.length,
    visibleCount: usable.length,
    matchMode: mode,
    disabled: first ? first.disabled === true : null,
    className: first && typeof first.className === 'string' ? first.className.slice(0, 120) : '',
  }};
}})()
""".format(text_literal=literal)


@dataclass(frozen=True)
class LocatedButton:
    text: str
    hit_count: int
    visible_count: int
    match_mode: str
    disabled: Optional[bool]
    class_name: str
    reason: str = ""

    @property
    def unique(self) -> bool:
        return self.hit_count == 1


def describe_located_button(payload: Any) -> LocatedButton:
    if not isinstance(payload, dict):
        return LocatedButton("", 0, 0, "none", None, "", reason="页面没有返回可解析的定位结果")
    hits = payload.get("hitCount")
    hits = hits if isinstance(hits, int) and hits >= 0 else 0
    visible = payload.get("visibleCount")
    visible = visible if isinstance(visible, int) and visible >= 0 else 0
    reason = ""
    if hits == 0:
        reason = "按文本没有定位到按钮"
    elif hits > 1:
        reason = "按文本定位到多个按钮；写入会点错，必须先补限定条件"
    elif visible == 0:
        reason = "按钮存在但不可见（可能在别的 tab 或折叠区）"
    return LocatedButton(
        text=str(payload.get("text") or ""),
        hit_count=hits,
        visible_count=visible,
        match_mode=str(payload.get("matchMode") or "none"),
        disabled=payload.get("disabled") if isinstance(payload.get("disabled"), bool) else None,
        class_name=str(payload.get("className") or ""),
        reason=reason,
    )


def require_unique_button(button: LocatedButton) -> LocatedButton:
    """命中数不为 1、或按钮不可见时抛错。**点击之前必须调用它。**"""

    if button.hit_count == 0:
        raise LabelNotFound("{}（按钮 {!r}）".format(button.reason, button.text))
    if button.hit_count > 1:
        raise LabelAmbiguous("{}（按钮 {!r} 命中 {} 个）".format(button.reason, button.text, button.hit_count))
    if button.visible_count == 0:
        raise LabelNotFound("{}（按钮 {!r}）".format(button.reason, button.text))
    return button


def operate_button_expression(text: str, action_js: str) -> str:
    """按文本定位到唯一且可见的按钮后执行 ``action_js``；``button`` 变量可用。"""

    literal = _js_string(text)
    if not isinstance(action_js, str) or not action_js.strip():
        raise ValueError("action_js 不能为空")
    return """
(() => {{
  const TEXT = {text_literal};
  const all = Array.from(document.querySelectorAll('button'));
  const norm = (b) => (b.textContent || '').trim();
  let hits = all.filter(b => norm(b) === TEXT);
  if (hits.length === 0) hits = all.filter(b => norm(b).includes(TEXT));
  const usable = hits.filter(b => {{
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }});
  if (hits.length !== 1 || usable.length !== 1) {{
    return {{ ok: false, reason: hits.length === 0 ? 'button_not_found'
              : (hits.length > 1 ? 'button_ambiguous' : 'button_not_visible'),
              text: TEXT, hitCount: hits.length, visibleCount: usable.length }};
  }}
  const button = usable[0];
  {action}
  return {{ ok: true, text: TEXT }};
}})()
""".format(text_literal=literal, action=action_js)


#: 文本锚点定位默认向上找几层。
DEFAULT_MAX_HOPS = 4


def locate_text_anchor_expression(anchor: str, max_hops: int = DEFAULT_MAX_HOPS) -> str:
    """按**任意文本锚点**定位它附近的控件。

    用途：那些**类名是 CSS Modules 哈希**、不能当选择器的区块。

    实测例子（2026-10-03，运费模板）::

        div.template-lzNicC          ← 容器，哈希类名
          ├── div.label-HElTNK       ← 标签，哈希类名
          └── [role=combobox]

    ``template-lzNicC`` 与 ``label-HElTNK`` 每次构建都会变，**写进契约等于埋雷**。
    所以这里不认类名，只认文本：找到文本恰好等于锚点的**最深**元素，
    再逐层向上找「恰好含 1 个可见控件」的容器。

    「最深」很关键：不取最深会拿到包住整块的外层容器，那里的控件数远不止 1。
    向上找的每一层都会记录控件数，命中数不为 1 时由调用方按唯一性规则拒绝。
    """

    literal = _js_string(anchor)
    hops = int(max_hops)
    if hops < 1 or hops > 8:
        raise ValueError("max_hops 必须在 1..8 之间")
    return """
(() => {{
  const ANCHOR = {anchor_literal};
  const MAX_HOPS = {hops};
  const CONTROL = {control};

  const all = Array.from(document.querySelectorAll('div,span,label,dt,th,p'));
  const exact = all.filter(el => (el.textContent || '').trim() === ANCHOR);
  if (!exact.length) {{
    return {{ anchor: ANCHOR, found: false, hitCount: 0, candidates: [] }};
  }}
  const anchorEl = exact[exact.length - 1];

  const visible = (el) => {{
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }};

  const candidates = [];
  let node = anchorEl;
  for (let hop = 0; hop <= MAX_HOPS && node; hop++) {{
    const controls = Array.from(node.querySelectorAll(CONTROL)).filter(visible);
    candidates.push({{
      hop,
      tag: node.tagName.toLowerCase(),
      className: typeof node.className === 'string' ? node.className.slice(0, 100) : '',
      controlCount: controls.length,
      controls: controls.slice(0, 3).map(el => ({{
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        placeholder: el.getAttribute('placeholder') || '',
      }})),
    }});
    node = node.parentElement;
  }}

  // 取「控件恰好 1 个」的**最近**一层；没有就报没找到。
  const usable = candidates.filter(c => c.controlCount === 1);

  return {{
    anchor: ANCHOR,
    found: true,
    anchorTag: anchorEl.tagName.toLowerCase(),
    anchorClass: typeof anchorEl.className === 'string' ? anchorEl.className.slice(0, 100) : '',
    hitCount: usable.length,
    chosen: usable.length ? usable[0] : null,
    candidates,
  }};
}})()
""".format(anchor_literal=literal, hops=hops, control=json.dumps(CONTROL_SELECTOR))


@dataclass(frozen=True)
class LocatedAnchor:
    anchor: str
    found: bool
    hit_count: int
    chosen_hop: Optional[int]
    chosen_class: str
    chosen_control_count: int
    candidates: List[Dict[str, Any]]

    @property
    def unique(self) -> bool:
        return self.found and self.hit_count == 1


def describe_located_anchor(payload: Any) -> LocatedAnchor:
    if not isinstance(payload, dict):
        return LocatedAnchor("", False, 0, None, "", 0, [])
    chosen = payload.get("chosen") if isinstance(payload.get("chosen"), dict) else None
    hits = payload.get("hitCount")
    hits = hits if isinstance(hits, int) and hits >= 0 else 0
    candidates = payload.get("candidates")
    return LocatedAnchor(
        anchor=str(payload.get("anchor") or ""),
        found=bool(payload.get("found")),
        hit_count=hits,
        chosen_hop=chosen.get("hop") if chosen else None,
        chosen_class=str(chosen.get("className") or "") if chosen else "",
        chosen_control_count=int(chosen.get("controlCount") or 0) if chosen else 0,
        candidates=candidates if isinstance(candidates, list) else [],
    )


def require_unique_anchor(anchor: LocatedAnchor) -> LocatedAnchor:
    """锚点必须存在，且**恰好有一层**含唯一控件。"""

    if not anchor.found:
        raise LabelNotFound("文本锚点 {!r} 在页面上找不到".format(anchor.anchor))
    if anchor.hit_count == 0:
        raise LabelNotFound(
            "文本锚点 {!r} 找到了，但向上 {} 层都没有「恰好 1 个可见控件」的容器".format(
                anchor.anchor, DEFAULT_MAX_HOPS))
    if anchor.hit_count > 1:
        raise LabelAmbiguous(
            "文本锚点 {!r} 有 {} 层都只含 1 个控件，无法确定该用哪一层".format(
                anchor.anchor, anchor.hit_count))
    return anchor


#: 类名不可信、只能按文本锚点定位的区块（实测）。
TEXT_ANCHOR_ONLY: Dict[str, Dict[str, str]] = {
    "运费模板": {
        "reason": "容器与标签都是 CSS Modules 哈希类名（实测 div.template-lzNicC / div.label-HElTNK），"
                  "每次构建都会变，不能写进契约当选择器",
        "control": "[role=combobox]",
    },
}


def describe_locator_payload(payload: Any) -> Optional[Dict[str, Any]]:
    """调试用：把定位结果整理成可打印的字典。"""

    row = describe_located_row(payload)
    return {
        "label": row.label,
        "unique": row.unique,
        "hit_count": row.hit_count,
        "match_mode": row.match_mode,
        "control_count": row.control_count,
        "row_class": row.row_class,
        "reason": row.reason,
    }
