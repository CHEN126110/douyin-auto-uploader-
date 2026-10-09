# -*- coding: utf-8 -*-
"""可见发布表单行的必填事实；只读，不把局部覆盖声明为整页证明。"""
import json

from .errors import Blocker
from .locating import LABEL_SELECTOR, ROW_SELECTOR, PROPERTY_ROW


def expression():
    config = {'row': ROW_SELECTOR, 'label': LABEL_SELECTOR, 'property': PROPERTY_ROW.row_selector}
    return r'''(() => {
      const C = CONFIG;
      // ⚠️ **`visible()` 必须同时查 `display`**：只查 `visibility` 会把
      // `display:none` 的行也算成可见（实测踩过——隐藏的旧区块被当成当前必填项）。
      const visible = e => {const r=e.getBoundingClientRect();const s=getComputedStyle(e);
        return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
      const norm = text => String(text||'').trim().replace(/^[*＊\s]+|[*＊\s]+$/g,'');
      const owners=C.row+','+C.property;
      const baseRows=Array.from(document.querySelectorAll(C.row)).filter(visible);
      const rows=Array.from(document.querySelectorAll(owners)).filter(visible);
      const own=(row,selector)=>Array.from(row.querySelectorAll(selector)).filter(e=>e.closest(owners)===row&&visible(e));
      const labelSelector=row=>row.matches(C.property)?'label':C.label;
      const labelOf=row=>{const labels=own(row,labelSelector(row));return labels.length===1?norm(labels[0].textContent):''};
      const labels=rows.map(labelOf), required=[];
      const native='input,textarea,select,[role="combobox"],[contenteditable="true"]';
      const inspect=control=>{
        // 回读不要求控件可编辑。禁用/只读的原生计算字段仍按实际值检查。
        const tag=control.tagName,type=(control.type||'text').toLowerCase();
        if(tag==='INPUT'&&['password','hidden','file','button','submit','reset','image'].includes(type))
          return {supported:false,filled:false,valid:null,reason:'special_required_control'};
        if(control.getAttribute('role')==='combobox')return {supported:false,filled:false,valid:null,reason:'combobox_selection_unconfirmed'};
        if(tag==='SELECT'){
          const selected=Array.from(control.selectedOptions).filter(o=>!o.disabled&&String(o.value||'').trim());
          return {supported:true,filled:selected.length>0,valid:control.validity.valid,reader:'native_select'};
        }
        if(tag==='INPUT'||tag==='TEXTAREA'){
          if(['checkbox','radio'].includes(type))return {supported:true,filled:control.checked===true,valid:control.validity.valid,reader:type};
          return {supported:true,filled:String(control.value||'').trim().length>0,valid:control.validity.valid,reader:'native_text'};
        }
        if(control.isContentEditable)return {supported:true,filled:!!(norm(control.textContent)||control.querySelector('img[src],video[src]')),valid:true,reader:'native_rich_text'};
        return {supported:false,filled:false,valid:null,reason:'unsupported_required_control'};
      };
      for(let index=0;index<rows.length;index++){
        const row=rows[index], ownLabels=own(row,labelSelector(row)), label=labels[index];
        const labelNode=ownLabels.length===1?ownLabels[0]:null;
        // 这一类由既有属性读取器逐值核对；本读取器补充其它区域及其它原生必填标记。
        if(row.matches(C.property)&&labelNode&&labelNode.matches('label.required'))continue;
        const controls=own(row,native);
        const nativeRequired=controls.filter(e=>e.required===true||e.getAttribute('aria-required')==='true');
        let marker=labelNode&&(labelNode.classList.contains('required')||labelNode.getAttribute('aria-required')==='true'
          ||/^[*＊]|[*＊]$/.test((labelNode.textContent||'').trim()));
        if(labelNode){
          const wrap=labelNode.closest('.sell-component-info-wrapper-label-wrap');
          if(wrap&&wrap.closest(owners)===row)marker=marker||Array.from(wrap.childNodes).some(n=>
            n!==labelNode&&/^[*＊]$/.test((n.textContent||'').trim()));
        }
        if(!marker&&!nativeRequired.length)continue;
        const entry={label,hitCount:labels.filter(x=>x===label).length,marker:marker?'label':'native',
                     supportedReader:false,filled:false,valid:null};
        if(!label||entry.hitCount!==1){required.push({...entry,reason:'required_label_not_unique'});continue}
        const values=own(row,'.next-select-values').filter(e=>!e.classList.contains('next-select-placeholder'));
        const selectedTexts=values.map(e=>{const copy=e.cloneNode(true);
          copy.querySelectorAll('.next-select-placeholder,.next-placeholder').forEach(n=>n.remove());
          return norm(copy.textContent)}).filter(Boolean);
        if(values.length===1&&controls.some(e=>e.getAttribute('role')==='combobox')){
          required.push({...entry,supportedReader:true,filled:selectedTexts.length===1,valid:true,reader:'selected_combobox'});continue;
        }
        if(label==='1:1主图'){
          const slots=own(row,'.sell-component-material-item-view');
          const filled=slots.filter(slot=>!slot.querySelector('.image-empty')&&Array.from(slot.querySelectorAll('img[src]'))
            .some(img=>/^https?:\/\/|^\/\//.test(img.getAttribute('src')||'')));
          required.push({...entry,supportedReader:slots.length>0,filled:filled.length>0,valid:true,reader:'main_images'});continue;
        }
        if(label==='当前类目'){
          // 类目行不是输入控件，是**展示路径**。判据：行内文本除标签外还有实际路径内容。
          const body=norm(Array.from(row.querySelectorAll('*')).filter(e=>!e.children.length
            &&e!==labelNode).map(e=>norm(e.textContent)).filter(Boolean).join(' '));
          const filled=body.length>0;
          required.push({...entry,supportedReader:true,filled:filled,valid:filled,
                         reader:'category_path_text'});continue;
        }
        if(label==='宝贝详情'){
          // ⚠️ **空富文本标记不算内容**：`<p><br></p>` 的 `textContent` 是空串，
          // 但 `innerText`/带空白的内容串不是——必须先**去掉所有空白**再判，
          // 否则空编辑区会被判成"已填"（这是既有契约，测试盯着它）。
          const strip=e=>String(e.textContent||'').replace(/\s+/g,'');
          // 真机的新版详情是**模块编辑器**（没有 contenteditable/textarea，E-233/234）；
          // 旧版/夹具是原生富文本。两条形态都要认。
          //
          // ⚠️ **变量名统一加 `detail` 前缀**：这段代码和后面几个分支处在**同一个块作用域**，
          // 若与别处的名字撞上就是 `SyntaxError: Identifier has already been declared`——
          // 而真机报的只是一句笼统的「页面内执行报错」，极难定位（实测踩过：
          // 注入一个 `const probeOne=1;` 都失败，才确认是重复声明而不是逻辑问题）。
          const detailEditor=Array.from(row.querySelectorAll('[contenteditable="true"],textarea'))
            .filter(visible)[0]||null;
          const detailHost=row.querySelector('.sell-component-lite-decoration-editor');
          // ⚠️ **`textarea` 的内容在 `.value` 里，不在 `textContent` 里。**
          // `textarea.textContent` 永远是空串（内容是它的 value 属性/子节点文本在
          // 解析后就变成默认值），拿 `textContent` 判会把写好内容的原生 textarea
          // 判成"空的"（实测：夹具里 `vlen=190` 而 `tlen=0`，于是详情被误报未填）。
          const detailEditorText=e=>{
            if(!e)return '';
            if(e.tagName==='TEXTAREA')return String(e.value||'').replace(/\s+/g,'');
            return strip(e);
          };
          // 编辑器里的图：contenteditable 走 DOM；textarea 走解析后的 HTML
          const detailEditorImages=e=>{
            if(!e)return [];
            if(e.tagName==='TEXTAREA'){
              const box=document.createElement('div');
              box.innerHTML=String(e.value||'');
              return Array.from(box.querySelectorAll('img[src],video[src]'))
                .filter(x=>/^https?:\/\/|^\/\//.test(x.getAttribute('src')||''));
            }
            return Array.from(e.querySelectorAll('img[src],video[src]'))
              .filter(x=>/^https?:\/\/|^\/\//.test(x.getAttribute('src')||''));
          };
          let detailText='';
          if(detailEditor){
            detailText=detailEditorText(detailEditor);
          }else{
            // 模块编辑器：把标签与"图片"这类模块入口文字排掉，只留正文
            detailText=Array.from(row.querySelectorAll('*'))
              .filter(e=>!e.children.length&&e!==labelNode)
              .map(e=>strip(e)).filter(Boolean)
              .filter(t=>!['图片','文字','视频','清空','宝贝详情'].includes(t))
              .join('');
          }
          const detailImages=detailEditor?detailEditorImages(detailEditor):[];
          // ⚠️ **有图也要算填**：详情常用**纯图片**写法（`<p><img src=…></p>`，没有文字），
          // 只看文本会把"图写进去了"判成"空的"（实测踩过）。
          const detailFilled=!!(detailEditor||detailHost)
            &&(detailImages.length>0||detailText.length>0);
          required.push({...entry,supportedReader:!!(detailEditor||detailHost),
                         filled:detailFilled,valid:detailFilled,
                         reader:detailEditor?'native_rich_text':'detail_modules'});continue;
        }
        if(label==='商品属性'){
          // 商品属性是**复合区**：本体没有控件，必填落在它的子行上（那些子行各自有
          // 独立的必填标记，但不在 `.sell-component-info-wrapper-wrap` 这一层）。
          // 判据：区里**带必填标记的子行**，其可选控件是否都有选中值。
          const marks=Array.from(row.querySelectorAll('.sell-component-info-wrapper-required')).filter(visible);
          let childRequired=0, childFilled=0;
          const seenHolder=new Set();
          for(const mark of marks){
            let node=mark.parentElement, holder=null;
            for(let level=0;level<8&&node&&node!==row;level+=1){
              const selects=Array.from(node.querySelectorAll('.next-select')).filter(visible);
              if(selects.length===1){holder=node;break;}
              if(selects.length>1)break;
              node=node.parentElement;
            }
            if(!holder||seenHolder.has(holder))continue;
            seenHolder.add(holder);
            const select=Array.from(holder.querySelectorAll('.next-select')).filter(visible)[0];
            const valBox=select.querySelector('.next-select-values')||select;
            const copy=valBox.cloneNode(true);
            copy.querySelectorAll('.next-select-placeholder,.next-placeholder').forEach(n=>n.remove());
            const value=norm(copy.textContent);
            childRequired+=1;
            if(value&&value!=='请选择')childFilled+=1;
          }
          const filled=childRequired>0&&childFilled===childRequired;
          required.push({...entry,supportedReader:childRequired>0,filled:filled,valid:filled,
                         reader:'property_composite',
                         reason:childRequired>0?'':'property_composite_no_required_child'});continue;
        }
        if(label==='销售规格'){
          const roots=own(row,'.sell-sku-table-wrapper-new');
          const skuRows=roots.length===1?Array.from(roots[0].querySelectorAll('tr.sku-table-row')).filter(visible):[];
          // ⚠️ **不能要求"行内每个 input 都有值"**：规格表里还有筛选框、批量填写框、
          // 全选框这类**本来就该是空的**输入（实测该行 44 个文本输入 + 22 个选择器），
          // 拿"全都非空"当判据会把填好的表判成"未填写"（实测踩过）。
          // 真正要核的是**规格数据本身**：每行有规格文本 + 价格/库存有有效数值。
          const fieldsOf=r=>Array.from(r.querySelectorAll('input')).filter(visible)
            .filter(e=>{const t=(e.type||'text').toLowerCase();
              return ['text','number','search','tel',''].includes(t)&&!e.readOnly});
          const numberish=r=>fieldsOf(r).filter(e=>{
            const raw=String(e.value||'').trim();
            return raw&&Number.isFinite(Number(raw.replace(/[^0-9.\-]/g,'')))&&Number(raw.replace(/[^0-9.\-]/g,''))>=0;
          });
          const present=skuRows.length>0&&skuRows.every(r=>{
            const cells=Array.from(r.querySelectorAll('td'));
            const hasSpec=cells.slice(0,2).some(c=>norm(c.textContent));
            // 每行至少要有 2 个有效数值（价格 + 库存）
            return hasSpec&&numberish(r).length>=2;
          });
          required.push({...entry,supportedReader:roots.length===1,filled:present,valid:present,reader:'sku_table'});continue;
        }
        const relevant=nativeRequired.length?nativeRequired:controls;
        // 行级单选组必须按name逐组检查，不允许其中一组有值就覆盖另一空组。
        //
        // ⚠️ **单选组的判定要看整行的单选，不能看 `controls`。**
        // `controls` 是用 `native` 选择器在**行内**取"最近的 owns 祖先就是本行"的元素；
        // 而 `上架时间`/`发货时间` 这种行的单选藏在 `div.sell-shelf-time > span.sell-radio`
        // 里，会被算到**外层容器行**上——于是本行拿到 0 个控件，`relevant.length` 为 0，
        // 最终落到 `composite_required_field_needs_adapter`（实测踩过：
        // 「上架时间」被判成"控件类型尚未支持"，而它明明有 3 个单选）。
        // 所以这里直接用 `row.querySelectorAll('input[type=radio]')` 取本行内的全部单选。
        const rowRadios=Array.from(row.querySelectorAll('input[type="radio"]')).filter(visible);
        if(rowRadios.length&&rowRadios.every(e=>e.type==='radio')){
          // ⚠️ **分组边界既不是"直接父容器"，也不是单纯的 `name`**，两种都踩过：
          //
          // * 直接父容器是 `span.next-radio`（每个单选各有一个**单例**包装），
          //   按它分组等于"每组一个"，永远"恰好一个选中"，是**假通过**；
          // * 真机上 `上架时间`/`发货时间` 的单选**全都没有 name**（空串），
          //   而 `发货时间` 一行里有**两组独立选择**（发货模式 2 个 + 发货时效 4 个），
          //   只按 name 分就合成一组，要求"恰好一个选中"必然失败。
          //
          // 所以要**两段式**：先按"第一个包含 ≥2 个单选的祖先"当容器（实测就是
          // `span.sell-radio.hoz`）；若同一容器里出现**多个不同 name**，再按 name 细分
          // （覆盖"单选是行容器直接子节点、靠 name 区分组"的页面）。
          const containerOf=e=>{
            let node=e.parentElement;
            for(let level=0;level<8&&node&&node!==row;level+=1){
              if(node.querySelectorAll('input[type="radio"]').length>=2)return node;
              node=node.parentElement;
            }
            return row;
          };
          rowRadios.forEach((e,index)=>{
            const container=containerOf(e);
            if(!container.__taobaoKey){container.__taobaoKey='g'+index;}
          });
          // ⚠️ 同一个容器里出现**多个不同的 name** 时，按 name 再细分。
          // 真机上这些单选没有 name（合成一组，正确）；而"单选是行容器直接子节点、
          // 靠 name 区分组"的页面（既有测试）必须分成 `mode` / `time` 两组，
          // 否则"一组已选"会掩盖"另一组为空"——那正是这道门要防的事。
          const groupOf=e=>{
            const container=containerOf(e);
            const key=container.__taobaoKey;
            const name=String(e.name||'');
            if(!name)return key;
            const sameNameInContainer=rowRadios.filter(x=>containerOf(x)===container
              &&String(x.name||'')===name);
            // 该容器里若存在**别的** name，就按 name 分
            const otherName=rowRadios.some(x=>containerOf(x)===container
              &&String(x.name||'')&&String(x.name||'')!==name);
            return otherName?key+':'+name:key;
          };
          const groups=[];
          for(const e of rowRadios){
            const key=groupOf(e);
            let group=groups.find(g=>g.key===key);
            if(!group){group={key,items:[]};groups.push(group);}
            group.items.push(e);
          }
          // 「支持性」看的是**整行至少有 2 个单选**，不是"每组至少 2 个"：
          // 按 name 细分后完全可能出现"每组 1 个"（实测 `mode` + `time` + `time`
          // 会分成 3 组，前两组各 1 个）——那种页面的语义就是"每个 name 各自一组"，
          // 组内 1 个单选、选中即填好。要求每组 ≥2 个会把这种页面误判成"不支持"。
          const supported=rowRadios.length>=2&&groups.length>0;
          required.push({...entry,supportedReader:supported,
                         filled:supported&&groups.every(g=>g.items.filter(e=>e.checked).length===1),
                         valid:supported&&groups.every(g=>g.items.every(e=>e.validity.valid)),
                         reader:'radio_groups',groupCount:groups.length});continue;
        }
        if(relevant.length===1){
          const fact=inspect(relevant[0]);required.push({...entry,supportedReader:fact.supported,filled:fact.filled,
                                                      valid:fact.valid,reader:fact.reader||'',reason:fact.reason||''});continue;
        }
        if(relevant.length>1&&nativeRequired.length){
          const facts=relevant.map(inspect);
          required.push({...entry,supportedReader:facts.every(f=>f.supported),filled:facts.every(f=>f.filled),
                         valid:facts.every(f=>f.valid===true),reader:'native_required_controls'});continue;
        }
        required.push({...entry,reason:'composite_required_field_needs_adapter'});
      }
      const unowned=Array.from(document.querySelectorAll('[required],[aria-required="true"]'))
        .filter(e=>visible(e)&&!e.closest(owners)&&e.tagName!=='OPTION');
      return {known:baseRows.length>0,scope:'visible_publish_rows_required',completePage:false,
              rowCount:rows.length,required,unownedRequiredCount:unowned.length,
              coverageLimits:['virtual_or_unrendered_sections_not_proven','platform_private_validation_not_run']};
    })()'''.replace('CONFIG', json.dumps(config, ensure_ascii=False), 1)


