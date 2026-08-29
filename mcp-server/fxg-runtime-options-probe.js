import { probeFxgFreightOptions } from "./fxg-freight-probe.js";
import { probeFxgSchema } from "./fxg-schema-probe.js";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT,
    categoryKeyword: options.categoryKeyword || process.env.CATEGORY_KEYWORD || "长筒袜",
    categoryId: options.categoryId || process.env.CATEGORY_ID || "",
    operationType: options.operationType || process.env.OPERATION_TYPE || "select_normal,normal",
    timeoutMs: Number(options.timeoutMs || process.env.TIMEOUT_MS || 20000),
    includeFreight: options.includeFreight ?? process.env.INCLUDE_FREIGHT !== "0",
  };
}

function detailByKey(schemaSummary, key) {
  const details = Array.isArray(schemaSummary?.fieldDetails) ? schemaSummary.fieldDetails : [];
  return details.find((item) => item?.key === key) || null;
}

function summarizeCategory(category) {
  const path = [category?.first_name, category?.second_name, category?.third_name, category?.fourth_name]
    .filter(Boolean)
    .join(" > ");
  return {
    path,
    leafId: String(category?.categoryLeafId || category?.fourth_cid || category?.third_cid || ""),
    first_cid: category?.first_cid,
    second_cid: category?.second_cid,
    third_cid: category?.third_cid,
    fourth_cid: category?.fourth_cid,
    enable: category?.enable,
    industry_status: category?.industry_status,
  };
}

function summarizeOptions(field) {
  return {
    key: field?.key || "",
    label: field?.label || "",
    required: Boolean(field?.required),
    valueType: field?.valueType || "",
    optionCount: Number(field?.optionCount || 0),
    optionPreview: Array.isArray(field?.optionPreview) ? field.optionPreview : [],
    additionKeys: Array.isArray(field?.additionKeys) ? field.additionKeys : [],
    extraKeys: Array.isArray(field?.extraKeys) ? field.extraKeys : [],
  };
}

function normalizeKeywordList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean);
  }
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function summarizeCategoryProperties(schemaSummary) {
  const properties = Array.isArray(schemaSummary?.categoryProperties) ? schemaSummary.categoryProperties : [];
  return properties.map((item) => ({
    id: String(item?.id || ""),
    label: String(item?.label || ""),
    required: Boolean(item?.required),
    optionCount: Number(item?.optionCount || 0),
    optionPreview: Array.isArray(item?.optionPreview) ? item.optionPreview : [],
    hasMeasureTemplates: Array.isArray(item?.measureTemplates) && item.measureTemplates.length > 0,
    measureTemplates: Array.isArray(item?.measureTemplates) ? item.measureTemplates : [],
  }));
}

function freightOptionsFromProbe(freightProbe) {
  const runtimeProbe = freightProbe?.runtimeProbe;
  const options = Array.isArray(runtimeProbe?.optionPreview) ? runtimeProbe.optionPreview : [];
  return {
    ok: Boolean(freightProbe?.ok) && !runtimeProbe?.error,
    requestUrl: runtimeProbe?.requestUrl || "",
    optionCount: Number(runtimeProbe?.optionCount || options.length || 0),
    options,
    currentValue: runtimeProbe?.freightField?.value || "",
    error: runtimeProbe?.error || null,
  };
}

function buildSettingsReadiness(schemaSummary, freightOptions) {
  const issues = [];
  const categoryProperties = summarizeCategoryProperties(schemaSummary);
  const requiredProps = categoryProperties.filter((item) => item.required);
  if (!requiredProps.length) {
    issues.push("未读取到必填类目属性，不能生成可靠的设置表单。");
  }
  if (freightOptions && !freightOptions.ok) {
    issues.push("运费模板读取失败，设置页不能保存未校验的运费模板。");
  }
  return {
    canRenderCategorySettings: Boolean(schemaSummary?.ok) && requiredProps.length > 0,
    canRenderFreightSettings: freightOptions ? freightOptions.ok : false,
    issues,
  };
}

