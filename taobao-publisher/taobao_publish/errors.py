# -*- coding: utf-8 -*-
"""淘宝发布的错误与阻塞项模型。

约定（照搬抖店 v4 的分层，但字段体系独立）：

* 每个错误都有**稳定错误码**。前端与测试只依赖错误码，不依赖中文文案。
* 中文文案与处置建议集中在 :data:`ERROR_CATALOG`，不在业务代码里散落。
* 「没证据」不是错误，是**阻塞项**（:class:`Blocker`），必须原样上报，
  不允许被兜底逻辑吞掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, Iterable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# 错误目录
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ErrorSpec:
    """一个错误码的展示信息。"""

    code: str
    category: str
    message: str
    hint: str = ""


def _spec(code: str, category: str, message: str, hint: str = "") -> ErrorSpec:
    return ErrorSpec(code=code, category=category, message=message, hint=hint)


_CATALOG_LIST: Sequence[ErrorSpec] = (
    # --- 授权 / 安全门 ---
    _spec(
        "WRITE_NOT_AUTHORIZED",
        "授权",
        "写操作未授权，已阻止",
        "需要显式设置 TAOBAO_UPLOAD_ALLOW_WRITE 才能执行写操作",
    ),
    _spec(
        "SUBMIT_NOT_AUTHORIZED",
        "授权",
        "提交发布未二次确认，已阻止",
        "提交不可撤销，需要额外设置 TAOBAO_UPLOAD_ALLOW_SUBMIT=1",
    ),
    _spec(
        "PREFLIGHT_BLOCKED",
        "安全门",
        "发布前置检查未通过",
        "按 blockers 逐条修复后重试，不要跳过",
    ),
    # --- 环境 / 会话 ---
    _spec(
        "CDP_UNREACHABLE",
        "环境",
        "无法连接调试浏览器",
        "先用 protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs 启动 9334",
    ),
    _spec(
        "WRONG_CDP_PORT",
        "环境",
        "连接到了非淘宝调试端口",
        "淘宝固定用 9334；连着 9333 说明连到了抖店实例，必须中止",
    ),
    _spec(
        "LOGIN_REQUIRED",
        "会话",
        "淘宝登录态缺失",
        "在该 profile 里扫码登录一次；不要尝试复制 cookie 库（已实证失败）",
    ),
    _spec("RISK_CONTROL_HIT", "风控", "命中平台风控拦截页", "停止自动化，交由人工处理；不得尝试绕过"),
    _spec("WRONG_PAGE", "会话", "当前页面不是淘宝发布工作台", "导航到发布工作台后重试"),
    # --- 证据 / 契约 ---
    _spec(
        "EVIDENCE_INSUFFICIENT",
        "证据",
        "需要的字段或选择器缺少实证证据",
        "先跑只读探针补齐证据；不允许用猜测值放行写操作",
    ),
    _spec("CONTRACT_INVALID", "契约", "契约文件缺失或格式非法", "检查 contracts/ 下的 JSON 是否完整"),
    _spec("REQUIRED_FIELD_MISSING", "数据", "必填字段缺失", "补齐本地商品资料后重试"),
    _spec("UNSUPPORTED_REQUIRED_FIELD", "回读", "当前必填字段尚无已确认的读取方式",
          "保留已填写内容，补充该字段控件证据后再确认；不能把未知控件当作已填写"),
    _spec("FIELD_UNMAPPED", "映射", "字段没有可用的平台映射", "在 field_mapping.json 中补证据，或确认该字段可省略"),
    # --- 平台交互 ---
    _spec("IMAGE_UPLOAD_FAILED", "图片", "图片上传失败", "检查登录态与网络；确认图片格式与体积"),
    _spec("MEDIA_SOURCE_CHANGED", "图片", "本地图片内容与任务快照不一致",
          "保留原图，本批文件尚未发送；确认修改后的图片再启动新任务"),
    _spec("MEDIA_IMAGE_MISSING", "图片", "图片空间未找到精确对应的素材",
          "未选择未知图片；确认素材已入库及文件名控件，不能按图片数量代替身份核对"),
    _spec("CATEGORY_INVALID", "类目", "类目不存在或已失效", "重新从类目接口拉取叶子类目 ID"),
    _spec("PROP_INVALID", "属性", "类目属性值不合法", "属性值必须来自该类目的属性值列表，不可硬编码"),
    _spec("SKU_INVALID", "规格", "销售规格结构非法", "检查销售属性与 SKU 行的对应关系"),
    _spec("PRICE_INVALID", "价格", "价格或库存数值非法", "价格必须是正数且落在平台允许区间内"),
    _spec("FREIGHT_MISSING", "物流", "缺少可用的运费模板", "先在卖家后台创建运费模板"),
    _spec("READBACK_MISMATCH", "回读", "回读结果与预期不一致", "不要强行提交；先定位是哪个字段写错了"),
    _spec("SUBMIT_WITHOUT_READBACK", "提交", "没有回读核对结果就要求提交",
          "平台是**点击之后才校验**的（实测：标题为空时提交按钮仍然可用），"
          "所以「按钮可用」不能当放行信号。没有通过的回读核对，就绝不点提交"),
    _spec("SUBMIT_BLOCKED_BY_FORM", "提交", "表单未填完，提交按钮被禁用或回读未通过",
          "先看 readback 阶段的阻塞项：常见原因是必填项未填，或选完类目后未选品牌"),
    _spec("SUBMIT_FAILED", "提交", "平台拒绝发布", "见 platform_message 原始文案"),
    _spec("PLATFORM_ERROR", "平台", "平台返回未归类错误", "保留原始文案，人工判断后补进错误目录"),
    _spec("NOT_IMPLEMENTED", "开发", "该阶段尚未实现", "见 blockers：缺证据或未开发"),
    # 页面交互类。这四个码原先**不在目录里**，后果是所有页面异常的
    # ``describe_error`` 都落到「未知错误码」分支，展示成「平台返回未归类错误」——
    # 一个按钮点不到和平台风控看起来一模一样，排查全靠猜。
    _spec("PAGE_ERROR", "页面", "页面交互失败", "确认调试浏览器停留在预期的页面与登录态"),
    _spec("CANDIDATE_NOT_FOUND", "页面", "没有唯一定位到目标元素",
          "多为页面改版或标签文案变了；先跑只读探针确认定位表达式"),
    _spec("OPTION_NOT_FOUND", "页面", "下拉里没有精确匹配的选项",
          "值必须是平台标准候选项里的原文；把当时可见的候选列出来比对"),
    _spec("FIELD_MISMATCH", "页面", "单个字段回读与写入不一致",
          "不要继续提交；先确认该字段的写入方式（React 受控组件需要原生 setter）"),
    _spec("SKU_SPEC_VALUE_MISSING", "规格", "已勾选的销售属性没有值",
          "分层展示模式下任一已勾选属性为空会让「确认创建」静默失败：要么补值，要么取消勾选"),
    _spec("SKU_CREATE_SILENT_FAILURE", "规格", "确认创建后 SKU 表格没有出现",
          "E-097 的典型表现：点击无响应且不报错。检查已勾选属性是否都有值"),
    _spec("RENDERER_HUNG", "环境", "标签页的 JS 主线程无响应",
          "浏览器调试通道还通，但页面内的 JS 已经不执行了（实测：1+1 超时、"
          "readyState 返回 null、Page.navigate 也超时）。**请手动重载该标签页**，"
          "CDP 救不回来；也不要在同一个标签页上无限堆积状态"),
    _spec("VERIFICATION_REQUIRED", "平台", "平台要求人工完成验证码 / 风控校验",
          "如实报告，**不要尝试绕过**。请人工在浏览器里完成验证（例如滑动验证码）"
          "后重跑；同时说明本次是高频操作触发的，应降低频率"),
    # --- 本地校验（**不是平台错误**）-----------------------------------------
    #
    # 这八个码以前**不在目录里**：``describe_error`` 会把未知码退化成
    # ``PLATFORM_ERROR``，于是界面上显示成「平台返回未归类错误」——
    # 而它们全是本地校验失败，消息与处置建议都是错的。
    _spec("TITLE_TOO_LONG", "数据", "宝贝标题超过契约上限",
          "见 contracts/rules.json 的标题长度上限；改短标题后重试，不要截断凑数"),
    _spec("TITLE_TOO_SHORT", "数据", "宝贝标题少于契约下限",
          "见 contracts/rules.json 的标题长度下限；补足到下限以上"),
    _spec("BRAND_REQUIRED", "数据", "该页要求先选品牌才能进入下一步",
          "item.props 里补一条「品牌」；值必须是平台候选项里的原文"),
    _spec("PRICE_TOO_LOW", "数据", "一口价低于契约下限",
          "见 contracts/rules.json 的 sku_price_min；调高到下限以上"),
    _spec("FREIGHT_TEMPLATE_NOT_FOUND", "物流", "店铺里没有指定的运费模板",
          "模板名必须与卖家后台里的**完全一致**；可用 /api/shop/freight-templates 取当前列表"),
    _spec("SELECTION_NOT_CONFIRMED", "类目", "点击后选中的类目与目标不一致",
          "类目路径必须与平台候选**精确相等**；不要用简称或近似名"),
    _spec("READBACK_FAILED", "回读", "回读核对未通过",
          "看 blockers 里逐条的不一致项；**不要强行提交**，先定位是哪个字段写错了"),
    _spec("READBACK_UNREADABLE", "回读", "回读时有字段读不到",
          "通常是定位失效或字段不在了；先确认页面结构没变，再重试"),
    _spec("SELECTOR_AMBIGUOUS", "定位", "定位到了多个元素，拒绝写入",
          "标签/选择器不再唯一——通常是页面结构变了。**不要挑第一个**，" 
          "先确认页面结构并更新选择器契约"),
    _spec("MEDIA_SELECTION_NOT_IMPLEMENTED", "图片", "主图已上传，但选图没有入位",
          "**这个码现在不应该再出现**：选图入位已实现（点卡片里的 `<label>`，"
          "顺序：每张图重开弹层 → 滚动找到 → 点 label → 回读主图位数）。"
          "若它再次出现，说明选图环节**退化了**——去查为什么没选中，"
          "不要只是把「未实现」报出来"),
)

ERROR_CATALOG: Dict[str, ErrorSpec] = {spec.code: spec for spec in _CATALOG_LIST}


def describe_error(code: str) -> ErrorSpec:
    """取错误码的展示信息；未知错误码退化为 ``PLATFORM_ERROR`` 但保留原名。"""

    if code in ERROR_CATALOG:
        return ERROR_CATALOG[code]
    fallback = ERROR_CATALOG["PLATFORM_ERROR"]
    return ErrorSpec(code=code, category=fallback.category, message=fallback.message, hint=fallback.hint)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class TaobaoPublishError(RuntimeError):
    """本子项目的异常基类。``code`` 必须存在于错误目录。"""

    def __init__(self, code: str, detail: str = "", blockers: Optional[Iterable["Blocker"]] = None) -> None:
        spec = describe_error(code)
        super().__init__(f"[{spec.code}] {spec.message}" + (f"：{detail}" if detail else ""))
        self.code = spec.code
        self.detail = detail
        self.blockers: List[Blocker] = list(blockers or ())

    def to_dict(self) -> Dict[str, Any]:
        spec = describe_error(self.code)
        return {
            "code": spec.code,
            "category": spec.category,
            "message": spec.message,
            "hint": spec.hint,
            "detail": self.detail,
            "blockers": [b.to_dict() for b in self.blockers],
        }


class WriteNotAuthorizedError(TaobaoPublishError):
    """试图执行未被授权的写操作。"""

    def __init__(self, operation: str, detail: str = "") -> None:
        super().__init__("WRITE_NOT_AUTHORIZED", detail or f"操作 {operation} 未被授权")
        self.operation = operation


class SubmitNotAuthorizedError(TaobaoPublishError):
    """试图提交发布但缺少第二把锁。"""

    def __init__(self, detail: str = "") -> None:
        super().__init__("SUBMIT_NOT_AUTHORIZED", detail)
        self.operation = "submit_publish"


class PreflightBlockedError(TaobaoPublishError):
    """前置检查未通过。异常携带全部阻塞项，便于一次修完。"""

    def __init__(self, blockers: Sequence["Blocker"], detail: str = "") -> None:
        super().__init__("PREFLIGHT_BLOCKED", detail, blockers=blockers)


class BlockerError(TaobaoPublishError):
    """证据不足 / 未实现导致的阻塞。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code, detail)


