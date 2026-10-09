#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只读探针：淘宝图片空间「上传」端点取证。

两条路线，全部只读：

* **路线 A（静态分析，不需要浏览器、不需要登录）**
  1. HTTP GET 公开应用外壳 `market.m.taobao.com/app/crs-qn/sucai-selector-ng/index`
     （发布页素材中心 iframe 就是它）与 `sucai.taobao.com` / `sc.taobao.com`；
  2. 抽出其中的 JS bundle（`g.alicdn.com` / `o.alicdn.com`）并下载文本；
  3. 从 bundle 里发现**微模块**（`MicroLoader` 的
     `https://{cdnHost}/merchant-micro-mods/{name}/{version}/js/remoteEntry.js`），
     反解 webpack runtime 的 `r.u=`（chunk 名 + hash 映射）得到全部 chunk URL；
  4. 在全部文本里正则搜索上传端点线索，命中处记录**前后各 200 字符上下文**。

* **路线 B（CDP 被动观察，需要 9334 调试 Chrome 已在跑）**
  `Network.enable` 后被动记录页面自己发出的请求，**只保留
  `host + path（去 query）+ method + content-type`**，不记录任何 header / cookie /
  postData 原值；不点击、不上传、不提交。

红线（见 `taobao-publisher/AGENTS.md` §1）：

1. 只会发 HTTP **GET**（CDP 侧只有 `Network.enable` / `Page.enable` /
   `Page.navigate` / `Runtime.evaluate` 读 `location.href`），没有任何写路径。
2. **不发送 cookie**，不带登录态，不做登录 / 验证码 / 风控绕过。
3. 同一 host 两次请求间隔 ≥ `--min-interval`（默认 1 秒），总请求数 ≤ `--max-requests`。
4. 原始产物落 `tmp/`；进 `captures/` 必须再跑
   `python -m taobao_publish sanitize <raw> <out>`。

