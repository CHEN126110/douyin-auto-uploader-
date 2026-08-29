import { withCdpTarget } from '../cdp-client.js';

const TEST_IMAGE = 'E:\\Script Project\\Dyin\\beiufen\\2.0\\tmp_runtime_probe_live\\test_images\\TM.png';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');
    await client.call('DOM.enable');
    await client.call('Page.enable');

    // 1. Get document and find the file input via DOM tree
    const doc = await client.call('DOM.getDocument', { depth: -1 });
    
    // 2. Find file input under the 主图 area
    // First mark the input via JS
    const markResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const mainArea = document.querySelector('[attr-field-id="主图"]');
        const inputs = mainArea?.querySelectorAll('input[type="file"]');
        if (!inputs || inputs.length === 0) return {ok: false, count: 0};
        // Mark the first one
        inputs[0].id = 'cdp-main-image-input';
        return {ok: true, count: inputs.length, idSet: true};
      })()`,
      returnByValue: true
    });
    console.log('Mark:', JSON.stringify(markResult.result?.value));

    // 3. Now query the DOM tree for the marked element
    const nodeResult = await client.call('DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector: '#cdp-main-image-input'
    });
    console.log('Node query:', JSON.stringify({nodeId: nodeResult?.nodeId}));

    if (nodeResult.nodeId > 0) {
      // 4. Upload file
      const uploadResult = await client.call('DOM.setFileInputFiles', {
        files: [TEST_IMAGE],
        nodeId: nodeResult.nodeId
      });
      console.log('Upload result:', JSON.stringify(uploadResult));

      // Also dispatch change event via JS
      await client.call('Runtime.evaluate', {
        expression: `(() => {
          const input = document.getElementById('cdp-main-image-input');
          if (input) {
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return {ok: true};
          }
          return {ok: false};
        })()`,
        returnByValue: true
      });
    }

    // Wait for upload
    console.log('Waiting 5s for upload...');
    await new Promise(r => setTimeout(r, 5000));

    // 5. Fill title
    await client.call('Runtime.evaluate', {
      expression: `(() => {
        const area = document.querySelector('[attr-field-id="商品标题"]');
        const input = area?.querySelector('textarea, input');
        if (input && input.tagName === 'TEXTAREA') {
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          setter.call(input, 'C975测试商品-长筒袜-棉质透气-多色可选');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.dispatchEvent(new Event('blur', { bubbles: true }));
          return {ok: true, value: input.value};
        }
        return {ok: false};
      })()`,
      returnByValue: true
    });

    // 6. Check button state
    const btnState = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const nextBtn = btns.find(b => b.textContent.includes('下一步'));
        return {
          disabled: nextBtn?.disabled ?? null,
          text: nextBtn?.textContent?.trim() ?? '',
          attrFields: Array.from(document.querySelectorAll('[attr-field-id]')).slice(0,12).map(e => e.getAttribute('attr-field-id')),
        };
      })()`,
      returnByValue: true
    });
    console.log('Button state:', JSON.stringify(btnState.result?.value));

    // 7. Click if enabled
    if (btnState.result?.value?.disabled === false) {
      console.log('Clicking next step...');
      await client.call('Runtime.evaluate', {
        expression: `(() => {
          const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('下一步') && !b.disabled);
          if (nextBtn) { nextBtn.click(); return {clicked:true}; }
          return {clicked:false};
        })()`,
        returnByValue: true
      });
      await new Promise(r => setTimeout(r, 3000));

      const ps = await client.call('Runtime.evaluate', {
        expression: `(() => ({
          url: location.href,
          attrFields: Array.from(document.querySelectorAll('[attr-field-id]')).slice(0,25).map(e => e.getAttribute('attr-field-id')).filter(Boolean),
          hasPriceStock: !!document.querySelector('[attr-field-id="价格与库存"]'),
          hasSkuSection: !!document.getElementById('skuValue-颜色分类'),
          textSample: (document.body?.innerText || '').slice(0, 500)
        }))()`,
        returnByValue: true
      });
      console.log('After click:', JSON.stringify(ps.result?.value));
    } else {
      console.log('Button still disabled - may need category selection too');
    }
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
