# -*- coding: utf-8 -*-
"""协议优先素材路线的离线验证：开关语义、回执对账、身份核对。

真机跑通的部分（上传端点、同源要求、token）见 ``docs/33``；
这里验证的是**接线是否正确**——尤其是三类必须失败的场景：
缺回执、页面上找不到、同名不同 URL。
"""
from __future__ import annotations

import json

import pytest

from taobao_publish.errors import TaobaoPublishError
from taobao_publish.protocol_media import (
    ENV_MEDIA_ROUTE,
    MEDIA_ROUTES,
    ROOT_FOLDER_ID,
    ROUTE_DOM,
    ROUTE_PROTOCOL,
    ProtocolMediaEntry,
    build_entries,
    media_route_from_environment,
    plan_from_entries,
    verify_against_gallery,
)


# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------
def test_route_defaults_to_dom_when_unset():
    assert media_route_from_environment({}) == ROUTE_DOM
    assert media_route_from_environment({ENV_MEDIA_ROUTE: ""}) == ROUTE_DOM
    assert media_route_from_environment({ENV_MEDIA_ROUTE: "  "}) == ROUTE_DOM


def test_route_accepts_protocol_case_insensitively():
    assert media_route_from_environment({ENV_MEDIA_ROUTE: "protocol"}) == ROUTE_PROTOCOL
    assert media_route_from_environment({ENV_MEDIA_ROUTE: " PROTOCOL "}) == ROUTE_PROTOCOL
    assert ROUTE_DOM in MEDIA_ROUTES and ROUTE_PROTOCOL in MEDIA_ROUTES


def test_unknown_route_raises_instead_of_silently_falling_back():
    """静默回退到 DOM 会让人以为跑的是协议——必须报错。"""

    with pytest.raises(ValueError) as error:
        media_route_from_environment({ENV_MEDIA_ROUTE: "http"})
    assert "TAOBAO_MEDIA_ROUTE" in str(error.value)


def test_root_folder_id_matches_bundle_default():
    assert ROOT_FOLDER_ID == "0"


# ---------------------------------------------------------------------------
# 回执对账
# ---------------------------------------------------------------------------
IDENTITIES = {
    "main": [
        {"path": r"C:\p\主图_01.jpg", "name": "tb_1_main_1_aaa.jpg", "sha256": "a" * 64},
        {"path": r"C:\p\主图_02.jpg", "name": "tb_1_main_2_bbb.jpg", "sha256": "b" * 64},
    ],
    "detail": [
        {"path": r"C:\p\详情页\详情01.jpg", "name": "tb_1_detail_ccc.jpg", "sha256": "c" * 64},
    ],
}

RECEIPTS = {
    "tb_1_main_1_aaa.jpg": {"url": "https://img.alicdn.com/i1/aaa.jpg", "picture_id": "1"},
    "tb_1_main_2_bbb.jpg": {"url": "https://img.alicdn.com/i1/bbb.jpg", "picture_id": "2"},
    "tb_1_detail_ccc.jpg": {"url": "https://img.alicdn.com/i1/ccc.jpg", "picture_id": "3"},
}


def test_build_entries_pairs_identities_with_receipts():
    entries = build_entries(roles=IDENTITIES, receipts=RECEIPTS)
    assert [item.name for item in entries["main"]] == ["tb_1_main_1_aaa.jpg", "tb_1_main_2_bbb.jpg"]
    assert entries["detail"][0].url.endswith("ccc.jpg")
    assert entries["detail"][0].picture_id == "3"
    plan = plan_from_entries(entries)
    assert plan["main"][0]["url"].startswith("https://")
    assert plan["main"][0]["sha256"] == "a" * 64


def test_missing_receipt_fails_instead_of_uploading_something_else():
    partial = {"tb_1_main_1_aaa.jpg": RECEIPTS["tb_1_main_1_aaa.jpg"]}
    with pytest.raises(TaobaoPublishError) as error:
        build_entries(roles=IDENTITIES, receipts=partial)
    assert "没有协议上传回执" in str(error.value)


