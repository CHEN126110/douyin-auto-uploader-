/**
 * Standalone Chrome DevTools Protocol helpers for MCP (no Flask dependency).
 * Used for authorized local page diagnostics while Chrome runs with --remote-debugging-port.
 */
import * as z from "zod/v4";
import { buildPriceStockCaptureReport } from "./cdp-price-stock.js";
import { probeFxgCategoryMatrix } from "./fxg-category-matrix-probe.js";
import { probeFxgFreightOptions } from "./fxg-freight-probe.js";
import { probeFxgMaterialModules } from "./fxg-material-probe.js";
import { captureFxgProtocolRequests } from "./fxg-protocol-capture.js";
import { probeFxgQualification } from "./fxg-qualification-probe.js";
import { probeFxgRuntimeOptions, probeFxgRuntimeOptionsMatrix } from "./fxg-runtime-options-probe.js";
import { probeFxgSchema } from "./fxg-schema-probe.js";
import { probeFxgSubmitAndSku } from "./fxg-submit-probe.js";
import { probeFxgUploadEndpoints } from "./fxg-upload-probe.js";
import {
  CdpToolError,
  delay,
  getCdpTargets,
  normalizeCdpListUrl,
  withCdpTarget,
} from "./cdp-client.js";

function jsonText(payload) {
  return JSON.stringify(payload, null, 2);
}

function jsonResult(payload) {
  return {
    content: [{ type: "text", text: jsonText(payload) }],
    structuredContent: payload,
  };
}

function errorResult(error) {
  const normalized =
    error instanceof CdpToolError ? error : new CdpToolError(error instanceof Error ? error.message : String(error));
  const payload = {
    success: false,
    error: normalized.message,
    details: normalized.details,
  };
  return {
    isError: true,
    content: [{ type: "text", text: jsonText(payload) }],
    structuredContent: payload,
  };
}

