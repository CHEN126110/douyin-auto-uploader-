import { delay, withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    categoryKeyword: options.categoryKeyword || process.env.CATEGORY_KEYWORD || "长筒袜",
    categoryId: options.categoryId || process.env.CATEGORY_ID || "",
    timeoutMs: Number(options.timeoutMs || process.env.TIMEOUT_MS || 20000),
    waitAfterActionMs: Number(options.waitAfterActionMs || process.env.WAIT_AFTER_ACTION_MS || 2500),
    triggerAction: options.triggerAction ?? process.env.TRIGGER_ACTION !== "0",
  };
}

function buildBrowserExpression(options) {
  return `(async () => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const get = req(28974).J;
    const post = req(90665).bE;

    const simplifyOption = (option) => ({
      value_id: option && (option.value_id || option.id || option.value || option.freight_id || option.template_id),
      value_name: option && (option.value_name || option.name || option.label || option.template_name),
      disabled: !!(option && option.disabled)
    });

    const readOptions = (field) => {
      if (!field || typeof field !== 'object') return [];
      const additions = field.additions && typeof field.additions === 'object' ? field.additions : {};
      const extra = field.extra && typeof field.extra === 'object' ? field.extra : {};
      const candidates = [
        field.options,
        field.values,
        field.value_options,
        field.select_options,
        additions.options,
        additions.value_options,
        additions.freight_options,
        extra.options,
        extra.value_options,
        extra.freight_options,
      ];
      for (const candidate of candidates) {
        if (Array.isArray(candidate)) return candidate;
      }
      return [];
    };

    const summarizeField = (field) => {
      if (!field || typeof field !== 'object') return null;
      const additions = field.additions && typeof field.additions === 'object' ? field.additions : {};
      const extra = field.extra && typeof field.extra === 'object' ? field.extra : {};
      const options = readOptions(field);
      return {
        id: field.id || '',
        label: field.label || field.title || field.name || '',
        required: !!field.required,
        value: field.value,
        additionKeys: Object.keys(additions).slice(0, 80),
        extraKeys: Object.keys(extra).slice(0, 80),
        optionCount: options.length,
        optionPreview: options.slice(0, 30).map(simplifyOption)
      };
    };

    const findFreightRefs = (root) => {
      const refs = [];
      const seen = new WeakSet();
      const visit = (value, path, depth) => {
        if (refs.length >= 80 || depth > 7 || value == null) return;
        const valueType = typeof value;
        if (valueType === 'string') {
          if (/freight|template_options|运费|物流/i.test(value)) {
            refs.push({ path, type: 'string', value: value.slice(0, 240) });
          }
          return;
        }
        if (valueType !== 'object') return;
        if (seen.has(value)) return;
        seen.add(value);
        if (Array.isArray(value)) {
          for (let index = 0; index < Math.min(value.length, 30); index += 1) {
            visit(value[index], path + '[' + index + ']', depth + 1);
          }
          return;
        }
        for (const [key, child] of Object.entries(value)) {
          const childPath = path ? path + '.' + key : key;
          if (/freight|template_options|运费|物流/i.test(key)) {
            refs.push({
              path: childPath,
              type: Array.isArray(child) ? 'array' : typeof child,
              value: typeof child === 'string' ? child.slice(0, 240) : undefined,
            });
          }
          visit(child, childPath, depth + 1);
        }
      };
      visit(root, '', 0);
      return refs;
    };

    const searchCategory = async () => {
      if (options.categoryId) return { categoryLeafId: String(options.categoryId) };
      const response = await get('/product/tproduct/searchCategoryN?key=' + encodeURIComponent(options.categoryKeyword) + '&search_type=1', { timeout: options.timeoutMs });
      const rows = Array.isArray(response && response.data) ? response.data : [];
      return rows.find((item) => item && item.enable && item.industry_status === 0 && item.fourth_name === options.categoryKeyword) ||
        rows.find((item) => item && item.enable && item.industry_status === 0 && (item.fourth_cid || item.third_cid)) ||
        rows[0] ||
        null;
    };

    const selectedCategory = await searchCategory();
    if (!selectedCategory) {
      return { ok: false, error: 'No category candidate returned.', url: location.href };
    }

    const publishId = req(68671).T({
      useUrlParams: true,
      useWindowCache: true,
      writeWindowCache: true
    });
    const categoryId = String(selectedCategory.categoryLeafId || selectedCategory.category_leaf_id || selectedCategory.fourth_cid || selectedCategory.third_cid);
    const context = {
      category_id: categoryId,
      operation_type: 'select_normal,normal',
      ability: [],
      feature: {
        session_publish_id: 'helper_' + publishId
      }
    };
    const schemaResponse = await post('/product/tproduct/getSchema', { context, model: void 0 }, { timeout: options.timeoutMs });
    const schemaData = schemaResponse && schemaResponse.data ? schemaResponse.data : schemaResponse;
    const model = schemaData && schemaData.model ? schemaData.model : {};
    const schemaFreightField = summarizeField(model.freight_id);

    const summarizeAction = (action) => {
      if (!action || typeof action !== 'object') return null;
      const content = action.content && typeof action.content === 'object' ? action.content : {};
      const request = content.request && typeof content.request === 'object' ? content.request : {};
      return {
        id: action.id || '',
        type: action.type || action.action || '',
        contentKeys: Object.keys(content).slice(0, 40),
        request: request.url
          ? {
              method: request.method || '',
              url: request.url,
            }
          : null,
        target: content.target || '',
        dependencies: Array.isArray(content.dependencies) ? content.dependencies.slice(0, 20) : [],
      };
    };

    const freightActions = Array.isArray(model.freight_id && model.freight_id.actions)
      ? model.freight_id.actions.map(summarizeAction).filter(Boolean)
      : [];

    const module99281 = (() => {
      try {
        const mod = req(99281);
        return {
          ok: true,
          keys: Object.keys(mod),
          types: Object.fromEntries(Object.entries(mod).map(([key, value]) => [key, typeof value])),
        };
      } catch (error) {
        return { ok: false, error: String(error && error.message || error) };
      }
    })();

    let runtimeProbe = {
      method: 'direct_refetchSchema',
      requestUrl: null,
      responseTopLevelKeys: [],
      freightField: null,
      optionCount: 0,
      optionPreview: [],
      error: null,
    };

    try {
      const freightLoadAction = freightActions.find((action) => action.id === 'freight_template_options_load' && action.request && action.request.url);
      runtimeProbe.requestUrl = freightLoadAction && freightLoadAction.request ? freightLoadAction.request.url : null;
      if (options.triggerAction && runtimeProbe.requestUrl) {
        const refetchResponse = await post(runtimeProbe.requestUrl, { context: schemaData.context, model }, { timeout: options.timeoutMs });
        await new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(options.waitAfterActionMs, 0), 10000)));
        const refetchData = refetchResponse && refetchResponse.data ? refetchResponse.data : refetchResponse;
        const refetchModel = refetchData && refetchData.model ? refetchData.model : {};
        const freightField = refetchModel.freight_id || (refetchModel.model && refetchModel.model.freight_id) || null;
        const summarized = summarizeField(freightField);
        runtimeProbe.responseTopLevelKeys = refetchData && typeof refetchData === 'object' ? Object.keys(refetchData).slice(0, 80) : [];
        runtimeProbe.freightField = summarized;
        runtimeProbe.optionCount = summarized ? summarized.optionCount : 0;
        runtimeProbe.optionPreview = summarized ? summarized.optionPreview : [];
      }
    } catch (error) {
      runtimeProbe.error = String(error && error.message || error);
    }

    return {
      ok: true,
      url: location.href,
      categoryId,
      schemaTopLevelKeys: schemaData && typeof schemaData === 'object' ? Object.keys(schemaData).slice(0, 80) : [],
      schemaFreightField,
      freightActions,
      schemaFreightRefs: findFreightRefs(schemaData),
      module99281,
      runtimeProbe
    };
  })()`;
}