def test_receipt_without_https_url_fails():
    bad = dict(RECEIPTS)
    bad["tb_1_main_2_bbb.jpg"] = {"url": "http://img.alicdn.com/i1/bbb.jpg", "picture_id": "2"}
    with pytest.raises(TaobaoPublishError):
        build_entries(roles=IDENTITIES, receipts=bad)


# ---------------------------------------------------------------------------
# 页面身份核对
# ---------------------------------------------------------------------------
#: 真实形态的图片地址（``imgextra/iN/<用户ID>/O1CN…``）。
#: 身份判据 ``image_identity`` 取的就是 ``O1CN…`` 那一段，
#: 所以测试必须用**真实形态**——用 ``img.example.invalid/x.jpg`` 这种占位地址
#: 会得到空标识，被正确地判成「无法确认」（这本身也是一条要被钉住的规则）。
REAL_URL = ("https://img.alicdn.com/imgextra/i3/2214966481149/"
            "O1CN012vpW9ytISlG1chua_!!2214966481149.jpg")
OTHER_REAL_URL = ("https://img.alicdn.com/imgextra/i4/2214966481149/"
                  "O1CN01ZZZzzz_!!2214966481149.jpg")


def test_gallery_verification_accepts_same_resource_in_thumbnail_form():
    """回执是原图地址、卡片是缩略地址——同一张图必须通过，并且算「已确认」。"""

    entry = ProtocolMediaEntry(
        role="main", path=r"C:\p\主图_01.jpg", name="tb_1_main_1_aaa.jpg",
        sha256="a" * 64, url=REAL_URL, picture_id="1",
    )
    card = {"url": REAL_URL + "_320x320q80_.webp?t=1791218506000", "page_number": 2}
    resolved = verify_against_gallery({entry.name: card}, [entry])
    assert resolved[0].page_number == 2
    assert resolved[0].url == entry.url, "回执地址是权威值，卡片地址只用于判定身份"


def test_placeholder_url_without_resource_id_falls_back_to_literal_compare():
    """没有 ``O1CN`` 标识的地址**退回逐字比较**：完全一样才算同一张。

    为什么不是「取不到标识就判否」：不是所有图片地址都长成 imgextra 形态，
    一律判否会误杀形态不同的真实地址，也会打挂既有用例。
    但**逐字不一样就一定判否**——不会把不同图当同一张。
    """

    entry = ProtocolMediaEntry(
        role="main", path=r"C:\p\主图_01.jpg", name="tb_1_main_1_aaa.jpg",
        sha256="a" * 64, url="https://img.example.invalid/aaa.jpg",
    )
    # 完全一致 → 通过
    resolved = verify_against_gallery({entry.name: {"url": entry.url}}, [entry])
    assert resolved[0].url == entry.url
    # 换个地址 → 必须失败
    with pytest.raises(TaobaoPublishError):
        verify_against_gallery(
            {entry.name: {"url": "https://img.example.invalid/other.jpg"}}, [entry])


def test_same_name_different_url_is_a_failure_not_a_substitute():
    """同名但指向不同资源 = 图片空间里那张不是我们刚传的那张。绝不将就。"""

    entry = ProtocolMediaEntry(
        role="main", path=r"C:\p\主图_01.jpg", name="tb_1_main_1_aaa.jpg",
        sha256="a" * 64, url=REAL_URL,
    )
    with pytest.raises(TaobaoPublishError) as error:
        verify_against_gallery(
            {entry.name: {"url": OTHER_REAL_URL + "_320x320"}}, [entry]
        )
    assert "不是同一张图" in str(error.value)


def test_missing_from_gallery_is_a_failure():
    entry = ProtocolMediaEntry(
        role="main", path=r"C:\p\主图_01.jpg", name="tb_1_main_1_aaa.jpg",
        sha256="a" * 64, url="https://img.alicdn.com/i1/aaa.jpg",
    )
    with pytest.raises(TaobaoPublishError) as error:
        verify_against_gallery({}, [entry])
    assert "没有找到" in str(error.value)