function summarizeRuntimeMatrixItem(keyword, result) {
  const publishControls = {};
  for (const [key, value] of Object.entries(result?.publishControls || {})) {
    publishControls[key] = {
      label: value?.label || "",
      required: Boolean(value?.required),
      optionCount: Number(value?.optionCount || 0),
      optionNames: Array.isArray(value?.optionPreview)
        ? value.optionPreview.map((item) => String(item?.value_name || "")).filter(Boolean)
        : [],
    };
  }
  return {
    keyword,
    ok: Boolean(result?.ok),
    category: result?.category || {},
    requiredCategoryProperties: Array.isArray(result?.requiredCategoryProperties)
      ? result.requiredCategoryProperties.map((item) => ({
          id: item.id,
          label: item.label,
          optionCount: item.optionCount,
          hasMeasureTemplates: item.hasMeasureTemplates,
        }))
      : [],
    specAxes: Array.isArray(result?.specAxes) ? result.specAxes.map((item) => item.name).filter(Boolean) : [],
    skuColumns: Array.isArray(result?.skuColumns)
      ? result.skuColumns.map((item) => ({
          key: item.key,
          label: item.label,
          required: item.required,
          hidden: item.hidden,
        }))
      : [],
    publishControls,
    freight: result?.freight
      ? {
          ok: Boolean(result.freight.ok),
          optionCount: Number(result.freight.optionCount || 0),
          hasCurrentValue: Boolean(result.freight.currentValue),
          error: result.freight.error || null,
        }
      : null,
    settingsReadiness: result?.settingsReadiness || {},
  };
}

export async function probeFxgRuntimeOptions(options = {}) {
  const normalized = normalizeOptions(options);
  const schemaSummary = await probeFxgSchema({
    cdpListUrl: normalized.cdpListUrl,
    targetUrlContains: normalized.targetUrlContains,
    categoryKeyword: normalized.categoryKeyword,
    categoryId: normalized.categoryId,
    operationType: normalized.operationType,
    timeoutMs: normalized.timeoutMs,
  });

  const freightProbe = normalized.includeFreight
    ? await probeFxgFreightOptions({
        cdpListUrl: normalized.cdpListUrl,
        targetUrlContains: normalized.targetUrlContains,
        categoryKeyword: normalized.categoryKeyword,
        categoryId: normalized.categoryId,
        timeoutMs: normalized.timeoutMs,
      })
    : null;

  const freight = freightProbe ? freightOptionsFromProbe(freightProbe) : null;
  const categoryProperties = summarizeCategoryProperties(schemaSummary);
  const skuDetail = detailByKey(schemaSummary, "sku_detail");

  return {
    ok: Boolean(schemaSummary?.ok) && (!freight || freight.ok),
    category: summarizeCategory(schemaSummary?.category),
    categoryCandidates: Array.isArray(schemaSummary?.categoryCandidates)
      ? schemaSummary.categoryCandidates.map(summarizeCategory)
      : [],
    categoryProperties,
    requiredCategoryProperties: categoryProperties.filter((item) => item.required),
    specAxes: Array.isArray(schemaSummary?.specDetail)
      ? schemaSummary.specDetail.map((item) => ({
          id: String(item?.id || ""),
          cp_id: item?.cp_id,
          name: String(item?.name || ""),
        }))
      : [],
    skuColumns: Array.isArray(skuDetail?.columns)
      ? skuDetail.columns.map((item) => ({
          key: String(item?.key || ""),
          label: String(item?.label || ""),
          required: Boolean(item?.required),
          hidden: Boolean(item?.hidden),
        }))
      : [],
    publishControls: {
      pickup_method: summarizeOptions(detailByKey(schemaSummary, "pickup_method")),
      start_sale_type: summarizeOptions(detailByKey(schemaSummary, "start_sale_type")),
      sale_channel_type: summarizeOptions(detailByKey(schemaSummary, "sale_channel_type")),
      product_type: summarizeOptions(detailByKey(schemaSummary, "product_type")),
      presell_type: summarizeOptions(detailByKey(schemaSummary, "presell_type")),
    },
    freight,
    settingsReadiness: buildSettingsReadiness(schemaSummary, freight),
  };
}

export async function probeFxgRuntimeOptionsMatrix(options = {}) {
  const keywords = normalizeKeywordList(options.categoryKeywords || options.categoryKeyword || "长筒袜");
  const entries = [];
  for (const keyword of keywords) {
    try {
      const result = await probeFxgRuntimeOptions({
        ...options,
        categoryKeyword: keyword,
        categoryId: "",
      });
      entries.push(summarizeRuntimeMatrixItem(keyword, result));
    } catch (error) {
      entries.push({
        keyword,
        ok: false,
        error: error?.message || String(error),
      });
    }
  }
  return {
    ok: entries.every((entry) => entry.ok),
    categoryKeywords: keywords,
    entries,
  };
}
