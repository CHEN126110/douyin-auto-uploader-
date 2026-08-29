from __future__ import annotations

import json
from typing import Any


_CAPTURE_STATE_KEY = "__codexPriceStockProtocol"


def arm_price_stock_protocol_capture(main_tab: Any) -> dict[str, Any]:
    script = f"""
(() => {{
  const key = "{_CAPTURE_STATE_KEY}";
  const endpointPattern = /\\/product\\/tproduct\\/(?:add|edit)WithSchema/;
  const ensureState = () => {{
    if (!window[key]) {{
      window[key] = {{
        installed: false,
        installedAt: '',
        version: 1,
        replaying: false,
        records: []
      }};
    }}
    return window[key];
  }};
  const state = ensureState();
  state.records = [];
  if (state.installed) {{
    return {{
      ok: true,
      installed: true,
      records: state.records.length,
      installedAt: state.installedAt,
      version: state.version
    }};
  }}

  const normalizeHeaders = (value) => {{
    const headers = {{}};
    if (!value) return headers;
    try {{
      if (value instanceof Headers) {{
        value.forEach((item, headerKey) => {{
          headers[String(headerKey || '')] = String(item || '');
        }});
        return headers;
      }}
      if (Array.isArray(value)) {{
        value.forEach((item) => {{
          if (Array.isArray(item) && item.length >= 2) {{
            headers[String(item[0] || '')] = String(item[1] || '');
          }}
        }});
        return headers;
      }}
      Object.keys(value).forEach((headerKey) => {{
        headers[String(headerKey || '')] = String(value[headerKey] || '');
      }});
    }} catch (error) {{
      headers.__header_error__ = String(error && error.message ? error.message : error);
    }}
    return headers;
  }};

  const normalizeBody = async (body, request) => {{
    if (body == null) {{
      if (request && typeof request.clone === 'function') {{
        try {{
          return await request.clone().text();
        }} catch (error) {{
          return `[[request-body-read-failed:${{String(error && error.message ? error.message : error)}}]]`;
        }}
      }}
      return '';
    }}
    if (typeof body === 'string') return body;
    if (body instanceof URLSearchParams) return body.toString();
    if (body instanceof FormData) {{
      const pairs = [];
      body.forEach((item, name) => {{
        if (typeof item === 'string') {{
          pairs.push(`${{name}}=${{item}}`);
        }} else {{
          pairs.push(`${{name}}=[[binary:${{item && item.name ? item.name : 'blob'}}]]`);
        }}
      }});
      return pairs.join('&');
    }}
    if (body instanceof Blob) {{
      try {{
        return await body.text();
      }} catch (error) {{
        return `[[blob-read-failed:${{String(error && error.message ? error.message : error)}}]]`;
      }}
    }}
    return String(body);
  }};

  const originalFetch = window.fetch ? window.fetch.bind(window) : null;
  if (originalFetch) {{
    window.fetch = async function(input, init) {{
      const request = input instanceof Request ? input : null;
      const url = String(request ? request.url : input || '');
      const method = String((init && init.method) || (request && request.method) || 'GET').toUpperCase();
      const requestHeaders = normalizeHeaders((init && init.headers) || (request && request.headers) || null);
      const shouldCapture = !state.replaying && endpointPattern.test(url);
      const bodyText = shouldCapture ? await normalizeBody(init && init.body, request) : '';
      const startedAt = new Date().toISOString();
      const response = await originalFetch(input, init);
      if (shouldCapture) {{
        let responseText = '';
        try {{
          responseText = await response.clone().text();
        }} catch (error) {{
          responseText = `[[response-read-failed:${{String(error && error.message ? error.message : error)}}]]`;
        }}
        state.records.push({{
          channel: 'fetch',
          method,
          url,
          headers: requestHeaders,
          bodyText,
          status: response.status,
          ok: !!response.ok,
          responseText,
          capturedAt: startedAt
        }});
      }}
      return response;
    }};
  }}

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url) {{
    this.__codexPriceStockMeta = {{
      method: String(method || 'GET').toUpperCase(),
      url: String(url || ''),
      headers: {{}},
      bodyText: '',
      capturedAt: ''
    }};
    return originalOpen.apply(this, arguments);
  }};

  XMLHttpRequest.prototype.setRequestHeader = function(headerKey, headerValue) {{
    if (this.__codexPriceStockMeta) {{
      this.__codexPriceStockMeta.headers[String(headerKey || '')] = String(headerValue || '');
    }}
    return originalSetRequestHeader.apply(this, arguments);
  }};

  XMLHttpRequest.prototype.send = function(body) {{
    const meta = this.__codexPriceStockMeta || null;
    const shouldCapture = !!meta && !state.replaying && endpointPattern.test(String(meta.url || ''));
    if (shouldCapture) {{
      meta.bodyText = typeof body === 'string'
        ? body
        : body instanceof URLSearchParams
          ? body.toString()
          : body == null
            ? ''
            : String(body);
      meta.capturedAt = new Date().toISOString();
      this.addEventListener('loadend', function() {{
        state.records.push({{
          channel: 'xhr',
          method: meta.method,
          url: meta.url,
          headers: meta.headers,
          bodyText: meta.bodyText,
          status: this.status,
          ok: this.status >= 200 && this.status < 300,
          responseText: String(this.responseText || ''),
          capturedAt: meta.capturedAt
        }});
      }});
    }}
    return originalSend.apply(this, arguments);
  }};

  state.installed = true;
  state.installedAt = new Date().toISOString();
  return {{
    ok: true,
    installed: true,
    records: state.records.length,
    installedAt: state.installedAt,
    version: state.version
  }};
}})()
"""
    return main_tab.run_js(script) or {}