用法（从仓库根或 `taobao-publisher/` 都能跑）：

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
python taobao-publisher/scripts/probe-image-space-upload-endpoint.py --route a
python taobao-publisher/scripts/probe-image-space-upload-endpoint.py --route b --cdp-port 9334
python taobao-publisher/scripts/probe-image-space-upload-endpoint.py --route all
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PACKAGE_ROOT = _SCRIPT_DIR.parent  # taobao-publisher/
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from taobao_publish.sanitize import (  # noqa: E402  （路径注入必须在导入之前）
    CAPTURE_FORBIDDEN_MARKERS,
    REDACTED,
    SENSITIVE_COOKIE_NAMES,
    SENSITIVE_HEADER_NAMES,
    SENSITIVE_QUERY_KEYS,
    contains_secret_like,
    sanitize_payload,
    sanitize_text,
    sanitize_url,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 应用外壳（公开可访问，2026-10-05 实测 200，title=图片选择器）。
SUCAI_SELECTOR_NG = (
    "https://market.m.taobao.com/app/crs-qn/sucai-selector-ng/index?type=pic&realtime=true"
)

#: 发布页素材中心 iframe 的 URL 提示（与 page.MEDIA_IFRAME_URL_HINT 一致）。
MEDIA_IFRAME_HINT = "sucai-selector-ng"

#: 路线 A 种子页。每个只 GET 一次。
ROUTE_A_SEEDS: Tuple[Dict[str, str], ...] = (
    {"name": "sucai_selector_ng_shell", "url": SUCAI_SELECTOR_NG, "expect": "publish_page_media_iframe_app"},
    {"name": "sucai_home", "url": "https://sucai.taobao.com/", "expect": "wangpu_sucai_library_not_picture_space"},
    {"name": "sc_home", "url": "https://sc.taobao.com/", "expect": "unverified_alias"},
)

#: 路线 B 的观察目标：① 发布工作台（确认登录态）② 素材中心 App（拿真实请求形态）。
ROUTE_B_TARGETS: Tuple[Dict[str, str], ...] = (
    {
        "name": "publish_workbench",
        "url": "https://item.upload.taobao.com/sell/ai/category.htm",
        "expect": "login_redirect_when_logged_out",
    },
    {
        "name": "sucai_selector_ng_runtime",
        "url": SUCAI_SELECTOR_NG,
        "expect": "public_app_shell_runtime_requests",
    },
)

#: 微模块加载规则（来自 `o.alicdn.com/crs-qn/microapp-loader/MicroLoader.js`）。
MICRO_MODULE_PATTERN = "https://{cdn_host}/merchant-micro-mods/{name}/{version}/js/remoteEntry.js"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

ASSET_SUFFIXES = (".js", ".mjs", ".json")

#: 允许抓取的静态资源 host（公开 CDN）。
ALLOWED_ASSET_HOSTS = (
    "g.alicdn.com",
    "at.alicdn.com",
    "gw.alicdn.com",
    "o.alicdn.com",
    "assets.alicdn.com",
    "market.m.taobao.com",
    "sucai.taobao.com",
    "sc.taobao.com",
)

#: 线索分组：``endpoint`` 组逐条记录上下文；``marker`` 组只计数 + 少量样本。
ENDPOINT_CLUES: Tuple[Tuple[str, str], ...] = (
    ("upload_path", r"['\"`][^'\"`\n]{0,200}/upload[^'\"`\n]{0,120}['\"`]"),
    ("upload_api_word", r"upload\.api|/api/upload"),
    ("upload_host", r"['\"`](?:https?:)?//[A-Za-z0-9.\-]*(?:stream-upload|pre-stream|tadget|picasso)[A-Za-z0-9.\-]*[^'\"`\n]{0,120}['\"`]"),
    ("mtop_call", r"mtop\.[A-Za-z0-9_]{2,30}\.[A-Za-z0-9_.]{2,60}"),
    ("upload_fn", r"uploadImg|uploadImage|uploadPic|uploadFile|batchUpload|startUpload|handleUpload"),
    ("folder_id", r"folderId|pictureCategoryId|dirId"),
    ("api_path", r"['\"`]/(?:api|h5|gw|rest|media|resource)/[A-Za-z0-9_\-./]{2,80}['\"`]"),
    ("sucai_or_qsm_host", r"['\"`](?:https?:)?//[A-Za-z0-9.\-]*(?:sucai|qsm|qn)[A-Za-z0-9.\-]*[^'\"`\n]{0,100}['\"`]"),
    ("upload_panel_class", r"UploadPanel_[A-Za-z0-9_]+"),
    ("appkey_value", r"appkey\s*:\s*[\"'`][A-Za-z0-9_]{1,20}[\"'`]"),
)

MARKER_CLUES: Tuple[Tuple[str, str], ...] = (
    ("formdata_new", r"new FormData"),
    ("formdata_any", r"FormData"),
    ("multipart", r"multipart"),
    ("picture", r"picture"),
    ("sucai_word", r"sucai"),
    ("tb_token_read", r"get\(\s*[\"']_tb" r"_token_[\"']\s*\)"),
    ("formdata_append", r"\.append\(\s*[\"'][^\"']{1,40}[\"']"),
    ("drag_drop_dirs", r"webkitGetAsEntry|getAsFileSystemHandle"),
    ("accept_image", r"accept:\s*[\"']?image"),
    ("slice_upload", r"sliceSize|sliceNum|uploadUrlList|uploadId"),
)

#: 从 JS 文本里抽「像 URL / 像路径」的引号字面量时的过滤词。
INTERESTING_WORDS = (
    "upload",
    "pic",
    "image",
    "media",
    "resource",
    "sucai",
    "qsm",
    "file",
    "album",
    "folder",
    "stream",
)

_SCRIPT_SRC_RE = re.compile(
    r"<script[^>]*?\ssrc\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"'>]+))", re.IGNORECASE
)
_LINK_HREF_RE = re.compile(
    r"<link[^>]*?\shref\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"'>]+))", re.IGNORECASE
)
_RAW_URL_RE = re.compile(r"(?:https?:)?//[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-%]*)+")
_QUOTED_RE = re.compile(r"[\"'`]([^\"'`\n\r]{4,300})[\"'`]")
_ABS_URL_RE = re.compile(r"[\"'`](https?://[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-/%]*)?)[\"'`]")
#: webpack ``r.u`` chunk 拼接表达式（含 ``{id:"name"}`` 与 ``{id:"hash"}`` 两张映射表）。
_CHUNK_MAP_RE = re.compile(
    r'r\.u\s*=\s*\w+\s*=>\s*"([^"]*)"\s*\+\s*\((\{[^}]*\})\[\w+\]\s*\|\|\s*\w+\)'
    r'\s*\+\s*"\."\s*\+\s*(\{[^}]*\})\[\w+\]\s*\+\s*"([^"]*)"'
)
#: 微模块声明：``remoteAppName:"x", moduleName:"Y"`` / ``microModName:"x",version:Var``。
_REMOTE_APP_RE = re.compile(r'remoteAppName\s*:\s*"([A-Za-z0-9_\-]{2,60})"')
_MICRO_MOD_RE = re.compile(
    r'microModName\s*:\s*"([A-Za-z0-9_\-]{2,60})"\s*,\s*version\s*:\s*'
    r'(?:"([\d.]+)"|([A-Za-z_$][\w$]{0,20}))'
)
_VERSION_MAP_RE = re.compile(r'\{\s*name\s*:\s*"([A-Za-z0-9_\-]{2,60})"\s*,\s*version\s*:\s*"([\d.]+)"\s*\}')
_VERSION_VAR_RE = re.compile(r'([A-Za-z_$][\w$]{0,20})\s*=\s*"([\d]+\.[\d]+\.[\d]+)"')


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
class HostRateLimiter:
    """同一个 host 两次请求之间的最小间隔，并维护总请求预算。"""

    def __init__(self, min_interval: float, max_requests: int) -> None:
        self.min_interval = float(min_interval)
        self.max_requests = int(max_requests)
        self._last: Dict[str, float] = {}
        self.requests_made = 0
        self.budget_exhausted = False

    def take(self, host: str) -> bool:
        if self.requests_made >= self.max_requests:
            self.budget_exhausted = True
            return False
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()
        self.requests_made += 1
        return True


def http_get(
    url: str,
    limiter: HostRateLimiter,
    *,
    max_bytes: int = 32 * 1024 * 1024,
    timeout: float = 40.0,
) -> Dict[str, Any]:
    """只读 GET。**不发送任何 cookie**（urllib 默认不带 cookie jar）。"""

    host = urllib.parse.urlsplit(url).netloc
    if not limiter.take(host):
        return {"ok": False, "error": "request_budget_exhausted", "url": url}

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/javascript,application/json,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        method="GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes)
            final = urllib.parse.urlsplit(response.geturl())
            return {
                "ok": True,
                "url": url,
                "final_host": final.netloc,
                "final_path": final.path,
                "status": int(getattr(response, "status", 0) or 0),
                "content_type": (response.headers.get("content-type") or "")[:80],
                "bytes": len(body),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "body": body,
            }
    except urllib.error.HTTPError as error:
        return {
            "ok": False,
            "error": f"HTTPError {error.code}",
            "status": int(error.code),
            "url": url,
            "final_host": urllib.parse.urlsplit(error.geturl()).netloc,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "body": b"",
        }
    except Exception as error:  # noqa: BLE001 - 探针要把失败如实记下来
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "url": url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "body": b"",
        }


