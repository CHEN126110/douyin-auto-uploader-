import { withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";
import fs from "node:fs/promises";
import path from "node:path";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  const uploadImagePaths = Array.isArray(options.uploadImagePaths)
    ? options.uploadImagePaths
    : String(options.uploadImagePaths || process.env.UPLOAD_IMAGE_PATHS || "")
        .split(";")
        .map((item) => item.trim())
        .filter(Boolean);
  const uploadFileNames = Array.isArray(options.uploadFileNames)
    ? options.uploadFileNames
    : String(options.uploadFileNames || process.env.UPLOAD_FILE_NAMES || "")
        .split(";")
        .map((item) => item.trim())
        .filter(Boolean);
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    maxModules: Number(options.maxModules || process.env.MAX_MODULES || 80),
    uploadImagePath: options.uploadImagePath || process.env.UPLOAD_IMAGE_PATH || "",
    uploadImagePaths,
    uploadMode: options.uploadMode || process.env.UPLOAD_MODE || "single",
    uploadFileName: options.uploadFileName || process.env.UPLOAD_FILE_NAME || "",
    uploadFileNames,
  };
}

function inferImageMimeType(filePath) {
  const ext = path.extname(filePath || "").toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  if (ext === ".bmp") return "image/bmp";
  return "image/png";
}

async function loadUploadSample(uploadImagePath, uploadFileName = "") {
  const resolvedPath = path.resolve(uploadImagePath);
  const buffer = await fs.readFile(resolvedPath);
  const explicitFileName = String(uploadFileName || "").trim();
  return {
    fileName: explicitFileName || path.basename(resolvedPath),
    mimeType: inferImageMimeType(resolvedPath),
    size: buffer.length,
    base64: buffer.toString("base64"),
  };
}

async function loadUploadSamples(options) {
  const paths = options.uploadImagePaths.length > 0 ? options.uploadImagePaths : [options.uploadImagePath].filter(Boolean);
  const fallbackName = String(options.uploadFileName || "").trim();
  const samples = [];
  for (const [index, itemPath] of paths.entries()) {
    const explicitName = options.uploadFileNames[index] || (index === 0 ? fallbackName : "");
    samples.push(await loadUploadSample(itemPath, explicitName));
  }
  return samples;
}

function buildBrowserExpression(options) {
  return `(() => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const moduleFactories = req.m && typeof req.m === 'object' ? req.m : {};
    const endpointPatterns = [
      '/product/img/batchupload',
      '/product/tproduct/saveMaterial',
      '/product/tproduct/materialDetail',
      '/product/tproduct/spuImgUpload',
      'request_source',
      'FormData',
      'image[index]',
      'append("image"',
      "append('image'",
    ];
    const modules = [];
    for (const [moduleId, factory] of Object.entries(moduleFactories)) {
      const source = String(factory);
      const matched = endpointPatterns.filter((pattern) => source.includes(pattern));
      if (!matched.length) continue;
      const snippets = matched.slice(0, 8).map((pattern) => {
        const index = source.indexOf(pattern);
        const start = Math.max(0, index - 220);
        const end = Math.min(source.length, index + pattern.length + 420);
        return {
          pattern,
          snippet: source.slice(start, end)
            .replace(/__token=[^"'&]+/g, '__token=<redacted>')
            .replace(/msToken=[^"'&]+/g, 'msToken=<redacted>')
            .replace(/a_bogus=[^"'&]+/g, 'a_bogus=<redacted>')
        };
      });
      modules.push({
        moduleId,
        matched,
        snippets,
      });
      if (modules.length >= options.maxModules) break;
    }

    const tryRequire = (moduleId) => {
      try {
        const mod = req(moduleId);
        return {
          ok: true,
          keys: Object.keys(mod).slice(0, 80),
          types: Object.fromEntries(Object.entries(mod).slice(0, 80).map(([key, value]) => [key, typeof value])),
        };
      } catch (error) {
        return { ok: false, error: String(error && error.message || error) };
      }
    };

    return {
      ok: true,
      url: location.href,
      webpackModuleCount: Object.keys(moduleFactories).length,
      modules,
      knownRequestModules: {
        lowerWrapper28974: tryRequire(28974),
        postWrapper90665: tryRequire(90665),
      },
    };
  })()`;
}

