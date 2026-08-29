import { withCdpTarget } from '../cdp-client.js';

async function go() {
  await withCdpTarget({ 
    cdpListUrl: 'http://127.0.0.1:9333/json/list', 
    targetUrlContains: 'fxg.jinritemai.com/ffa/g/create' 
  }, async (client) => {
    await client.call('Runtime.enable');

    // Find all editable elements in the page
    const result = await client.call('Runtime.evaluate', {
      expression: `(() => {
        const findings = {};
        
        // Approach 1: Find any input/textarea/contenteditable inside title area
        const titleArea = document.querySelector('[attr-field-id="商品标题"]');
        if (titleArea) {
          const allInputs = titleArea.querySelectorAll('input, textarea, [contenteditable="true"]');
          findings.titleInputs = Array.from(allInputs).map(el => ({
            tag: el.tagName,
            type: el.type || '',
            contentEditable: el.contentEditable,
            className: el.className?.slice(0, 80),
            placeholder: el.placeholder || '',
            value: (el.value || el.innerText || '').slice(0, 50),
            visible: el.offsetParent !== null,
          }));
          
          // Also check for react-controlled inputs
          const allElements = titleArea.querySelectorAll('*');
          findings.titleElementCount = allElements.length;
          
          // Look for the actual text container
          const textContainers = Array.from(allElements).filter(e => 
            (e.innerText || '').includes('标题内容需包含') || 
            e.getAttribute('placeholder')?.includes('标题')
          );
          findings.textContainers = textContainers.map(e => ({
            tag: e.tagName,
            text: e.innerText?.slice(0, 100),
            className: e.className?.slice(0, 80),
          }));
          
          // Try to find the react fiber/state
          const fiberKey = Object.keys(titleArea).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
          findings.hasFiber = !!fiberKey;
        } else {
          findings.titleArea = 'not found';
        }
        
        // Approach 2: Find category
        const catSelectors = ['商品类目', '类目', 'category'];
        for (const sel of catSelectors) {
          const area = document.querySelector('[attr-field-id="' + sel + '"]');
          if (area) {
            findings.category = { selector: sel, html: area.innerHTML.slice(0, 200) };
            break;
          }
        }
        if (!findings.category) findings.category = 'not found';
        
        // Approach 3: Check all buttons
        findings.allButtons = Array.from(document.querySelectorAll('button')).slice(0, 8).map(b => ({
          text: b.textContent.trim().slice(0, 30),
          disabled: b.disabled,
          visible: b.offsetParent !== null,
        }));
        
        return findings;
      })()`,
      returnByValue: true
    });
    console.log(JSON.stringify(result.result?.value, null, 2));
  });
}

go().catch(e => { console.error('Error:', e.message); process.exit(1); });