def http_get_json(url: str, timeout: float = 10.0, method: str = "GET") -> Any:
    """CDP HTTP 端点（127.0.0.1）用，不参与 host 限速预算。"""

    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read(4 * 1024 * 1024).decode("utf-8", "replace")
    return json.loads(text) if text.strip() else None


def _guard_sample(text: str) -> Optional[str]:
    """单条样本的最后一道闸：仍疑似残留登录态 → 整条丢弃。

    先过 :func:`contains_secret_like`，再按 `captures/` 守卫的规则检查
    :data:`CAPTURE_FORBIDDEN_MARKERS`：这些字面量只允许出现在样本里带
    ``***REDACTED***`` 的邻近位置。样本级先挡一遍，避免一条 JS 片段把整份
    captures 产物顶掉。
    """

    if contains_secret_like(text):
        return None
    lowered = text.lower()
    for marker in CAPTURE_FORBIDDEN_MARKERS:
        position = lowered.find(marker.lower())
        while position != -1:
            window = text[max(0, position - 100) : position + len(marker) + 200]
            if REDACTED not in window:
                return None
            position = lowered.find(marker.lower(), position + len(marker))
    return text


SAMPLE_WITHHELD = (
    "<sample withheld: 命中 captures 守卫的敏感标记名（cookie/header 名）且邻近没有脱敏占位符；"
    "原始上下文见 tmp/ 下的 raw 产物>"
)


def context_of(text: str, start: int, end: int, *, pad: int = 200) -> str:
    snippet = sanitize_text(text[max(0, start - pad) : min(len(text), end + pad)])
    return (_guard_sample(snippet) or SAMPLE_WITHHELD).replace("\n", " ").replace("\r", " ")


def collect_matches(text: str, pattern: str, *, limit: int) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for match in re.finditer(pattern, text):
        if len(hits) >= limit:
            break
        hits.append(
            {
                "match": sanitize_text(match.group(0))[:160],
                "offset": match.start(),
                "context": context_of(text, match.start(), match.end()),
            }
        )
    return hits


def resolve_url(base: str, candidate: str) -> Optional[str]:
    candidate = (candidate or "").strip()
    if not candidate or candidate.startswith(("data:", "javascript:", "#")):
        return None
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    joined = urllib.parse.urljoin(base, candidate)
    return joined if joined.startswith("http") else None


def host_allowed(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_ASSET_HOSTS)


def asset_kind(url: str) -> bool:
    return urllib.parse.urlsplit(url).path.lower().endswith(ASSET_SUFFIXES)


def short_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def shape_of(url: str) -> str:
    """只保留 scheme + host + path，丢掉 query（query 里常有签名/token）。"""

    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def is_login_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return "login.taobao.com" in parts.netloc or "/login" in parts.path


def guard_safe_name(name: str) -> str:
    """把「敏感名字」写成 captures 守卫能接受的形式。

    ``captures/`` 的守卫（``assert_capture_ready``）要求 ``_tb_token_`` / ``cookie2``
    这类标记名出现时，邻近必须有 ``***REDACTED***`` 占位符。研究需要知道**字段名**，
    不需要值；所以这里把名字写成 ``名字=***REDACTED***`` 的配对形态——
    既保留「存在这个名字」的证据，又满足守卫。
    """

    lowered = name.strip().lower()
    if lowered in SENSITIVE_COOKIE_NAMES or lowered in SENSITIVE_QUERY_KEYS or lowered in SENSITIVE_HEADER_NAMES:
        return f"{name}={REDACTED}"
    return name


def _json_map(raw: str) -> Dict[str, str]:
    """把 webpack 里 ``{792:"main",802:"cropper"}`` 这样的映射转成 dict。"""

    fixed = re.sub(r"(\d+)\s*:", r'"\1":', raw)
    try:
        return {str(key): str(value) for key, value in json.loads(fixed).items()}
    except json.JSONDecodeError:
        return {}


