import { withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    maxModules: Number(options.maxModules || process.env.MAX_MODULES || 120),
  };
}

function buildBrowserExpression(options) {
  return `(() => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const moduleFactories = req.m && typeof req.m === 'object' ? req.m : {};
    const patterns = [
      '/product/tproduct/addWithSchema',
      '/product/tproduct/editWithSchema',
      'check_status',
      'spec_detail_ids',
      'stock_info',
      'sku_detail',
      'spec_detail',
      'spec_values',
      'sku_pic',
      'cpv_id',
      'sku_status',
      'stock_not_default_zero',
    ];

    const sanitizeSnippet = (value) => String(value)
      .replace(/__token=[^"'&]+/g, '__token=<redacted>')
      .replace(/msToken=[^"'&]+/g, 'msToken=<redacted>')
      .replace(/a_bogus=[^"'&]+/g, 'a_bogus=<redacted>');

    const extractSchemaSnippets = (moduleId, fieldPatterns, radius = 520) => {
      const factory = moduleFactories[moduleId];
      if (!factory) {
        return { ok: false, error: 'module not found' };
      }
      const source = String(factory);
      const snippets = [];
      for (const pattern of fieldPatterns) {
        const index = source.indexOf(pattern);
        if (index < 0) continue;
        const start = Math.max(0, index - radius);
        const end = Math.min(source.length, index + pattern.length + radius);
        snippets.push({
          pattern,
          snippet: sanitizeSnippet(source.slice(start, end)),
        });
      }
      return {
        ok: true,
        moduleId,
        snippetCount: snippets.length,
        snippets,
      };
    };

    const hasInModule = (moduleId, pattern) => {
      const factory = moduleFactories[moduleId];
      return Boolean(factory && String(factory).includes(pattern));
    };

    const modules = [];
    for (const [moduleId, factory] of Object.entries(moduleFactories)) {
      const source = String(factory);
      const matched = patterns.filter((pattern) => source.includes(pattern));
      if (!matched.length) continue;
      const snippets = matched.slice(0, 10).map((pattern) => {
        const index = source.indexOf(pattern);
        const start = Math.max(0, index - 260);
        const end = Math.min(source.length, index + pattern.length + 520);
        return {
          pattern,
          snippet: sanitizeSnippet(source.slice(start, end)),
        };
      });
      modules.push({ moduleId, matched, snippets });
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

    const knownModules = {
      submit51313: tryRequire(51313),
      request90665: tryRequire(90665),
      getPost28974: tryRequire(28974),
    };

    const submitModelSchemaSnippets = extractSchemaSnippets(90665, [
      'pic:y.YOg(y.Ikc({url:y.YjP()})).optional()',
      'main_image_three_to_four:y.YOg(y.Ikc({url:y.YjP()})).optional()',
      'long_pic:y.YOg(y.Ikc({url:y.YjP()})).optional()',
      'white_background_pic:y.YOg(y.Ikc({url:y.YjP()})).optional()',
      'main_pic_video:ea.optional()',
      'description:y.YjP().optional()',
      'qualification:y.g1P(y.YjP(),y.bzn()).optional()',
      'spec_detail:eN.optional()',
      'sku_detail:eU.optional()',
      'freight_id:y.YjP().optional()',
      'sale_channel_type:y.YjP().optional()',
      'enable_all_channel_product_online:y.zMY().optional()',
    ]);

    const submitModelDefinitionSnippets = extractSchemaSnippets(90665, [
      'ea=y.YOg(y.Ikc({resource_id:y.YjP(),video_choice:y.aig().optional(),video_source:y.YjP().optional(),video_application_type:ei.optional()}))',
      'main_pic_video:ea.optional()',
      'qualification:y.g1P(y.YjP(),y.bzn()).optional()',
    ], 1600);

    const skuPriceStockDefinitionSnippets = extractSchemaSnippets(90665, [
      'M=y.Ikc({id:y.YjP(),name:y.YjP().optional(),cpv_id:y.aig().optional()',
      'T=y.Ikc({id:y.YjP(),name:y.YjP(),is_default:y.zMY().optional(),cp_id:y.aig().optional()',
      'F=y.Ikc({stock_num:y.aig().optional(),stock_inc_num:y.aig().optional()',
      'X=y.Ikc({id:y.YjP().optional(),sku_id:y.YjP().optional(),spec_detail_ids:y.YOg(y.YjP()).optional()',
      'sku_detail:y.YOg(X)',
      'spec_detail:y.YOg(T)',
      'stock_info:F.optional()',
      'price:y.YjP().optional()',
      'stock:y.aig().optional()',
      'sku_pic:y.YOg(y.YjP()).optional()',
    ], 2600);

    const skuPriceStockFieldShapeSummary = {
      sourceModuleId: 90665,
      spec_value:
        hasInModule(90665, 'M=y.Ikc({id:y.YjP(),name:y.YjP().optional(),cpv_id:y.aig().optional()')
          ? {
              shape: 'object',
              required: {
                id: 'string',
              },
              optional: {
                name: 'string',
                cpv_id: 'number',
                remark: 'string',
                disabled: 'boolean',
                disabled_img: 'boolean',
                measure_info: 'object',
                checked: 'boolean',
              },
            }
          : 'unverified',
      spec_detail:
        hasInModule(90665, 'T=y.Ikc({id:y.YjP(),name:y.YjP(),is_default:y.zMY().optional(),cp_id:y.aig().optional()')
          ? {
              shape: 'array<object>',
              item: {
                required: {
                  id: 'string',
                  name: 'string',
                  spec_values: 'array<spec_value>',
                },
                optional: {
                  is_default: 'boolean',
                  cp_id: 'number',
                  invalid: 'boolean',
                  is_time_spec: 'boolean',
                },
              },
            }
          : 'unverified',
      sku_detail:
        hasInModule(90665, 'X=y.Ikc({id:y.YjP().optional(),sku_id:y.YjP().optional(),spec_detail_ids:y.YOg(y.YjP()).optional()')
          ? {
              shape: 'array<object>',
              item: {
                optional: {
                  id: 'string',
                  sku_id: 'string',
                  spec_detail_ids: 'array<string>',
                  sku_pic: 'array<string>',
                  price: 'string',
                  stock: 'number',
                  self_sell_stock: 'number',
                  code: 'string',
                  barcodes: 'string',
                  outer_sku_id: 'string',
                  sku_status: 'boolean',
                  origin_price: 'object<{ value: string, status, description?: string }>',
                  step_stock_info: 'object<{ stock_num?: number, stock_inc_num?: number, multi_delivery_day_stocks?: array }>',
                  stock_info: 'stock_info',
                  reserved_stock_info: 'object',
                  disabled_map: 'object',
                  weight: 'object<{ info_value: string, info_unit: string }>',
                },
              },
            }
          : 'unverified',
      stock_info:
        hasInModule(90665, 'F=y.Ikc({stock_num:y.aig().optional(),stock_inc_num:y.aig().optional()')
          ? {
              shape: 'object',
              optional: {
                stock_num: 'number',
                stock_inc_num: 'number',
                use_cargo_stock: 'boolean',
              },
              note: 'stock_info field exists in frontend submit schema, but the required runtime relationship between stock and stock_info still needs blocked addWithSchema evidence.',
            }
          : 'unverified',
      evidenceLimitations: [
        'This is frontend submit schema evidence, not a real addWithSchema request body.',
        'spec_detail/spec_values IDs generated by the page still need blocked request evidence.',
        'Whether price+stock alone is accepted or stock_info is required still needs blocked addWithSchema evidence.',
      ],
    };

    const submitModelFieldShapeSummary = {
      sourceModuleId: 90665,
      pic:
        hasInModule(90665, 'pic:y.YOg(y.Ikc({url:y.YjP()})).optional()')
          ? 'array<{ url: string }>'
          : 'unverified',
      main_image_three_to_four:
        hasInModule(90665, 'main_image_three_to_four:y.YOg(y.Ikc({url:y.YjP()})).optional()')
          ? 'array<{ url: string }>'
          : 'unverified',
      long_pic:
        hasInModule(90665, 'long_pic:y.YOg(y.Ikc({url:y.YjP()})).optional()')
          ? 'array<{ url: string }>'
          : 'unverified',
      white_background_pic:
        hasInModule(90665, 'white_background_pic:y.YOg(y.Ikc({url:y.YjP()})).optional()')
          ? 'array<{ url: string }>'
          : 'unverified',
      description:
        hasInModule(90665, 'description:y.YjP().optional()')
          ? 'string'
          : 'unverified',
      main_pic_video:
        hasInModule(
          90665,
          'ea=y.YOg(y.Ikc({resource_id:y.YjP(),video_choice:y.aig().optional(),video_source:y.YjP().optional(),video_application_type:ei.optional()}))'
        )
          ? 'array<{ resource_id: string, video_choice?: number, video_source?: string, video_application_type?: enum }>'
          : 'unverified',
      qualification:
        hasInModule(90665, 'qualification:y.g1P(y.YjP(),y.bzn()).optional()')
          ? 'record<string, unknown>'
          : 'unverified',
      sale_channel_type:
        hasInModule(90665, 'sale_channel_type:y.YjP().optional()')
          ? 'string'
          : 'unverified',
      enable_all_channel_product_online:
        hasInModule(90665, 'enable_all_channel_product_online:y.zMY().optional()')
          ? 'boolean'
          : 'unverified',
      unresolved: [
        'description is only confirmed as a string field; the accepted serialization format still needs addWithSchema preflight evidence',
        'media URL fields are only confirmed by schema shape; final server acceptance still needs addWithSchema preflight evidence',
        'main_pic_video and qualification have shape evidence but still need operation-specific request body evidence',
        'sale_channel_type is confirmed as a string field but has no live schema value/options yet',
      ],
      note: 'shape summary is derived from the live frontend submit schema; it is not a submit request',
    };

    const submitEnvelopeSnippets = extractSchemaSnippets(51313, [
      '/product/tproduct/addWithSchema?check_status=',
      '/product/tproduct/editWithSchema?check_status=',
      'pass_through_extra',
      'gray_components:void 0',
      'withLoadingModal:!0',
    ], 1700);

    const submitEnvelopeSummary = {
      sourceModuleId: 51313,
      addWithSchema: hasInModule(51313, '/product/tproduct/addWithSchema?check_status=') ? {
        endpoint: '/product/tproduct/addWithSchema?check_status=<check_status>',
        bodyMergeOrder: [
          '{ schema: model }',
          '{ category_id, context: { ...schema.context, gray_components: undefined } }',
          '{ pass_through_extra, optional recruit_info }',
          'submit options object containing check_status',
        ],
        withLoadingModal: hasInModule(51313, 'withLoadingModal:!0'),
      } : null,
      editWithSchema: hasInModule(51313, '/product/tproduct/editWithSchema?check_status=') ? {
        endpoint: '/product/tproduct/editWithSchema?check_status=<check_status>',
        bodyMergeOrder: [
          '{ product_id, schema: model }',
          '{ category_id, context: { ...schema.context, gray_components: undefined } }',
          '{ pass_through_extra, optional recruit_info }',
          'submit options object containing check_status',
        ],
        withLoadingModal: hasInModule(51313, 'withLoadingModal:!0'),
      } : null,
      passThroughExcludedQueryKeys: [
        'copyid',
        'category_leaf_id',
        'product_id',
        'diagnose',
        'fast_publish',
        'fast_publish_type',
        'ss_id',
        'cid',
        'biz',
        'entrance',
        'btm_ppre',
        'btm_pre',
        'btm_show_id',
      ],
      note: 'envelope summary is derived from the live frontend submit wrapper; no submit request was sent',
    };
    const preflightCapturePlan = {
      safeMode: 'Use cdp_fxg_protocol_capture with blockMatchedRequests=true so matched write requests are aborted before reaching the server.',
      requiredPageState: [
        'Current logged-in FXG publish page is reachable through CDP.',
        'The form is filled enough for the frontend to build addWithSchema instead of only local validation errors.',
      ],
      targetEndpoints: [
        '/product/tproduct/addWithSchema',
        '/product/tproduct/editWithSchema',
        '/product/tproduct/submitWhiteImg',
        '/product/tproduct/saveMaterial',
      ],
      stillBlockedWithoutPreflight: [
        'description final serialization',
        'white_background_pic audit action_list',
        'main_pic_video saveMaterial relationship',
        'qualification dynamic attachment payload',
        'complete addWithSchema envelope accepted by frontend submit wrapper',
      ],
    };

    return {
      ok: true,
      url: location.href,
      webpackModuleCount: Object.keys(moduleFactories).length,
      modules,
      knownModules,
      submitModelSchemaSnippets,
      submitModelDefinitionSnippets,
      skuPriceStockDefinitionSnippets,
      submitModelFieldShapeSummary,
      skuPriceStockFieldShapeSummary,
      submitEnvelopeSnippets,
      submitEnvelopeSummary,
      preflightCapturePlan,
    };
  })()`;
}

export async function probeFxgSubmitAndSku(options = {}) {
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
