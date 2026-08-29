import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');

    // Check current page state in detail
    const state = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const results = {};
        
        // 1. Button state
        const btns = Array.from(document.querySelectorAll('button'));
        const nextBtn = btns.find(b => b.textContent.trim() === '下一步');
        results.nextBtn = nextBtn ? {
          disabled: nextBtn.disabled,
          className: nextBtn.className.slice(0, 100),
          parentClass: nextBtn.parentElement?.className?.slice(0, 100),
        } : 'not found';
        
        // 2. Title
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        const textarea = titleArea?.querySelector('textarea');
        results.title = textarea ? {
          value: textarea.value,
          placeholder: textarea.placeholder,
          hasText: textarea.value.length > 0,
        } : 'no textarea';
        
        // 3. Main images - check if any uploaded
        const mainArea = document.querySelector('[attr-field-id="主图"]');
        const imgs = mainArea?.querySelectorAll('img');
        results.mainImages = {
          imgCount: imgs?.length || 0,
          imgSrcs: Array.from(imgs || []).slice(0, 3).map(i => i.src.slice(0, 80)),
        };
        
        // 4. Category
        const catArea = document.querySelector('[attr-field-id="商品类目"]');
        results.category = catArea ? {
          hasContent: catArea.innerText.length > 20,
          textSample: catArea.innerText.slice(0, 100),
          hasInput: !!catArea.querySelector('input'),
        } : 'no cat area';
        
        // 5. All attr fields
        results.allFields = Array.from(document.querySelectorAll('[attr-field-id]')).map(e => ({
          id: e.getAttribute('attr-field-id'),
          hasValue: e.innerText.length > 20 || e.querySelector('img'),
          text: e.innerText.slice(0, 50),
        }));
        
        // 6. Any error messages
        const errors = Array.from(document.querySelectorAll('[class*="error"], [class*="Error"], [class*="warning"], [class*="tip"]')).filter(e => e.offsetParent !== null);
        results.errors = errors.slice(0, 5).map(e => ({
          class: e.className.slice(0, 80),
          text: e.innerText?.slice(0, 80),
        }));
        
        return results;
      })()`,
      returnByValue: true
    });
    console.log(JSON.stringify(state.result?.value, null, 2));
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