def derive_chunk_urls(remote_entry_text: str, public_path: str) -> List[str]:
    """反解 webpack runtime 的 ``r.u``，列出该微模块的全部 chunk URL。"""

    match = _CHUNK_MAP_RE.search(remote_entry_text)
    if not match:
        return []
    prefix, names_raw, hashes_raw, suffix = match.groups()
    names = _json_map(names_raw)
    hashes = _json_map(hashes_raw)
    return [
        f"{public_path}{prefix}{names.get(chunk_id, chunk_id)}.{digest}{suffix}"
        for chunk_id, digest in hashes.items()
    ]


# ---------------------------------------------------------------------------
# 路线 A：公开前端资源静态分析
# ---------------------------------------------------------------------------
def _scan_text(
    label: str,
    text: str,
    *,
    per_file_samples: int,
    endpoint_counts: Dict[str, int],
    endpoint_hits: Dict[str, List[Dict[str, Any]]],
    marker_counts: Dict[str, int],
    marker_samples: Dict[str, List[str]],
    mtop_sources: Dict[str, List[str]],
    absolute_urls: Dict[str, Dict[str, Any]],
    quoted_candidates: Dict[str, Dict[str, Any]],
) -> None:
    for key, pattern in ENDPOINT_CLUES:
        count = 0
        for _ in re.finditer(pattern, text):
            count += 1
        if not count:
            continue
        endpoint_counts[key] += count
        endpoint_hits[key].extend(
            {"source": label, **hit} for hit in collect_matches(text, pattern, limit=per_file_samples)
        )
    for key, pattern in MARKER_CLUES:
        matches = list(re.finditer(pattern, text))
        if not matches:
            continue
        marker_counts[key] += len(matches)
        if len(marker_samples[key]) < 3:
            for match in matches[: 3 - len(marker_samples[key])]:
                marker_samples[key].append(f"[{label}] {context_of(text, match.start(), match.end(), pad=120)}")
    for match in re.finditer(r"mtop\.[A-Za-z0-9_]{2,30}\.[A-Za-z0-9_.]{2,60}", text):
        api = sanitize_text(match.group(0))
        sources = mtop_sources.setdefault(api, [])
        if label not in sources:
            sources.append(label)
    for match in _ABS_URL_RE.finditer(text):
        url = sanitize_text(match.group(0)[1:-1])
        record = absolute_urls.setdefault(
            url, {"url": url, "host": urllib.parse.urlsplit(url).netloc, "sources": [], "count": 0}
        )
        record["count"] += 1
        if label not in record["sources"]:
            record["sources"].append(label)
    for match in _QUOTED_RE.finditer(text):
        literal = match.group(1)
        lowered = literal.lower()
        if not any(word in lowered for word in INTERESTING_WORDS):
            continue
        if len(literal) > 160 or literal.count(" ") > 3:
            continue
        if not (literal.startswith(("/", "http://", "https://", "//")) or literal.startswith("mtop.")):
            continue
        safe = _guard_sample(sanitize_text(literal))
        if not safe:
            continue
        record = quoted_candidates.setdefault(safe, {"literal": safe, "sources": [], "count": 0})
        record["count"] += 1
        if label not in record["sources"]:
            record["sources"].append(label)


