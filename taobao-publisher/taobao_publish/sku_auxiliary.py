# -*- coding: utf-8 -*-
"""平台动态 SKU 附加规格列：按真实表头填写，并逐格回读。

主规格（通常是颜色分类）仍由 `form_adapters.create_custom_skus` 创建。
本模块只处理平台随后生成的额外表格列，不把 SKU 备注猜成规格值。
"""
import json
import time

from .category_defaults import hosiery_height_for
from .sku_specs import primary_spec_name, primary_spec_value


_AUX_CONTROL_EXPRESSION = r'''(() => {
  const A=INPUT;
  const roots=Array.from(document.querySelectorAll('.sell-sku-table-wrapper-new'));
  if(roots.length!==1)return {ok:false,reason:'sku_root_not_unique'};
  const rows=Array.from(roots[0].querySelectorAll('tr.sku-table-row'));
  const row=rows[A.rowIndex];
  if(!row)return {ok:false,reason:'sku_row_missing'};
  const cell=row.querySelectorAll('td')[A.columnIndex];
  if(!cell)return {ok:false,reason:'sku_cell_missing'};
  const combo=cell.querySelector('input[role="combobox"]');
  const input=combo||cell.querySelector('input,textarea');
  if(A.action==='read'){
    // 淘宝异步下拉选中值在展示层，input.value 可能始终为空；展示值优先，原生输入兜底。
    const displays=combo?Array.from(cell.querySelectorAll('.next-select-values'))
      .map(el=>(el.innerText||el.textContent||'').trim()).filter(Boolean):[];
    const displayed=displays.find(text=>text&&text!=='请选择')||'';
    const value=combo?(displayed||String(combo.value||'')):(input?String(input.value||''):'');
    const kind=combo?'combobox':cell.classList.contains('sell-sku-cell-skuMeasurement')?'measurement':input?'text':'other';
    return {ok:true,kind:kind,value:value,text:(cell.innerText||cell.textContent||'').trim()};
  }
  if(A.action==='open_measurement'){
    const overlay=cell.querySelector('.fake-input-wrapper .overlay');
    if(!overlay)return {ok:false,reason:'measurement_overlay_missing'};
    overlay.click();return {ok:true,kind:'measurement'};
  }
  if(A.action==='open'&&combo){
    if(combo.disabled)return {ok:false,reason:'sku_aux_control_disabled'};
    combo.click();combo.focus();return {ok:true,kind:'combobox'};
  }
  if(A.action==='write'&&input&&!combo){
    if(input.disabled||input.readOnly)return {ok:false,reason:'sku_aux_control_readonly'};
    const proto=Object.getPrototypeOf(input);
    const descriptor=Object.getOwnPropertyDescriptor(proto,'value');
    if(descriptor&&descriptor.set)descriptor.set.call(input,A.value);
    else input.value=A.value;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
    input.dispatchEvent(new Event('blur',{bubbles:true}));
    return {ok:true,kind:'text'};
  }
  return {ok:false,reason:'sku_aux_control_unsupported'};
})()'''


def _control_expression(row_index, column_index, action, value=''):
    payload = {'rowIndex':int(row_index),'columnIndex':int(column_index),'action':action,'value':str(value)}
    return _AUX_CONTROL_EXPRESSION.replace('INPUT',json.dumps(payload,ensure_ascii=False),1)


def _read_cell(client, row_index, column_index):
    result = client.evaluate(_control_expression(row_index,column_index,'read'))
    if not isinstance(result,dict) or result.get('ok') is not True:
        from . import page
        raise page.PageError('无法读取 SKU 附加规格单元格：{}行 {}列'.format(row_index+1,column_index+1))
    return result


def read_sku_auxiliary_headers(client):
    """返回与 ``td`` 索引一致的动态表头，不用列序号猜字段。"""
    result = client.evaluate(r'''(() => {
      const roots=Array.from(document.querySelectorAll('.sell-sku-table-wrapper-new'));
      if(roots.length!==1)return {ok:false,reason:'sku_root_not_unique'};
      const headers=Array.from(roots[0].querySelectorAll('.sell-sku-table-header-common-new'));
      return {ok:true,headers:headers.map((el,index)=>({
        index,name:(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(),
        required:el.classList.contains('required')}))};
    })()''')
    if not isinstance(result,dict) or result.get('ok') is not True:
        from . import page
        raise page.PageError('无法读取 SKU 动态规格表头')
    return list(result.get('headers') or [])


