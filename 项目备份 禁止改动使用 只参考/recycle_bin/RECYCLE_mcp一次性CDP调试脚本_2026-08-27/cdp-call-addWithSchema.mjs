import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');

    // Get the current page schema via the webpack form store
    const result = await client.call('Runtime.evaluate', {
      expression: `(() => {
        try {
          if (!window.__fxgWebpackRequire) return {ok:false, error:'no webpack require'};
          const req = window.__fxgWebpackRequire;
          
          // Find the form store - try known module IDs
          const storeCandidates = [99281, 991, 265, 1471];
          let store = null;
          
          for (const id of storeCandidates) {
            try {
              const mod = req(id);
              if (mod && (mod.ox || mod.getState)) {
                try {
                  const s = mod.ox ? mod.ox() : null;
                  if (s && (s.na || s.getState)) {
                    store = {moduleId: id, keys: Object.keys(s).slice(0,20)};
                    break;
                  }
                } catch(e2) {}
              }
            } catch(e) {}
          }
          
          if (!store) {
            // Try module 99281 specifically
            try {
              const mod99281 = req(99281);
              store = {moduleId: 99281, keys: Object.keys(mod99281).slice(0,30), types: {}};
              for (const k of Object.keys(mod99281).slice(0,30)) {
                store.types[k] = typeof mod99281[k];
              }
            } catch(e) {
              store = {error: e.message};
            }
          }
          
          // Try to get the submit module
          let submitInfo = null;
          try {
            const submitMod = req(51313);
            submitInfo = {
              keys: Object.keys(submitMod),
              types: Object.fromEntries(Object.keys(submitMod).slice(0,6).map(k => [k, typeof submitMod[k]]))
            };
          } catch(e) {
            submitInfo = {error: e.message};
          }
          
          return {ok:true, store, submitInfo};
          
        } catch(e) {
          return {ok:false, error: e.message};
        }
      })()`,
      returnByValue: true
    });
    console.log('Modules:', JSON.stringify(result.result?.value, null, 2));

    // Try directly calling f$ from module 51313 with a constructed request
    const callResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        try {
          const req = window.__fxgWebpackRequire;
          const submitMod = req(51313);
          
          // Try calling f$ with a minimal schema
          // The function signature from the decompiled code:
          // f = function(e, t) { ... } where e = schema, t = {check_status}
          
          // First, what does f$ actually do?
          if (typeof submitMod.f$ === 'function') {
            // Don't actually call it - just inspect
            const fnStr = submitMod.f$.toString().slice(0, 300);
            return {ok:true, f$Signature: fnStr};
          }
          if (typeof submitMod.KB === 'function') {
            const fnStr = submitMod.KB.toString().slice(0, 300);
            return {ok:true, KBSignature: fnStr};
          }
          if (typeof submitMod.DQ === 'function') {
            const fnStr = submitMod.DQ.toString().slice(0, 300);
            return {ok:true, DQSignature: fnStr};
          }
          
          return {ok:false, error:'no matching function', keys: Object.keys(submitMod)};
        } catch(e) {
          return {ok:false, error: e.message, stack: e.stack?.slice(0,300)};
        }
      })()`,
      returnByValue: true
    });
    console.log('Call:', JSON.stringify(callResult.result?.value, null, 2));
    
    // If we can see the function signature, we know how to call it
    // Then we can construct a test schema with sku_pic and call it
    // while running the capture tool
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