def route_a_static_analysis(
    limiter: HostRateLimiter, *, per_file_samples: int, max_modules: int
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "description": "公开前端资源静态分析（只 GET，不登录、不带 cookie）",
        "seeds": [],
        "assets": [],
        "micro_modules": [],
        "evidence": {},
        "clue_counts": {},
        "notes": [],
    }
    endpoint_counts = {key: 0 for key, _ in ENDPOINT_CLUES}
    endpoint_hits: Dict[str, List[Dict[str, Any]]] = {key: [] for key, _ in ENDPOINT_CLUES}
    marker_counts = {key: 0 for key, _ in MARKER_CLUES}
    marker_samples: Dict[str, List[str]] = {key: [] for key, _ in MARKER_CLUES}
    mtop_sources: Dict[str, List[str]] = {}
    absolute_urls: Dict[str, Dict[str, Any]] = {}
    quoted_candidates: Dict[str, Dict[str, Any]] = {}

    texts: Dict[str, str] = {}  # label -> 文本（只驻内存，不落盘）
    queue: List[Tuple[str, str]] = []  # (来源, URL)
    seen: set[str] = set()

    # ---- 阶段 1：应用外壳 + 首跳资源 ----
    for seed in ROUTE_A_SEEDS:
        fetched = http_get(seed["url"], limiter)
        body = fetched.pop("body", b"")
        text = body.decode("utf-8", "replace")
        entry: Dict[str, Any] = {
            "name": seed["name"],
            "url": seed["url"],
            "expect": seed["expect"],
            "ok": fetched.get("ok", False),
            "status": fetched.get("status"),
            "error": fetched.get("error"),
            "content_type": fetched.get("content_type"),
            "bytes": fetched.get("bytes", 0),
            "final_host": fetched.get("final_host"),
            "final_path": fetched.get("final_path"),
            "login_redirect": bool(
                fetched.get("final_host")
                and is_login_url(f"{fetched.get('final_host')}{fetched.get('final_path') or ''}")
            ),
            "title": None,
            "references_media_iframe_app": MEDIA_IFRAME_HINT in text,
        }
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if title:
            entry["title"] = sanitize_text(title.group(1).strip())[:80]
        references: List[str] = []
        for regex in (_SCRIPT_SRC_RE, _LINK_HREF_RE):
            for match in regex.finditer(text):
                candidate = next((group for group in match.groups() if group), None)
                resolved = resolve_url(seed["url"], candidate or "")
                if resolved:
                    references.append(resolved)
        for match in _RAW_URL_RE.finditer(text):
            resolved = resolve_url(seed["url"], match.group(0))
            if resolved:
                references.append(resolved)
        unique_refs = sorted({url for url in references if asset_kind(url)})
        entry["referenced_assets"] = [shape_of(url) for url in unique_refs][:40]
        entry["referenced_asset_count"] = len(unique_refs)
        result["seeds"].append(entry)
        for url in unique_refs:
            if url in seen:
                continue
            seen.add(url)
            if host_allowed(url):
                queue.append((seed["name"], url))
            else:
                result["notes"].append(f"跳过非白名单 host 资源：{shape_of(url)}")

    # ---- 阶段 2：下载首跳资源 ----
    while queue and not limiter.budget_exhausted:
        origin, url = queue.pop(0)
        fetched = http_get(url, limiter)
        body = fetched.pop("body", b"")
        asset = {
            "stage": "shell_asset",
            "source_page": origin,
            "url": shape_of(url),
            "host": urllib.parse.urlsplit(url).netloc,
            "path": urllib.parse.urlsplit(url).path,
            "ok": fetched.get("ok", False),
            "status": fetched.get("status"),
            "error": fetched.get("error"),
            "bytes": fetched.get("bytes", 0),
            "sha256_16": short_digest(body) if body else None,
        }
        result["assets"].append(asset)
        if not fetched.get("ok") or not body:
            continue
        text = body.decode("utf-8", "replace")
        label = f"{origin}:{asset['path'].rsplit('/', 1)[-1]}"
        texts[label] = text
        _scan_text(
            label,
            text,
            per_file_samples=per_file_samples,
            endpoint_counts=endpoint_counts,
            endpoint_hits=endpoint_hits,
            marker_counts=marker_counts,
            marker_samples=marker_samples,
            mtop_sources=mtop_sources,
            absolute_urls=absolute_urls,
            quoted_candidates=quoted_candidates,
        )

    # ---- 阶段 3：发现微模块（MicroLoader 规则），并把它们的 chunk 也扫一遍 ----
    # 微模块之间会互相引用（sucai-tu-selector 的 chunk 里声明了
    # sucai-center-components 的版本），所以发现 → 下载 → 再发现要迭代到没有新模块为止。
    expanded: set[str] = set()

    def discover_micro_modules() -> List[Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}
        for label, text in texts.items():
            version_vars = {name: value for name, value in _VERSION_VAR_RE.findall(text)}
            version_map = dict(_VERSION_MAP_RE.findall(text))
            for match in _MICRO_MOD_RE.finditer(text):
                name = match.group(1)
                version = match.group(2) or version_vars.get(match.group(3) or "", "")
                if version:
                    found.setdefault(name, {"name": name, "version": version, "sources": []})
                    if label not in found[name]["sources"]:
                        found[name]["sources"].append(label)
            for match in _REMOTE_APP_RE.finditer(text):
                name = match.group(1)
                if name in version_map:
                    found.setdefault(name, {"name": name, "version": version_map[name], "sources": []})
                    if label not in found[name]["sources"]:
                        found[name]["sources"].append(label)
            # 版本映射表里的其它条目也登记（宿主可能按需加载其中任意一个）
            for name, version in version_map.items():
                found.setdefault(name, {"name": name, "version": version, "sources": []})
                if label not in found[name]["sources"]:
                    found[name]["sources"].append(label)
        return [
            meta
            for meta in found.values()
            if f"{meta['name']}@{meta['version']}" not in expanded
        ]

    while not limiter.budget_exhausted:
        pending_modules = discover_micro_modules()
        if not pending_modules:
            break
        for meta in sorted(pending_modules, key=lambda item: item["name"]):
            name, version = meta["name"], meta["version"]
            expanded.add(f"{name}@{version}")
            if len(result["micro_modules"]) >= max_modules or limiter.budget_exhausted:
                result["notes"].append(
                    f"微模块展开停止于 {name}@{version}（--max-modules={max_modules} 或请求预算用尽）"
                )
                continue
            remote_entry = MICRO_MODULE_PATTERN.format(
                cdn_host="g.alicdn.com", name=name, version=version
            )
            public_path = remote_entry.rsplit("js/remoteEntry.js", 1)[0]
            module_record: Dict[str, Any] = {
                "name": name,
                "version": version,
                "discovered_from": meta["sources"][:4],
                "public_path": public_path,
                "remote_entry": shape_of(remote_entry),
                "remote_entry_status": None,
                "chunks": [],
                "exposed_modules": [],
            }
            fetched = http_get(remote_entry, limiter)
            body = fetched.pop("body", b"")
            module_record["remote_entry_status"] = fetched.get("status")
            if not fetched.get("ok") or not body:
                module_record["error"] = fetched.get("error") or f"status={fetched.get('status')}"
                result["micro_modules"].append(module_record)
                continue
            remote_text = body.decode("utf-8", "replace")
            module_record["exposed_modules"] = sorted(
                {
                    match.group(1)
                    for match in re.finditer(r'\{\s*"?([A-Za-z][A-Za-z0-9_]{2,40})"?\s*:\s*\(\)\s*=>\s*Promise\.all', remote_text)
                }
            )
            chunk_urls = derive_chunk_urls(remote_text, public_path)
            module_record["chunk_urls_derived"] = len(chunk_urls)
            for chunk_url in chunk_urls:
                if not limiter.take(urllib.parse.urlsplit(chunk_url).netloc):
                    break
                chunk_fetched = http_get(chunk_url, limiter)
                chunk_body = chunk_fetched.pop("body", b"")
                chunk_record = {
                    "stage": "micro_module_chunk",
                    "module": f"{name}#{version}",
                    "path": urllib.parse.urlsplit(chunk_url).path,
                    "ok": chunk_fetched.get("ok", False),
                    "status": chunk_fetched.get("status"),
                    "bytes": chunk_fetched.get("bytes", 0),
                    "sha256_16": short_digest(chunk_body) if chunk_body else None,
                }
                module_record["chunks"].append(chunk_record)
                if chunk_fetched.get("ok") and chunk_body:
                    chunk_text = chunk_body.decode("utf-8", "replace")
                    label = f"{name}#{version}#{chunk_record['path'].rsplit('/', 1)[-1]}"
                    texts[label] = chunk_text
                    _scan_text(
                        label,
                        chunk_text,
                        per_file_samples=per_file_samples,
                        endpoint_counts=endpoint_counts,
                        endpoint_hits=endpoint_hits,
                        marker_counts=marker_counts,
                        marker_samples=marker_samples,
                        mtop_sources=mtop_sources,
                        absolute_urls=absolute_urls,
                        quoted_candidates=quoted_candidates,
                    )
            result["micro_modules"].append(module_record)

    # ---- 阶段 4：证据汇总 ----
    upload_host_urls = sorted(
        (
            record
            for record in absolute_urls.values()
            if re.search(
                r"upload|stream|picasso|tadget|picture|mediafront|qn\.taobao|sucai", record["url"], re.IGNORECASE
            )
        ),
        key=lambda item: (-item["count"], item["url"]),
    )
    params: Dict[str, int] = {}
    for text in texts.values():
        for match in re.finditer(
            r"(?:appkey|appKey|folderId|watermark|picCompress|autoCompress|resizeWidth|hideUserId|"
            r"_input_charset|bizCode|sliceSize|sliceNum|uploadId|uploadUrlList|dirId|clientType|"
            r"partList|sha256|fileName|fileSize|pixel|fileType)\b",
            text,
        ):
            params[match.group(0)] = params.get(match.group(0), 0) + 1

    result["evidence"] = {
        "upload_related_urls": upload_host_urls[:60],
        "mtop_apis": [
            {"api": api, "sources": sources}
            for api, sources in sorted(mtop_sources.items())
        ],
        "multipart_or_upload_note": {
            "formdata_append_fields": sorted(
                {
                    guard_safe_name(sanitize_text(match.group(1)))
                    for text in texts.values()
                    for match in re.finditer(r"\.append\(\s*[\"']([^\"']{1,40})[\"']", text)
                }
            ),
            "protocol_params_seen": dict(sorted(params.items(), key=lambda item: (-item[1], item[0]))),
        },
        "upload_panel_class_names": sorted(
            {
                match.group(0)
                for text in texts.values()
                for match in re.finditer(r"UploadPanel_[A-Za-z0-9_]+", text)
            }
        ),
        "router_hints": sorted(
            {
                record["url"]
                for record in absolute_urls.values()
                if re.search(r"qn\.taobao\.com|quick\.taobao\.com|wangpu\.taobao\.com", record["url"])
            }
        ),
    }
    result["clue_counts"] = {
        "endpoint_counts": endpoint_counts,
        "marker_counts": marker_counts,
        "texts_scanned": len(texts),
    }
    result["clues"] = {
        "endpoint_hits": {key: hits[: per_file_samples * 4] for key, hits in endpoint_hits.items() if hits},
        "marker_samples": {key: value for key, value in marker_samples.items() if value},
        "quoted_candidates": sorted(
            quoted_candidates.values(), key=lambda item: (-item["count"], item["literal"])
        )[:160],
    }
    result["assets_downloaded"] = sum(1 for asset in result["assets"] if asset.get("ok"))
    result["requests_made"] = limiter.requests_made
    return result