function shouldKeepNetworkEntry(url) {
  return /freight|logistics|template|tproduct|product/i.test(String(url || ""));
}

function sanitizeUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return {
      origin: url.origin,
      path: url.pathname,
      queryKeys: Array.from(url.searchParams.keys()).slice(0, 80),
    };
  } catch {
    return {
      origin: "",
      path: String(rawUrl || "").split("?")[0],
      queryKeys: [],
    };
  }
}

export async function probeFxgFreightOptions(options = {}) {
  const normalized = normalizeOptions(options);
  return withCdpTarget(
    {
      cdpListUrl: normalized.cdpListUrl,
      targetUrlContains: normalized.targetUrlContains,
    },
    async (client) => {
      const requests = new Map();
      const responses = new Map();
      client.onEvent((method, params) => {
        if (method === "Network.requestWillBeSent") {
          const url = params.request?.url || "";
          if (shouldKeepNetworkEntry(url)) {
            requests.set(params.requestId, {
              url: sanitizeUrl(url),
              method: params.request?.method || "",
              resourceType: params.type || "",
              rawUrlForFilter: url,
            });
          }
        }
        if (method === "Network.responseReceived") {
          const request = requests.get(params.requestId);
          const url = params.response?.url || request?.rawUrlForFilter || "";
          if (request || shouldKeepNetworkEntry(url)) {
            responses.set(params.requestId, {
              url: sanitizeUrl(url),
              status: params.response?.status,
              mimeType: params.response?.mimeType || "",
              resourceType: params.type || request?.resourceType || "",
            });
          }
        }
      });

      await client.call("Network.enable");
      const result = await client.call("Runtime.evaluate", {
        expression: buildBrowserExpression(normalized),
        awaitPromise: true,
        returnByValue: true,
      });
      await delay(Math.min(Math.max(normalized.waitAfterActionMs, 0), 10000));
      await client.call("Network.disable");

      const payload = result.result?.value ?? null;
      const network = Array.from(responses.values())
        .filter((item) => shouldKeepNetworkEntry(item.url?.path || ""))
        .slice(0, 80);
      if (result.exceptionDetails) {
        return {
          ok: false,
          error: "Browser evaluation failed.",
          details: result.exceptionDetails,
          network,
        };
      }
      return {
        ...payload,
        network,
      };
    }
  );
}