function buildSampleUploadExpression(samples, options) {
  return `(async () => {
    const samples = ${JSON.stringify(samples)};
    const options = ${JSON.stringify({ uploadMode: options.uploadMode })};

    const sanitizeString = (value) => {
      if (typeof value !== 'string') return value;
      let result = value
        .replace(/__token=[^"'&]+/g, '__token=<redacted>')
        .replace(/msToken=[^"'&]+/g, 'msToken=<redacted>')
        .replace(/a_bogus=[^"'&]+/g, 'a_bogus=<redacted>');
      try {
        const parsed = new URL(result, location.origin);
        if (/^https?:/.test(parsed.protocol)) {
          return parsed.origin + parsed.pathname + (parsed.search ? '?<query-redacted>' : '');
        }
      } catch (_) {
        // not a URL
      }
      if (result.length > 180) {
        result = result.slice(0, 180) + '...<truncated>';
      }
      return result;
    };

    const sanitize = (value, depth = 0) => {
      if (depth > 4) return '<max-depth>';
      if (value == null) return value;
      if (typeof value === 'string') return sanitizeString(value);
      if (typeof value !== 'object') return value;
      if (Array.isArray(value)) return value.slice(0, 6).map((item) => sanitize(item, depth + 1));
      const result = {};
      for (const [key, item] of Object.entries(value).slice(0, 80)) {
        if (/cookie|token|authorization|mobile|phone/i.test(key)) {
          result[key] = '<redacted>';
        } else {
          result[key] = sanitize(item, depth + 1);
        }
      }
      return result;
    };

    const summarize = (payload) => {
      const data = payload && payload.data;
      const firstItem = Array.isArray(data) ? data[0] : data;
      return {
        topLevelKeys: payload && typeof payload === 'object' ? Object.keys(payload) : [],
        code: payload && payload.code,
        message: payload && (payload.msg || payload.message),
        dataType: Array.isArray(data) ? 'array' : typeof data,
        dataLength: Array.isArray(data) ? data.length : null,
        dataItemKeys: firstItem && typeof firstItem === 'object' ? Object.keys(firstItem) : [],
        dataItemTypeMap: firstItem && typeof firstItem === 'object'
          ? Object.fromEntries(Object.entries(firstItem).map(([key, item]) => [key, Array.isArray(item) ? 'array' : typeof item]))
          : {},
      };
    };

    const buildFile = (sample) => {
      const binary = atob(sample.base64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return new File([bytes], sample.fileName, { type: sample.mimeType });
    };

    if (!Array.isArray(samples) || !samples.length) {
      return {
        ok: false,
        error: 'No upload samples were provided.'
      };
    }

    const form = new FormData();
    const mode = options.uploadMode === 'batch' ? 'batch' : 'single';
    if (mode === 'batch') {
      samples.forEach((sample, index) => {
        form.append('image[' + index + ']', buildFile(sample));
      });
    } else {
      form.append('image', buildFile(samples[0]));
    }
    form.append('extra', JSON.stringify({ request_source: 'pc' }));
    const requestUrl = mode === 'batch' ? '/product/img/batchupload?_bid=ffa_goods' : '/product/img/batchupload';
    const startedAt = Date.now();
    const response = await fetch(requestUrl, {
      method: 'POST',
      body: form,
      credentials: 'include',
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (error) {
      payload = { parseError: String(error && error.message || error), rawText: text };
    }
    const elapsedMs = Date.now() - startedAt;
    return {
      ok: response.ok && payload && String(payload.code) === '0',
      uploadMode: mode,
      url: location.href,
      requestUrl,
      httpStatus: response.status,
      elapsedMs,
      sample: samples[0] ? {
        fileName: samples[0].fileName,
        mimeType: samples[0].mimeType,
        size: samples[0].size,
      } : null,
      samples: samples.map((sample) => ({
        fileName: sample.fileName,
        mimeType: sample.mimeType,
        size: sample.size,
      })),
      responseSummary: summarize(payload),
      responseSanitized: sanitize(payload),
    };
  })()`;
}

export async function probeFxgUploadEndpoints(options = {}) {
  const normalized = normalizeOptions(options);
  return withCdpTarget(
    {
      cdpListUrl: normalized.cdpListUrl,
      targetUrlContains: normalized.targetUrlContains,
    },
    async (client) => {
      const result = await client.call("Runtime.evaluate", {
        expression: buildBrowserExpression(normalized),
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        return {
          ok: false,
          error: "Browser evaluation failed.",
          details: result.exceptionDetails,
        };
      }
      const scanResult = result.result?.value ?? null;
      if (!normalized.uploadImagePath && normalized.uploadImagePaths.length === 0) {
        return scanResult;
      }

      const samples = await loadUploadSamples(normalized);
      const uploadResult = await client.call("Runtime.evaluate", {
        expression: buildSampleUploadExpression(samples, normalized),
        awaitPromise: true,
        returnByValue: true,
      });
      if (uploadResult.exceptionDetails) {
        return {
          ok: false,
          scanResult,
          sampleUpload: {
            ok: false,
            error: "Sample upload evaluation failed.",
            details: uploadResult.exceptionDetails,
          },
        };
      }
      return {
        ok: Boolean(scanResult?.ok) && Boolean(uploadResult.result?.value?.ok),
        scanResult,
        sampleUpload: uploadResult.result?.value ?? null,
      };
    }
  );
}
