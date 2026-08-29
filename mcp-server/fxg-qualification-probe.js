import { withCdpTarget } from "./cdp-client.js";
import { FXG_WEBPACK_BOOTSTRAP_SNIPPET } from "./fxg-webpack-bootstrap.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

function normalizeOptions(options = {}) {
  return {
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    maxModules: Number(options.maxModules || process.env.MAX_MODULES || 120),
    snippetRadius: Number(options.snippetRadius || process.env.SNIPPET_RADIUS || 1200),
  };
}

function buildBrowserExpression(options) {
  return `(() => {
    const options = ${JSON.stringify(options)};
${FXG_WEBPACK_BOOTSTRAP_SNIPPET}

    const moduleFactories = req.m && typeof req.m === 'object' ? req.m : {};
    const patterns = [
      'qualification',
      'Qualification',
      'QualityInspection',
      'quality_inspection_info',
      'select_attachments',
      'quality_attachment_id',
      'reference_price_certificate_urls',
      '/ffa/grs/qualification/list',
      '/ffa/mshop/qualification/list',
      '/product/img/batchupload',
      '/product/tproduct/addWithSchema',
      '水洗标',
      '吊牌',
      '包装标签图',
      '赠品资质',
      '报关单',
      '质检报告',
      '老字号认证证书',
      '合格证',
    ];
    const sectionTerms = [
      '资质',
      '质检',
      '合格证',
      '包装标签图',
      '赠品资质',
      '报关单',
      '老字号认证证书',
      '水洗标',
      '吊牌',
    ];

    const sanitizeSnippet = (value) => String(value)
      .replace(/__token=[^"'&]+/g, '__token=<redacted>')
      .replace(/msToken=[^"'&]+/g, 'msToken=<redacted>')
      .replace(/a_bogus=[^"'&]+/g, 'a_bogus=<redacted>');

    const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    const rectOf = (el) => {
      const rect = el.getBoundingClientRect();
      return {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        visible: rect.width > 0 && rect.height > 0,
      };
    };
    const sectionMatches = (el) => {
      const id = el.getAttribute('attr-field-id') || '';
      const text = textOf(el);
      return sectionTerms.some((term) => id.includes(term) || text.includes(term));
    };

    const modules = [];
    for (const [moduleId, factory] of Object.entries(moduleFactories)) {
      const source = String(factory);
      const matched = patterns.filter((pattern) => source.includes(pattern));
      if (!matched.length) continue;
      const radius = Math.max(300, Math.min(Number(options.snippetRadius) || 1200, 4000));
      const snippets = matched.slice(0, 12).map((pattern) => {
        const index = source.indexOf(pattern);
        const start = Math.max(0, index - radius);
        const end = Math.min(source.length, index + pattern.length + radius);
        return {
          pattern,
          snippet: sanitizeSnippet(source.slice(start, end)),
        };
      });
      modules.push({ moduleId, matched, snippets });
      if (modules.length >= options.maxModules) break;
    }

    const sourceOf = (moduleId) => {
      const factory = moduleFactories[moduleId];
      return factory ? String(factory) : '';
    };
    const hasInModule = (moduleId, pattern) => sourceOf(moduleId).includes(pattern);

    const schemaSummary = {
      sourceModuleId: 90665,
      qualification:
        hasInModule(90665, 'qualification:y.g1P(y.YjP(),y.bzn()).optional()')
          ? 'record<string, unknown>'
          : 'unverified',
      quality_inspection_info:
        hasInModule(90665, 'quality_inspection_info:y.Ikc')
          ? 'object<{ support_quality_inspection, quality_inspection_stock_mode?, quality_inspection_agency?, quality_inspection_certificate_code? }>'
          : 'unverified',
      reference_price_certificate_urls:
        hasInModule(90665, 'reference_price_certificate_urls:y.YOg(y.YjP()).optional()')
          ? 'array<string>'
          : 'unverified',
    };
    const qualificationComponentSummary = {
      sourceModuleId: 82042,
      formPath:
        hasInModule(82042, 'node("qualification").node(n.id).nodeArray("select_attachments")')
          ? 'qualification.<qualItem.id>.select_attachments'
          : 'unverified',
      attachmentKeys: {
        quality_attachment_id: hasInModule(82042, 'quality_attachment_id'),
        quality_content_name: hasInModule(82042, 'quality_content_name'),
        quality_attachments: hasInModule(82042, 'quality_attachments'),
        url: hasInModule(82042, '.url') || hasInModule(82042, 'url:'),
      },
      note: 'These keys are component/module evidence only. The final addWithSchema request body still needs local preflight capture before protocol submission is enabled.',
    };

    const fieldSections = Array.from(document.querySelectorAll('[attr-field-id]'))
      .filter(sectionMatches)
      .map((el, index) => ({
        index,
        attrFieldId: el.getAttribute('attr-field-id') || '',
        text: textOf(el).slice(0, 500),
        rect: rectOf(el),
        fileInputs: Array.from(el.querySelectorAll("input[type='file']")).slice(0, 10).map((input) => ({
          accept: input.getAttribute('accept') || '',
          disabled: Boolean(input.disabled) || input.getAttribute('aria-disabled') === 'true',
          rect: rectOf(input),
        })),
        buttons: Array.from(el.querySelectorAll("button,[role='button'],a")).slice(0, 20).map((button) => ({
          text: textOf(button).slice(0, 100),
          disabled: Boolean(button.disabled) || button.getAttribute('aria-disabled') === 'true',
          rect: rectOf(button),
        })),
      }));

    return {
      ok: true,
      url: location.href,
      webpackModuleCount: Object.keys(moduleFactories).length,
      schemaSummary,
      qualificationComponentSummary,
      moduleCount: modules.length,
      modules,
      fieldSections,
      note: 'Read-only qualification probe. It scans current page modules and DOM; no upload, save, draft, or publish request is sent.',
    };
  })()`;
}

export async function probeFxgQualification(options = {}) {
  const normalized = normalizeOptions(options);
  return withCdpTarget(
    {
      cdpListUrl: normalized.cdpListUrl,
      targetUrlContains: normalized.targetUrlContains,
    },
    async (client, target) => {
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
          target,
        };
      }
      return {
        target: {
          id: target.id,
          title: target.title,
          url: target.url,
        },
        ...(result.result?.value || {}),
      };
    }
  );
}
