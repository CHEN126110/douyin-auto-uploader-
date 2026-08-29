/**
 * Shared Chrome DevTools Protocol client utilities.
 * Keep this file focused on target discovery, socket lifecycle, and low-level helpers.
 */
import WebSocket from "ws";

export const DEFAULT_CDP_LIST_URL = "http://127.0.0.1:9333/json/list";

export function getDefaultCdpListUrl() {
  return process.env.DOUYIN_CDP_LIST_URL || DEFAULT_CDP_LIST_URL;
}

export class CdpToolError extends Error {
  constructor(message, context = {}) {
    super(message);
    this.name = "CdpToolError";
    this.details = context.details ?? null;
  }
}

async function fetchJson(url) {
  const response = await fetch(url);
  const rawText = await response.text();
  let payload = {};
  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = { raw: rawText };
    }
  }
  if (!response.ok) {
    throw new CdpToolError(`HTTP ${response.status} while fetching ${url}.`, { details: payload });
  }
  return payload;
}

export function normalizeCdpListUrl(cdpListUrl) {
  return cdpListUrl || getDefaultCdpListUrl();
}

export async function getCdpTargets(cdpListUrl) {
  const targets = await fetchJson(normalizeCdpListUrl(cdpListUrl));
  return Array.isArray(targets) ? targets : [];
}

function matchesTarget(target, targetUrlContains) {
  if (!targetUrlContains) return true;
  const needle = String(targetUrlContains);
  return String(target.url || "").includes(needle) || String(target.title || "").includes(needle);
}

async function resolveTarget({ cdpListUrl, webSocketDebuggerUrl, targetUrlContains } = {}) {
  if (webSocketDebuggerUrl) {
    return { webSocketDebuggerUrl };
  }
  const targets = await getCdpTargets(cdpListUrl);
  const target =
    targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl && matchesTarget(item, targetUrlContains)) ||
    targets.find((item) => item.webSocketDebuggerUrl && matchesTarget(item, targetUrlContains));
  if (!target) {
    throw new CdpToolError("No matching Chrome DevTools target found.", {
      details: { cdpListUrl: normalizeCdpListUrl(cdpListUrl), targetUrlContains },
    });
  }
  return target;
}

export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class CdpClient {
  constructor(webSocketDebuggerUrl) {
    this.webSocketDebuggerUrl = webSocketDebuggerUrl;
    this.id = 0;
    this.pending = new Map();
    this.socket = null;
    this.eventHandlers = new Set();
  }

  onEvent(handler) {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  connect() {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.webSocketDebuggerUrl);
      this.socket = socket;
      socket.once("open", resolve);
      socket.once("error", reject);
      socket.on("message", (message) => {
        let payload;
        try {
          payload = JSON.parse(String(message));
        } catch {
          return;
        }
        if (payload.id && this.pending.has(payload.id)) {
          const { resolve: resolveCall, reject: rejectCall } = this.pending.get(payload.id);
          this.pending.delete(payload.id);
          if (payload.error) {
            rejectCall(new CdpToolError(payload.error.message || "CDP call failed.", { details: payload.error }));
          } else {
            resolveCall(payload.result);
          }
          return;
        }
        if (payload.method) {
          for (const handler of this.eventHandlers) {
            try {
              handler(payload.method, payload.params || {});
            } catch {
              /* ignore handler errors */
            }
          }
        }
      });
    });
  }

  call(method, params = {}) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new CdpToolError("CDP socket is not connected.");
    }
    const id = ++this.id;
    const message = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(message, (error) => {
        if (error) {
          this.pending.delete(id);
          reject(error);
        }
      });
    });
  }

  close() {
    this.eventHandlers.clear();
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.close();
    }
  }
}

export async function withCdpTarget(targetOptions, callback) {
  const target = await resolveTarget(targetOptions);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  try {
    return await callback(client, target);
  } finally {
    client.close();
  }
}
