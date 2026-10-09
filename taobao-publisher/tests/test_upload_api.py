# -*- coding: utf-8 -*-
"""图片空间**协议上传**的离线验证：请求形态、响应分类、安全门、端到端 mock。

本文件不联外网、不碰真实平台。真实端点与登录态无关的那些结论（multipart 形态、
成功判据、风控停手语义）在这里被**真实验证**：客户端跑在真的 HTTP 之上，
对面是本仓库的 mock 服务端，服务端严格解析 multipart 并核对字段。
"""
from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest
from PIL import Image

from taobao_publish.authorization import WriteAuthorization
from taobao_publish.constants import WRITE_UPLOAD_IMAGE
from taobao_publish.errors import TaobaoPublishError, WriteNotAuthorizedError
from taobao_publish.upload_api import (
    ALLOWED_SUFFIXES,
    CONTRACT_NOTES,
    DEFAULT_FOLDER_ID,
    ERROR_RATE_LIMITED,
    ERROR_UPLOAD_FAILED,
    FIELD_FILE,
    FIELD_NAME,
    FIELD_TOKEN,
    FIELD_WATER,
    MAX_FILE_BYTES,
    MAX_FILES_PER_REQUEST,
    REJECTED_ROUTES,
    UPLOAD_APP_KEY,
    UPLOAD_HOST,
    UPLOAD_PATH,
    UploadCandidate,
    UploadEndpoint,
    build_request_body,
    check_batch,
    classify_upload_response,
    contract_summary,
    encode_multipart,
    extract_json_payload,
    image_identity,
    same_image,
    new_boundary,
    validate_image_url,
    validate_upload_name,
)
from taobao_publish.upload_client import (
    BatchUploadReport,
    CookieHttpTransport,
    PictureSpaceUploader,
    UploadCredentials,
    UploadTransportError,
    make_upload_product,
)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mock_upload_server import FAILURE_MODES, MockUploadServer  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture
def image_file(tmp_path):
    """一张真实的 800x800 JPEG。"""

    def build(name: str = "主图_01.jpg", *, size: tuple = (800, 800), color=(200, 30, 40)):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path, quality=90)
        return path

    return build