def read(client):
    payload = client.evaluate(expression())
    if (not isinstance(payload, dict) or payload.get('known') is not True
            or payload.get('scope') != 'visible_publish_rows_required' or payload.get('completePage') is not False
            or type(payload.get('rowCount')) is not int or payload['rowCount'] < 1
            or not isinstance(payload.get('required'), list)
            or len(payload['required']) > payload['rowCount']
            or type(payload.get('unownedRequiredCount')) is not int or payload['unownedRequiredCount'] < 0):
        return {'known': False, 'scope': 'visible_publish_rows_required', 'completePage': False,
                'required': [], 'reason': '未取得可解析的发布表单必填控件事实'}
    for item in payload['required']:
        if (not isinstance(item, dict) or not isinstance(item.get('label'), str)
                or type(item.get('hitCount')) is not int or type(item.get('supportedReader')) is not bool
                or type(item.get('filled')) is not bool
                or (item.get('valid') is not None and type(item.get('valid')) is not bool)):
            return {'known': False, 'scope': 'visible_publish_rows_required', 'completePage': False,
                    'required': [], 'reason': '必填控件回执字段格式不完整'}
    return payload


def blockers(coverage):
    """只根据读到的必填事实判断，不猜默认值，不返回控件中的敏感文本。"""
    def failure(code, label, detail):
        return Blocker(code=code, field=label, detail=detail, source='required_fields.readback')
    if coverage.get('known') is not True:
        return [failure('EVIDENCE_INSUFFICIENT', 'page.required_controls', coverage.get('reason') or '必填控件未知')]
    result=[]
    for item in coverage['required']:
        label=item['label'] or 'page.required_controls'
        if not item['label'] or item['hitCount'] != 1:
            result.append(failure('READBACK_UNREADABLE', label, '必填行标签缺失或不唯一'))
        elif item['supportedReader'] is not True:
            reasons={'special_required_control':'图片或文件等特殊控件需要专用读取器',
                     'combobox_selection_unconfirmed':'只有输入框内容，没有确认下拉选中值',
                     'composite_required_field_needs_adapter':'复合控件尚无对应读取器'}
            reason=item.get('reason') or 'unsupported_required_control'
            result.append(failure('UNSUPPORTED_REQUIRED_FIELD', label,
                                  '该行标为必填，'+reasons.get(reason,'当前控件类型尚未支持')))
        elif item['filled'] is not True:
            result.append(failure('REQUIRED_FIELD_MISSING', label, '当前页面标为必填，但实际控件未填写或未选择'))
        elif item['valid'] is not True:
            result.append(failure('READBACK_MISMATCH', label, '当前必填控件未通过自身格式、范围或有效性约束'))
    if coverage['unownedRequiredCount']:
        result.append(failure('UNSUPPORTED_REQUIRED_FIELD', 'page.required_controls',
                              '发现{}个不属于已识别发布表单行的可见必填控件'.format(coverage['unownedRequiredCount'])))
    return result
