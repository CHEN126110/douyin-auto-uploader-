import { probeFxgSchema } from "./fxg-schema-probe.js";

const DEFAULT_CATEGORY_KEYWORDS = ["长筒袜", "短袜", "中筒袜"];

function splitList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeCategories(options = {}) {
  if (Array.isArray(options.categories) && options.categories.length) {
    return options.categories
      .map((item) => {
        if (typeof item === "string") return { keyword: item, categoryId: "" };
        return {
          keyword: String(item?.keyword || item?.categoryKeyword || "").trim(),
          categoryId: String(item?.categoryId || "").trim(),
        };
      })
      .filter((item) => item.keyword || item.categoryId);
  }

  const ids = splitList(options.categoryIds || process.env.CATEGORY_IDS);
  const keywords = splitList(options.categoryKeywords || process.env.CATEGORY_KEYWORDS);
  if (ids.length) {
    return ids.map((categoryId, index) => ({
      categoryId,
      keyword: keywords[index] || "",
    }));
  }
  return (keywords.length ? keywords : DEFAULT_CATEGORY_KEYWORDS).map((keyword) => ({
    keyword,
    categoryId: "",
  }));
}

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT,
    operationType: options.operationType || process.env.OPERATION_TYPE || "select_normal,normal",
    optionKeywords: Array.isArray(options.optionKeywords)
      ? options.optionKeywords
      : splitList(options.optionKeywords || process.env.OPTION_KEYWORDS || "棉,氨纶,长筒袜,短筒袜,中筒袜,女,男,通用"),
    timeoutMs: Number(options.timeoutMs || process.env.TIMEOUT_MS || 20000),
    includeRaw: Boolean(options.includeRaw),
    categories: normalizeCategories(options),
  };
}

function fieldByKey(schemaSummary, key) {
  const fields = Array.isArray(schemaSummary?.importantFields) ? schemaSummary.importantFields : [];
  return fields.find((item) => item?.key === key) || null;
}

function detailByKey(schemaSummary, key) {
  const details = Array.isArray(schemaSummary?.fieldDetails) ? schemaSummary.fieldDetails : [];
  return details.find((item) => item?.key === key) || null;
}

function categoryPath(category) {
  return [category?.first_name, category?.second_name, category?.third_name, category?.fourth_name]
    .filter(Boolean)
    .join(" > ");
}

function summarizeCategoryProperties(schemaSummary) {
  const properties = Array.isArray(schemaSummary?.categoryProperties) ? schemaSummary.categoryProperties : [];
  return properties.map((item) => ({
    id: String(item?.id || ""),
    label: String(item?.label || ""),
    required: Boolean(item?.required),
    optionCount: Number(item?.optionCount || 0),
    hasMeasureTemplates: Array.isArray(item?.measureTemplates) && item.measureTemplates.length > 0,
    matchedKeywords: Array.isArray(item?.optionMatches)
      ? item.optionMatches.map((match) => ({
          keyword: match.keyword,
          matchType: match.matchType,
          value_id: match.value_id,
          value_name: match.value_name,
        }))
      : [],
  }));
}

function summarizeSchema(schemaSummary, input) {
  const modelKeys = Array.isArray(schemaSummary?.modelKeys) ? schemaSummary.modelKeys : [];
  const fieldKeys = [
    "title",
    "goods_category",
    "category_properties",
    "pic",
    "main_image_three_to_four",
    "white_background_pic",
    "main_pic_video",
    "description",
    "qualification",
    "freight_id",
    "spec_detail",
    "sku_detail",
  ];
  const fields = Object.fromEntries(
    fieldKeys.map((key) => {
      const field = fieldByKey(schemaSummary, key);
      return [
        key,
        field
          ? {
              present: true,
              label: field.label || "",
              required: Boolean(field.required),
              hidden: Boolean(field.hidden),
              valueType: field.valueType || "",
              itemCount: field.itemCount,
              columnCount: field.columnCount,
            }
          : { present: false },
      ];
    })
  );

  const skuDetail = detailByKey(schemaSummary, "sku_detail");
  const specDetail = Array.isArray(schemaSummary?.specDetail) ? schemaSummary.specDetail : [];
  const categoryProperties = summarizeCategoryProperties(schemaSummary);
  const requiredCategoryProperties = categoryProperties.filter((item) => item.required);
  const measureProperties = categoryProperties.filter((item) => item.hasMeasureTemplates);

  return {
    input,
    ok: Boolean(schemaSummary?.ok),
    category: {
      leafId: String(schemaSummary?.category?.categoryLeafId || ""),
      path: categoryPath(schemaSummary?.category),
      raw: schemaSummary?.category || null,
    },
    responseContextSummary: schemaSummary?.responseContextSummary || {},
    modelKeyCount: modelKeys.length,
    modelKeys,
    fields,
    requiredFieldKeys: Object.entries(fields)
      .filter(([, value]) => value.present && value.required)
      .map(([key]) => key),
    categoryProperties,
    requiredCategoryProperties,
    measureProperties,
    specAxes: specDetail.map((item) => ({
      id: String(item?.id || ""),
      cp_id: item?.cp_id,
      name: String(item?.name || ""),
      specValueCount: Number(item?.specValueCount || 0),
    })),
    skuColumns: Array.isArray(skuDetail?.columns)
      ? skuDetail.columns.map((item) => ({
          key: String(item?.key || ""),
          label: String(item?.label || ""),
          required: Boolean(item?.required),
          hidden: Boolean(item?.hidden),
        }))
      : [],
  };
}

