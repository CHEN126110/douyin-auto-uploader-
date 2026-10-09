/* 人工类目页模型；href 仅为测试数据，不导航、请求或连接任何平台。 */
window.setupCategoryModel = function (variant) {
  const originals = Array.from(document.body.children).map(el => [el, el.style.display]);
  originals.forEach(([el]) => { el.style.display = 'none'; });
  const root = document.createElement('section');
  root.innerHTML = '<input placeholder="可输入产品名称、类目关键词、条码信息">' +
    '<button id="model-search">搜索</button>' +
    '<div role="tab" id="model-tab">类目</div><div id="model-candidates"></div>' +
    '<div id="model-breadcrumb"></div>' +
    '<div class="sell-catProp-item-common"><label>品牌*</label><input id="model-brand" role="combobox" readonly></div>' +
    '<div class="sell-o-select-options" id="model-brand-options" hidden><div class="options-search"><input id="model-brand-search"></div><div id="model-brand-items"></div></div>' +
    '<button id="model-next" disabled>确认，下一步</button>';
  document.body.appendChild(root);
  const state = window.categoryModel = {
    href: 'https://item.upload.taobao.com/sell/ai/category.htm',
    keyword: '', brand: '', events: [], nextClicks: 0, candidateClicks: 0
  };
  const input = root.querySelector('input');
  input.addEventListener('input', () => { state.keyword = input.value; state.events.push('input'); });
  input.addEventListener('change', () => { state.keyword = input.value; state.events.push('change'); });
  const renderBrands = () => {
    const list = root.querySelector('#model-brand-items'); list.innerHTML = '';
    const labels = variant === 'brand_missing' ? ['模型注册品牌'] :
      variant === 'brand_duplicate' ? ['无品牌', '无品牌'] :
      variant === 'brand_alias' ? ['无品牌/无注册商标'] : ['无品牌', '模型注册品牌'];
    labels.forEach(name => {
      const item = document.createElement('div'); item.className = 'options-item';
      const text = document.createElement('span'); text.className = 'info-content'; text.textContent = name;
      item.appendChild(text);
      if (variant === 'brand_disabled' && name === '无品牌') item.setAttribute('aria-disabled', 'true');
      item.onclick = () => {
        state.brand = name; state.events.push('brand_select');
        root.querySelector('#model-brand').value = name;
        root.querySelector('#model-brand-options').hidden = true;
        setTimeout(() => { if (variant !== 'brand_unconfirmed') root.querySelector('#model-next').disabled = false; }, 25);
      };
      list.appendChild(item);
    });
  };
  root.querySelector('#model-brand').onclick = () => {
    state.events.push('brand_open'); root.querySelector('#model-brand-options').hidden = false; renderBrands();
  };
  root.querySelector('#model-brand-search').onchange = () => { state.events.push('brand_search'); renderBrands(); };
  const search = root.querySelector('#model-search');
  search.disabled = variant === 'search_disabled';
  search.onclick = () => { state.events.push('search'); };
  root.querySelector('#model-tab').onclick = () => {
    state.events.push('category_tab');
    const candidates = variant === 'missing' ? ['模型上级>长筒袜'] :
      variant === 'ambiguous' ? ['模型上级>中筒袜', '另一个模型上级>中筒袜'] : ['模型上级>中筒袜'];
    const list = root.querySelector('#model-candidates');
    list.innerHTML = '';
    candidates.forEach(path => {
      const container = document.createElement('div');
      container.className = 'sell-component-general-category-result-cate-path';
      const text = document.createElement('span');
      text.className = 'sell-rich-text path-text';
      text.textContent = path;
      text.onclick = () => {
        state.candidateClicks++;
        state.events.push('select_category');
        setTimeout(() => {
          const breadcrumb = root.querySelector('#model-breadcrumb');
          breadcrumb.innerHTML = '';
          path.split('>').forEach(segment => {
            const item = document.createElement('span');
            item.className = 'category-item selected';
            item.textContent = segment;
            breadcrumb.appendChild(item);
          });
          root.querySelector('#model-next').disabled = true;
        }, 25);
      };
      container.appendChild(text);
      list.appendChild(container);
    });
  };
  root.querySelector('#model-next').onclick = () => {
    state.nextClicks++;
    state.events.push('next');
    if (variant === 'next_stays') return;
    setTimeout(() => {
      state.href = 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=' +
        (variant === 'invalid_id' ? '0' : '900000001');
      const carried = originals.map(([el]) => el).find(el => el.matches('.sell-catProp-item-common'));
      if (carried) carried.querySelector('input').value = state.brand;
      root.remove();
      originals.forEach(([el, display]) => { el.style.display = display; });
    }, 25);
  };
};
