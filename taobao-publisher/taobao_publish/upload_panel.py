"""素材上传面板：明确上传至全部图片，复用现有原生/Fusion选择控件。"""
import json
import time

from . import page


def destination_expression(action='read'):
    if action not in ('read', 'open', 'pick'):
        raise ValueError('未知上传目录动作')
    return r'''(() => {
      const action=ACTION;
      const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;};
      const nodes=Array.from(document.querySelectorAll('[class*="UploadPanel_uploadDir"]')).filter(visible);
      if(nodes.length!==1)return {ok:false,reason:'upload_destination_not_unique'};
      const owner=nodes[0], ownSelect=owner.matches('select')?owner:owner.querySelector('select');
      if(ownSelect){
        if(ownSelect.multiple)return {ok:false,reason:'upload_destination_is_multiple'};
        if(action==='pick'){
          const matches=Array.from(ownSelect.options).filter(o=>o.textContent.trim()==='全部图片'
            &&!o.disabled&&!o.closest('optgroup[disabled]'));
          if(ownSelect.disabled||matches.length!==1)return {ok:false,reason:'all_images_option_unavailable'};
          Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(ownSelect,matches[0].value);
          ownSelect.dispatchEvent(new Event('change',{bubbles:true}));
        }
        const selected=ownSelect.selectedOptions;
        return {ok:true,kind:'native_select',value:selected.length===1?selected[0].textContent.trim():''};
      }
      const inputs=owner.querySelectorAll('[role=combobox]');
      if(inputs.length!==1)return {ok:false,reason:'upload_destination_control_unknown'};
      const input=inputs[0], values=owner.querySelector('.next-select-values');
      const value=(values?.textContent||owner.textContent||'').trim();
      if(action==='read')return {ok:true,kind:'combobox',value};
      if(input.disabled||owner.getAttribute('aria-disabled')==='true')return {ok:false,reason:'upload_destination_disabled'};
      if(action==='open'){
        owner.click();return {ok:true,kind:'combobox',value};
      }
      const id=input.getAttribute('aria-controls')||input.getAttribute('aria-owns');
      const owned=id?document.getElementById(id):null;
      const popups=owned&&visible(owned)?[owned]:Array.from(document.querySelectorAll('.next-select-popup-wrap,[role=listbox]')).filter(visible)
        .filter(el=>!el.parentElement.closest('.next-select-popup-wrap,[role=listbox]'));
      if(popups.length!==1)return {ok:false,reason:'upload_destination_popup_not_unique'};
      const options=Array.from(popups[0].querySelectorAll('[role=option],.next-menu-item,.next-tree-node-label'))
        .filter(el=>visible(el)&&el.textContent.trim()==='全部图片');
      const hits=options.filter(el=>!options.some(other=>other!==el&&el.contains(other)));
      if(hits.length!==1||hits[0].closest('[aria-disabled=true],.next-disabled'))
        return {ok:false,reason:'all_images_option_unavailable'};
      hits[0].click();return {ok:true,kind:'combobox'};
    })()'''.replace('ACTION',json.dumps(action),1)


def ensure_all_images(client, *, context_id, timeout=3.0):
    def run(action):
        result=client.evaluate(destination_expression(action),context_id=context_id)
        if not isinstance(result,dict) or result.get('ok') is not True:
            reason=result.get('reason','无有效结果') if isinstance(result,dict) else '无有效结果'
            raise page.PageError('无法确认上传至全部图片：'+reason)
        return result
    initial=run('read')
    if initial.get('value')=='全部图片':
        return initial
    if initial.get('kind')=='combobox':
        run('open')
        time.sleep(0.2)
    run('pick')
    deadline=time.monotonic()+timeout
    while True:
        result=run('read')
        if result.get('value')=='全部图片':
            return result
        if time.monotonic()>=deadline:
            raise page.FieldMismatchError('上传目标未回读为全部图片，尚未发送文件')
        time.sleep(0.1)
