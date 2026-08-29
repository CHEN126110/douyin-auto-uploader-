from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PRICE_STOCK_STAGE_KEY = "price_stock"


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


@dataclass(slots=True)
class PriceStockDiscoveryProfile:
    stage: str = PRICE_STOCK_STAGE_KEY
    target_url_contains: str = "fxg.jinritemai.com/ffa/g/create"
    url_contains: str = "jinritemai.com"
    resource_types: list[str] = field(default_factory=lambda: ["XHR", "Fetch"])
    duration_ms: int = 15000
    max_entries: int = 400
    include_responses: bool = True
    include_response_body: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PriceStockCandidate:
    method: str
    host: str
    pathname: str
    count: int
    statuses: list[str] = field(default_factory=list)
    query_keys: list[str] = field(default_factory=list)
    post_keys: list[str] = field(default_factory=list)
    candidate_score: int = 0
    candidate_hits: list[str] = field(default_factory=list)
    sample_url: str = ""
    sample_body_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_candidate(endpoint: dict[str, Any]) -> tuple[int, list[str]]:
    haystack_parts = [
        str(endpoint.get("pathname") or ""),
        str(endpoint.get("sampleUrl") or endpoint.get("sample_url") or ""),
        " ".join(map(str, _safe_list(endpoint.get("queryKeys") or endpoint.get("query_keys")))),
        " ".join(map(str, _safe_list(endpoint.get("postKeys") or endpoint.get("post_keys")))),
        str(endpoint.get("sampleBodyPreview") or endpoint.get("sample_body_preview") or ""),
    ]
    haystack = "\n".join(part for part in haystack_parts if part).lower()

    score = 0
    hits: list[str] = []
    for keyword, weight in (
        ("sku", 4),
        ("spec", 3),
        ("price", 4),
        ("stock", 4),
        ("inventory", 4),
        ("save", 2),
        ("draft", 2),
        ("batch", 2),
    ):
        if keyword in haystack:
            score += weight
            hits.append(keyword)

    method = str(endpoint.get("method") or "").upper()
    if method == "POST":
        score += 2
        hits.append("post")

    if _safe_list(endpoint.get("postKeys") or endpoint.get("post_keys")):
        score += 2
        hits.append("postKeys")

    statuses = {str(item) for item in _safe_list(endpoint.get("statuses"))}
    if any(item.startswith("2") for item in statuses):
        score += 1
        hits.append("2xx")

    return score, hits


def summarize_price_stock_capture(payload: dict[str, Any], *, min_score: int = 4) -> dict[str, Any]:
    endpoints = _safe_list(payload.get("endpoints"))
    candidates: list[PriceStockCandidate] = []

    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        score, hits = _score_candidate(endpoint)
        candidates.append(
            PriceStockCandidate(
                method=str(endpoint.get("method") or ""),
                host=str(endpoint.get("host") or ""),
                pathname=str(endpoint.get("pathname") or ""),
                count=int(endpoint.get("count") or 0),
                statuses=[str(item) for item in _safe_list(endpoint.get("statuses"))],
                query_keys=[str(item) for item in _safe_list(endpoint.get("queryKeys") or endpoint.get("query_keys"))],
                post_keys=[str(item) for item in _safe_list(endpoint.get("postKeys") or endpoint.get("post_keys"))],
                candidate_score=score,
                candidate_hits=hits,
                sample_url=str(endpoint.get("sampleUrl") or endpoint.get("sample_url") or ""),
                sample_body_preview=str(endpoint.get("sampleBodyPreview") or endpoint.get("sample_body_preview") or ""),
            )
        )

    candidates.sort(key=lambda item: (-item.candidate_score, -item.count, item.pathname))
    top_candidates = [item.to_dict() for item in candidates if item.candidate_score >= min_score]

    return {
        "stage": PRICE_STOCK_STAGE_KEY,
        "request_count": int(payload.get("requestCount") or payload.get("request_count") or 0),
        "endpoint_count": len(endpoints),
        "candidate_count": len(top_candidates),
        "top_candidates": top_candidates,
        "profile": PriceStockDiscoveryProfile().to_dict(),
    }
