import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');
    await client.call('Input.enable');

    // 1. Focus the title input via JS
    const focusResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        const input = titleArea?.querySelector('input[type="text"]');
        if (!input) return {ok:false, error:'no input'};
        input.focus();
        input.click();
        return {ok:true, tag: input.tagName};
      })()`,
      returnByValue: true
    });
    console.log('Focus:', JSON.stringify(focusResult.result?.value));

    await new Promise(r => setTimeout(r, 300));

    // 2. Insert text via CDP Input (simulates real typing)
    const titleText = 'C975长筒袜棉质透气多色可选';
    for (let i = 0; i < 3; i++) {
      await client.call('Input.insertText', { text: titleText });
      await new Promise(r => setTimeout(r, 200));
    }

    await new Promise(r => setTimeout(r, 500));

    // 3. Check state
    const state = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        const input = titleArea?.querySelector('input[type="text"]');
        const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('下一步'));
        const mainArea = document.querySelector('[attr-field-id="主图"]');
        const imgs = mainArea?.querySelectorAll('img');
        return {
          nextBtnDisabled: nextBtn?.disabled,
          titleValue: input?.value || '',
          titleLen: (input?.value || '').length,
          imgCount: imgs?.length || 0,
        };
      })()`,
      returnByValue: true
    });
    console.log('State:', JSON.stringify(state.result?.value, null, 2));

    // 4. If title is set, try uploading image again
    if ((state.result?.value?.titleLen || 0) > 0) {
      // Find and upload main image
      const markImgInput = await client.call('Runtime.evaluate', {
        expression: `(() => {
          const mainArea = document.querySelector('[attr-field-id="主图"]');
          const inputs = mainArea?.querySelectorAll('input[type="file"]');
          if (inputs?.length > 0) {
            inputs[0].id = 'cdp-main-img';
            return {ok:true, count: inputs.length};
          }
          return {ok:false};
        })()`,
        returnByValue: true
      });
      console.log('Mark img input:', JSON.stringify(markImgInput.result?.value));

      const doc = await client.call('DOM.getDocument', { depth: -1 });
      const node = await client.call('DOM.querySelector', {
        nodeId: doc.root.nodeId,
        selector: '#cdp-main-img'
      });
      
      if (node.nodeId > 0) {
        const testImg = 'E:\\Script Project\\Dyin\\beiufen\\2.0\\tmp_runtime_probe_live\\test_images\\TM.png';
        await client.call('DOM.setFileInputFiles', { nodeId: node.nodeId, files: [testImg] });
        console.log('Image uploaded');
        
        await client.call('Runtime.evaluate', {
          expression: `document.getElementById('cdp-main-img')?.dispatchEvent(new Event('change', {bubbles:true}))`,
          returnByValue: true
        });
      }

      await new Promise(r => setTimeout(r, 3000));

      const finalState = await client.call('Runtime.evaluate', {
        expression: `(() => {
          const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('下一步'));
          const input = document.querySelector('[attr-field-id="商品标题"] input[type="text"]');
          const imgs = document.querySelectorAll('[attr-field-id="主图"] img');
          return {
            nextBtnDisabled: nextBtn?.disabled,
            titleValue: input?.value || '',
            imgCount: imgs?.length || 0,
          };
        })()`,
        returnByValue: true
      });
      console.log('Final:', JSON.stringify(finalState.result?.value, null, 2));

      if (finalState.result?.value?.nextBtnDisabled === false) {
        console.log('CLICKING NEXT');
        await client.call('Runtime.evaluate', {
          expression: `Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('下一步') && !b.disabled)?.click()`,
          returnByValue: true
        });
        await new Promise(r => setTimeout(r, 3000));
        
        const step2 = await client.call('Runtime.evaluate', {
          expression: `(() => ({
            url: location.href,
            attrFields: Array.from(document.querySelectorAll('[attr-field-id]')).slice(0,20).map(e => e.getAttribute('attr-field-id')),
            hasPriceStock: !!document.querySelector('[attr-field-id="价格与库存"]'),
          }))()`,
          returnByValue: true
        });
        console.log('Step 2:', JSON.stringify(step2.result?.value, null, 2));
      }
    }
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