def reset_price_stock_protocol_capture(main_tab: Any) -> dict[str, Any]:
    script = f"""
(() => {{
  const state = window["{_CAPTURE_STATE_KEY}"];
  if (!state) {{
    return {{ ok: true, installed: false, cleared: 0 }};
  }}
  const cleared = Array.isArray(state.records) ? state.records.length : 0;
  state.records = [];
  state.replaying = false;
  return {{ ok: true, installed: !!state.installed, cleared }};
}})()
"""
    return main_tab.run_js(script) or {}


def read_price_stock_protocol_capture(main_tab: Any) -> dict[str, Any] | None:
    script = f"""
(() => {{
  const state = window["{_CAPTURE_STATE_KEY}"];
  if (!state || !Array.isArray(state.records) || !state.records.length) {{
    return null;
  }}
  return state.records[state.records.length - 1] || null;
}})()
"""
    return main_tab.run_js(script)


def replay_price_stock_protocol_request(
    main_tab: Any,
    *,
    url: str,
    method: str,
    headers: dict[str, Any] | None,
    body_text: str,
) -> dict[str, Any]:
    safe_headers = json.dumps(dict(headers or {}), ensure_ascii=False)
    safe_url = json.dumps(str(url or ""))
    safe_method = json.dumps(str(method or "POST").upper())
    safe_body = json.dumps(str(body_text or ""), ensure_ascii=False)
    script = f"""
(() => {{
  const state = window["{_CAPTURE_STATE_KEY}"] || (window["{_CAPTURE_STATE_KEY}"] = {{ records: [], replaying: false }});
  const url = {safe_url};
  const method = {safe_method};
  const headers = {safe_headers};
  const bodyText = {safe_body};
  const forbidden = new Set([
    'accept-charset',
    'accept-encoding',
    'access-control-request-headers',
    'access-control-request-method',
    'connection',
    'content-length',
    'cookie',
    'cookie2',
    'date',
    'dnt',
    'expect',
    'host',
    'keep-alive',
    'origin',
    'referer',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
    'via'
  ]);
  state.replaying = true;
  try {{
    const xhr = new XMLHttpRequest();
    xhr.open(method, url, false);
    xhr.withCredentials = true;
    Object.keys(headers || {{}}).forEach((headerKey) => {{
      const lower = String(headerKey || '').trim().toLowerCase();
      if (!lower || forbidden.has(lower)) {{
        return;
      }}
      try {{
        xhr.setRequestHeader(headerKey, String(headers[headerKey] || ''));
      }} catch (error) {{
      }}
    }});
    xhr.send(bodyText);
    return {{
      ok: xhr.status >= 200 && xhr.status < 300,
      status: xhr.status,
      responseText: String(xhr.responseText || ''),
      responseUrl: xhr.responseURL || url
    }};
  }} finally {{
    state.replaying = false;
  }}
}})()
"""
    return main_tab.run_js(script) or {}