# ---------------------------------------------------------------------------
# 阻塞项
# ---------------------------------------------------------------------------
#: 严重级别。``blocker`` 会阻止流水线继续；``warning`` 只提示，不阻断。
SEVERITY_BLOCKER: str = "blocker"
SEVERITY_WARNING: str = "warning"
SEVERITIES: tuple = (SEVERITY_BLOCKER, SEVERITY_WARNING)


@dataclass
class Blocker:
    """一条阻塞项（或告警）。

    :param code: 错误码，取值于 :data:`ERROR_CATALOG`（或自定义但必须稳定）。
    :param field: 出问题的字段路径，例如 ``"skus[0].price"``；没有具体字段时为 ``""``。
    :param detail: 面向开发的具体说明。
    :param severity: ``blocker``（默认，阻断）或 ``warning``（仅提示）。
    :param evidence: 该阻塞项对应的证据等级，便于区分「缺证据」与「数据错」。
    :param source: 产出该阻塞项的模块或脚本，便于回溯。

    注意：``field`` 这个**属性名**与 ``dataclasses.field`` 同名，因此本模块用
    ``dataclass_field`` 别名导入。改这里之前先确认不会再撞名。
    """

    code: str
    field: str = ""
    detail: str = ""
    severity: str = SEVERITY_BLOCKER
    evidence: str = ""
    source: str = ""
    extra: Dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity 取值非法：{self.severity!r}（应为 {SEVERITIES}）")

    @property
    def is_blocking(self) -> bool:
        return self.severity == SEVERITY_BLOCKER

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "field": self.field,
            "detail": self.detail,
            "severity": self.severity,
            "evidence": self.evidence,
            "source": self.source,
        }
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    @property
    def message(self) -> str:
        return describe_error(self.code).message

    def render(self) -> str:
        """单行中文描述，用于 CLI 与日志。"""

        head = f"[{self.code}] {self.message}"
        if self.field:
            head += f" @ {self.field}"
        if self.detail:
            head += f" — {self.detail}"
        return head


def collect_blockers(items: Iterable[Optional[Blocker]]) -> List[Blocker]:
    """过滤掉 ``None`` 并保持顺序，避免调用方写重复的列表推导。"""

    return [item for item in items if item is not None]


def split_by_severity(items: Iterable[Blocker]) -> tuple:
    """拆成 ``(blockers, warnings)``，各自保持原顺序。"""

    blockers: List[Blocker] = []
    warnings: List[Blocker] = []
    for item in items:
        (blockers if item.is_blocking else warnings).append(item)
    return blockers, warnings


def dedupe_blockers(blockers: Iterable[Blocker]) -> List[Blocker]:
    """按 ``(code, field, detail)`` 去重并保持首次出现顺序。

    重复阻塞项会让用户以为有很多问题，实际只差一件事没做。
    """

    seen = set()
    result: List[Blocker] = []
    for blocker in blockers:
        key = (blocker.code, blocker.field, blocker.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(blocker)
    return result