function buildDiff(summaries) {
  const byCategory = summaries.map((item) => ({
    category: item.category.path || item.category.leafId || item.input.keyword || item.input.categoryId,
    leafId: item.category.leafId,
    requiredFieldKeys: item.requiredFieldKeys,
    requiredCategoryPropertyLabels: item.requiredCategoryProperties.map((prop) => prop.label),
    measurePropertyLabels: item.measureProperties.map((prop) => prop.label),
    specAxisNames: item.specAxes.map((axis) => axis.name),
    skuColumnKeys: item.skuColumns.map((column) => column.key),
  }));

  const union = (selector) => Array.from(new Set(byCategory.flatMap(selector))).filter(Boolean).sort();
  const categoryPropertyUnion = union((item) => item.requiredCategoryPropertyLabels);
  const specAxisUnion = union((item) => item.specAxisNames);
  const skuColumnUnion = union((item) => item.skuColumnKeys);
  const requiredFieldUnion = union((item) => item.requiredFieldKeys);

  const categoryDifferences = byCategory.map((item) => ({
    category: item.category,
    leafId: item.leafId,
    missingRequiredFieldsFromUnion: requiredFieldUnion.filter((key) => !item.requiredFieldKeys.includes(key)),
    missingRequiredCategoryPropertiesFromUnion: categoryPropertyUnion.filter(
      (label) => !item.requiredCategoryPropertyLabels.includes(label)
    ),
    missingSpecAxesFromUnion: specAxisUnion.filter((name) => !item.specAxisNames.includes(name)),
    missingSkuColumnsFromUnion: skuColumnUnion.filter((key) => !item.skuColumnKeys.includes(key)),
  }));

  return {
    requiredFieldUnion,
    requiredCategoryPropertyUnion: categoryPropertyUnion,
    specAxisUnion,
    skuColumnUnion,
    byCategory,
    categoryDifferences,
  };
}

function buildRiskFindings(summaries, diff) {
  const findings = [];
  if (diff.requiredCategoryPropertyUnion.length) {
    findings.push("类目属性差异是常态，协议流水线不能硬编码筒高、面料材质、品牌等属性，必须按 schema 动态映射。");
  }
  if (diff.specAxisUnion.length) {
    findings.push("规格轴名称和数量可能因类目变化，SKU 生成不能固定为颜色分类/码数。");
  }
  if (diff.skuColumnUnion.length) {
    findings.push("SKU 表列会随类目和能力开关变化，价格/库存只应按列 key 写入，不能按固定列序号写入。");
  }
  const failed = summaries.filter((item) => !item.ok);
  if (failed.length) {
    findings.push("存在类目 schema 读取失败，正式配置界面必须暴露失败原因并禁止继续协议上传。");
  }
  return findings;
}

export async function probeFxgCategoryMatrix(options = {}) {
  const normalized = normalizeOptions(options);
  const results = [];

  for (const category of normalized.categories) {
    const schema = await probeFxgSchema({
      cdpListUrl: normalized.cdpListUrl,
      targetUrlContains: normalized.targetUrlContains,
      categoryKeyword: category.keyword,
      categoryId: category.categoryId,
      operationType: normalized.operationType,
      optionKeywords: normalized.optionKeywords,
      timeoutMs: normalized.timeoutMs,
    });
    const summary = summarizeSchema(schema, category);
    results.push(normalized.includeRaw ? { ...summary, raw: schema } : summary);
  }

  const diff = buildDiff(results);
  return {
    ok: results.every((item) => item.ok),
    categoryCount: results.length,
    categories: results,
    diff,
    riskFindings: buildRiskFindings(results, diff),
  };
}
