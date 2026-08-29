import { withCdpTarget } from '../cdp-client.js';

await withCdpTarget({ 
  cdpListUrl: 'http://127.0.0.1:9333/json/list', 
  targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
}, async (client) => {
  await client.call('Runtime.enable');
  const r = await client.call('Runtime.evaluate', {
    expression: `(() => {
      const fields = Array.from(document.querySelectorAll('[attr-field-id]')).slice(0,20).map(e => e.getAttribute('attr-field-id'));
      const hasPriceStock = !!document.querySelector('[attr-field-id="价格与库存"]');
      const hasSku = !!document.getElementById('skuValue-颜色分类');
      const btns = Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim()).filter(Boolean).slice(0,10);
      return {fields, hasPriceStock, hasSku, btns, url: location.href};
    })()`,
    returnByValue: true
  });
  console.log(JSON.stringify(r.result?.value));
});