def _resolved_values(item, headers):
    """在任何写入前解析全部值；缺商品事实就明确失败。"""
    from . import page
    primary = {primary_spec_name(sku) for sku in item.skus}
    if len(primary) != 1 or not next(iter(primary), ''):
        raise page.PageError('SKU 主规格维度不明确，无法补填附加规格列')
    primary_name = next(iter(primary))
    header_names = {str(header.get('name') or '') for header in headers}
    unknown = sorted({key for sku in item.skus for key in (sku.spec_values or {})
                      if key != primary_name and key not in header_names})
    if unknown:
        raise page.PageError('SKU 规格资料在当前表格没有对应列：' + '、'.join(unknown))
    resolved = {}
    for header in headers:
        name = str(header.get('name') or '').strip()
        required = header.get('required') is True
        if not name or name in ('价格','数量') or name == primary_name:
            continue
        values = []
        category_path = item.category.path or (item.category.search_keyword,)
        for sku in item.skus:
            value = str((sku.spec_values or {}).get(name,'') or '').strip()
            if not value and name == '袜筒高度':
                value = hosiery_height_for(category_path) or ''
            values.append(value)
        if required and any(not value for value in values):
            raise page.PageError(
                'SKU 必填规格「{}」缺少资料；请在对应 SKU 资料列中明确填写后再发布'.format(name))
        if any(values):
            if any(not value for value in values):
                raise page.PageError('SKU 附加规格「{}」并非每行都有明确值'.format(name))
            resolved[name] = values
    return resolved


def _measurement_point_expression(selector, option_text=''):
    return r'''(() => {
      const SELECTOR=SELECTOR_VALUE,OPTION=OPTION_VALUE;
      const popups=Array.from(document.querySelectorAll('.sell-common-sale-props-multi-expression-overlay'))
        .filter(el=>el.getBoundingClientRect().height>0);
      const popup=popups[popups.length-1];
      let target=null;
      if(OPTION){
        const menus=Array.from(document.querySelectorAll('.next-select-popup-wrap'))
          .filter(el=>el.getBoundingClientRect().height>0);
        const menu=menus[menus.length-1];
        if(menu)target=Array.from(menu.querySelectorAll('.options-item'))
          .find(el=>(el.textContent||'').trim()===OPTION);
      }else if(popup){
        target=popup.querySelector(SELECTOR);
      }
      if(!target)return null;
      target.scrollIntoView({block:'center',inline:'center'});
      const rect=target.getBoundingClientRect();
      return {x:rect.left+rect.width/2,y:rect.top+rect.height/2};
    })()'''.replace('SELECTOR_VALUE',json.dumps(selector,ensure_ascii=False)) \
             .replace('OPTION_VALUE',json.dumps(option_text,ensure_ascii=False))


def _click_measurement(client, selector, option_text=''):
    from . import page
    point = client.evaluate(_measurement_point_expression(selector,option_text))
    if not isinstance(point,dict):
        raise page.PageError('组合规格控件未就绪：' + (option_text or selector))
    page._click_point(client,point,settle=0.05,event_interval=0.03)


def _fill_measurement_cell(client, row_index, column_index, value):
    """用真实鼠标路径填写“数量 + 单位”，不直接写外层受控文本。"""
    from . import page
    import re
    match = re.fullmatch(r'[1-9]\d*',str(value))
    if not match:
        raise page.PageError('双数必须是正整数，例如 1 或 2；不接受其它文本或带单位后缀的值')
    quantity,unit = match.group(0),'双'
    opened = client.evaluate(_control_expression(row_index,column_index,'open_measurement'))
    if not isinstance(opened,dict) or opened.get('ok') is not True:
        raise page.PageError('无法打开双数组合输入面板：' + str(opened))
    _click_measurement(client,'input[placeholder="请输入数量"]')
    client.send('Input.insertText',{'text':quantity})
    if _read_cell(client,row_index,column_index).get('value') == _display_value('measurement',value):
        return
    _click_measurement(client,'.next-select')
    _click_measurement(client,'.options-item',unit)
    if _read_cell(client,row_index,column_index).get('value') == _display_value('measurement',value):
        _click_measurement(client,'.mask')


