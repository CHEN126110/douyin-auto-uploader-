# -*- coding: utf-8 -*-
"""图片空间 mtop 目录/文件接口的离线验证：请求形态、字段解析、定位规则。

这些 api 的**名字与入参**来自生产 bundle 原文（``verified``），
但真实 version / 网关 / 响应字段名尚未实测（``candidate``）。
所以本文件只验证「我们拼出去的请求长什么样」与「遇到不认识的结构会如实报错」——
不验证远端行为。真实行为由 `scripts/probe-image-space-upload.py` 在登录态下取证。
"""
from __future__ import annotations

import json

import pytest

from taobao_publish.mtop import H5_APP_KEY_DEFAULT, classify_response, sign
from taobao_publish.picturecenter import (
    ALL_IMAGES_NODE,
    PICTURECENTER_EVIDENCE,
    build_directory_add,
    build_directory_query,
    build_file_query,
    all_images_folder,
    contract_summary,
    find_folder_by_path,
    folder_id_from_add_response,
    parse_directory_tree,
    parse_files,
)
from taobao_publish.upload_api import (
    MTOP_API_DIR_ADD,
    MTOP_API_DIR_QUERY,
    MTOP_API_FILE_QUERY,
)

TOKEN = "0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------------------
# 请求构造
# ---------------------------------------------------------------------------
def test_directory_query_request_shape():
    request = build_directory_query(TOKEN, timestamp_ms="1700000000000")
    assert request.api == MTOP_API_DIR_QUERY
    url = request.request.url
    assert MTOP_API_DIR_QUERY in url
    assert f"appKey={H5_APP_KEY_DEFAULT}" in url
    assert sign(TOKEN, "1700000000000", H5_APP_KEY_DEFAULT, request.request.data_str) in url
    # 实测：真实页面调 dir.query 时 data 是空对象（不是 {"clientType":0}）
    assert request.evidence_level == PICTURECENTER_EVIDENCE


def test_directory_add_requires_parent_and_name():
    with pytest.raises(ValueError):
        build_directory_add(TOKEN, parent_id="", name="商品A")
    with pytest.raises(ValueError):
        build_directory_add(TOKEN, parent_id="1", name="  ")
    request = build_directory_add(TOKEN, parent_id="1", name="商品A", timestamp_ms="1700000000000")
    assert request.api == MTOP_API_DIR_ADD
    assert json.loads(request.request.data_str) == {"dirId": "1", "name": "商品A"}


def test_file_query_matches_measured_params():
    """入参按**实测**对齐（见 tmp/live-directory-headers.json 的 data_keys）。"""

    request = build_file_query(TOKEN, folder_id="888", page=2, timestamp_ms="1700000000000")
    data = json.loads(request.request.data_str)
    assert request.api == MTOP_API_FILE_QUERY
    for key in ("catId", "page", "orderBy", "deleted", "status", "ignoreCat",
                "clientType", "type"):
        assert key in data, key
    assert "pageSize" not in data, "实测真实调用没有 pageSize；多带会偏离实测形态"
    assert "key" not in data, "只在有关键词时才带 key"
    assert data["catId"] == "888"
    assert data["page"] == 2
    assert data["deleted"] == 0 and data["status"] == 0


def test_file_query_carries_keyword_only_when_given():
    with_keyword = json.loads(
        build_file_query(TOKEN, folder_id="1", keyword="主图", timestamp_ms="1700000000000").request.data_str
    )
    assert with_keyword["key"] == "主图"


def test_browser_request_shape_matches_measurement():
    """回归守卫：这三个参数实测缺一不可，改了就会重演 ILLEGAL_ACCESS。"""

    from urllib.parse import parse_qs, urlsplit

    request = build_directory_query(TOKEN, ttid="123@taobao_WEB_7.0.0", timestamp_ms="1700000000000")
    query = {key: values[0] for key, values in parse_qs(urlsplit(request.request.url).query).items()}
    assert query["dataType"] == "originaljsonp", "实测 dataType=originaljsonp（写成 jsonp 会被拒）"
    assert query["type"] == "originaljsonp"
    assert "timeout" not in query, "实测真实调用不带 timeout"
    assert query["ttid"] == "123@taobao_WEB_7.0.0"
    assert query["callback"].startswith("mtopjsonp"), "实测回调名是全小写 mtopjsonp<N>"
    assert query["data"] == "{}", "实测 dir.query 的 data 是空对象"


def test_file_query_rejects_bad_input():
    with pytest.raises(ValueError):
        build_file_query(TOKEN, folder_id="")
    with pytest.raises(ValueError):
        build_file_query(TOKEN, folder_id="1", page=0)
    with pytest.raises(ValueError):
        build_file_query(TOKEN, folder_id="1", page="1")  # type: ignore[arg-type]


def test_contract_summary_declares_unknowns():
    summary = contract_summary()
    apis = {item["api"] for item in summary["apis"]}
    assert apis == {MTOP_API_DIR_QUERY, MTOP_API_DIR_ADD, MTOP_API_FILE_QUERY}
    assert summary["unknown"], "未实测的项必须列出来，不能被省略"
    assert all(item["overall_evidence"] == PICTURECENTER_EVIDENCE for item in summary["apis"])


# ---------------------------------------------------------------------------
# 目录树解析
# ---------------------------------------------------------------------------
TREE_PAYLOAD = {
    "api": MTOP_API_DIR_QUERY,
    "ret": ["SUCCESS::调用成功"],
    "data": {
        "dirs": [
            {
                "pictureCategoryId": "100",
                "name": ALL_IMAGES_NODE,
                "children": [
                    {"pictureCategoryId": "200", "name": "商品A",
                     "children": [
                         {"pictureCategoryId": "201", "name": "主图"},
                         {"pictureCategoryId": "202", "name": "SKU"},
                     ]},
                    {"pictureCategoryId": "300", "name": "商品B", "children": []},
                ],
            }
        ]
    },
}