# ---------------------------------------------------------------------------
# 路线 B：CDP 被动观察
# ---------------------------------------------------------------------------
def cdp_available(port: int) -> Dict[str, Any]:
    try:
        version = http_get_json(f"http://127.0.0.1:{port}/json/version")
        return {
            "ok": True,
            "version": {
                "Browser": str(version.get("Browser", ""))[:80],
                "Protocol-Version": str(version.get("Protocol-Version", ""))[:20],
            },
        }
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def cdp_observe(port: int, target: Dict[str, str], *, seconds: float) -> Dict[str, Any]:
    """新建标签页 → 打开目标 → 纯被动记录请求形态，然后关掉这个标签页。"""

    import websocket  # 局部导入：不做 CDP 时无需依赖

    record: Dict[str, Any] = {
        "name": target["name"],
        "url": target["url"],
        "expect": target["expect"],
        "method": "passive_network_observation",
        "shapes": [],
        "final_url": None,
        "title": None,
    }
    try:
        created = http_get_json(
            f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote('about:blank')}", method="PUT"
        )
    except Exception as error:  # noqa: BLE001
        record["error"] = f"cdp_new_tab_failed: {type(error).__name__}: {error}"
        return record

    target_id = created.get("id")
    ws_url = created.get("webSocketDebuggerUrl")
    if not ws_url:
        record["error"] = "cdp_new_tab_returned_no_websocket"
        return record

    connection = None
    try:
        connection = websocket.create_connection(ws_url, timeout=seconds + 10, suppress_origin=True)
        message_id = 0

        def send(method: str, params: Optional[Dict[str, Any]] = None) -> None:
            nonlocal message_id
            message_id += 1
            connection.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))

        send("Network.enable")
        send("Page.enable")
        send("Runtime.enable")
        send("Page.navigate", {"url": target["url"]})

        started = time.monotonic()
        pending: Dict[str, Dict[str, Any]] = {}
        shapes: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        while time.monotonic() - started < seconds:
            connection.settimeout(max(0.5, seconds - (time.monotonic() - started)))
            try:
                raw = connection.recv()
            except Exception:  # noqa: BLE001 - 超时/断连只意味着观察窗口结束
                break
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            method = message.get("method")
            params = message.get("params") or {}
            if method == "Network.requestWillBeSent":
                request = params.get("request") or {}
                url = str(request.get("url", ""))
                if not url.startswith("http"):
                    continue
                parts = urllib.parse.urlsplit(url)
                key = (parts.netloc, parts.path or "/", str(request.get("method", "GET")), str(params.get("type", "")))
                shape = shapes.setdefault(
                    key,
                    {
                        "host": key[0],
                        "path": key[1],
                        "method": key[2],
                        "resource_type": key[3],
                        "status": None,
                        "content_type": None,
                        "count": 0,
                        "initiator": str((params.get("initiator") or {}).get("type", ""))[:40],
                    },
                )
                shape["count"] += 1
                pending[str(params.get("requestId"))] = shape
            elif method == "Network.responseReceived":
                shape = pending.get(str(params.get("requestId")))
                response = params.get("response") or {}
                if shape is not None:
                    shape["status"] = response.get("status")
                    content_type = ""
                    for header_name, header_value in (response.get("headers") or {}).items():
                        if str(header_name).lower() == "content-type":
                            content_type = str(header_value)
                            break
                    shape["content_type"] = content_type.split(";")[0].strip()[:60] or None

        # 页面最终落点（判断是否被踢到登录页）——只读 location.href / title
        try:
            connection.settimeout(5)
            send(
                "Runtime.evaluate",
                {
                    "expression": "JSON.stringify({href: location.href, title: document.title})",
                    "returnByValue": True,
                },
            )
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                message = json.loads(connection.recv())
                result_value = ((message.get("result") or {}).get("result") or {}).get("value")
                if result_value:
                    payload = json.loads(result_value)
                    record["final_url"] = sanitize_url(str(payload.get("href", "")))
                    record["title"] = sanitize_text(str(payload.get("title", "")))[:80]
                    break
        except Exception:  # noqa: BLE001
            pass

        record["shapes"] = sorted(
            shapes.values(), key=lambda item: (item["host"], item["path"], item["method"])
        )
        record["shape_count"] = len(record["shapes"])
        record["login_redirect"] = bool(record.get("final_url") and is_login_url(record["final_url"]))
    except Exception as error:  # noqa: BLE001
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            if connection is not None:
                connection.close()
        except Exception:  # noqa: BLE001
            pass
        if target_id:
            try:
                http_get_json(f"http://127.0.0.1:{port}/json/close/{target_id}")
            except Exception:  # noqa: BLE001
                pass
    return record


