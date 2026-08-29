/**
 * Shared FXG webpack chunk bootstrap snippet.
 * Injected verbatim into every fxg-*-probe browser expression so the chunk name and
 * the webpack runtime push protocol only need to be maintained in one place.
 * Read-only: it captures `__fxgWebpackRequire` and never triggers any upload or submit call.
 */
export const FXG_WEBPACK_BOOTSTRAP_SNIPPET = `    const chunkName = Object.keys(window).find((key) => key.includes('@ecom-mcenter/ffa-goods'));
    if (!chunkName || !Array.isArray(window[chunkName])) {
      return { ok: false, error: 'FXG webpack chunk was not found.', url: location.href };
    }
    if (!window.__fxgWebpackRequire) {
      window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
        window.__fxgWebpackRequire = req;
      }]);
    }
    const req = window.__fxgWebpackRequire;
    if (typeof req !== 'function') {
      return { ok: false, error: 'FXG webpack require was not captured.', url: location.href };
    }`;