def test_gallery_verification_ignores_junk_page_number():
    entry = ProtocolMediaEntry(
        role="main", path=r"C:\p\x.jpg", name="n.jpg", sha256="d" * 64,
        url=REAL_URL,
    )
    for value in (0, -1, "2", None):
        resolved = verify_against_gallery(
            {entry.name: {"url": REAL_URL + "_320x320", "page_number": value}}, [entry])
        assert resolved[0].page_number is None, f"page_number={value!r} 不该被当成有效页码"


# ---------------------------------------------------------------------------
# 上传计划：整个商品文件夹
# ---------------------------------------------------------------------------
class _Item:
    def __init__(self, tmp_path, *, main=(), sku=(), detail=(), record_id=7, name="ID-1"):
        self.record_id = record_id
        self.record_name = name

        class _Images:
            pass

        images = _Images()
        images.main = list(main)
        images.sku = list(sku)
        images.detail = list(detail)
        self.images = images


def test_upload_plan_covers_all_roles_and_dedupes(tmp_path):
    from taobao_publish.protocol_media import build_upload_plan

    main = tmp_path / "主图_01.jpg"
    main.write_bytes(b"x")
    shared = main
    detail = tmp_path / "详情01.jpg"
    detail.write_bytes(b"y")
    item = _Item(tmp_path, main=[str(main)], sku=[str(shared)], detail=[str(detail)])
    plan = build_upload_plan(item)
    assert plan.role_paths["main"] == (str(main),)
    assert plan.role_paths["sku"] == (str(shared),)
    # 同一张图出现在两个用途里只传一次
    assert len(plan.all_paths) == 2
    assert plan.describe()["total_unique"] == 2


def test_upload_plan_requires_main_images(tmp_path):
    from taobao_publish.protocol_media import build_upload_plan

    with pytest.raises(TaobaoPublishError) as error:
        build_upload_plan(_Item(tmp_path))
    assert "主图" in str(error.value)


def test_upload_plan_reports_missing_files(tmp_path):
    from taobao_publish.protocol_media import build_upload_plan

    with pytest.raises(TaobaoPublishError) as error:
        build_upload_plan(_Item(tmp_path, main=[str(tmp_path / "不存在.jpg")]))
    assert "不存在" in str(error.value)


# ---------------------------------------------------------------------------
# 接线：stage 只在这个开关打开时给出钩子
# ---------------------------------------------------------------------------
def test_stage_hook_is_none_by_default(monkeypatch):
    from taobao_publish import stages

    monkeypatch.delenv("TAOBAO_MEDIA_ROUTE", raising=False)

    class _Ctx:
        pass

    assert stages._protocol_upload_hook(_Ctx()) is None


def test_stage_hook_is_callable_on_protocol(monkeypatch):
    from taobao_publish import stages

    monkeypatch.setenv("TAOBAO_MEDIA_ROUTE", "protocol")

    class _Ctx:
        pass

    hook = stages._protocol_upload_hook(_Ctx())
    assert callable(hook)


def test_stage_hook_rejects_unknown_route(monkeypatch):
    from taobao_publish import stages

    monkeypatch.setenv("TAOBAO_MEDIA_ROUTE", "mtop")

    class _Ctx:
        pass

    with pytest.raises(ValueError):
        stages._protocol_upload_hook(_Ctx())


def test_cdp_port_parsing_defaults_to_research_port():
    from taobao_publish import stages

    assert stages._cdp_port_from_url("http://127.0.0.1:9334/json/list") == 9334
    assert stages._cdp_port_from_url("http://127.0.0.1:9501/json/list") == 9501
    assert stages._cdp_port_from_url("") == 9334


# ---------------------------------------------------------------------------
# 上传回执账本（断点续传）
# ---------------------------------------------------------------------------
IDENT = {"path": r"C:\p\主图_01.jpg", "name": "tb_1_main_1_aaa.jpg", "sha256": "a" * 64}
RECEIPT = {"url": "https://img.alicdn.com/i1/aaa.jpg", "picture_id": "1"}