def route_b_passive(args: argparse.Namespace) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "description": "CDP 被动观察（Network.enable，只记 host+path+method+content-type）",
        "cdp_port": args.cdp_port,
        "targets": [],
        "limitations": [
            "只记录请求形态，不记录 header / cookie / postData / 响应体",
            "不点击任何按钮、不上传文件、不保存草稿、不提交",
        ],
    }
    availability = cdp_available(args.cdp_port)
    result["cdp"] = availability
    if not availability.get("ok"):
        result["blocked"] = (
            f"{args.cdp_port} 端口 CDP 不可达：{availability.get('error')}。"
            "启动命令：node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs"
        )
        return result
    for target in ROUTE_B_TARGETS:
        if args.targets and target["name"] not in args.targets:
            continue
        result["targets"].append(cdp_observe(args.cdp_port, target, seconds=args.observe_seconds))
    return result


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_output(args: argparse.Namespace) -> Dict[str, Any]:
    limiter = HostRateLimiter(args.min_interval, args.max_requests)
    output: Dict[str, Any] = {
        "probe": "tb_image_space_upload_endpoint_probe",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "readonly": True,
        "policy": {
            "http_methods": ["GET"],
            "cookies_sent": False,
            "login_state_used": False,
            "min_interval_seconds_per_host": args.min_interval,
            "max_requests": args.max_requests,
            "notes": "只读探针；不触发上传/保存/提交；产物必须过 taobao_publish.sanitize 才能进 captures/",
        },
        "route": args.route,
    }
    if args.route in ("a", "all"):
        output["route_a"] = route_a_static_analysis(
            limiter, per_file_samples=args.samples, max_modules=args.max_modules
        )
    if args.route in ("b", "all"):
        output["route_b"] = route_b_passive(args)
    output["requests_made_total"] = limiter.requests_made
    return output


