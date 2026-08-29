import { withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    maxModules: Number(options.maxModules || process.env.MAX_MODULES || 160),
    snippetRadius: Number(options.snippetRadius || process.env.SNIPPET_RADIUS || 900),
    deepScan: Boolean(options.deepScan || /^(1|true|yes|on)$/i.test(String(process.env.DEEP_SCAN || ""))),
  };
}

function buildBrowserExpression(options) {
  return `(async () => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const lazyChunkLoads = [];
    const loadLazyChunk = async (chunkId, chunkLabel) => {
      const before = Object.keys(req.m || {}).length;
      if (!req.e || typeof req.e !== 'function') {
        lazyChunkLoads.push({
          chunkId,
          chunkLabel,
          ok: false,
          reason: 'webpack chunk loader req.e is not available',
          moduleCountBefore: before,
          moduleCountAfter: before,
        });
        return false;
      }
      try {
        await req.e(chunkId);
        const after = Object.keys(req.m || {}).length;
        lazyChunkLoads.push({
          chunkId,
          chunkLabel,
          ok: true,
          moduleCountBefore: before,
          moduleCountAfter: after,
        });
        return true;
      } catch (error) {
        lazyChunkLoads.push({
          chunkId,
          chunkLabel,
          ok: false,
          reason: String(error && error.message || error),
          moduleCountBefore: before,
          moduleCountAfter: Object.keys(req.m || {}).length,
        });
        return false;
      }
    };
    await loadLazyChunk(2492, 'goods-components-MaterialImg');

    const moduleFactories = req.m && typeof req.m === 'object' ? req.m : {};
    const endpointPatterns = [
      '/product/tproduct/saveMaterial',
      '/product/tproduct/materialDetail',
      '/product/tproduct/material/batchApplyMaterial',
      '/product/tproduct/submitWhiteImg',
      '/product/tproduct/batchDelMaterials',
      '/product/tproduct/batchApprovalWhiteImgs',
      '/doudian/ai/same_pic/judge_main_pic',
      '/product/img/batchupload',
      '/common/img/IsWhiteBackgroundPic',
      '/product/tproduct/img/IntelligentOptimizeVerify',
      '/product/img/trans_img_style',
      '/product/tproduct/batchSaveMaterial',
    ];
    const payloadPatterns = [
      'material_type',
      'material_ids',
      'bind_object',
      'product_id',
      'media_metaData',
      'composite_video_metaData_extra_properties',
      'request_source',
      'main_pic_video',
      'white_background_pic',
      'proof_pictures',
      'qualification',
      '主图视频',
      '白底图',
      '装修主图',
      '商品素材',
      'MaterialImg',
      'highQualityWhite',
      'IsWhiteBackgroundPic',
    ];
    const patterns = endpointPatterns.concat(payloadPatterns);

    const sanitizeSnippet = (value) => String(value)
      .replace(/__token=[^"'&]+/g, '__token=<redacted>')
      .replace(/msToken=[^"'&]+/g, 'msToken=<redacted>')
      .replace(/a_bogus=[^"'&]+/g, 'a_bogus=<redacted>');

    const summarizeValue = (value, depth = 0) => {
      if (depth > 3) return '<max-depth>';
      if (value == null) return value;
      const type = typeof value;
      if (type === 'function') return '<function>';
      if (type === 'string') return sanitizeSnippet(value.length > 240 ? value.slice(0, 240) + '...<truncated>' : value);
      if (type === 'number' || type === 'boolean') return value;
      if (Array.isArray(value)) {
        return {
          type: 'array',
          length: value.length,
          sample: value.slice(0, 12).map((item) => summarizeValue(item, depth + 1)),
        };
      }
      if (type === 'object') {
        const entries = Object.entries(value).slice(0, 120);
        return Object.fromEntries(entries.map(([key, item]) => [key, summarizeValue(item, depth + 1)]));
      }
      return '<unsupported>';
    };

    const modules = [];
    for (const [moduleId, factory] of Object.entries(moduleFactories)) {
      const source = String(factory);
      const matched = patterns.filter((pattern) => source.includes(pattern));
      if (!matched.length) continue;
      const snippets = matched.slice(0, 14).map((pattern) => {
        const index = source.indexOf(pattern);
        const radius = Math.max(200, Math.min(Number(options.snippetRadius) || 900, 3000));
        const start = Math.max(0, index - radius);
        const end = Math.min(source.length, index + pattern.length + radius);
        return {
          pattern,
          snippet: sanitizeSnippet(source.slice(start, end)),
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
        const entries = Object.entries(mod).slice(0, 100);
        return {
          ok: true,
          keys: Object.keys(mod).slice(0, 100),
          types: Object.fromEntries(entries.map(([key, value]) => [key, typeof value])),
          valueSummary: summarizeValue(mod),
        };
      } catch (error) {
        return { ok: false, error: String(error && error.message || error) };
      }
    };

    const knownModuleIds = [9559, 12274, 14796, 25595, 55060, 71532, 73896, 86908, 16365, 60026, 13305, 18828];
    const knownModules = Object.fromEntries(knownModuleIds.map((moduleId) => [moduleId, tryRequire(moduleId)]));

    const materialTypeCandidates = [];
    for (const [moduleId, summary] of Object.entries(knownModules)) {
      if (!summary.ok || !summary.valueSummary || typeof summary.valueSummary !== 'object') continue;
      for (const [exportKey, value] of Object.entries(summary.valueSummary)) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
        const entries = Object.entries(value).filter(([, item]) => typeof item === 'number' || typeof item === 'string');
        if (!entries.length) continue;
        const keyText = entries.map(([key]) => key).join(',');
        if (!/主图|视频|白底|素材|资质|装修|material/i.test(keyText + exportKey)) continue;
        materialTypeCandidates.push({
          moduleId,
          exportKey,
          values: Object.fromEntries(entries.slice(0, 80)),
        });
      }
    }

    const hasInModule = (moduleId, pattern) => {
      const factory = moduleFactories[moduleId];
      return Boolean(factory && String(factory).includes(pattern));
    };

    const sourceOf = (moduleId) => {
      const factory = moduleFactories[moduleId];
      return factory ? String(factory) : '';
    };

    const containsAll = (moduleId, patterns) => {
      const source = sourceOf(moduleId);
      return patterns.every((pattern) => source.includes(pattern));
    };

    const materialImgComponentSummary = {
      chunkId: 2492,
      chunkLabel: 'goods-components-MaterialImg',
      moduleId: 9559,
      exportName: knownModules[9559]?.ok && knownModules[9559]?.keys?.includes('MaterialImg') ? 'MaterialImg' : null,
      formKey: containsAll(9559, ['form_key', 'white_background_pic']) ? ['white_background_pic'] : null,
      valueMapping: containsAll(9559, ['mapValue', 'onUpdateValue', 'white_background_pic']) ? {
        mapValue: 'model value array -> url string array',
        onUpdateValue: 'url string array -> array<{ url: string }>',
      } : null,
      imageAspectValidation: hasInModule(12274, 'getValidateImgAspectRatioCacheKey') ? {
        sourceModuleId: 12274,
        exportedFunction: 'QG',
        behavior: 'checks local or remote image dimensions against aspect constraints before accepting white background image',
      } : null,
      whiteBackgroundQualityCheck: hasInModule(71532, '/common/img/IsWhiteBackgroundPic') ? {
        sourceModuleId: 71532,
        endpoint: '/common/img/IsWhiteBackgroundPic',
        requestShape: {
          url: 'image url list or value from MaterialImg validator',
          high_quality_check: true,
          shop_id: 'current shop id',
          product_id: 'product id',
          product_name: 'product title',
        },
      } : null,
      intelligentOptimizeVerify: hasInModule(71532, '/product/tproduct/img/IntelligentOptimizeVerify') ? {
        sourceModuleId: 71532,
        endpoint: '/product/tproduct/img/IntelligentOptimizeVerify',
      } : null,
      aiWhiteImageGenerate: hasInModule(14796, '/product/img/trans_img_style') ? {
        sourceModuleId: 14796,
        endpoint: '/product/img/trans_img_style',
        requestShape: {
          urls: 'source image urls',
          style: 7,
          material_infos: 'optional material metadata',
        },
      } : null,
      batchApprovalWhiteImgs: hasInModule(9559, '/product/tproduct/batchApprovalWhiteImgs') ? {
        sourceModuleId: 9559,
        endpoint: '/product/tproduct/batchApprovalWhiteImgs',
        requestShape: {
          approval_materials: [{
            product_id: 'product id',
            material_id: 'white_background_pic.extra.additions.material_id',
            material_type: 1,
          }],
        },
      } : null,
      imageUploadComponent: hasInModule(73896, '/product/img/batchupload') ? {
        sourceModuleId: 73896,
        endpoint: '/product/img/batchupload?_bid=ffa_goods',
        singleRequestShape: {
          image: 'File',
          extra: { request_source: 'pc' },
        },
      } : null,
      unresolved: [
        'submitWhiteImg.action_list concrete values were not found in MaterialImg chunk',
        'MaterialImg confirms white_background_pic component value mapping, not the accepted final addWithSchema request',
        'whether addWithSchema white_background_pic can skip submitWhiteImg audit flow remains unverified',
      ],
      note: 'summary is derived from lazy-loaded MaterialImg component source; no white image audit, saveMaterial, or submit request was sent',
    };

    const buildTargetedChunkScanSummary = async () => {
      if (!options.deepScan) {
        return {
          enabled: false,
          reason: 'set DEEP_SCAN=1 to load and scan related async chunks',
        };
      }
      const chunkEntries = [];
      const chunkMatcher = /(\\d+):"([^"]+)"/g;
      const chunkSource = String(req.u || '');
      let chunkMatch;
      while ((chunkMatch = chunkMatcher.exec(chunkSource))) {
        chunkEntries.push({ id: Number(chunkMatch[1]), name: chunkMatch[2] });
      }
      const relatedChunkPattern = /material|img|image|video|qualification|goods-components|goods-container|create-goods|edit-goods|publish|detail/i;
      const relatedChunks = chunkEntries.filter((entry) => relatedChunkPattern.test(entry.name));
      const loaded = [];
      const failed = [];
      for (const chunk of relatedChunks) {
        try {
          await req.e(chunk.id);
          loaded.push(chunk);
        } catch (error) {
          failed.push({
            id: chunk.id,
            name: chunk.name,
            reason: String(error && error.message || error).slice(0, 300),
          });
        }
      }

      const searchPatterns = [
        'submitWhiteImg',
        'whiteImgUrl',
        'actionList',
        'action_list',
        '/product/tproduct/submitWhiteImg',
        'batchApprovalWhiteImgs',
      ];
      const hitModules = [];
      for (const [moduleId, factory] of Object.entries(req.m || {})) {
        const source = String(factory || '');
        const matched = searchPatterns.filter((pattern) => source.includes(pattern));
        if (!matched.length) continue;
        hitModules.push({ moduleId, matched });
      }
      const submitCallerPatterns = ['submitWhiteImg', 'whiteImgUrl', 'actionList', 'action_list', '/product/tproduct/submitWhiteImg'];
      const submitCallerCandidates = hitModules.filter((item) => (
        item.moduleId !== '55060'
        && item.matched.some((pattern) => submitCallerPatterns.includes(pattern))
      ));
      return {
        enabled: true,
        relatedChunkPattern: String(relatedChunkPattern),
        relatedChunkCount: relatedChunks.length,
        loadedChunkCount: loaded.length,
        failedChunkCount: failed.length,
        failedChunks: failed.slice(0, 30),
        searchPatterns,
        submitCallerPatterns,
        hitModules,
        submitCallerCandidates,
        conclusion: submitCallerCandidates.length
          ? 'submitWhiteImg/action_list appeared outside wrapper module 55060; inspect submitCallerCandidates'
          : 'submitWhiteImg/action_list still only appeared in wrapper module 55060 after related async chunks were loaded',
      };
    };

    const targetedChunkScanSummary = await buildTargetedChunkScanSummary();

    const whiteImageFlowSummary = {
      sourceModuleId: 55060,
      submitWhiteImg: hasInModule(55060, '/product/tproduct/submitWhiteImg') ? {
        endpoint: '/product/tproduct/submitWhiteImg',
        requestShape: {
          name: 'whiteImgUrl',
          product_id: 'productId',
          action_list: 'actionList',
        },
      } : null,
      batchApprovalWhiteImgs: hasInModule(55060, '/product/tproduct/batchApprovalWhiteImgs') ? {
        endpoint: '/product/tproduct/batchApprovalWhiteImgs',
        requestShape: {
          approval_materials: 'approval material list',
        },
      } : null,
      cancelProductMaterialPicAudit: hasInModule(55060, '/product/tproduct/CancelProductMaterialPicAudit') ? {
        endpoint: '/product/tproduct/CancelProductMaterialPicAudit',
        requestShape: {
          product_id: 'product id',
          materail_type: 'material type',
        },
      } : null,
      unresolved: [
        'submitWhiteImg.action_list concrete values',
        'whether addWithSchema white_background_pic can skip submitWhiteImg audit flow',
      ],
      note: 'summary is derived from the live frontend material wrapper; no white image audit request was sent',
    };

    return {
      ok: true,
      url: location.href,
      webpackModuleCount: Object.keys(moduleFactories).length,
      lazyChunkLoads,
      endpointPatterns,
      modules,
      knownModules,
      materialTypeCandidates,
      materialImgComponentSummary,
      targetedChunkScanSummary,
      whiteImageFlowSummary,
      note: 'read-only module scan; no saveMaterial/addWithSchema request was sent',
    };
  })()`;
}

export async function probeFxgMaterialModules(options = {}) {
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
