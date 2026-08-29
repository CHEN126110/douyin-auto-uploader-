function normalizeUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return {
      host: url.host,
      pathname: url.pathname,
      queryKeys: Array.from(url.searchParams.keys()).slice(0, 50),
    };
  } catch {
    return {
      host: "",
      pathname: rawUrl,
      queryKeys: [],
    };
  }
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function pickPostKeys(postData) {
  if (!postData) return [];
  const parsed = safeJsonParse(postData);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    return Object.keys(parsed).slice(0, 50);
  }
  if (typeof postData === "string" && postData.includes("=") && postData.includes("&")) {
    return postData
      .split("&")
      .map((item) => item.split("=")[0])
      .filter(Boolean)
      .slice(0, 50);
  }
  return [];
}

function scorePriceStockCandidate(row) {
  const haystack = [
    row.pathname,
    row.url,
    ...(row.queryKeys || []),
    ...(row.postKeys || []),
    row.responseBodyPreview || "",
  ]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();

  let score = 0;
  const hits = [];

  const keywordGroups = [
    ["sku", 4],
    ["spec", 3],
    ["price", 4],
    ["stock", 4],
    ["inventory", 4],
    ["quantity", 2],
    ["batch", 2],
    ["save", 2],
    ["draft", 2],
    ["publish", 1],
    ["template", 1],
  ];

  for (const [keyword, weight] of keywordGroups) {
    if (haystack.includes(keyword)) {
      score += weight;
      hits.push(keyword);
    }
  }

  if (row.method === "POST") {
    score += 2;
    hits.push("post");
  }

  if ((row.postKeys || []).length > 0) {
    score += 2;
    hits.push("postKeys");
  }

  if (row.status && Number(row.status) >= 200 && Number(row.status) < 300) {
    score += 1;
    hits.push("2xx");
  }

  return { score, hits };
}

export function summarizePriceStockRequests(requests = []) {
  const normalizedRows = requests.map((row) => {
    const normalized = normalizeUrl(row.url);
    const postKeys = pickPostKeys(row.postData);
    const candidate = scorePriceStockCandidate({
      ...row,
      ...normalized,
      postKeys,
    });
    return {
      ...row,
      ...normalized,
      postKeys,
      candidateScore: candidate.score,
      candidateHits: candidate.hits,
    };
  });

  const grouped = new Map();
  for (const row of normalizedRows) {
    const key = `${row.method} ${row.host}${row.pathname}`;
    const existing = grouped.get(key) || {
      method: row.method,
      host: row.host,
      pathname: row.pathname,
      count: 0,
      statuses: new Set(),
      queryKeys: new Set(),
      postKeys: new Set(),
      bestCandidateScore: 0,
      candidateHits: new Set(),
      sampleUrl: row.url,
      sampleBodyPreview: row.responseBodyPreview || "",
    };
    existing.count += 1;
    if (row.status != null) existing.statuses.add(String(row.status));
    for (const item of row.queryKeys || []) existing.queryKeys.add(item);
    for (const item of row.postKeys || []) existing.postKeys.add(item);
    for (const item of row.candidateHits || []) existing.candidateHits.add(item);
    existing.bestCandidateScore = Math.max(existing.bestCandidateScore, row.candidateScore || 0);
    if (!existing.sampleBodyPreview && row.responseBodyPreview) {
      existing.sampleBodyPreview = row.responseBodyPreview;
    }
    grouped.set(key, existing);
  }

  const endpoints = Array.from(grouped.values())
    .map((item) => ({
      method: item.method,
      host: item.host,
      pathname: item.pathname,
      count: item.count,
      statuses: Array.from(item.statuses).sort(),
      queryKeys: Array.from(item.queryKeys).slice(0, 50),
      postKeys: Array.from(item.postKeys).slice(0, 50),
      bestCandidateScore: item.bestCandidateScore,
      candidateHits: Array.from(item.candidateHits),
      sampleUrl: item.sampleUrl,
      sampleBodyPreview: item.sampleBodyPreview,
    }))
    .sort((left, right) => {
      if (right.bestCandidateScore !== left.bestCandidateScore) {
        return right.bestCandidateScore - left.bestCandidateScore;
      }
      return right.count - left.count;
    });

  return {
    normalizedRows,
    endpoints,
    topCandidates: endpoints.filter((item) => item.bestCandidateScore >= 4).slice(0, 30),
  };
}

export function buildPriceStockCaptureReport(capture, options = {}) {
  const summary = summarizePriceStockRequests(capture?.requests || []);
  const minScore = Number.isFinite(options.minCandidateScore) ? Number(options.minCandidateScore) : 4;
  return {
    ok: true,
    stage: "price_stock",
    capture,
    requestCount: summary.normalizedRows.length,
    endpointCount: summary.endpoints.length,
    topCandidateCount: summary.endpoints.filter((item) => item.bestCandidateScore >= minScore).length,
    topCandidates: summary.endpoints.filter((item) => item.bestCandidateScore >= minScore).slice(0, 30),
    endpoints: summary.endpoints,
    rawRequests: summary.normalizedRows,
    minCandidateScore: minScore,
  };
}