def test_ledger_records_and_reuses_after_restart(tmp_path):
    """被风控打断后重启进程：已传过的必须能复用，不再打平台。"""

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    first = UploadLedger.load(path)
    assert first.reuse([IDENT]) == {}
    first.record(IDENT, RECEIPT)
    assert path.is_file(), "登记后必须落盘，否则进程重启就丢"

    second = UploadLedger.load(path)
    reused = second.reuse([IDENT])
    assert reused[IDENT["name"]]["url"] == RECEIPT["url"]
    assert reused[IDENT["name"]]["uploaded_now"] is False, "复用不是本次上传"


def test_ledger_identity_includes_content_hash(tmp_path):
    """同名但内容变了不能复用——否则会拿旧图冒充新图。"""

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    ledger = UploadLedger.load(path)
    ledger.record(IDENT, RECEIPT)
    changed = dict(IDENT, sha256="b" * 64)
    assert ledger.reuse([changed]) == {}, "内容变了必须重传"


def test_ledger_rejects_non_https_record(tmp_path):
    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    ledger = UploadLedger.load(path)
    ledger.record(IDENT, {"url": "http://img.alicdn.com/i1/aaa.jpg", "picture_id": "1"})
    assert UploadLedger.load(path).reuse([IDENT]) == {}


def test_ledger_survives_corrupted_file(tmp_path):
    """账本坏了 → 当作空账本重来，但绝不静默使用坏数据。"""

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    path.write_text("{ not json", encoding="utf-8")
    ledger = UploadLedger.load(path)
    assert ledger.entries == {}
    assert ledger.reuse([IDENT]) == {}


def test_ledger_records_the_folder_and_only_reuses_a_matching_one(tmp_path):
    """**复用必须按目录校验**（E-284）。

    账本键是"文件名 + sha256"，**不含目录**。改成按用途分目录上传后，
    若复用不校验目录，旧版全部传在根层的回执会让这个改动**完全不生效**：
    平台上的图还在根层，程序却认为已经传好了——比报错更难发现。
    """

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    name = IDENT["name"]
    ledger = UploadLedger.load(path)
    ledger.record(IDENT, RECEIPT, folder_id="111")
    assert UploadLedger.load(path).entries[UploadLedger.key(IDENT)]["folder_id"] == "111"

    # 目录一致 → 复用
    assert name in UploadLedger.load(path).reuse([IDENT], {name: "111"})
    # 目录不同 → **不复用**，让它重传到正确目录
    assert UploadLedger.load(path).reuse([IDENT], {name: "222"}) == {}


def test_ledger_entry_without_folder_is_never_reused_when_destination_known(tmp_path):
    """旧账本条目没有 `folder_id` → 有目标目录时一律不复用，自动重传一次。

    这正是"修好结构上传后，历史散图会被搬到正确目录"的依据；
    不这么做，用户会看到"改了代码但图片还是散的"。
    """

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    name = IDENT["name"]
    # 模拟旧版账本：只有 url/picture_id，**没有 folder_id**
    path.write_text(
        json.dumps({"version": 1, "entries": {
            UploadLedger.key(IDENT): {
                "name": name, "sha256": IDENT["sha256"], "path": IDENT["path"],
                "url": RECEIPT["url"], "picture_id": RECEIPT["picture_id"],
            }}}, ensure_ascii=False),
        encoding="utf-8")

    ledger = UploadLedger.load(path)
    assert name in ledger.reuse([IDENT]), "不指定目标目录时维持原行为（兼容旧调用方）"
    assert ledger.reuse([IDENT], {name: "111"}) == {}, "指定了目标目录就必须校验，缺失即重传"


def test_ledger_reuse_without_destinations_keeps_old_behavior(tmp_path):
    """不给 `destinations` 时行为与改动前一致——避免影响其它调用方。"""

    from taobao_publish.protocol_media import UploadLedger

    path = tmp_path / "ledger.json"
    ledger = UploadLedger.load(path)
    ledger.record(IDENT, RECEIPT, folder_id="")
    assert IDENT["name"] in ledger.reuse([IDENT])


