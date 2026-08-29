import { withCdpTarget, normalizeCdpListUrl } from '../cdp-client.js';

async function go() {
  const cdpListUrl = 'http://127.0.0.1:9333/json/list';
  const targetHint = 'fxg.jinritemai.com/ffa/g/create';

  await withCdpTarget({ cdpListUrl, targetUrlContains: targetHint }, async (client) => {
    // 1. 先看按钮状态
    const btnResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const nextBtn = btns.find(b => b.textContent.includes('下一步'));
        if (!nextBtn) return {found: false, allBtns: btns.map(b => b.textContent.trim().slice(0,20)).filter(Boolean)};
        return { found: true, text: nextBtn.textContent.trim(), disabled: nextBtn.disabled, visible: nextBtn.offsetParent !== null };
      })()`,
      returnByValue: true
    });
    console.log('Button state:', JSON.stringify(btnResult.result?.value, null, 2));

    // 2. 查找并填写标题
    await client.call('Runtime.evaluate', {
      expression: `(() => {
        const area = document.querySelector('[attr-field-id="商品标题"]');
        if (!area) return {ok:false, error:'no title area'};
        const input = area.querySelector('textarea, input');
        if (input && input.tagName === 'TEXTAREA') {
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          setter.call(input, '测试商品SKU规格图验证用');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          return {ok:true, value: input.value};
        }
        return {ok:false, tag: input?.tagName};
      })()`,
      returnByValue: true
    });

    // 3. 点击下一步
    console.log('Clicking next...');
    const clickResult = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const nextBtn = btns.find(b => b.textContent.includes('下一步') && !b.disabled && b.offsetParent !== null);
        if (!nextBtn) return {clicked:false, reason:'next button not available'};
        nextBtn.click();
        return {clicked:true};
      })()`,
      returnByValue: true
    });
    console.log('Click result:', JSON.stringify(clickResult.result?.value, null, 2));

    // 等2秒看变化
    await new Promise(r => setTimeout(r, 2000));

    // 检查页面状态
    const pageState = await client.call('Runtime.evaluate', {
      expression: `(() => {
        return {
          url: location.href,
          title: document.title,
          attrFields: Array.from(document.querySelectorAll('[attr-field-id]')).slice(0,25).map(e => e.getAttribute('attr-field-id')).filter(Boolean),
          hasPriceStock: !!document.querySelector('[attr-field-id="价格与库存"]'),
          hasSkuSection: !!document.getElementById('skuValue-颜色分类'),
          hasNextStep: Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('下一步')),
          hasPublish: Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('发布') || b.textContent.includes('提交')),
          textSample: (document.body?.innerText || '').slice(0, 400)
        };
      })()`,
      returnByValue: true
    });
    console.log('Page state:', JSON.stringify(pageState.result?.value, null, 2));
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
