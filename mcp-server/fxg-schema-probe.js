import { withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    categoryKeyword: options.categoryKeyword || process.env.CATEGORY_KEYWORD || "长筒袜",
    categoryId: options.categoryId || process.env.CATEGORY_ID || "",
    operationType: options.operationType || process.env.OPERATION_TYPE || "select_normal,normal",
    optionKeywords: Array.isArray(options.optionKeywords)
      ? options.optionKeywords
      : String(process.env.OPTION_KEYWORDS || "长筒袜,中筒袜,短筒袜,棉,氨纶,女,男,通用,薄款,透气")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
    timeoutMs: Number(options.timeoutMs || process.env.TIMEOUT_MS || 20000),
  };
}

function buildBrowserExpression(options) {
  return `(async () => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const get = req(28974).J;
    const post = req(90665).bE;

    const readOptions = (item) => {
      const rawOptions = item && (item.options || item.values || item.value_options || item.select_options);
      return Array.isArray(rawOptions) ? rawOptions : [];
    };

    const simplifyOption = (option) => ({
      value_id: option && (option.value_id || option.id || option.value),
      value_name: option && (option.value_name || option.name || option.label)
    });

    const simplifyCategory = (item) => ({
      first_name: item && item.first_name,
      second_name: item && item.second_name,
      third_name: item && item.third_name,
      fourth_name: item && item.fourth_name,
      first_cid: item && item.first_cid,
      second_cid: item && item.second_cid,
      third_cid: item && item.third_cid,
      fourth_cid: item && item.fourth_cid,
      categoryLeafId: item && (item.categoryLeafId || item.category_leaf_id || item.fourth_cid || item.third_cid),
      enable: item && item.enable,
      industry_status: item && item.industry_status
    });

    let selectedCategory = null;
    let categoryCandidates = [];
    if (options.categoryId) {
      selectedCategory = { categoryLeafId: String(options.categoryId) };
    } else {
      const searchUrl = '/product/tproduct/searchCategoryN?key=' +
        encodeURIComponent(options.categoryKeyword) + '&search_type=1';
      const searchResponse = await get(searchUrl, { timeout: options.timeoutMs });
      const rows = Array.isArray(searchResponse && searchResponse.data) ? searchResponse.data : [];
      categoryCandidates = rows.slice(0, 20).map(simplifyCategory);
      selectedCategory =
        rows.find((item) => item && item.enable && item.industry_status === 0 && item.fourth_name === options.categoryKeyword) ||
        rows.find((item) => item && item.enable && item.industry_status === 0 && (item.fourth_cid || item.third_cid)) ||
        rows[0] ||
        null;
      if (!selectedCategory) {
        return { ok: false, error: 'No category candidate returned.', url: location.href, categoryCandidates };
      }
    }

    const publishId = req(68671).T({
      useUrlParams: true,
      useWindowCache: true,
      writeWindowCache: true
    });
    const categoryId = String(selectedCategory.categoryLeafId || selectedCategory.category_leaf_id || selectedCategory.fourth_cid || selectedCategory.third_cid);
    const context = {
      category_id: categoryId,
      operation_type: options.operationType,
      ability: [],
      feature: {
        session_publish_id: 'helper_' + publishId
      }
    };

    const response = await post('/product/tproduct/getSchema', { context, model: void 0 }, { timeout: options.timeoutMs });
    const data = response && response.data ? response.data : response;
    const model = data && data.model ? data.model : {};
    const modelKeys = model && typeof model === 'object' ? Object.keys(model) : [];

    const summarizeField = (key) => {
      const item = model && model[key];
      if (!item) return null;
      const value = item.value;
      return {
        key,
        id: item.id || '',
        label: item.label || item.title || '',
        required: !!item.required,
        hidden: !!item.hidden,
        disabled: !!item.disabled,
        valueType: value == null ? String(value) : Array.isArray(value) ? 'array' : typeof value,
        valuePreview: value == null ? value : JSON.stringify(value).slice(0, 500),
        itemCount: Array.isArray(item.items) ? item.items.length : null,
        columnCount: Array.isArray(item.columns) ? item.columns.length : null
      };
    };

    const summarizeColumn = (column) => ({
      key: column && (column.key || column.id || ''),
      label: column && (column.label || column.title || column.name || ''),
      required: !!(column && column.required),
      hidden: !!(column && column.hidden),
      disabled: !!(column && column.disabled),
      valueType: column && column.value == null
        ? String(column && column.value)
        : Array.isArray(column && column.value)
          ? 'array'
          : typeof (column && column.value)
    });

    const simplifyLoadedFreightOption = (option) => ({
      value_id: option && (option.value_id || option.id || option.value || option.freight_id || option.template_id),
      value_name: option && (option.value_name || option.name || option.label || option.template_name),
      disabled: !!(option && option.disabled)
    });

    const readLoadedFreightOptions = (field) => {
      if (!field || typeof field !== 'object') return [];
      const candidates = [
        field.options,
        field.values,
        field.value_options,
        field.select_options,
        field.additions && field.additions.options,
        field.extra && field.extra.options,
        field.additions && field.additions.value_options,
        field.extra && field.extra.value_options,
      ];
      for (const candidate of candidates) {
        if (Array.isArray(candidate)) return candidate;
      }
      return [];
    };

    const summarizeFieldDetail = (key) => {
      const item = model && model[key];
      if (!item) return null;
      const value = item.value;
      const additions = item.additions && typeof item.additions === 'object' ? item.additions : {};
      const extra = item.extra && typeof item.extra === 'object' ? item.extra : {};
      const columns = Array.isArray(item.columns) ? item.columns : [];
      const options = key === 'freight_id' ? readLoadedFreightOptions(item) : readOptions(item);
      return {
        ...summarizeField(key),
        additionKeys: Object.keys(additions).slice(0, 50),
        extraKeys: Object.keys(extra).slice(0, 50),
        columns: columns.slice(0, 40).map(summarizeColumn),
        optionCount: options.length,
        optionPreview: options.slice(0, 20).map(key === 'freight_id' ? simplifyLoadedFreightOption : simplifyOption),
        valueSample: Array.isArray(value)
          ? value.slice(0, 5)
          : value && typeof value === 'object'
            ? Object.fromEntries(Object.entries(value).slice(0, 20))
            : value
      };
    };

    const optionPreview = (item) => {
      const options = readOptions(item);
      return options.slice(0, 12).map(simplifyOption);
    };

    const optionMatches = (item) => {
      const keywords = Array.isArray(options.optionKeywords) ? options.optionKeywords : [];
      const rawOptions = readOptions(item);
      const matches = [];
      for (const keyword of keywords) {
        const exact = rawOptions.find((option) => {
          const name = String((option && (option.value_name || option.name || option.label)) || '');
          return name === keyword;
        });
        const fuzzy = exact
          ? null
          : rawOptions.find((option) => {
              const name = String((option && (option.value_name || option.name || option.label)) || '');
              return name.includes(keyword);
            });
        const hit = exact || fuzzy;
        if (hit) {
          matches.push({ keyword, matchType: exact ? 'exact' : 'contains', ...simplifyOption(hit) });
        }
      }
      return matches;
    };

    const measureTemplateSummary = (item) => {
      const templates = item && item.additions && Array.isArray(item.additions.measure_templates)
        ? item.additions.measure_templates
        : [];
      return templates.slice(0, 6).map((template) => ({
        template_id: template && template.template_id,
        name: template && (template.name || template.template_name || template.display_name || ''),
        modules: Array.isArray(template && (template.value_modules || template.modules))
          ? (template.value_modules || template.modules).slice(0, 12).map((module) => ({
              module_id: module && module.module_id,
              label: module && (module.label || module.name || module.module_name || ''),
              input_type: module && module.input_type,
              unitOptions: Array.isArray(module && module.unit_options)
                ? module.unit_options.map((unit) => ({
                    label: unit && unit.label,
                    value: unit && unit.value
                  }))
                : []
            }))
          : []
      }));
    };

    const categoryProperties = ((model.category_properties || {}).items || []).slice(0, 80).map((item) => ({
      id: item.id,
      label: item.label || item.name || '',
      required: !!item.required,
      hidden: !!item.hidden,
      disabled: !!item.disabled,
      additionKeys: item.additions && typeof item.additions === 'object' ? Object.keys(item.additions).slice(0, 20) : [],
      optionCount: readOptions(item).length,
      optionPreview: optionPreview(item),
      optionMatches: optionMatches(item),
      measureTemplates: measureTemplateSummary(item)
    }));

    const specDetail = Array.isArray((model.spec_detail || {}).value)
      ? model.spec_detail.value.map((item) => ({
          id: item.id,
          cp_id: item.cp_id,
          name: item.name,
          specValueCount: Array.isArray(item.spec_values) ? item.spec_values.length : 0
        }))
      : [];

    const responseContext = data && data.context ? data.context : {};
    return {
      ok: true,
      url: location.href,
      publishId,
      category: simplifyCategory(selectedCategory),
      categoryCandidates,
      requestContext: context,
      responseContextSummary: {
        category_id: responseContext.category_id || '',
        operation_type: responseContext.operation_type || '',
        product_id: responseContext.product_id || '',
        model_type: responseContext.model_type || '',
        version: responseContext.version || '',
        grayComponentsCount: Array.isArray(responseContext.gray_components) ? responseContext.gray_components.length : null
      },
      modelKeyCount: modelKeys.length,
      modelKeys,
      importantFields: [
        'goods_category',
        'category_properties',
        'pic',
        'main_image_three_to_four',
        'white_background_pic',
        'main_pic_video',
        'description',
        'qualification',
        'spec_detail',
        'sku_detail',
        'pickup_method',
        'start_sale_type',
        'sale_channel_type',
        'product_type',
        'presell_type',
        'title',
        'freight_id'
      ].map(summarizeField).filter(Boolean),
      fieldDetails: [
        'freight_id',
        'spec_detail',
        'sku_detail',
        'pic',
        'white_background_pic',
        'main_pic_video',
        'description',
        'qualification',
        'pickup_method',
        'start_sale_type',
        'sale_channel_type',
        'product_type',
        'presell_type'
      ].map(summarizeFieldDetail).filter(Boolean),
      categoryProperties,
      specDetail
    };
  })()`;
}

export async function probeFxgSchema(options = {}) {
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
      return result.result?.value ?? null;
    }
  );
}
