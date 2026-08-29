import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');

    // Step 1: Try to get the current page's form state (schema) via the webpack modules
    const getFormState = await client.call('Runtime.evaluate', {
      expression: `(() => {
        if (!window.__fxgWebpackRequire) return {ok:false, error:'webpackRequire not found'};
        
        const req = window.__fxgWebpackRequire;
        // Module 99281 seems to be the form store (ox, etc.)
        let formModule;
        for (const [key, factory] of Object.entries(req.m || {})) {
          try {
            const mod = req(parseInt(key));
            if (mod && mod.ox && typeof mod.ox === 'function') {
              try {
                const store = mod.ox();
                const schema = store.na ? store.na('sku_detail') : null;
                if (schema) {
                  formModule = {
                    moduleId: key,
                    hasOX: true,
                    hasNA: typeof store.na === 'function',
                    skuDetailState: schema.state?.value ? 'has data' : 'empty',
                  };
                  break;
                }
              } catch(e) {}
            }
          } catch(e) {}
        }
        return {ok:true, formModule: formModule || 'not found', totalModules: Object.keys(req.m || {}).length};
      })()`,
      returnByValue: true
    });
    console.log('Form state:', JSON.stringify(getFormState.result?.value, null, 2));

    // Step 2: Try to call addWithSchema directly with a constructed payload
    const callAddWithSchema = await client.call('Runtime.evaluate', {
      expression: `(() => {
        if (!window.__fxgWebpackRequire) return {ok:false, error:'no webpack require'};
        
        const req = window.__fxgWebpackRequire;
        
        // Find the submit module (51313 from probe)
        let submitMod;
        try {
          submitMod = req(51313);
        } catch(e) {
          return {ok:false, error:'cannot require 51313: ' + e.message};
        }
        
        if (!submitMod) return {ok:false, error:'submitMod is null'};
        
        // List available functions
        const keys = Object.keys(submitMod);
        const functions = {};
        for (const key of keys) {
          functions[key] = typeof submitMod[key];
        }
        
        // Try to find the form state module to get current schema
        let formMod;
        try { formMod = req(99281); } catch(e) {}
        
        let currentSchema = null;
        if (formMod && formMod.ox) {
          try {
            const store = formMod.ox();
            const allState = {};
            // Get raw schema state
            const nodes = ['sku_detail', 'spec_detail', 'title', 'pic', 'goods_category'];
            for (const node of nodes) {
              try {
                const n = store.na ? store.na(node) : store.n ? store.n(node) : null;
                if (n && n.state) {
                  allState[node] = {
                    hasValue: n.state.value !== undefined,
                    type: typeof n.state.value,
                    isEmpty: Array.isArray(n.state.value) ? n.state.value.length === 0 : !n.state.value,
                  };
                }
              } catch(e) {}
            }
            currentSchema = allState;
          } catch(e) {
            currentSchema = {error: e.message};
          }
        }
        
        return {
          ok: true,
          submitKeys: keys,
          submitFunctions: functions,
          currentSchema
        };
      })()`,
      returnByValue: true
    });
    console.log('Module analysis:', JSON.stringify(callAddWithSchema.result?.value, null, 2));

    // Step 3: If we can access the form state, try to construct and call addWithSchema
    // First, let's just print what we can to understand the API
    const exploreForm = await client.call('Runtime.evaluate', {
      expression: `(() => {
        if (!window.__fxgWebpackRequire) return {ok:false};
        const req = window.__fxgWebpackRequire;
        
        // Try module 99281 first
        let store = null;
        try {
          const mod = req(99281);
          if (mod.ox) {
            store = mod.ox();
          }
        } catch(e) {}
        
        if (!store) return {ok:false, error:'no store'};
        
        // Get the root state
        let rootState = null;
        try {
          rootState = store.getState ? store.getState() : null;
        } catch(e) {}
        
        // Get schema model
        let model = null;
        try {
          // Try various ways to get the model
          const na = store.na;
          if (na) {
            const schema = na('schema');  // might work
            if (schema && schema.state) {
              model = {
                keys: Object.keys(schema.state.value || {}).slice(0, 30),
                hasSkuDetail: !!schema.state.value?.sku_detail,
                hasSpecDetail: !!schema.state.value?.spec_detail,
              };
            }
          }
        } catch(e) {}
        
        // Try getSchema call
        let schemaInfo = null;
        try {
          const na = store.na;
          if (na) {
            const category = na('goods_category');
            schemaInfo = {
              categoryState: category?.state?.value,
            };
          }
        } catch(e) {}
        
        return {
          ok: true,
          hasRootState: !!rootState,
          rootStateKeys: rootState ? Object.keys(rootState).slice(0, 20) : [],
          model,
          schemaInfo,
        };
      })()`,
      returnByValue: true
    });
    console.log('Form explore:', JSON.stringify(exploreForm.result?.value, null, 2));
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