def guard_self_check(payload: Any) -> List[str]:
    """落下 raw 之前先按 `captures/` 守卫的规则自检一遍。

    返回**不含敏感文本**的告警列表（只有标记名与次数）。命中就说明这份产物直接
    跑 `python -m taobao_publish sanitize` 会被 `assert_capture_ready` 拒绝，
    必须先处理对应字段。
    """

    text = json.dumps(payload, ensure_ascii=False)
    warnings: List[str] = []
    if contains_secret_like(text):
        warnings.append("contains_secret_like=true（有未脱敏的疑似登录态）")
    for marker in CAPTURE_FORBIDDEN_MARKERS:
        count = 0
        for match in re.finditer(re.escape(marker), text, flags=re.IGNORECASE):
            window = text[max(0, match.start() - 100) : match.end() + 200]
            if REDACTED not in window:
                count += 1
        if count:
            warnings.append(f"captures 守卫会拒绝：标记 {marker!r} 出现 {count} 次且邻近没有脱敏占位符")
    return warnings


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="淘宝图片空间上传端点只读探针")
    parser.add_argument("--route", choices=("a", "b", "all"), default="all")
    parser.add_argument("--out-raw", default=None, help="原始产物路径（默认 tmp/…）")
    parser.add_argument("--max-requests", type=int, default=80)
    parser.add_argument("--min-interval", type=float, default=1.0, help="同一 host 最小请求间隔（秒）")
    parser.add_argument("--samples", type=int, default=3, help="每个线索每组上下文样本数上限")
    parser.add_argument("--max-modules", type=int, default=6, help="最多展开多少个微模块")
    parser.add_argument("--cdp-port", type=int, default=9334)
    parser.add_argument("--observe-seconds", type=float, default=14.0)
    parser.add_argument(
        "--targets",
        default="",
        help="路线 B 只观察这些目标（逗号分隔：publish_workbench,sucai_selector_ng_runtime）",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.targets = [item.strip() for item in args.targets.split(",") if item.strip()]

    output = build_output(args)
    sanitized = sanitize_payload(output)
    guard_warnings = guard_self_check(sanitized)
    sanitized.setdefault("guard_self_check", []).extend(guard_warnings or ["ok"])

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw_path = Path(args.out_raw) if args.out_raw else (
        _PACKAGE_ROOT / "tmp" / f"image-space-endpoint-probe-raw-{stamp}.json"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary: Dict[str, Any] = {
        "raw": str(raw_path),
        "route": args.route,
        "requests_made": output.get("requests_made_total"),
        "guard_self_check": guard_warnings or ["ok"],
    }
    if "route_a" in output:
        route_a = output["route_a"]
        summary["route_a"] = {
            "seeds": [
                {
                    "name": seed["name"],
                    "status": seed.get("status"),
                    "ok": seed.get("ok"),
                    "title": seed.get("title"),
                    "login_redirect": seed.get("login_redirect"),
                    "referenced_asset_count": seed.get("referenced_asset_count"),
                }
                for seed in route_a["seeds"]
            ],
            "assets_ok": route_a["assets_downloaded"],
            "micro_modules": [
                {
                    "module": f"{item['name']}@{item['version']}",
                    "remote_entry_status": item["remote_entry_status"],
                    "chunks_ok": sum(1 for chunk in item["chunks"] if chunk.get("ok")),
                    "chunks_total": len(item["chunks"]),
                }
                for item in route_a["micro_modules"]
            ],
            "texts_scanned": route_a["clue_counts"]["texts_scanned"],
            "endpoint_counts": route_a["clue_counts"]["endpoint_counts"],
            "marker_counts": route_a["clue_counts"]["marker_counts"],
            "upload_related_url_count": len(route_a["evidence"]["upload_related_urls"]),
            "mtop_api_count": len(route_a["evidence"]["mtop_apis"]),
        }
    if "route_b" in output:
        summary["route_b"] = {
            "cdp_ok": output["route_b"]["cdp"].get("ok"),
            "blocked": output["route_b"].get("blocked"),
            "targets": [
                {
                    "name": item["name"],
                    "final_url": item.get("final_url"),
                    "title": item.get("title"),
                    "shape_count": item.get("shape_count"),
                    "login_redirect": item.get("login_redirect"),
                    "error": item.get("error"),
                }
                for item in output["route_b"]["targets"]
            ],
        }
    if not args.quiet:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