def test_parse_directory_tree_builds_hierarchy():
    root, note = parse_directory_tree(TREE_PAYLOAD)
    assert note == "ok"
    assert root is not None
    assert root.name == ALL_IMAGES_NODE
    paths = {"/".join(node.name for node in [root] + []) for node in []}
    product = find_folder_by_path(root, [ALL_IMAGES_NODE, "商品A"])
    assert product is not None and product.folder_id == "200"
    main = find_folder_by_path(root, [ALL_IMAGES_NODE, "商品A", "主图"])
    assert main is not None and main.folder_id == "201"
    assert all_images_folder(root) is not None
    assert all_images_folder(root).folder_id == "100"


def test_find_folder_by_path_requires_full_path_not_first_name_hit():
    """图片空间允许同名目录；按名字取第一个就会传错商品目录。"""

    payload = {"data": {"dirs": [
        {"pictureCategoryId": "1", "name": ALL_IMAGES_NODE, "children": [
            {"pictureCategoryId": "10", "name": "商品A", "children": [
                {"pictureCategoryId": "11", "name": "主图"}]},
            {"pictureCategoryId": "20", "name": "商品B", "children": [
                {"pictureCategoryId": "21", "name": "主图"}]},
        ]},
    ]}}
    root, _ = parse_directory_tree(payload)
    assert find_folder_by_path(root, [ALL_IMAGES_NODE, "商品A", "主图"]).folder_id == "11"
    assert find_folder_by_path(root, [ALL_IMAGES_NODE, "商品B", "主图"]).folder_id == "21"
    # 路径不存在时必须返回 None，不能退化成「差不多就选一个」
    assert find_folder_by_path(root, [ALL_IMAGES_NODE, "商品C"]) is None
    assert find_folder_by_path(root, [ALL_IMAGES_NODE, "主图"]) is None


def test_parse_directory_tree_reports_unknown_shape_with_real_keys():
    root, note = parse_directory_tree({"data": {"weirdKey": [1, 2]}})
    assert root is None
    assert "weirdKey" in note, "必须把实际键名报出来，否则无法据实调整解析器"


def test_parse_directory_tree_empty_is_not_a_folder():
    root, note = parse_directory_tree({"data": {"dirs": []}})
    assert root is None
    assert "目录" in note


def test_parse_directory_tree_handles_multiple_roots():
    payload = {"data": {"dirs": [
        {"pictureCategoryId": "1", "name": "根A"},
        {"pictureCategoryId": "2", "name": "根B"},
    ]}}
    root, note = parse_directory_tree(payload)
    assert note == "ok"
    assert root is not None and len(root.children) == 2
    assert root.folder_id == "", "多根时用匿名根，避免假装只有一个根"


# ---------------------------------------------------------------------------
# 文件清单解析
# ---------------------------------------------------------------------------
def test_parse_files_reads_bundle_field_names():
    payload = {"data": {"fileModule": [
        {"pictureId": "9", "name": "主图_01.jpg",
         "fullUrl": "https://img.alicdn.com/imgextra/i1/主图_01.jpg",
         "catId": "201", "pixel": "800x800", "status": "0"},
    ]}}
    files, note = parse_files(payload)
    assert note == "ok"
    assert len(files) == 1
    assert files[0].picture_id == "9"
    assert files[0].full_url.startswith("https://img.alicdn.com/")
    assert files[0].folder_id == "201"


def test_parse_files_unknown_shape_reports_keys():
    files, note = parse_files({"data": {"oops": []}})
    assert files == ()
    assert "oops" in note


def test_parse_files_skips_items_without_identity():
    payload = {"data": {"files": [
        {"name": "没有 ID.jpg"},
        {"pictureId": "1", "name": "正常.jpg", "fullUrl": "https://img.alicdn.com/a.jpg"},
    ]}}
    files, _ = parse_files(payload)
    assert [item.name for item in files] == ["正常.jpg"]


# ---------------------------------------------------------------------------
# dir.add 响应 → folderId
# ---------------------------------------------------------------------------
def test_folder_id_from_add_response_reads_nested_node():
    text = json.dumps({
        "ret": ["SUCCESS::调用成功"],
        "data": {"jsPictureCategoryDO": {"pictureCategoryId": 555, "name": "商品A"}},
    }, ensure_ascii=False)
    folder_id, response = folder_id_from_add_response(text)
    assert response.ok
    assert folder_id == "555"


def test_folder_id_from_add_response_fails_loudly_when_missing():
    text = json.dumps({"ret": ["SUCCESS::调用成功"], "data": {"something": 1}})
    folder_id, response = folder_id_from_add_response(text)
    assert response.ok is True
    assert folder_id == "", "拿不到目录 ID 时必须为空，调用方据此停下，不能传默认目录"


def test_folder_id_from_add_response_propagates_platform_failure():
    text = json.dumps({"ret": ["FAIL_SYS_SESSION_EXPIRED::Session过期"]}, ensure_ascii=False)
    folder_id, response = folder_id_from_add_response(text)
    assert folder_id == ""
    assert response.ok is False
    assert response.error_code == "LOGIN_REQUIRED"


def test_classify_response_still_handles_gateway_ret():
    """回归守卫：picturecenter 用的是既有 mtop 分类器，不另起一套。"""

    response = classify_response(json.dumps({"ret": ["FAIL_SYS_SESSION_EXPIRED::Session过期"]}))
    assert response.error_code == "LOGIN_REQUIRED"
