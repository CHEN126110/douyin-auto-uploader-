# -*- coding: utf-8 -*-
"""Helpers for validating and normalizing capture source URLs."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_URL_CANDIDATE_RE = re.compile(
    r"""(?ix)
    (
        https?://[^\s<>"'，。；;、]+
        |
        (?:
            tb\.cn
            |
            (?:[a-z0-9-]+\.)+(?:taobao\.com|tmall\.com|1688\.com|tb\.cn)
        )
        [^\s<>"'，。；;、]*
    )
    """
)

_TRAILING_URL_PUNCTUATION = " \t\r\n\"'<>，。；;、!！)）]】》"

SUPPORTED_CAPTURE_HOST_SUFFIXES = (".taobao.com", ".tmall.com", ".1688.com")
SUPPORTED_CAPTURE_HOSTS = {"taobao.com", "tmall.com", "1688.com"}
TAOBAO_SHORT_LINK_HOSTS = {"tb.cn", "m.tb.cn"}


def _strip_url_tail(value: str) -> str:
    return str(value or "").strip().rstrip(_TRAILING_URL_PUNCTUATION)


def extract_first_capture_url(raw_value: str) -> str:
    """Extract the first likely capture URL from a plain URL or share text."""
    text = html.unescape(str(raw_value or "")).strip()
    if not text:
        return ""

    match = _URL_CANDIDATE_RE.search(text)
    return _strip_url_tail(match.group(1) if match else text)


def normalize_capture_url(raw_value: str) -> str:
    """Normalize pasted capture input to an absolute http(s) URL."""
    candidate = extract_first_capture_url(raw_value)
    if not candidate:
        return ""
    if candidate.startswith("//"):
        return "https:" + candidate
    if not re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        return "https://" + candidate
    return candidate


def capture_url_host(url: str) -> str:
    normalized = normalize_capture_url(url)
    if not normalized:
        return ""
    try:
        return (urlparse(normalized).hostname or "").lower()
    except Exception:
        return ""


def is_taobao_short_link(url: str) -> bool:
    host = capture_url_host(url)
    return host in TAOBAO_SHORT_LINK_HOSTS or host.endswith(".tb.cn")


def is_supported_capture_host(url: str) -> bool:
    host = capture_url_host(url)
    if not host:
        return False
    return (
        host in SUPPORTED_CAPTURE_HOSTS
        or host in TAOBAO_SHORT_LINK_HOSTS
        or host.endswith(SUPPORTED_CAPTURE_HOST_SUFFIXES)
        or host.endswith(".tb.cn")
    )