def test_default_pace_is_configurable_and_validated(monkeypatch):
    from taobao_publish.protocol_media import default_pace_seconds

    monkeypatch.delenv("TAOBAO_UPLOAD_PACE_SECONDS", raising=False)
    assert default_pace_seconds() > 0, "默认必须有间隔：风控是按频率触发的"
    monkeypatch.setenv("TAOBAO_UPLOAD_PACE_SECONDS", "0.5")
    assert default_pace_seconds() == 0.5
    monkeypatch.setenv("TAOBAO_UPLOAD_PACE_SECONDS", "0")
    assert default_pace_seconds() == 0.0, "显式设 0 表示不限速（自担风险）"
    monkeypatch.setenv("TAOBAO_UPLOAD_PACE_SECONDS", "abc")
    with pytest.raises(ValueError):
        default_pace_seconds()
    monkeypatch.setenv("TAOBAO_UPLOAD_PACE_SECONDS", "-1")
    with pytest.raises(ValueError):
        default_pace_seconds()


@pytest.mark.real_ledger_path
def test_ledger_path_follows_runtime_data_dir(tmp_path, monkeypatch):
    from taobao_publish.protocol_media import LEDGER_FILENAME, ledger_path

    monkeypatch.setenv("DOUYIN_DATA_DIR", str(tmp_path))
    assert ledger_path() == tmp_path / LEDGER_FILENAME


# ---------------------------------------------------------------------------
# 按回执 pictureId 精确选图（确定性选择的锚点）
# ---------------------------------------------------------------------------
def test_pick_by_id_expression_embeds_ids_and_select_flag():
    from taobao_publish.page import build_pick_media_by_id_expression

    expression = build_pick_media_by_id_expression(
        ["1114908854813672480", "1114908854729358410"], select=True)
    assert "1114908854813672480" in expression
    assert "1114908854729358410" in expression
    assert "select: true" in expression
    # 身份来源：checkbox 的 value（实测就是 pictureId）
    assert "checkbox" in expression and "value" in expression
    # 祖先 id 必须**先判形状**再采信（注释里提到滚动容器是说明，不算把容器当 ID）
    assert "/^\\d{10,}$/.test(rawValue)" in expression, "checkbox.value 必须先判是否像图片 ID"
    assert "if (/^\\d{10,}$/.test(candidate)) { id = candidate; break; }" in expression, (
        "祖先 id 只采信形如图片 ID 的值，否则会取到滚动容器（实测踩过）")
    assert expression.count("{{") + expression.count("}}") == 0


def test_pick_by_id_expression_rejects_empty_and_bad_card():
    from taobao_publish.page import build_pick_media_by_id_expression

    with pytest.raises(ValueError):
        build_pick_media_by_id_expression([])
    with pytest.raises(ValueError):
        build_pick_media_by_id_expression(["1"], card_selector="  ")


def test_pick_by_id_reports_missing_without_guessing():
    """ID 没渲染出来时**报缺失**，不能改成"按名字凑一张"。"""

    from taobao_publish import page as page_module
    from taobao_publish.page import MediaImageMissing

    class _Client:
        def evaluate(self, expression, **kwargs):
            return {"ok": True, "matched": 0, "missing": ["111"], "selected": []}

    with pytest.raises(MediaImageMissing):
        page_module.pick_media_by_id(_Client(), ["111"], context_id=1, select=True, wait=0)


def test_pick_by_id_refuses_ambiguous_hit():
    from taobao_publish import page as page_module
    from taobao_publish.page import CandidateNotFound

    class _Client:
        def evaluate(self, expression, **kwargs):
            return {"ok": False, "reason": "ambiguous", "matched": 2, "pictureId": "111"}

    with pytest.raises(CandidateNotFound):
        page_module.pick_media_by_id(_Client(), ["111"], context_id=1, select=True, wait=0)
