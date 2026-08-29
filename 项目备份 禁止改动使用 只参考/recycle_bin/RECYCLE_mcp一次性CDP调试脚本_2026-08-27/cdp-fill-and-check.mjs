import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');

    // Fill title using the correct input element
    const fillResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        const input = titleArea?.querySelector('input[type="text"]');
        if (!input) return {ok: false, error: 'input not found'};
        
        // Use native setter for React controlled input
        const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(input, 'C975测试商品 长筒袜 棉质透气 多色可选');
        
        // Dispatch React-compatible events
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        
        // Also try React's internal event system
        const fiberKey = Object.keys(input).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (fiberKey) {
          try {
            const fiber = input[fiberKey];
            let currentFiber = fiber;
            for (let i = 0; i < 20 && currentFiber; i++) {
              if (currentFiber.memoizedProps?.onChange) {
                currentFiber.memoizedProps.onChange({ target: input, currentTarget: input });
                break;
              }
              if (currentFiber.memoizedProps?.onInput) {
                currentFiber.memoizedProps.onInput({ target: input, currentTarget: input });
                break;
              }
              currentFiber = currentFiber.return;
            }
          } catch(e) {}
        }
        
        return {ok: true, value: input.value};
      })()`,
      returnByValue: true
    });
    console.log('Fill result:', JSON.stringify(fillResult.result?.value));

    // Wait
    await new Promise(r => setTimeout(r, 1000));

    // Check state now
    const state = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '下一步');
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        const input = titleArea?.querySelector('input[type="text"]');
        const mainArea = document.querySelector('[attr-field-id="主图"]');
        const imgs = mainArea?.querySelectorAll('img');
        
        return {
          nextBtnDisabled: nextBtn?.disabled,
          titleValue: input?.value || '',
          titleCharCount: (input?.value || '').length,
          imgCount: imgs?.length || 0,
          allButtons: Array.from(document.querySelectorAll('button')).map(b => ({text: b.textContent.trim().slice(0,30), disabled: b.disabled})),
        };
      })()`,
      returnByValue: true
    });
    console.log('After fill:', JSON.stringify(state.result?.value, null, 2));

    // If button still disabled, try to find what's blocking
    if (state.result?.value?.nextBtnDisabled !== false) {
      const debug = await client.call('Runtime.evaluate', {
        expression: `(() => {
          // Check for required field indicators
          const requiredFields = Array.from(document.querySelectorAll('[attr-field-id]')).map(el => {
            const label = el.querySelector('[class*="label"], [class*="title"], [class*="header"]');
            const hasStar = el.innerText.includes('*');
            const hasValue = el.querySelector('img') || (el.querySelector('input')?.value?.length > 0) || el.querySelector('textarea')?.value?.length > 0;
            return {
              id: el.getAttribute('attr-field-id'),
              hasStar,
              hasValue: !!hasValue,
            };
          });
          
          // Check for validation messages
          const msgs = Array.from(document.querySelectorAll('[class*="error"], [class*="help"], [class*="tip"], [class*="message"]')).filter(e => e.offsetParent && e.innerText.trim().length > 0);
          
          // Check if main image has error
          const imgError = document.querySelector('.style_imgErrorWrapper__utELD');
          
          return {
            requiredFields,
            validationMessages: msgs.slice(0, 5).map(m => ({class: m.className.slice(0,60), text: m.innerText.slice(0,100)})),
            hasImgError: !!imgError,
            imgErrorText: imgError?.innerText?.slice(0, 100) || '',
          };
        })()`,
        returnByValue: true
      });
      console.log('Debug:', JSON.stringify(debug.result?.value, null, 2));
    }
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