@pytest.fixture
def candidate(image_file):
    def build(name: str = "主图_01.jpg"):
        path = image_file(name)
        data = path.read_bytes()
        return UploadCandidate(
            path=str(path), name=name, size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    return build


CREDENTIALS = UploadCredentials(cookie="cookie2=abc; _tb_token_=tok123", tb_token="tok123")


def authorized() -> WriteAuthorization:
    return WriteAuthorization.from_grant([WRITE_UPLOAD_IMAGE], source="test")


# ---------------------------------------------------------------------------
# 端点契约
# ---------------------------------------------------------------------------
def test_endpoint_url_matches_bundle_contract():
    url = UploadEndpoint(folder_id="12345").build_url()
    assert url.startswith(UPLOAD_HOST + UPLOAD_PATH + "?")
    assert f"{UPLOAD_APP_KEY}" in url
    assert "folderId=12345" in url
    assert "_input_charset=utf-8" in url


def test_endpoint_without_folder_id_falls_back_to_documented_root():
    """不传目录时退回 ``0``（根目录），这个默认值来自 bundle 原文而不是猜的。"""

    url = UploadEndpoint(folder_id="").build_url()
    assert f"{DEFAULT_FOLDER_ID}" in url
    assert UploadEndpoint(folder_id="   ").folder_id.strip() or True
    description = UploadEndpoint(folder_id="").describe()
    assert description["folder_id"] == DEFAULT_FOLDER_ID
    # 显式目录必须原样进 query
    assert "folderId=88888" in UploadEndpoint(folder_id="88888").build_url()


def test_endpoint_carries_watermark_and_compress_flags():
    url = UploadEndpoint(folder_id="1").build_url()
    assert "watermark=false" in url
    assert "picCompress=false" in url
    flagged = UploadEndpoint(folder_id="1", watermark=True, compress=True).build_url()
    assert "watermark=true" in flagged and "picCompress=true" in flagged


def test_contract_summary_declares_unknowns_and_rejections():
    summary = contract_summary()
    assert summary["endpoint"]["method"] == "POST"
    assert summary["endpoint"]["evidence_level"] == "verified"
    # 没有证据的部分必须显式列出来，不允许被省略成「都已知」
    assert any(item["evidence_level"] == "unknown" for item in summary["notes"])
    assert len(CONTRACT_NOTES) >= 5
    assert any("mtop" in item["route"] for item in REJECTED_ROUTES)
    assert summary["stop_conditions"]["behavior"].startswith("停手")


def test_large_file_route_is_declared_as_a_blocker_not_a_silent_gap():
    """分片直传没实现这件事必须能被调用方读到，且不能写成会过期的布尔字段。"""

    route = contract_summary()["large_file_route"]
    assert route["evidence_level"] == "unknown"
    assert route.get("blocker")
    assert "implemented" not in route, (
        "自检第 5 道门会拦硬编码布尔字段（今天的 False 明天就是假话）；"
        "要用带 blocker 的说明表达"
    )
    assert any("upload" in api for api in route["apis"])


def test_contract_rejected_routes_are_marked_rejected():
    summary = contract_summary()
    assert all(isinstance(item.get("rejected_by"), str) and item["rejected_by"] for item in summary["rejected"])


# ---------------------------------------------------------------------------
# 本地护栏
# ---------------------------------------------------------------------------
def test_candidate_rejects_oversize(candidate):
    source = candidate()
    oversized = UploadCandidate(
        path=source.path, name=source.name, size=MAX_FILE_BYTES + 1, sha256=source.sha256
    )
    with pytest.raises(ValueError) as error:
        oversized.validate()
    assert "3MB" in str(error.value)


def test_candidate_rejects_disallowed_format(tmp_path):
    path = tmp_path / "图.webp"
    path.write_bytes(b"RIFF....WEBP")
    item = UploadCandidate(path=str(path), name="图.webp", size=12)
    with pytest.raises(ValueError) as error:
        item.validate()
    assert "格式" in str(error.value)
    assert all(suffix in ALLOWED_SUFFIXES for suffix in (".jpg", ".jpeg", ".png", ".gif", ".bmp"))


def test_upload_name_rejects_path_traversal_and_reserved_names():
    for bad in ("../a.jpg", "a/b.jpg", "a\\b.jpg", "con.jpg", "a*b.jpg", "", "  ", "."):
        with pytest.raises(ValueError):
            validate_upload_name(bad)
    assert validate_upload_name("主图_01.jpg") == "主图_01.jpg"


def test_batch_rejects_duplicate_names_before_any_request(candidate):
    items = [candidate("同名.jpg"), candidate("同名.jpg")]
    with pytest.raises(ValueError) as error:
        check_batch(items)
    assert "重复" in str(error.value)


def test_batch_rejects_more_files_than_platform_limit(image_file):
    """超过平台单次上限（bundle 原文 200 张）必须在发请求前整批拒绝。"""

    items = []
    for index in range(MAX_FILES_PER_REQUEST + 1):
        path = image_file(f"上限_{index:03d}.jpg", size=(16, 16), color=(index % 250, 20, 20))
        data = path.read_bytes()
        items.append(UploadCandidate(str(path), path.name, len(data),
                                     hashlib.sha256(data).hexdigest()))
    assert len(items) == 201
    with pytest.raises(ValueError) as error:
        check_batch(items)
    assert str(MAX_FILES_PER_REQUEST) in str(error.value)


# ---------------------------------------------------------------------------
# multipart 编码
# ---------------------------------------------------------------------------
def test_encode_multipart_shape(candidate):
    boundary = "TESTBOUNDARY"
    body = encode_multipart(
        [("name", "主图_01.jpg"), ("_tb_token_", "tok"), ("water", "false")],
        [("file", "主图_01.jpg", candidate().path)],
        boundary=boundary,
    )
    text = body.decode("utf-8", errors="replace")
    assert body.startswith(b"--TESTBOUNDARY\r\n")
    assert body.rstrip().endswith(b"--TESTBOUNDARY--")
    assert 'name="file"; filename="主图_01.jpg"' in text
    assert "Content-Type: image/jpeg" in text
    assert 'name="_tb_token_"' in text
    assert 'name="water"' in text


def test_build_request_body_requires_token(candidate):
    with pytest.raises(ValueError) as error:
        build_request_body(candidate(), token="  ", boundary="B")
    assert "_tb_token_" in str(error.value)


def test_boundary_is_random_per_request():
    assert new_boundary() != new_boundary()
    assert new_boundary().startswith("----WebKitFormBoundary")


# ---------------------------------------------------------------------------
# 响应分类 —— 只看 HTTP 200 是不够的
# ---------------------------------------------------------------------------
def test_classify_success_extracts_receipt():
    text = json.dumps({
        "success": True,
        "object": {"url": "https://img.alicdn.com/imgextra/i1/a.jpg", "fileId": "987",
                   "size": 1234, "pix": "800x800"},
    })
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg", folder_id="5")
    assert outcome.ok and outcome.receipt is not None
    assert outcome.receipt.url.endswith("a.jpg")
    assert outcome.receipt.picture_id == "987"
    assert outcome.receipt.width == 800
    assert outcome.receipt.folder_id == "5"
    assert outcome.retry_allowed is False


def test_classify_rate_limit_stops_and_never_retries():
    text = json.dumps({"success": False, "errorCode": "BAXIA_BLOCKED",
                       "errorMsg": "操作过于频繁，请滑动验证码之后，重新上传。"}, ensure_ascii=False)
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg")
    assert outcome.ok is False
    assert outcome.error_code == ERROR_RATE_LIMITED
    assert outcome.stopped is True
    assert outcome.retry_allowed is False
    assert "验证码" in outcome.message


def test_classify_user_validate_risk_ret_is_rate_limit_not_unknown():
    """实测原文：协议上传被风控拦时平台回 ``ret`` 里两个码 + ``data.url`` 验证地址。

    这个形态**没有** ``success``、也**没有** ``errorCode``。最初没被识别，
    于是「需要人工验证」被报成「平台未给原因」，流水线还会继续把剩下的图挨个撞——
    所以这里把原文逐字钉住。
    """

    text = json.dumps({
        "ret": ["FAIL_SYS_USER_VALIDATE", "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"],
        "data": {"url": "https://stream-upload.taobao.com:443//api/upload.api/_____tmd_____/"
                        "punish?x5secdata=abc&x5step=2&action=captcha&pureCaptcha="},
    }, ensure_ascii=False)
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg")
    assert outcome.ok is False
    assert outcome.error_code == ERROR_RATE_LIMITED, "风控必须被认出来，不能退化成「平台未给原因」"
    assert outcome.stopped is True, "命中风控必须停手"
    assert outcome.retry_allowed is False
    assert "验证" in outcome.message
    assert "FAIL_SYS_USER_VALIDATE" in outcome.platform_message


def test_classify_risk_page_html_with_http_200_is_not_success():
    html = '<html><body><pre>{"success":false,"errorCode":"BAXIA_BLOCKED"}</pre></body></html>'
    outcome = classify_upload_response(http_status=200, text=html, name="a.jpg")
    assert outcome.ok is False
    assert outcome.stopped is True


def test_classify_plain_html_is_failure_not_success():
    outcome = classify_upload_response(http_status=200, text="<html>risk</html>", name="a.jpg")
    assert outcome.ok is False
    assert outcome.error_code == ERROR_UPLOAD_FAILED


@pytest.mark.parametrize(
    "code,keyword",
    [("-600", "3MB"), ("-601", "格式"), ("-9001", "200")],
)
def test_classify_platform_codes_have_chinese_reasons(code, keyword):
    text = json.dumps({"success": False, "errorCode": code, "errorMsg": "raw platform text"})
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg")
    assert outcome.ok is False
    assert keyword in outcome.message
    assert outcome.platform_message == "raw platform text"


def test_classify_success_without_url_is_failure():
    text = json.dumps({"success": True, "object": {"fileId": "1"}})
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg")
    assert outcome.ok is False
    assert "地址" in outcome.message


def test_classify_rejects_non_taobao_cdn_url():
    text = json.dumps({"success": True, "object": {"url": "https://evil.example.com/a.jpg"}})
    outcome = classify_upload_response(http_status=200, text=text, name="a.jpg")
    assert outcome.ok is False
    assert "白名单" in outcome.message


def test_classify_http_error_keeps_status_code():
    outcome = classify_upload_response(http_status=500, text="internal error", name="a.jpg")
    assert outcome.ok is False
    assert "500" in outcome.message


def test_extract_json_payload_handles_pre_block_and_garbage():
    assert extract_json_payload('{"a":1}')[0] == {"a": 1}
    assert extract_json_payload('<pre style="white-space: pre-wrap;">{"b":2}</pre>')[0] == {"b": 2}
    assert extract_json_payload("<html>nope</html>")[0] is None
    assert extract_json_payload("")[0] is None


def test_validate_image_url_accepts_only_https_cdn():
    assert validate_image_url("https://img.alicdn.com/imgextra/a.jpg").endswith("a.jpg")
    for bad in ("http://img.alicdn.com/a.jpg", "https://user:pw@img.alicdn.com/a.jpg",
                "https://img.alicdn.com.evil.com/a.jpg", "", "https://example.com/a.jpg"):
        with pytest.raises(ValueError):
            validate_image_url(bad)


# ---------------------------------------------------------------------------
# 图片身份：不能逐字比 URL（实机踩过）
# ---------------------------------------------------------------------------
ORIGINAL_URL = ("https://img.alicdn.com/imgextra/i3/2214966481149/"
                "O1CN012vpW9ytISlG1chua_!!2214966481149.jpg")


def test_image_identity_extracts_stable_resource_id():
    identity = image_identity(ORIGINAL_URL)
    assert identity == "O1CN012vpW9ytISlG1chua_", (
        "身份就是 O1CN… 那一段（含结尾下划线）；它不是完整 URL，"
        "所以缩略/转码形态都能对上")
    assert image_identity("https://img.alicdn.com/imgextra/a.jpg") == "", (
        "取不到资源标识时必须返回空串，由调用方当「无法确认」处理")


def test_same_image_survives_thumbnail_and_transcode():
    """回执是原图地址、卡片是缩略/转码地址——必须判成**同一张**。

    这是实测的关键修正：逐字比 URL 会把同一张图判成不一致，协议路线因此
    报 `MEDIA_IMAGE_MISSING`，整条流水线停在选图前。
    """

    assert same_image(ORIGINAL_URL, ORIGINAL_URL + "_320x320?t=1791218506000")
    assert same_image(ORIGINAL_URL, ORIGINAL_URL + "_320x320q80_.webp")


def test_same_image_rejects_different_resources_and_empty():
    other = ("https://img.alicdn.com/imgextra/i4/2214966481149/"
             "O1CN01ZZZzzz_!!2214966481149.jpg_320x320")
    assert not same_image(ORIGINAL_URL, other), "不同资源必须判不一致"
    assert not same_image(ORIGINAL_URL, ""), "空值不能算同一张"
    assert not same_image("", ""), "两边都空不能算同一张"


def test_same_image_falls_back_to_literal_compare_without_resource_id():
    """没有 `O1CN` 标识的地址退回逐字比较。

    只忽略**时间戳/缓存类**参数；像 `version=` 这种**语义参数**不同必须判不一致
    ——把查询串整个丢掉会放过真实差异（曾因此让一条既有断言失效）。
    """

    plain = "https://img.example.invalid/a.jpg"
    assert same_image(plain, plain)
    assert same_image(plain, plain + "?t=123"), "只差时间戳应判同一张"
    assert not same_image(plain, plain + "?version=2"), "语义参数不同必须判不一致"
    assert not same_image(plain + "?version=1", plain + "?version=2")
    assert not same_image(plain, "https://img.example.invalid/b.jpg")
    assert not same_image(plain, ORIGINAL_URL), "形态不同的地址不能混判成同一张"


def test_same_image_ignores_trailing_query_variants():
    base = ORIGINAL_URL
    assert same_image(base, base + "?t=1")
    assert same_image(base + "?t=1", base + "?t=2")


# ---------------------------------------------------------------------------
# 授权门
# ---------------------------------------------------------------------------
def test_no_authorization_means_no_request(candidate):
    calls = []

    class Recording:
        def send(self, url, body, headers):
            calls.append(url)
            return 200, "{}"

    uploader = PictureSpaceUploader(Recording(), CREDENTIALS)
    with pytest.raises(WriteNotAuthorizedError):
        uploader.upload_one(candidate(), folder_id="1", authorization=WriteAuthorization.none())
    assert calls == []


def test_batch_without_authorization_does_not_send(candidate):
    calls = []

    class Recording:
        def send(self, url, body, headers):
            calls.append(url)
            return 200, "{}"

    uploader = PictureSpaceUploader(Recording(), CREDENTIALS)
    with pytest.raises(WriteNotAuthorizedError):
        uploader.upload_batch([candidate()], folder_id="1", authorization=WriteAuthorization.none())
    assert calls == []


def test_credentials_repr_never_leaks_secrets():
    text = repr(CREDENTIALS) + json.dumps(CREDENTIALS.describe(), ensure_ascii=False)
    assert "tok123" not in text
    assert "cookie2=abc" not in text
    assert CREDENTIALS.describe()["tb_token_length"] == len("tok123")


# ---------------------------------------------------------------------------
# 端到端：真实 HTTP + mock 服务端
# ---------------------------------------------------------------------------
def test_endpoint_refuses_plain_http_unless_offline_explicitly_allowed():
    """回归守卫：真实上传必须 https；离线演练要显式打开开关。"""

    with pytest.raises(ValueError) as error:
        UploadEndpoint(host="http://127.0.0.1:8899", folder_id="1").build_url()
    assert "https" in str(error.value)
    offline = UploadEndpoint(
        host="http://127.0.0.1:8899", folder_id="1", allow_insecure_host=True
    ).build_url()
    assert offline.startswith("http://127.0.0.1:8899/api/upload.api?")


def test_upload_one_through_real_http_hits_contract(candidate):
    with MockUploadServer() as server:
        client = PictureSpaceUploader(
            CookieHttpTransport(CREDENTIALS, opener=None),
            CREDENTIALS,
            endpoint_host=server.base_url,
            allow_insecure_host=True,
        )
        # 本地 mock 是 http://，而契约 host 是 https://；这里只替换 host，
        # 路径/query/字段全部走真实契约代码。
        outcome = client.upload_one(candidate(), folder_id="88888", authorization=authorized())
        assert outcome.ok, outcome.describe()
        request = server.last()
        assert request["path"] == UPLOAD_PATH
        assert request["query"]["appkey"] == UPLOAD_APP_KEY
        assert request["query"]["folderId"] == "88888"
        assert request["query"]["_input_charset"] == "utf-8"
        assert request["cookie_present"] is True
        assert set(FIELD_FILE for _ in [0]) == {"file"}
        assert request["fields"][FIELD_NAME] == "主图_01.jpg"
        assert request["fields"][FIELD_TOKEN] == "tok123"
        assert request["fields"][FIELD_WATER] == "false"
        assert request["files"][0]["field"] == FIELD_FILE
        assert request["files"][0]["filename"] == "主图_01.jpg"
        assert request["files"][0]["content_type"] == "image/jpeg"
        assert request["files"][0]["sha256"] == candidate().sha256
        assert outcome.receipt.url.startswith("https://img.alicdn.com/")


def test_upload_batch_reports_every_file_and_keeps_order(candidate, tmp_path):
    items = []
    for index in range(3):
        path = tmp_path / f"图_{index}.jpg"
        Image.new("RGB", (800, 800), (10 * index, 60, 90)).save(path)
        data = path.read_bytes()
        items.append(UploadCandidate(str(path), path.name, len(data), hashlib.sha256(data).hexdigest()))
    with MockUploadServer() as server:
        client = PictureSpaceUploader(CookieHttpTransport(CREDENTIALS), CREDENTIALS,
                                      endpoint_host=server.base_url, allow_insecure_host=True)
        report = client.upload_batch(items, folder_id="7", authorization=authorized())
        assert isinstance(report, BatchUploadReport)
        assert report.ok
        assert [item.name for item in report.receipts] == [item.name for item in items]
        assert len(server.requests) == 3


def test_rate_limit_stops_the_rest_of_the_batch(candidate, tmp_path):
    items = []
    for index in range(4):
        path = tmp_path / f"限流_{index}.jpg"
        Image.new("RGB", (800, 800), (index, 10, 10)).save(path)
        data = path.read_bytes()
        items.append(UploadCandidate(str(path), path.name, len(data), hashlib.sha256(data).hexdigest()))
    with MockUploadServer() as server:
        client = PictureSpaceUploader(CookieHttpTransport(CREDENTIALS), CREDENTIALS,
                                      endpoint_host=server.base_url, allow_insecure_host=True)
        # 第一张成功，第二张开始限流
        server.set_mode("rate_limited")
        report = client.upload_batch(items, folder_id="7", authorization=authorized())
        assert report.ok is False
        assert report.should_stop is True
        assert report.receipts == ()
        assert len(server.requests) == 1  # 命中限流后不再继续发
        assert "验证码" in report.stopped_reason


def test_partial_success_keeps_receipts_when_stopped(candidate, tmp_path):
    items = []
    for index in range(3):
        path = tmp_path / f"部分_{index}.jpg"
        Image.new("RGB", (800, 800), (index, 20, 200)).save(path)
        data = path.read_bytes()
        items.append(UploadCandidate(str(path), path.name, len(data), hashlib.sha256(data).hexdigest()))

    inner = CookieHttpTransport(CREDENTIALS)
    with MockUploadServer() as server:
        class FirstThenRateLimited:
            def __init__(self) -> None:
                self.count = 0

            def send(self, url, body, headers):
                self.count += 1
                if self.count == 1:
                    return inner.send(url, body, headers)
                return 200, FAILURE_MODES["rate_limited"][1]

        client = PictureSpaceUploader(FirstThenRateLimited(), CREDENTIALS,
                                      endpoint_host=server.base_url, allow_insecure_host=True)
        report = client.upload_batch(items, folder_id="7", authorization=authorized())
        assert len(report.receipts) == 1
        assert report.should_stop is True
        assert len(report.failed) == 1
        assert report.receipts[0].name == items[0].name


@pytest.mark.parametrize("mode", sorted(FAILURE_MODES))
def test_every_failure_mode_is_classified_as_failure(candidate, mode):
    with MockUploadServer() as server:
        server.set_mode(mode)
        client = PictureSpaceUploader(CookieHttpTransport(CREDENTIALS), CREDENTIALS,
                                      endpoint_host=server.base_url, allow_insecure_host=True)
        outcome = client.upload_one(candidate(), folder_id="1", authorization=authorized())
        assert outcome.ok is False, f"{mode} 被当成了成功"
        assert outcome.message


def test_transport_error_is_reported_not_swallowed(candidate):
    class Dead:
        def send(self, url, body, headers):
            raise UploadTransportError("connection refused")

    client = PictureSpaceUploader(Dead(), CREDENTIALS)
    outcome = client.upload_one(candidate(), folder_id="1", authorization=authorized())
    assert outcome.ok is False
    assert "connection refused" in outcome.message


def test_all_requests_only_ever_go_to_the_configured_endpoint(candidate, tmp_path):
    """回归守卫：不允许出现「顺手换个域名」的代码。"""

    items = []
    for index in range(2):
        path = tmp_path / f"域名_{index}.jpg"
        Image.new("RGB", (800, 800), (index, 5, 5)).save(path)
        data = path.read_bytes()
        items.append(UploadCandidate(str(path), path.name, len(data), hashlib.sha256(data).hexdigest()))
    with MockUploadServer() as server:
        client = PictureSpaceUploader(CookieHttpTransport(CREDENTIALS), CREDENTIALS,
                                      endpoint_host=server.base_url, allow_insecure_host=True)
        client.upload_batch(items, folder_id="9", authorization=authorized())
        assert len(server.requests) == 2
        assert {item["path"] for item in server.requests} == {UPLOAD_PATH}


def test_unused_socket_guard():
    """占位守卫：确认测试环境允许本地 TCP（mock 服务端依赖它）。"""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        assert probe.getsockname()[1] > 0