function truncateText(value, maxLength = 12000) {
  if (value == null) return value;
  const text = String(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...<truncated ${text.length - maxLength} chars>`;
}

async function evaluateOnTarget(targetOptions, expression, options = {}) {
  return withCdpTarget(targetOptions, async (client, target) => {
    const result = await client.call("Runtime.evaluate", {
      expression,
      awaitPromise: options.awaitPromise ?? true,
      returnByValue: options.returnByValue ?? true,
    });
    if (result.exceptionDetails) {
      throw new CdpToolError("Browser evaluation failed.", { details: result.exceptionDetails });
    }
    return {
      target: {
        id: target.id,
        title: target.title,
        url: target.url,
        webSocketDebuggerUrl: target.webSocketDebuggerUrl,
      },
      value: result.result?.value ?? null,
    };
  });
}

function browserSnapshotExpression({ includeHtml = false, limit = 30, htmlLimit = 12000, includeHiddenControls = false }) {
  return `(() => {
    const limit = ${Number(limit)};
    const htmlLimit = ${Number(htmlLimit)};
    const includeHiddenControls = ${includeHiddenControls ? "true" : "false"};
    const isVisible = (el) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const rectOf = (el) => {
      const rect = el.getBoundingClientRect();
      return {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        visible: rect.width > 0 && rect.height > 0
      };
    };
    const textOf = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 180);
    const attrs = (el) => ({
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      className: el.className || "",
      name: el.getAttribute("name") || "",
      type: el.getAttribute("type") || "",
      role: el.getAttribute("role") || "",
      placeholder: el.getAttribute("placeholder") || "",
      ariaLabel: el.getAttribute("aria-label") || "",
      attrFieldId: el.getAttribute("attr-field-id") || "",
      text: textOf(el),
      rect: rectOf(el)
    });
    const controls = Array.from(document.querySelectorAll("input,textarea,button,select,a,[role='button'],[role='textbox'],[role='combobox'],[role='radio'],[role='switch']"))
      .filter((el) => includeHiddenControls || isVisible(el))
      .slice(0, limit)
      .map(attrs);
    const sections = Array.from(document.querySelectorAll("[attr-field-id],[data-kora-exposure]"))
      .filter(isVisible)
      .slice(0, limit)
      .map((el) => ({
        ...attrs(el),
        fileInputs: Array.from(el.querySelectorAll("input[type='file']"))
          .slice(0, 12)
          .map((input) => ({
            accept: input.getAttribute("accept") || "",
            disabled: Boolean(input.disabled) || input.getAttribute("aria-disabled") === "true",
            rect: rectOf(input)
          })),
        buttons: Array.from(el.querySelectorAll("button,[role='button'],a"))
          .slice(0, 20)
          .map((button) => ({
            tag: button.tagName.toLowerCase(),
            text: textOf(button),
            disabled: Boolean(button.disabled) || button.getAttribute("aria-disabled") === "true",
            rect: rectOf(button)
          }))
      }));
    const tables = Array.from(document.querySelectorAll("table"))
      .filter(isVisible)
      .slice(0, 6)
      .map((table) => ({
        text: textOf(table).slice(0, 500),
        headers: Array.from(table.querySelectorAll("th")).map(textOf).filter(Boolean).slice(0, 30),
        rowCount: table.querySelectorAll("tr").length
      }));
    return {
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      sections,
      controls,
      tables,
      htmlExcerpt: ${includeHtml ? "document.documentElement.outerHTML.slice(0, htmlLimit)" : "undefined"}
    };
  })()`;
}

function findElementsExpression({ locator, locatorType, includeHtml, limit, onlyVisible }) {
  return `(() => {
    const locator = ${JSON.stringify(locator)};
    const locatorType = ${JSON.stringify(locatorType || "css")};
    const limit = ${Number(limit || 20)};
    const includeHtml = ${includeHtml ? "true" : "false"};
    const onlyVisible = ${onlyVisible === false ? "false" : "true"};
    const isVisible = (el) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const nodes = locatorType === "xpath"
      ? (() => {
          const result = document.evaluate(locator, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
          return Array.from({ length: result.snapshotLength }, (_, index) => result.snapshotItem(index)).filter(Boolean);
        })()
      : Array.from(document.querySelectorAll(locator));
    return nodes
      .filter((el) => !onlyVisible || isVisible(el))
      .slice(0, limit)
      .map((el, index) => {
        const rect = el.getBoundingClientRect();
        return {
          index,
          tag: el.tagName.toLowerCase(),
          id: el.id || "",
          className: el.className || "",
          text: (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 240),
          value: el.value || "",
          name: el.getAttribute("name") || "",
          type: el.getAttribute("type") || "",
          role: el.getAttribute("role") || "",
          placeholder: el.getAttribute("placeholder") || "",
          href: el.getAttribute("href") || "",
          visible: isVisible(el),
          rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          html: includeHtml ? el.outerHTML.slice(0, 3000) : undefined
        };
      });
  })()`;
}

function browserActionExpression(args) {
  const {
    action,
    locator,
    locatorType = "css",
    index = 0,
    value = "",
    url,
    clear = true,
    scrollY = 600,
  } = args;
  return `(() => {
    const action = ${JSON.stringify(action)};
    const locator = ${JSON.stringify(locator || "")};
    const locatorType = ${JSON.stringify(locatorType)};
    const index = ${Number(index || 0)};
    const value = ${JSON.stringify(value || "")};
    const url = ${JSON.stringify(url || "")};
    const clear = ${clear === false ? "false" : "true"};
    const scrollY = ${Number(scrollY || 600)};
    const findNodes = () => {
      if (!locator) return [];
      if (locatorType === "xpath") {
        const result = document.evaluate(locator, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        return Array.from({ length: result.snapshotLength }, (_, i) => result.snapshotItem(i)).filter(Boolean);
      }
      return Array.from(document.querySelectorAll(locator));
    };
    if (action === "navigate") {
      if (!url) throw new Error("url is required for navigate.");
      location.href = url;
      return { ok: true, action, url };
    }
    if (action === "scroll" && !locator) {
      window.scrollBy({ top: scrollY, behavior: "instant" });
      return { ok: true, action, scrollY, url: location.href };
    }
    const el = findNodes()[index];
    if (!el) throw new Error("Element not found.");
    if (action === "scroll") {
      el.scrollIntoView({ block: "center", inline: "center" });
    } else if (action === "click") {
      el.scrollIntoView({ block: "center", inline: "center" });
      el.click();
    } else if (action === "hover") {
      el.scrollIntoView({ block: "center", inline: "center" });
      for (const type of ["mouseover", "mouseenter", "mousemove"]) {
        el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
      }
    } else if (action === "input") {
      el.focus();
      if (clear && "value" in el) el.value = "";
      if ("value" in el) {
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        el.textContent = value;
      }
    } else {
      throw new Error("Unsupported action.");
    }
    return {
      ok: true,
      action,
      locator,
      index,
      url: location.href,
      text: (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 160)
    };
  })()`;
}

function browserFetchExpression({ url, method, headers, body, parseJson }) {
  return `(async () => {
    const response = await fetch(${JSON.stringify(url)}, {
      method: ${JSON.stringify(method || "GET")},
      credentials: "include",
      headers: ${JSON.stringify(headers || {})},
      body: ${body === undefined ? "undefined" : JSON.stringify(typeof body === "string" ? body : JSON.stringify(body))}
    });
    const text = await response.text();
    let json = null;
    if (${parseJson === false ? "false" : "true"}) {
      try { json = JSON.parse(text); } catch {}
    }
    return {
      ok: response.ok,
      status: response.status,
      url: response.url,
      contentType: response.headers.get("content-type"),
      json,
      text: json ? undefined : text.slice(0, 20000)
    };
  })()`;
}

function registerTool(server, name, config, handler) {
  server.registerTool(name, config, async (args) => {
    try {
      return jsonResult(await handler(args ?? {}));
    } catch (error) {
      return errorResult(error);
    }
  });
}

export async function captureNetworkTraffic({
  cdpListUrl,
  webSocketDebuggerUrl,
  targetUrlContains,
  durationMs,
  urlContains,
  resourceTypes,
  maxEntries,
  dedupeByUrl,
  includeResponses,
  includeResponseBody,
  includeFullPostData,
  postDataPreviewLimit,
  responseBodyLimit,
} = {}) {
  const dur = durationMs ?? 8000;
  const cap = maxEntries ?? 300;
  const typesSet = resourceTypes?.length ? new Set(resourceTypes) : null;
  const dedupe = dedupeByUrl !== false;
  const withResponses = includeResponses === true || includeResponseBody === true;
  const withResponseBody = includeResponseBody === true;
  const withFullPostData = includeFullPostData === true;
  const requestBodyPreviewLimit = postDataPreviewLimit ?? 4000;
  const bodyLimit = responseBodyLimit ?? 12000;

  return withCdpTarget({ cdpListUrl, webSocketDebuggerUrl, targetUrlContains }, async (client, target) => {
    const rows = [];
    const seen = new Map();
    const entriesByRequestId = new Map();
    const requestBodyTasks = new Map();
    const responseBodyTasks = new Map();

    const matchesFilters = (url, resourceType) => {
      if (!url) return false;
      if (urlContains && !url.includes(urlContains)) return false;
      if (typesSet && !typesSet.has(resourceType)) return false;
      return true;
    };

    const rememberEntry = (entry) => {
      entriesByRequestId.set(entry.requestId, entry);
      if (!dedupe) {
        rows.push(entry);
      }
    };

    const off = client.onEvent((method, params) => {
      if (method === "Network.requestWillBeSent") {
        const req = params.request;
        if (!req?.url || !matchesFilters(req.url, params.type)) return;
        if (entriesByRequestId.size >= cap) return;

        const entry = {
          requestId: params.requestId,
          url: req.url,
          method: req.method || "GET",
          resourceType: params.type,
          postData: req.postData ? truncateText(req.postData, requestBodyPreviewLimit) : undefined,
          postDataPreview: req.postData ? truncateText(req.postData, requestBodyPreviewLimit) : undefined,
        };

        rememberEntry(entry);
        if (dedupe) {
          seen.set(req.url, entry);
        }

        if (withFullPostData && !requestBodyTasks.has(params.requestId) && req.hasPostData) {
          const task = client
            .call("Network.getRequestPostData", { requestId: params.requestId })
            .then((postDataResult) => {
              const fullPostData = postDataResult?.postData ?? "";
              if (fullPostData) {
                entry.postData = fullPostData;
                entry.postDataFull = fullPostData;
                entry.postDataPreview = truncateText(fullPostData, requestBodyPreviewLimit);
              }
            })
            .catch((error) => {
              entry.postDataError = error instanceof Error ? error.message : String(error);
            })
            .finally(() => {
              requestBodyTasks.delete(params.requestId);
            });
          requestBodyTasks.set(params.requestId, task);
        }
        return;
      }

      if (method === "Network.responseReceived") {
        if (!withResponses) return;
        const entry = entriesByRequestId.get(params.requestId);
        const response = params.response;
        if (!entry || !response?.url || !matchesFilters(response.url, params.type || entry.resourceType)) return;

        entry.status = response.status ?? null;
        entry.statusText = response.statusText || "";
        entry.mimeType = response.mimeType || "";
        entry.responseUrl = response.url || entry.url;
        entry.remoteIPAddress = response.remoteIPAddress || "";
        entry.fromDiskCache = Boolean(response.fromDiskCache);
        entry.fromServiceWorker = Boolean(response.fromServiceWorker);
        entry.responseHeaders = response.headers ?? {};
        return;
      }

      if (method === "Network.loadingFinished") {
        if (!withResponseBody) return;
        const entry = entriesByRequestId.get(params.requestId);
        if (!entry) return;
        if (responseBodyTasks.has(params.requestId)) return;
        if (!["XHR", "Fetch", "Document"].includes(entry.resourceType)) return;

        const task = client
          .call("Network.getResponseBody", { requestId: params.requestId })
          .then((bodyResult) => {
            entry.responseBodyBase64Encoded = Boolean(bodyResult?.base64Encoded);
            if (bodyResult?.base64Encoded) {
              entry.responseBodyPreview = "[base64 body omitted]";
            } else {
              entry.responseBodyPreview = truncateText(bodyResult?.body ?? "", bodyLimit);
            }
          })
          .catch((error) => {
            entry.responseBodyError = error instanceof Error ? error.message : String(error);
          })
          .finally(() => {
            responseBodyTasks.delete(params.requestId);
          });
        responseBodyTasks.set(params.requestId, task);
      }
    });

    try {
      await client.call("Network.enable", {
        maxTotalBufferSize: 10000000,
        maxResourceBufferSize: 5000000,
        ...(withFullPostData ? { maxPostDataSize: 10 * 1024 * 1024 } : {}),
      });
      await delay(Math.min(dur, 60000));
      if (requestBodyTasks.size > 0) {
        await Promise.allSettled(Array.from(requestBodyTasks.values()));
      }
      if (responseBodyTasks.size > 0) {
        await Promise.allSettled(Array.from(responseBodyTasks.values()));
      }
    } finally {
      off();
    }

    const requests = dedupe ? Array.from(seen.values()) : rows;
    return {
      cdpListUrl: normalizeCdpListUrl(cdpListUrl),
      target: {
        id: target.id,
        title: target.title,
        url: target.url,
      },
      durationMs: dur,
      count: requests.length,
      hint:
        "Operate the page during the capture window, or increase durationMs. Use urlContains like fxg.jinritemai.com to focus API hosts. Enable includeResponses / includeResponseBody only for short, targeted captures.",
      includeResponses: withResponses,
      includeResponseBody: withResponseBody,
      includeFullPostData: withFullPostData,
      requests,
    };
  });
}

export function registerCdpTools(server) {
  registerTool(
    server,
    "cdp_discover_targets",
    {
      description:
        "List Chrome DevTools targets from /json/list (remote debugging). Use before other cdp_* tools. Set DOUYIN_CDP_LIST_URL if not using default 9333.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional().describe("Defaults to DOUYIN_CDP_LIST_URL or http://127.0.0.1:9333/json/list."),
      },
    },
    async ({ cdpListUrl }) => ({
      cdpListUrl: normalizeCdpListUrl(cdpListUrl),
      targets: await getCdpTargets(cdpListUrl),
    })
  );

  registerTool(
    server,
    "cdp_environment_check",
    {
      description:
        "Check whether the configured Chrome DevTools endpoint is reachable and whether a matching FXG publish page target exists. Read-only diagnostics; it does not launch or control Chrome.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional().describe("Defaults to DOUYIN_CDP_LIST_URL or http://127.0.0.1:9333/json/list."),
        targetUrlContains: z.string().optional().describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
      },
    },
    async ({ cdpListUrl, targetUrlContains }) => {
      const normalizedUrl = normalizeCdpListUrl(cdpListUrl);
      const targetHint = targetUrlContains || "fxg.jinritemai.com/ffa/g/create";
      try {
        const targets = await getCdpTargets(normalizedUrl);
        const pageTargets = targets.filter((item) => item.type === "page");
        const matchingTargets = pageTargets.filter(
          (item) => String(item.url || "").includes(targetHint) || String(item.title || "").includes(targetHint)
        );
        let pageState = null;
        let pageStateError = "";
        if (matchingTargets.length > 0) {
          try {
            const inspected = await evaluateOnTarget(
              { cdpListUrl: normalizedUrl, targetUrlContains: targetHint },
              `(() => {
                const text = document.body?.innerText || "";
                const attrFields = Array.from(document.querySelectorAll("[attr-field-id]"))
                  .slice(0, 30)
                  .map((el) => el.getAttribute("attr-field-id"))
                  .filter(Boolean);
                return {
                  href: location.href,
                  title: document.title,
                  readyState: document.readyState,
                  hasLoginText: /登录|扫码|手机号|验证码/.test(text),
                  hasPublishFields: /商品标题|主图上传|类目属性|图文信息|价格与库存|下一步/.test(text),
                  attrFields,
                  textSample: text.slice(0, 500)
                };
              })()`
            );
            pageState = inspected.value;
          } catch (error) {
            pageStateError = error instanceof Error ? error.message : String(error);
          }
        }
        const pageLooksReady = Boolean(pageState && !pageState.hasLoginText && pageState.hasPublishFields);
        return {
          ok: true,
          cdpListUrl: normalizedUrl,
          targetUrlContains: targetHint,
          targetCount: targets.length,
          pageTargetCount: pageTargets.length,
          matchingTargetCount: matchingTargets.length,
          matchingTargets: matchingTargets.map((item) => ({
            id: item.id,
            title: item.title,
            url: item.url,
          })),
          pageState,
          pageStateError: pageStateError || undefined,
          readyForFxgProtocolProbe: matchingTargets.length > 0 && pageLooksReady,
          nextStep: matchingTargets.length && pageLooksReady
            ? "Run the read-only FXG probes or a targeted local preflight capture."
            : "Open the logged-in FXG publish page in a Chrome instance that was started with a remote debugging port.",
        };
      } catch (error) {
        return {
          ok: false,
          cdpListUrl: normalizedUrl,
          targetUrlContains: targetHint,
          readyForFxgProtocolProbe: false,
          error: error instanceof Error ? error.message : String(error),
          nextStep:
            "No Chrome DevTools endpoint is reachable. Do not claim live page evidence until Chrome is running with --remote-debugging-port and the logged-in FXG page is visible in /json/list.",
        };
      }
    }
  );

  registerTool(
    server,
    "cdp_page_snapshot",
    {
      description: "Inspect the selected tab for authorized local debugging: URL, title, controls, attr-field sections, file inputs, and tables.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional().describe("Pick first page whose URL or title contains this substring."),
        includeHtml: z.boolean().optional(),
        includeHiddenControls: z.boolean().optional().describe("Default false. Enable to include hidden upload inputs for UI debugging."),
        limit: z.number().int().min(1).max(100).optional(),
      },
    },
    async (args) => evaluateOnTarget(args, browserSnapshotExpression(args))
  );

  registerTool(
    server,
    "cdp_find_elements",
    {
      description: "Find elements by CSS selector or XPath on the selected tab.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional(),
        locator: z.string().min(1),
        locatorType: z.enum(["css", "xpath"]).optional(),
        includeHtml: z.boolean().optional(),
        onlyVisible: z.boolean().optional(),
        limit: z.number().int().min(1).max(100).optional(),
      },
    },
    async (args) => evaluateOnTarget(args, findElementsExpression(args))
  );

  registerTool(
    server,
    "cdp_action",
    {
      description: "CDP-driven UI action: navigate, click, hover, input, or scroll.",
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional(),
        action: z.enum(["navigate", "click", "hover", "input", "scroll"]),
        locator: z.string().optional(),
        locatorType: z.enum(["css", "xpath"]).optional(),
        index: z.number().int().min(0).max(100).optional(),
        value: z.string().optional(),
        url: z.string().url().optional(),
        clear: z.boolean().optional(),
        scrollY: z.number().optional(),
      },
    },
    async (args) => evaluateOnTarget(args, browserActionExpression(args))
  );

  registerTool(
    server,
    "cdp_evaluate",
    {
      description: "Evaluate JavaScript in the page context (short snippets only).",
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional(),
        expression: z.string().min(1),
        awaitPromise: z.boolean().optional(),
      },
    },
    async (args) =>
      evaluateOnTarget(args, args.expression, {
        awaitPromise: args.awaitPromise ?? true,
      })
  );

  registerTool(
    server,
    "cdp_fetch_json",
    {
      description:
        "Run a low-frequency fetch() inside the user's already logged-in page for authorized diagnostics. Do not use for login bypass, token extraction, or platform-control bypass.",
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional(),
        url: z.string().url(),
        method: z.enum(["GET", "POST"]).optional(),
        headers: z.record(z.string(), z.string()).optional(),
        body: z.unknown().optional(),
        parseJson: z.boolean().optional(),
      },
    },
    async (args) => evaluateOnTarget(args, browserFetchExpression(args))
  );

  registerTool(
    server,
    "cdp_network_capture",
    {
      description:
        "Subscribe to CDP Network events for a few seconds to list page requests for authorized diagnostics. Can optionally include response status, headers, and body preview. Chrome must run with remote debugging.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional(),
        durationMs: z.number().int().min(500).max(60000).optional().describe("How long to listen (default 8000)."),
        urlContains: z.string().optional().describe("Only keep requests whose URL includes this substring."),
        resourceTypes: z
          .array(z.enum(["Document", "XHR", "Fetch", "Script", "Stylesheet", "Image", "Media", "Font", "WebSocket", "Other"]))
          .optional()
          .describe("If set, only these CDP resource types are kept."),
        maxEntries: z.number().int().min(1).max(500).optional(),
        dedupeByUrl: z.boolean().optional().describe("Default true: collapse identical URLs keeping latest."),
        includeResponses: z.boolean().optional().describe("Also capture response status / mimeType / response headers."),
        includeFullPostData: z
          .boolean()
          .optional()
          .describe("Use Network.getRequestPostData to capture the full request body for matching requests. Default false."),
        includeResponseBody: z
          .boolean()
          .optional()
          .describe("Capture a preview of response bodies after loadingFinished. Prefer XHR/Fetch and short durations."),
        postDataPreviewLimit: z.number().int().min(200).max(50000).optional().describe("Preview length for request body snippets, default 4000."),
        responseBodyLimit: z.number().int().min(200).max(50000).optional().describe("Max response body preview length, default 12000."),
      },
    },
    async ({
      cdpListUrl,
      webSocketDebuggerUrl,
      targetUrlContains,
      durationMs,
      urlContains,
      resourceTypes,
      maxEntries,
      dedupeByUrl,
      includeResponses,
      includeFullPostData,
      includeResponseBody,
      postDataPreviewLimit,
      responseBodyLimit,
    }) =>
      captureNetworkTraffic({
        cdpListUrl,
        webSocketDebuggerUrl,
        targetUrlContains,
        durationMs,
        urlContains,
        resourceTypes,
        maxEntries,
        dedupeByUrl,
        includeResponses,
        includeFullPostData,
        includeResponseBody,
        postDataPreviewLimit,
        responseBodyLimit,
      })
  );

  registerTool(
    server,
    "cdp_capture_price_stock_candidates",
    {
      description:
        "Capture XHR/Fetch traffic on the publish page and summarize price/stock API candidates for authorized local diagnostics.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        webSocketDebuggerUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create so it targets the publish page."),
        durationMs: z.number().int().min(500).max(60000).optional().describe("Capture window in milliseconds."),
        urlContains: z.string().optional().describe("Optional request URL substring filter."),
        maxEntries: z.number().int().min(1).max(500).optional(),
        includeResponseBody: z
          .boolean()
          .optional()
          .describe("Include a preview of response bodies. Only use for short targeted captures."),
        responseBodyLimit: z.number().int().min(200).max(50000).optional(),
        minCandidateScore: z
          .number()
          .int()
          .min(0)
          .max(100)
          .optional()
          .describe("Only endpoints at or above this score are returned in topCandidates. Default 4."),
      },
    },
    async ({
      cdpListUrl,
      webSocketDebuggerUrl,
      targetUrlContains,
      durationMs,
      urlContains,
      maxEntries,
      includeResponseBody,
      responseBodyLimit,
      minCandidateScore,
    }) => {
      const capture = await captureNetworkTraffic({
        cdpListUrl,
        webSocketDebuggerUrl,
        targetUrlContains: targetUrlContains || "fxg.jinritemai.com/ffa/g/create",
        durationMs: durationMs ?? 15000,
        urlContains,
        resourceTypes: ["XHR", "Fetch"],
        maxEntries: maxEntries ?? 400,
        dedupeByUrl: false,
        includeResponses: true,
        includeResponseBody: includeResponseBody ?? false,
        responseBodyLimit: responseBodyLimit ?? 20000,
      });
      return buildPriceStockCaptureReport(capture, {
        minCandidateScore: minCandidateScore ?? 4,
      });
    }
  );

  registerTool(
    server,
    "cdp_fxg_schema_probe",
    {
      description:
        "Read-only FXG publish schema probe. Uses the logged-in page runtime to search a category and call getSchema without submitting or saving drafts.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        categoryKeyword: z.string().optional().describe("Category search keyword. Default: 长筒袜."),
        categoryId: z.string().optional().describe("Optional leaf category id. If set, category search is skipped."),
        operationType: z.string().optional().describe("Default: select_normal,normal."),
        timeoutMs: z.number().int().min(1000).max(60000).optional(),
      },
    },
    async (args) => probeFxgSchema(args)
  );

  registerTool(
    server,
    "cdp_fxg_category_matrix_probe",
    {
      description:
        "Read-only FXG multi-category schema capability matrix. Compares required fields, category properties, spec axes, and SKU columns across categories to prevent hardcoded category assumptions.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        categories: z
          .array(
            z.object({
              keyword: z.string().optional(),
              categoryId: z.string().optional(),
            })
          )
          .optional()
          .describe("List of categories to probe. Each item can provide keyword, categoryId, or both."),
        categoryKeywords: z.string().optional().describe("Comma-separated category keywords if categories is not provided."),
        categoryIds: z.string().optional().describe("Comma-separated leaf category ids if categories is not provided."),
        optionKeywords: z.array(z.string()).optional().describe("Option keywords to exact-match in category properties."),
        operationType: z.string().optional().describe("Default: select_normal,normal."),
        timeoutMs: z.number().int().min(1000).max(60000).optional(),
        includeRaw: z.boolean().optional().describe("Default false. Keep false to avoid large outputs."),
      },
    },
    async (args) => probeFxgCategoryMatrix(args)
  );

  registerTool(
    server,
    "cdp_fxg_runtime_options_probe",
      {
        description:
          "Read-only FXG runtime options probe for settings UI. Returns selected category, required category properties, spec axes, SKU columns, publish controls, and real freight templates from the logged-in page runtime. Pass categoryKeywords for a compact multi-category matrix.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
          categoryKeyword: z.string().optional().describe("Category search keyword. Default: 长筒袜."),
          categoryKeywords: z
            .array(z.string())
            .optional()
            .describe("Optional keyword list for a compact multi-category settings matrix."),
          categoryId: z.string().optional().describe("Optional leaf category id. If set, category search is skipped."),
          operationType: z.string().optional().describe("Default: select_normal,normal."),
          timeoutMs: z.number().int().min(1000).max(60000).optional(),
          includeFreight: z.boolean().optional().describe("Default true."),
        },
      },
      async (args) => {
        if (Array.isArray(args?.categoryKeywords) && args.categoryKeywords.length > 0) {
          return probeFxgRuntimeOptionsMatrix(args);
        }
        return probeFxgRuntimeOptions(args);
      }
    );

  registerTool(
    server,
    "cdp_fxg_freight_probe",
    {
      description:
        "Read-only FXG freight template probe. Uses the logged-in page runtime to inspect schema freight actions and trigger the front-end freight_template_options_load data action without submitting or saving drafts.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        categoryKeyword: z.string().optional().describe("Category search keyword. Default: 长筒袜."),
        categoryId: z.string().optional().describe("Optional leaf category id. If set, category search is skipped."),
        timeoutMs: z.number().int().min(1000).max(60000).optional(),
        waitAfterActionMs: z.number().int().min(0).max(10000).optional(),
        triggerAction: z.boolean().optional().describe("Default true. Set false to only inspect schema/runtime state."),
      },
    },
    async (args) => probeFxgFreightOptions(args)
  );

  registerTool(
    server,
    "cdp_fxg_upload_probe",
    {
      description:
        "FXG upload endpoint probe. By default it only scans Webpack modules. If uploadImagePath is provided, it explicitly uploads one local sample image to /product/img/batchupload and returns sanitized response shape.",
      annotations: { readOnlyHint: false },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        maxModules: z.number().int().min(1).max(300).optional(),
        uploadImagePath: z
          .string()
          .optional()
          .describe("Optional local image path. When omitted, no upload is performed."),
        uploadMode: z.enum(["single", "batch"]).optional().describe("Default single."),
      },
    },
    async (args) => probeFxgUploadEndpoints(args)
  );

  registerTool(
    server,
    "cdp_fxg_material_probe",
    {
      description:
        "Read-only FXG material module probe. Scans logged-in page Webpack modules for saveMaterial/materialDetail/batchApplyMaterial, material type constants, and media payload snippets without sending save or submit requests.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        maxModules: z.number().int().min(1).max(300).optional(),
        snippetRadius: z.number().int().min(200).max(3000).optional(),
      },
    },
    async (args) => probeFxgMaterialModules(args)
  );

  registerTool(
    server,
    "cdp_fxg_qualification_probe",
    {
      description:
        "Read-only FXG qualification probe. Scans the logged-in publish page for qualification-related DOM sections, submit schema shape, and module snippets without uploading, saving, drafting, or publishing.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        maxModules: z.number().int().min(1).max(300).optional(),
        snippetRadius: z.number().int().min(300).max(4000).optional(),
      },
    },
    async (args) => probeFxgQualification(args)
  );

  registerTool(
    server,
    "cdp_fxg_protocol_capture",
    {
      description:
        "Targeted FXG publish-page request observer for authorized local diagnostics. Captures sanitized request summaries for endpoints such as batchupload/saveMaterial/materialDetail/addWithSchema during a short live page operation window. Optional blockMatchedRequests performs local request preflight by recording the sanitized summary and aborting matched requests before they reach the server.",
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        durationMs: z.number().int().min(1000).max(120000).optional(),
        maxEntries: z.number().int().min(1).max(200).optional(),
        postDataPreviewLimit: z.number().int().min(200).max(50000).optional(),
        includeResponseBody: z.boolean().optional().describe("Default false."),
        responseBodyLimit: z.number().int().min(200).max(50000).optional(),
        urlPatterns: z.array(z.string()).optional().describe("Optional URL substrings. Defaults to FXG publish endpoints."),
        blockMatchedRequests: z
          .boolean()
          .optional()
          .describe("Default false. When true, matching blockUrlPatterns are recorded and aborted at request stage for local preflight."),
        blockUrlPatterns: z
          .array(z.string())
          .optional()
          .describe("Optional URL substrings to abort. Defaults to urlPatterns when blockMatchedRequests is true."),
        blockedErrorReason: z.string().optional().describe("CDP Fetch.failRequest errorReason. Defaults to Aborted."),
      },
    },
    async (args) => captureFxgProtocolRequests(args)
  );

  registerTool(
    server,
    "cdp_fxg_submit_probe",
    {
      description:
        "Read-only FXG submit/SKU module probe. Scans the logged-in page Webpack modules for addWithSchema/editWithSchema and spec/sku model-generation snippets without submitting.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z
          .string()
          .optional()
          .describe("Defaults to fxg.jinritemai.com/ffa/g/create."),
        maxModules: z.number().int().min(1).max(300).optional(),
      },
    },
    async (args) => probeFxgSubmitAndSku(args)
  );

  server.registerPrompt(
    "investigate-douyin-fxg-api",
    {
      description: "Use CDP tools to discover FXG / Douyin ecommerce JSON endpoints from a logged-in Chrome tab.",
      argsSchema: {
        targetUrlContains: z.string().optional(),
        urlFilter: z.string().optional(),
      },
    },
    ({ targetUrlContains, urlFilter }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `1) Ensure Chrome/Edge runs with remote debugging (e.g. --remote-debugging-port=9333) and the Douyin/FXG tab is open.\n` +
              `2) For publish schema mining, prefer cdp_fxg_schema_probe first; it is read-only and returns category, model fields, category properties, and SKU/spec structure.\n` +
              `3) For price/stock mining, prefer cdp_capture_price_stock_candidates with targetUrlContains=${JSON.stringify(targetUrlContains || "fxg.jinritemai.com/ffa/g/create")} and durationMs 8000-15000 while table write actions are triggered.\n` +
              `4) For broader interface mining, use cdp_network_capture with targetUrlContains=${JSON.stringify(targetUrlContains || "fxg")} and urlContains=${JSON.stringify(urlFilter || "jinritemai")}.\n` +
              `5) Summarize candidate API base paths and parameters from captured URLs; optionally verify one endpoint with cdp_fetch_json (low frequency).\n` +
              `6) Do not hammer endpoints or bypass platform ToS.`,
          },
        },
      ],
    })
  );
}

export { getDefaultCdpListUrl as getConfiguredCdpListUrl } from "./cdp-client.js";