def _display_value(kind, value):
    return str(value) + '双' if kind == 'measurement' else str(value)


def _fill_cell(client, row_index, column_index, value, *, timeout=4.0):
    from . import page
    before = _read_cell(client,row_index,column_index)
    kind = before.get('kind')
    expected_display = _display_value(kind,value)
    if before.get('value') == expected_display:
        return
    if kind == 'measurement':
        _fill_measurement_cell(client,row_index,column_index,value)
    elif kind == 'combobox':
        opened = client.evaluate(_control_expression(row_index,column_index,'open'))
        if not isinstance(opened,dict) or opened.get('ok') is not True:
            raise page.PageError('SKU 附加规格下拉无法打开：' + str(opened))
        picked = client.evaluate(page.build_pick_spec_value_expression(value))
        if not isinstance(picked,dict) or picked.get('ok') is not True:
            raise page.CandidateNotFound('SKU 附加规格没有精确候选 {!r}：{}'.format(value,picked))
    elif kind == 'text':
        written = client.evaluate(_control_expression(row_index,column_index,'write',value))
        if not isinstance(written,dict) or written.get('ok') is not True:
            raise page.PageError('SKU 附加规格文本写入失败：' + str(written))
    else:
        raise page.PageError('SKU 附加规格单元格不支持填写')
    deadline = time.monotonic() + timeout
    while True:
        actual = _read_cell(client,row_index,column_index).get('value')
        if actual == expected_display:
            return
        if time.monotonic() >= deadline:
            raise page.FieldMismatchError(
                'SKU 附加规格回读不符：期望 {!r}，实际 {!r}'.format(expected_display,actual))
        time.sleep(0.1)


def fill_sku_auxiliary_values(client, item):
    """填写并回读平台动态附加规格列，返回结构化填写回执。"""
    from . import page
    headers = read_sku_auxiliary_headers(client)
    if not headers:
        return {'columns':[],'required_columns':[],'filled_cells':0}
    values = _resolved_values(item,headers)
    rows = list(page.read_sku_table(client).get('rows') or [])
    if len(rows) != len(item.skus):
        raise page.PageError('补填附加规格前 SKU 行数不一致')
    by_primary = {primary_spec_value(sku): index for index,sku in enumerate(item.skus)}
    if len(by_primary) != len(item.skus):
        raise page.PageError('SKU 主规格值重复，不能确认附加规格对应行')
    row_indexes = []
    for row in rows:
        specs = list(row.get('specs') or [])
        if len(specs) != 1 or specs[0] not in by_primary:
            raise page.PageError('SKU 附加规格无法按主规格对应行：' + '、'.join(specs))
        row_indexes.append(by_primary[specs[0]])
    filled = 0
    for header in headers:
        name = str(header.get('name') or '')
        if name not in values:
            continue
        for row_index, sku_index in enumerate(row_indexes):
            _fill_cell(client,row_index,int(header['index']),values[name][sku_index])
            filled += 1
    # 全部动作结束后再次读表头与每个目标格，不能只依赖写入函数返回值。
    for header in headers:
        name = str(header.get('name') or '')
        required = header.get('required') is True and name not in ('价格','数量')
        for row_index, sku_index in enumerate(row_indexes):
            cell = _read_cell(client,row_index,int(header['index']))
            if name in values:
                expected = _display_value(cell.get('kind'),values[name][sku_index])
                if cell.get('value') != expected:
                    raise page.FieldMismatchError(
                        'SKU「{}」第 {} 行回读不符：期望 {!r}，实际 {!r}'.format(
                            name,row_index+1,expected,cell.get('value')))
            elif required and not str(cell.get('value') or '').strip():
                raise page.FieldMismatchError('SKU 必填规格「{}」第 {} 行仍为空'.format(name,row_index+1))
    return {'columns':[str(header.get('name') or '') for header in headers if str(header.get('name') or '') in values],
            'required_columns':[str(header.get('name') or '') for header in headers
                                if header.get('required') is True and str(header.get('name') or '') not in ('价格','数量')],
            'filled_cells':filled}
