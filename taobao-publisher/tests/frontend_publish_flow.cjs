const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '../..');
const frontend = path.join(root, 'tauri-app');
const vue = require(path.join(frontend, 'node_modules/vue'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
const {parse, compileScript} = require(path.join(frontend, 'node_modules/@vue/compiler-sfc'));
const source = fs.readFileSync(path.join(frontend, 'src/views/ProductManager.vue'), 'utf8');
const {descriptor} = parse(source);
const compiled = compileScript(descriptor, {id: 'qa-real-product-manager'}).content;
const javascript = ts.transpileModule(compiled, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
const categories = [{value:0,label:'船袜'},{value:1,label:'短袜'},{value:2,label:'中筒袜'},{value:3,label:'长筒袜'},{value:4,label:'袜套'}];
const defer = () => {let resolve, reject; const promise = new Promise((r,j)=>{resolve=r;reject=j});return {promise,resolve,reject};};
const flush = async () => {for(let i=0;i<20;i++)await Promise.resolve();};
function task(extra={}) {return {task_id:'tao-task',platform:'taobao',account_profile:'tao-account',record_id:7,record_name:'ID-7',status:'running',progress:40,message:'填写中',steps:[],dry_run:false,stop_before_submit:true,publish_confirmed:false,result:null,created_at:'2026-10-04T00:00:00',...extra};}
function fixture() {
  const calls = [], notices = [], alerts = [], timers = new Map(); let counter=0;
  const store = vue.reactive({
    currentProductId:7,currentProduct:{id:7,name:'ID-7',title:'真实商品标题',remark:'',repo:100,clazz:2,content:[{name:'黑白组合',path:'SKU/black.jpg',price:29.8},{name:'粉色套装',path:'SKU/pink.jpg',price:32.8}]},
    currentShopSession:{platform:'taobao',active_profile:'tao-account'},targetPublishPlatform:'taobao',detailLoading:false,backendStatus:'offline',products:[],
    lastActionError:null,
    saveProduct:async(data,options)=>{calls.push(['save',JSON.parse(JSON.stringify(data)),options]);return {id:options.recordId,update_time:'2026-10-04 01:00',record_revision:'a'.repeat(64)}},
    fetchProducts:async()=>{calls.push(['fetchProducts'])},refreshCurrentProductSilently:async()=>{calls.push(['refreshProduct'])},
    getUploadStatus:async(id)=>{calls.push(['douyin-status',id]);return {success:true,data:{task_id:id,status:'running',progress:10,message:'抖音上传中'}}},
    startUpload:async(id,options)=>{calls.push(['douyin-start',id,options]);return {success:true,data:{task_id:'dy-task'}}},
    setShopSession(s){this.currentShopSession=s},
  });
  Object.defineProperty(store,'currentSkus',{get(){return store.currentProduct?.content||[]}});
  const api = {
    getTaobaoReadiness:async()=>{throw Error('must not check readiness')},prepareTaobaoProduct:async()=>{throw Error('must not prepare')},
    getTaobaoPublishStatus:async(id)=>{calls.push(['taobao-status',id]);return {success:true,data:task({task_id:id})}},
    listTaobaoPublishTasks:async()=>{calls.push(['taobao-list']);return {success:true,data:{count:0,tasks:[]}}},
    getUploadTasks:async()=>{calls.push(['douyin-list']);return {success:true,data:{tasks:[]}}},
    getSettings:async()=>({success:true,data:{settings:{automation_config:{publish_submit_mode_effective:'stop'}}}}),
    cancelTaobaoPublish:async(id)=>{calls.push(['taobao-cancel',id]);return {success:true,data:{task_id:id,status:'running'}}},
    cancelUpload:async(id)=>{calls.push(['douyin-cancel',id]);return {success:true}},
  };
  store.startTaobaoFill=async(id,product,account)=>{calls.push(['taobao-start',id,JSON.parse(JSON.stringify(product)),account]);return {success:true,data:{task_id:'tao-task',dry_run:false,stop_before_submit:true}}};
  const requireStub = name => {
    if(name==='vue')return {...vue,onMounted:()=>{},onUnmounted:()=>{}};
    if(name==='vue-router')return {useRouter:()=>({push:p=>calls.push(['navigate',p])})};
    if(name==='axios')return {__esModule:true,default:{isAxiosError:e=>Boolean(e?.isAxiosError)}};
    if(name==='element-plus')return {ElMessage:{success:m=>notices.push(['success',m]),error:m=>notices.push(['error',m]),warning:m=>notices.push(['warning',m]),info:m=>notices.push(['info',m])},ElMessageBox:{alert:async(...a)=>alerts.push(a),confirm:async()=>{}},ElButton:'button',ElLoading:{service:options=>{calls.push(['loading-open',options]);return {setText:()=>{},close:()=>calls.push(['loading-close'])}}}};
    if(name==='@/stores/productStore')return {useProductStore:()=>store};
    if(name==='@/utils/taobaoTextLength' || name==='@/utils/taobaoFormVerification'){
      const content=fs.readFileSync(path.join(frontend,'src/utils',name.split('/').pop()+'.ts'),'utf8');
      const js=ts.transpileModule(content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
      const module={exports:{}};vm.runInNewContext(js,{module,exports:module.exports});return module.exports;
    }
    if(name==='@/types')return {CATEGORY_OPTIONS:categories};
    if(name==='@/services/api')return {api};
    if(name.endsWith('.vue'))return {__esModule:true,default:{}};
    throw Error('unmocked dependency '+name);
  };
  const module={exports:{}};
  vm.runInNewContext(javascript,{module,exports:module.exports,require:requireStub,console:{...console,error:(...a)=>calls.push(['expected-error',...a]),warn:(...a)=>calls.push(['expected-warning',...a])},Set,Map,Date,Promise,
    window:{setInterval:f=>{timers.set(++counter,f);return counter},clearInterval:i=>timers.delete(i),addEventListener:()=>{},removeEventListener:()=>{}},
    document:{visibilityState:'visible',addEventListener:()=>{},removeEventListener:()=>{}},},{filename:'actual-ProductManager.vue'});
  const s=module.exports.default.setup({}, {expose:()=>{}});
  return {s,store,api,calls,notices,alerts,timers};
}
function actualStoreFixture(respond) {
  const posts=[];
  const http={get:async()=>{},post:async(url,payload)=>{posts.push([url,JSON.parse(JSON.stringify(payload))]);return respond(url,payload)},interceptors:{response:{use:()=>{}}}};
  const apiSource=fs.readFileSync(path.join(frontend,'src/services/api.ts'),'utf8');
  const apiJs=ts.transpileModule(apiSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
  const m={exports:{}};vm.runInNewContext(apiJs,{module:m,exports:m.exports,require:n=>n==='axios'?{__esModule:true,default:{create:()=>http}}:n==='@tauri-apps/api/core'?{invoke:async()=>{}}:n==='@/types'?{}:(()=>{throw Error(n)})(),console});
  const storeSource=fs.readFileSync(path.join(frontend,'src/stores/productStore.ts'),'utf8');
  const storeJs=ts.transpileModule(storeSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
  const st={exports:{}};vm.runInNewContext(storeJs,{module:st,exports:st.exports,require:n=>n==='pinia'?{defineStore:(_id,setup)=>setup}:n==='vue'?vue:n==='element-plus'?{}:n==='@/services/api'?{api:m.exports.api,initializeApi:async()=>{}}:(()=>{throw Error(n)})(),console:{...console,error:()=>{}},Map,Set,Date});
  return {store:st.exports.useProductStore(),posts};
}
function completeResult() {return {success:true,stopped_before_submit:true,data:{form_verification:{status:'complete',complete:true,reason:'人工模型整页回执',required_field_coverage:{known:true,completePage:true,scope:'whole_publish_form_required_fields',rowCount:8,required:[{label:'品牌',hitCount:1,supportedReader:true},{label:'标题',hitCount:1,supportedReader:true}],checked:[{label:'品牌',value:'无品牌'},{label:'标题',value:'人工模型商品'}],checkedCount:2}}}}}
const tests=[];
async function test(name,fn){await fn();tests.push(name);}
(async()=>{
  await test('淘宝点击直接启动真实填写，携带完整资料快照且不检查、不跳设置',async()=>{
    const f=fixture();f.s.formData.value.price=0.01;await f.s.handlePublishByAccount();await flush();
    const start=f.calls.find(c=>c[0]==='taobao-start');assert(start);assert.equal(start[1],7);assert.equal(start[3],'tao-account');
    assert.deepEqual(start[2],{title:'真实商品标题',category_keyword:'中筒袜',outer_id:'ID-7',sku_mode:'custom',skus:[{spec_values:{颜色分类:'黑白组合'},price:29.8,stock:100,image_path:'SKU/black.jpg'},{spec_values:{颜色分类:'粉色套装'},price:32.8,stock:100,image_path:'SKU/pink.jpg'}]});
    assert.equal(f.s.activeUploadTaskPlatform.value,'taobao');assert.equal(f.s.uploadProgress.value,40);assert(!f.calls.some(c=>c[0]==='navigate'||c[0]==='douyin-start'));assert(!source.includes('TaobaoPreflightSummary'));
  });
  await test('重复点击不重复启动',async()=>{const f=fixture();await f.s.handlePublishByAccount();await flush();await f.s.handlePublishByAccount();assert.equal(f.calls.filter(c=>c[0]==='taobao-start').length,1)});
  for(const [name,change]of [['空标题',f=>f.s.formData.value.title=' '],['负库存',f=>f.s.formData.value.repo=-1],['小数库存',f=>f.s.formData.value.repo=1.5],['无类目',f=>f.s.formData.value.clazz=null],['无效价格',f=>f.store.currentSkus[0].price=Infinity],['重复规格',f=>f.store.currentSkus[1].name=f.store.currentSkus[0].name]]){
    await test(`${name}阻止启动且无伪造默认值`,async()=>{const f=fixture();change(f);await f.s.handlePublishByAccount();assert(!f.calls.some(c=>c[0]==='taobao-start'))});
  }
  await test('POST返回后仍跟进启动时账户与商品，即使本地数据已变化',async()=>{
    const f=fixture(),d=defer(),entered=defer();f.store.startTaobaoFill=async()=>{entered.resolve();return d.promise};const pending=f.s.handlePublishByAccount();await entered.promise;f.store.currentProductId=8;f.store.currentShopSession.active_profile='other';f.s.formData.value.title='另一个标题';d.resolve({success:true,data:{task_id:'tao-task',dry_run:false,stop_before_submit:true}});await pending;await flush();assert.equal(f.s.activeUploadTaskId.value,'tao-task');assert.equal(f.s.activeUploadContext.value.recordId,7);assert.equal(f.s.activeUploadContext.value.accountProfile,'tao-account');assert.equal(f.s.uploadProgress.value,40);
  });
  await test('填写成功须真实非dry-run且回读成功并停在提交前',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',progress:100,result:completeResult()})});await f.s.handlePublishByAccount();await flush();assert.equal(f.s.activeUploadTaskId.value,null);assert.equal(f.alerts.length,1);assert.equal(f.alerts[0][1],'上传完成');assert.equal(f.alerts[0][2].type,'success');assert(!JSON.stringify(f.alerts).includes('发布成功'));
  });
  for(const [name,extra]of [['dry-run结束',{dry_run:true,result:{success:true,stopped_before_submit:true}}],['回读未成功',{result:{success:false,stopped_before_submit:true}}],['发生过提交',{result:{success:true,stopped_before_submit:false}}]]){
    await test(`${name}不能伪报填写完成`,async()=>{const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',...extra})});await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning')});
  }
  for(const [name,result] of [
    ['旧结果无覆盖证据',{success:true,stopped_before_submit:true}],
    ['部分必填回读',{success:true,stopped_before_submit:true,data:{form_verification:{status:'partial',complete:false,required_field_coverage:{known:true,completePage:false,scope:'visible_property_label_required'}}}}],
    ['完整标志但覆盖仍为部分',{...completeResult(),data:{form_verification:{status:'complete',complete:true,required_field_coverage:{known:true,completePage:false,scope:'visible_property_label_required'}}}}],
    ['覆盖来源不明',{...completeResult(),data:{form_verification:{status:'complete',complete:true,required_field_coverage:{known:true,completePage:true,scope:'unknown'}}}}]
  ]) {
    await test(name+'不报完整填写',async()=>{const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result})});await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');assert.equal(f.s.activeUploadTaskId.value,null)});
  }
  for (const [name, patch] of [
    ['缺少必填清单', {required:undefined}],
    ['空必填回执', {required:[],checked:[],checkedCount:0}],
    ['必填数大于行数', {rowCount:1}],
    ['回读清单缺失', {checked:undefined}],
    ['回读缺值', {checked:[{label:'品牌',value:''},{label:'标题',value:'人工模型商品'}]}],
    ['回读多余项', {checked:[{label:'品牌',value:'无品牌'},{label:'标题',value:'人工模型商品'},{label:'额外',value:'错误项'}],checkedCount:3}],
    ['回读重复项', {checked:[{label:'品牌',value:'无品牌'},{label:'品牌',value:'无品牌'}]}],
    ['回读数量矛盾', {checkedCount:1}],
    ['行数缺失', {rowCount:undefined}],
    ['行数非整数', {rowCount:1.5}],
    ['未知读取器', {required:[{label:'品牌',hitCount:1,supportedReader:false},{label:'标题',hitCount:1,supportedReader:true}]}],
    ['歧义必填项', {required:[{label:'品牌',hitCount:2,supportedReader:true},{label:'标题',hitCount:1,supportedReader:true}]}],
    ['空标签', {required:[{label:' ',hitCount:1,supportedReader:true},{label:'标题',hitCount:1,supportedReader:true}]}],
  ]) {
    await test(name+'不能被complete标记覆盖',async()=>{
      const f=fixture(),result=completeResult();Object.assign(result.data.form_verification.required_field_coverage,patch);
      f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result,message:'平台全部填写完成'})});
      await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts.length,1);assert.equal(f.alerts[0][2].type,'warning');
    });
  }
  await test('淘宝旧success终态不能绕过填写回执判断',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'success',result:completeResult(),message:'旧成功'})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');
  });
  await test('提交确认与提交前停止相互矛盾时不报填写完成',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',publish_confirmed:true,result:completeResult()})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');
  });
  for (const [name, patch] of [['错误平台回执',{platform:'douyin'}],['平台来源缺失',{platform:undefined}]]) {
    await test(name+'保留任务且不显示填写完成',async()=>{
      const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result:completeResult(),...patch})});
      await f.s.handlePublishByAccount();await flush();for(let i=0;i<4;i++)await f.s.pollUploadTask();
      assert.equal(f.alerts.length,0);assert.equal(f.s.activeUploadTaskId.value,'tao-task');assert.equal(f.s.uploadBusy.value,true);
      assert.equal(f.s.uploadMonitoringPaused.value,true);
    });
  }
  await test('提交确认字段缺失不能报告完整填写',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result:completeResult(),publish_confirmed:undefined})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');
  });
  await test('提交前填写完成提示不继承后端上架成功文案',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result:completeResult(),message:'商品发布成功'})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'success');
    assert(!JSON.stringify(f.alerts).includes('发布成功'));assert(f.alerts[0][0].includes('停在提交前'));
  });
  await test('旧后端完成文案不能覆盖缺少整页证据的警告',async()=>{
    const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',message:'全部填写通过',result:{success:true,stopped_before_submit:true}})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');assert(!f.alerts[0][0].includes('全部填写通过'));
  });
  await test('连续读不到状态仍保留任务与锁定状态' ,async()=>{const f=fixture();f.api.getTaobaoPublishStatus=async()=>{throw Error('断开')};await f.s.handlePublishByAccount();await flush();for(let i=0;i<5;i++)await f.s.pollUploadTask();assert.equal(f.s.activeUploadTaskId.value,'tao-task');assert.equal(f.s.publishButtonDisabled.value,true);assert(f.s.uploadStatusText.value.includes('任务可能仍在运行'))});
  await test('请求取消只读真实任务终态，不能提前宣称已取消',async()=>{const f=fixture();await f.s.handlePublishByAccount();await flush();await f.s.cancelUploadTask();await flush();assert.equal(f.s.activeUploadTaskId.value,'tao-task');assert(f.calls.some(c=>c[0]==='taobao-cancel'));f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'cancelled'})});await f.s.pollUploadTask();assert.equal(f.s.activeUploadTaskId.value,null)});
  await test('恢复淘宝外部任务时保存该任务账户和商品',async()=>{const f=fixture();f.api.listTaobaoPublishTasks=async()=>({success:true,data:{count:1,tasks:[task({record_id:10,account_profile:'external-account'})]}});f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({record_id:10,account_profile:'external-account'})});assert.equal(await f.s.syncExternalUploadTask(),true);await flush();assert.equal(f.s.activeUploadContext.value.recordId,10);assert.equal(f.s.activeUploadContext.value.accountProfile,'external-account');assert.equal(f.s.activeUploadTaskPlatform.value,'taobao')});
  await test('迟到的旧任务响应不覆盖新任务',async()=>{const f=fixture(),d=defer();f.api.getTaobaoPublishStatus=async()=>d.promise;f.s.startUploadMonitoring('old','local',null,'taobao',{recordId:7,accountProfile:'tao-account'});f.s.stopUploadMonitoring();f.s.startUploadMonitoring('new','local',null,'taobao',{recordId:7,accountProfile:'tao-account'});d.resolve({success:true,data:task({task_id:'old',status:'succeeded',result:{success:true,stopped_before_submit:true}})});await flush();assert.equal(f.s.activeUploadTaskId.value,'new');assert.equal(f.alerts.length,0)});
  await test('启动连接断开时保留待确认，重读只接回该次账户商品的真实任务',async()=>{const f=fixture();f.store.startTaobaoFill=async()=>{const e=Error('连接断开');e.isAxiosError=true;throw e};await f.s.handlePublishByAccount();assert(f.s.taobaoUnknownStart.value);assert.equal(f.s.publishButtonDisabled.value,true);await f.s.handlePublishByAccount();assert.equal(f.calls.filter(c=>c[0]==='taobao-start').length,0);const createdAt=new Date(f.s.taobaoUnknownStart.value.requestedAt+1).toISOString();f.api.listTaobaoPublishTasks=async()=>({success:true,data:{count:1,tasks:[task({created_at:createdAt})]}});await f.s.retryUploadProgress();await flush();assert.equal(f.s.taobaoUnknownStart.value,null);assert.equal(f.s.activeUploadTaskId.value,'tao-task')});
  await test('启动结果未知时不误接更早的同账户商品任务',async()=>{const f=fixture();f.store.startTaobaoFill=async()=>{const e=Error('连接断开');e.isAxiosError=true;throw e};await f.s.handlePublishByAccount();const createdAt=new Date(f.s.taobaoUnknownStart.value.requestedAt-1).toISOString();f.api.listTaobaoPublishTasks=async()=>({success:true,data:{count:1,tasks:[task({created_at:createdAt})]}});await f.s.retryUploadProgress();assert(f.s.taobaoUnknownStart.value);assert.equal(f.s.activeUploadTaskId.value,null)});
  await test('服务端明确4xx拒绝时如实显示并可修正后重试',async()=>{const f=fixture();f.store.startTaobaoFill=async()=>{const e=Error('输入缺失');e.isAxiosError=true;e.response={status:400,data:{message:'输入缺失'}};throw e};await f.s.handlePublishByAccount();assert.equal(f.s.taobaoUnknownStart.value,null);assert.equal(f.s.publishButtonDisabled.value,false);assert(f.notices.some(n=>n[0]==='error'&&n[1].includes('输入缺失')))});
  await test('淘宝后端失败原文可见且不报完成',async()=>{const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'failed',error:'必填材质缺失'})});await f.s.handlePublishByAccount();await flush();assert.equal(f.s.activeUploadTaskId.value,null);assert.equal(f.alerts[0][0],'必填材质缺失');assert.equal(f.alerts[0][2].type,'error')});
  await test('抖音原上传接口和提交前模式保持',async()=>{const f=fixture();f.store.targetPublishPlatform='douyin';f.store.currentShopSession={platform:'douyin',active_profile:'dy-account'};f.store.currentShopSession={platform:'douyin',active_profile:'dy-account'};await f.s.handlePublishByAccount();await flush();assert.deepEqual(JSON.parse(JSON.stringify(f.calls.find(c=>c[0]==='douyin-start'))),['douyin-start',7,{stopBeforeSubmit:true,accountProfile:'dy-account',expectedRecordRevision:'a'.repeat(64)}]);assert.equal(f.s.activeUploadTaskPlatform.value,'douyin');assert(!f.calls.some(c=>c[0]==='taobao-start'))});
  await test('真实store与API共同固定fill_only、非dry-run、提交前停止',async()=>{
    const f=actualStoreFixture(()=>({success:true,data:{task_id:'id'}}));const store=f.store;
    store.setShopSession({platform:'taobao',active_profile:'tao-account'});const product={title:'商品'};
    await store.startTaobaoFill(7,product,'tao-account');
    assert.deepEqual(f.posts,[['/api/taobao/publish/start',{record_id:7,platform:'taobao',account_profile:'tao-account',product,dry_run:false,stop_before_submit:true,fill_only:true}]]);
    store.setShopSession({platform:'douyin',active_profile:'other'});await assert.rejects(()=>store.startTaobaoFill(7,product,'tao-account'));assert.equal(f.posts.length,1);
  });
  for(const platform of ['taobao','douyin']){
    await test(`${platform} 使用相同上传遮罩与临时取消按钮，正常任务不暴露额外操作区`,async()=>{
      const f=fixture();f.store.targetPublishPlatform=platform;f.store.currentShopSession={platform,active_profile:platform==='douyin'?'dy-account':'tao-account'};await f.s.handlePublishByAccount();await flush();
      assert.equal(f.s.publishActionText.value,platform==='taobao'?'开始淘宝发布':'开始抖音发布');
      assert.equal(f.s.uploadBusy.value,true);assert.equal(f.s.uploadMonitoringPaused.value,false);
      const openings=f.calls.filter(c=>c[0]==='loading-open');assert.equal(openings.length,1);
      assert.equal(f.calls.filter(c=>c[0]==='loading-close').length,0);
      assert.equal(openings[0][1].customClass,'product-upload-loading');
      const vnode=openings[0][1].text.value;assert(vnode.children[0].children.includes('上传中：'));
      assert.equal(vnode.children[1].props.onClick,f.s.cancelUploadTask);assert.equal(vnode.children[1].children.default(),'取消上传');
      assert(source.includes('v-if="taobaoUnknownStart || uploadMonitoringPaused"'));
      assert(!source.includes('taobao-task-actions'));
    });
  }
  await test('抖音取消也走对应接口并等待真实终态',async()=>{
    const f=fixture();f.store.targetPublishPlatform='douyin';f.store.currentShopSession={platform:'douyin',active_profile:'dy-account'};await f.s.handlePublishByAccount();await flush();await f.s.cancelUploadTask();await flush();
    assert(f.calls.some(c=>c[0]==='douyin-cancel'&&c[1]==='dy-task'));assert(!f.calls.some(c=>c[0]==='taobao-cancel'));
    assert.equal(f.s.activeUploadTaskId.value,'dy-task');
    f.store.getUploadStatus=async(id)=>({success:true,data:{task_id:id,status:'cancelled'}});await f.s.pollUploadTask();assert.equal(f.s.activeUploadTaskId.value,null);
  });
  await test('抖音读取中断同样保留任务和编辑锁，恢复读取不会重启任务',async()=>{
    const f=fixture();f.store.targetPublishPlatform='douyin';f.store.currentShopSession={platform:'douyin',active_profile:'dy-account'};f.store.getUploadStatus=async()=>{throw Error('连接中断')};
    await f.s.handlePublishByAccount();await flush();for(let i=0;i<5;i++)await f.s.pollUploadTask();
    assert.equal(f.s.uploadMonitoringPaused.value,true);assert.equal(f.s.activeUploadTaskId.value,'dy-task');assert.equal(f.s.uploadBusy.value,true);
    f.store.getUploadStatus=async(id)=>({success:true,data:{task_id:id,status:'running',progress:60,message:'继续填写'}});
    await f.s.retryUploadProgress();await flush();assert.equal(f.s.uploadMonitoringPaused.value,false);assert.equal(f.s.uploadProgress.value,60);
    assert.equal(f.calls.filter(c=>c[0]==='douyin-start').length,1);
  });
  await test('后端明确拒绝启动浏览器时不锁死前端或误报未知任务',async()=>{
    const f=fixture();f.store.startTaobaoFill=async()=>({success:false,msg:'启动淘宝浏览器失败：Chrome不可用'});
    await f.s.handlePublishByAccount();assert.equal(f.s.taobaoUnknownStart.value,null);assert.equal(f.s.publishButtonDisabled.value,false);
    assert.equal(f.s.activeUploadTaskId.value,null);assert(f.notices.some(n=>n[0]==='error'&&n[1].includes('Chrome不可用')));
  });
  await test('HTTP 503 携带明确拒绝也不认作启动结果未知',async()=>{
    const f=fixture();f.store.startTaobaoFill=async()=>{const e=Error('浏览器启动失败');e.isAxiosError=true;e.response={status:503,data:{success:false,msg:'浏览器启动失败'}};throw e};
    await f.s.handlePublishByAccount();assert.equal(f.s.taobaoUnknownStart.value,null);assert.equal(f.s.publishButtonDisabled.value,false);
    assert(f.notices.some(n=>n[0]==='error'&&n[1].includes('启动失败')));
  });
  await test('接受请求却未返回任务编号仍保留未知状态，防止重复上传',async()=>{
    const f=fixture();f.store.startTaobaoFill=async()=>({success:true,data:{dry_run:false,stop_before_submit:true}});
    await f.s.handlePublishByAccount();assert(f.s.taobaoUnknownStart.value);assert.equal(f.s.publishButtonDisabled.value,true);
  });
  await test('淘宝中文标题显示计数，后端明确拒绝后可修正重试',async()=>{
    const f=fixture(),original=f.store.startTaobaoFill;f.s.formData.value.title='袜'.repeat(31);assert.equal(f.s.titleLength.value,62);
    f.store.startTaobaoFill=async()=>({success:false,msg:'宝贝标题62字符，超过已归档规则上限60'});
    await f.s.handlePublishByAccount();assert.equal(f.s.activeUploadTaskId.value,null);assert.equal(f.s.publishButtonDisabled.value,false);
    assert(f.notices.some(n=>n[0]==='error'&&n[1].includes('超过已归档规则')));
    f.store.startTaobaoFill=original;f.s.formData.value.title='袜'.repeat(29)+'AB';assert.equal(f.s.titleLength.value,60);
    await f.s.handlePublishByAccount();await flush();assert(f.calls.some(c=>c[0]==='taobao-start'));
  });
  await test('共同表单保留抖音原有计数，切换淘宝后应用汉字计2',async()=>{
    const f=fixture();f.s.formData.value.title='袜'.repeat(31);f.store.targetPublishPlatform='douyin';f.store.currentShopSession={platform:'douyin',active_profile:'dy-account'};assert.equal(f.s.titleLength.value,31);
    f.store.targetPublishPlatform='taobao';assert.equal(f.s.titleLength.value,62);
  });
  for(const platform of ['taobao','douyin']){
    await test(`${platform} 启动前保存同一份编辑快照，成本输入不覆盖 SKU 售价`,async()=>{
      const f=fixture();f.store.targetPublishPlatform=platform;f.store.currentShopSession={platform,active_profile:platform==='douyin'?'dy-account':'tao-account'};
      f.s.formData.value.title='点击时标题';f.s.formData.value.price=0.01;await f.s.handlePublishByAccount();await flush();
      const save=f.calls.find(c=>c[0]==='save'),start=f.calls.find(c=>c[0]===(platform==='taobao'?'taobao-start':'douyin-start'));
      assert(save&&start);assert(f.calls.indexOf(save)<f.calls.indexOf(start));
      assert.equal(save[1].title,'点击时标题');assert.equal(save[1].attr_price_1,29.8);assert.equal(save[1].attr_price_2,32.8);assert(!('price' in save[1]));
      assert.equal(save[2].recordId,7);assert.equal(save[2].publishPlatform,platform);
    });
    await test(`${platform} 保存失败不启动任务且保留当前编辑值`,async()=>{
      const f=fixture();f.store.targetPublishPlatform=platform;f.store.currentShopSession={platform,active_profile:platform==='douyin'?'dy-account':'tao-account'};
      f.store.saveProduct=async()=>false;f.store.lastActionError='SKU来源已改变';f.s.formData.value.title='保留编辑内容';await f.s.handlePublishByAccount();await flush();
      assert(!f.calls.some(c=>c[0]==='taobao-start'||c[0]==='douyin-start'));assert.equal(f.s.activeUploadTaskId.value,null);assert.equal(f.s.taobaoUnknownStart.value,null);
      assert.equal(f.s.publishButtonDisabled.value,false);assert.equal(f.s.formData.value.title,'保留编辑内容');assert(f.notices.some(n=>n[0]==='error'&&n[1].includes('SKU来源已改变')));
    });
    await test(`${platform} 保存期间账户或商品改变不启动错误任务`,async()=>{
      const f=fixture(),d=defer();f.store.targetPublishPlatform=platform;f.store.currentShopSession={platform,active_profile:platform==='douyin'?'dy-account':'tao-account'};
      f.store.saveProduct=async()=>d.promise;const pending=f.s.handlePublishByAccount();await flush();f.store.currentProductId=8;
      d.resolve({id:7,update_time:'2026-10-04',record_revision:'a'.repeat(64)});await pending;await flush();
      assert(!f.calls.some(c=>c[0]==='taobao-start'||c[0]==='douyin-start'));assert.equal(f.s.taobaoUnknownStart.value,null);
    });
  }
  await test('保存前固定快照，保存后不会把异步改变的售价偷换进去',async()=>{
    const f=fixture(),d=defer();f.store.saveProduct=async(data,opts)=>{f.calls.push(['save',JSON.parse(JSON.stringify(data)),opts]);return d.promise};
    const pending=f.s.handlePublishByAccount();f.s.formData.value.title='后来的标题';f.store.currentSkus[0].price=99;
    d.resolve({id:7,record_revision:'a'.repeat(64)});await pending;await flush();
    const save=f.calls.find(c=>c[0]==='save'),start=f.calls.find(c=>c[0]==='taobao-start');
    assert.equal(save[1].title,'真实商品标题');assert.equal(save[1].attr_price_1,29.8);assert.equal(start[2].title,'真实商品标题');assert.equal(start[2].skus[0].price,29.8);
  });
  for(const platform of ['taobao','douyin']){
    await test(`真实store/API将 ${platform} 保存的版本带到启动请求，忽略调用数据中的伪造ID`,async()=>{
      const rev='b'.repeat(64),f=actualStoreFixture(url=>url==='/save_info'?{success:true,data:{id:7,update_time:'2026-10-04',record_revision:rev}}:{success:true,data:{task_id:'job'}});
      f.store.setShopSession({platform,active_profile:'bound-account'});
      const saved=await f.store.saveProduct({_id:99,title:'当前标题'},{recordId:7,publishPlatform:platform,accountProfile:'bound-account'});
      assert.equal(saved.record_revision,rev);assert.equal(f.posts[0][1]._id,7);assert.equal(f.posts[0][1].for_publish,true);assert.equal(f.posts[0][1].account_profile,'bound-account');
      if(platform==='taobao')await f.store.startTaobaoFill(7,{title:'当前标题'},'bound-account',saved.record_revision);
      else await f.store.startUpload(7,{stopBeforeSubmit:true,accountProfile:'bound-account',expectedRecordRevision:saved.record_revision});
      assert.equal(f.posts[1][1].expected_record_revision,rev);
    });
  }
  for(const [reason,response]of [['错误商品',{success:true,data:{id:8,record_revision:'a'.repeat(64)}}],['缺少版本',{success:true,data:{id:7}}],['后端拒绝',{success:false,msg:'SKU来源已改变'}]]){
    await test(`真实保存回执 ${reason} 不能当作保存确认`,async()=>{
      const f=actualStoreFixture(()=>response);f.store.setShopSession({platform:'taobao',active_profile:'tao-account'});
      const saved=await f.store.saveProduct({title:'当前标题'},{recordId:7,publishPlatform:'taobao',accountProfile:'tao-account'});
      assert.equal(saved,false);assert(f.store.lastActionError.value);if(reason==='后端拒绝')assert.equal(f.store.lastActionError.value,'SKU来源已改变');
    });
  }
  const handoffPath=path.join(root,'taobao-publisher/outputs/phase_offline_pipeline_handoff.json');
  if(fs.existsSync(handoffPath)) {
    const handoff=JSON.parse(fs.readFileSync(handoffPath,'utf8'));
    const crypto=require('crypto');
    const testSource=fs.readFileSync(path.join(root,'taobao-publisher/tests/test_offline_pipeline_handoff.py'));
    assert.equal(handoff.test_source_sha256,crypto.createHash('sha256').update(testSource).digest('hex'));
    assert.equal(handoff.scope,'local_synthetic_browser_only');assert.equal(handoff.live_platform_tested,false);
    await test('真实本地HTTP线程与流水线的部分回读结果在共同前端显示未完整验证',async()=>{
      const f=fixture();f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',progress:100,message:handoff.message,result:handoff.result})});
      await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');
      assert(f.alerts[0][0].includes('整页必填尚未确认'));assert.equal(f.s.activeUploadTaskId.value,null);
    });
  }
  const categoryPath=path.join(root,'taobao-publisher/outputs/category_first_pipeline_handoff.json');
  if(fs.existsSync(categoryPath)) {
    const category=JSON.parse(fs.readFileSync(categoryPath,'utf8'));
    const crypto=require('crypto');
    const categoryTest=fs.readFileSync(path.join(root,'taobao-publisher/tests/test_category_first_pipeline.py'));
    assert.equal(category.test_source_sha256,crypto.createHash('sha256').update(categoryTest).digest('hex'));
    assert.equal(category.live_platform_tested,false);assert.equal(category.next_clicks,1);
    await test('共同前端显示类目、图片和标题已执行，详情失败如实显示且不跳设置',async()=>{
      const f=fixture(),result=category.result;
      f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'failed',progress:100,
        error:result.error.message,message:result.error.message,steps:result.steps,result})});
      await f.s.handlePublishByAccount();await flush();
      assert.equal(f.alerts[0][2].type,'error');assert.equal(f.alerts[0][0],result.error.message);
      assert.equal(f.s.activeUploadTaskId.value,null);
      assert(!f.calls.some(c=>c[0]==='navigate'));
      assert(result.steps.some(step=>step.name==='select_category'&&step.status==='ok'));
      assert(result.steps.some(step=>step.name==='upload_images'&&step.status==='ok'));
      assert.equal(category.model_upload_count,5);assert.equal(category.model_main_image_count,1);
      assert(!f.notices.some(n=>n[0]==='success'&&String(n[1]).includes('完成')));
    });
  }
  const nativePath=path.join(root,'taobao-publisher/outputs/runtime_native_pipeline_handoff.json');
  if(fs.existsSync(nativePath)) {
    const native=JSON.parse(fs.readFileSync(nativePath,'utf8'));
    const source=fs.readFileSync(path.join(root,'taobao-publisher/tests/test_runtime_native_controls.py'));
    assert.equal(native.test_source_sha256,require('crypto').createHash('sha256').update(source).digest('hex'));
    assert.equal(native.live_platform_tested,false);assert.equal(native.browser_protocol,'file:');
    await test('当前候选配置完成原生控件填写后共同前端保留整页必填未确认提示',async()=>{
      const f=fixture(),result=native.result;
      f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',progress:100,steps:result.steps,result})});
      await f.s.handlePublishByAccount();await flush();
      assert.equal(f.alerts[0][2].type,'warning');assert(f.alerts[0][0].includes('整页必填尚未确认'));
      assert.equal(f.s.activeUploadTaskId.value,null);assert(!f.calls.some(c=>c[0]==='navigate'));
      // ⚠️ `save_draft` **按设计**可以是 `skipped`：只有显式请求保存草稿才会点那个按钮
      // （E-268 的开关语义、E-273 的 GUI 基线就是"12 步里只有 save_draft skipped"）。
      // 原来写的是"每一步都必须 ok"，那条断言在 `save_draft` 出现后就必然过期。
      assert(result.steps.every(s=>s.status==='ok'||(s.name==='save_draft'&&s.status==='skipped')),
        '除 save_draft（未请求保存草稿时 skipped）外，每一步都应当是 ok');
      const names=result.steps.map(s=>s.name);assert(names.indexOf('fill_skus')<names.indexOf('fill_detail'));
      // ⚠️ **不要写死阶段数**。这里原来写的是 `assert.equal(result.steps.length,11)`，
      // 而流水线后来加了 fill_required_attrs / set_listing_time / save_draft，产物变成 14 步
      // ——断言红了不算最糟：**它让本文件 313 行之后的用例全部不再执行**（约 50 行被遮住）。
      // 按 `constants.py` 的 `STAGE_ORDER` 推导（E-257 的同一课）：
      // 模型联跑应当**跑到 submit 之前**，且名字与顺序都与当前阶段清单一致。
      const constantsSrc=fs.readFileSync(path.join(root,'taobao-publisher/taobao_publish/constants.py'),'utf8');
      const valueOf={};
      for(const m of constantsSrc.matchAll(/^(STAGE_\w+):\s*Final\s*=\s*"([^"]+)"/gm))valueOf[m[1]]=m[2];
      const orderBlock=constantsSrc.slice(constantsSrc.indexOf('STAGE_ORDER: Final = ('));
      const stageOrder=[...orderBlock.slice(0,orderBlock.indexOf(')')).matchAll(/STAGE_(\w+)/g)]
        .map(m=>valueOf['STAGE_'+m[1]]).filter(Boolean);
      assert(stageOrder.length>5,'没能从 constants.py 读出 STAGE_ORDER');
      assert.deepEqual(names,stageOrder.filter(n=>n!=='submit'),
        '模型联跑的阶段与当前 STAGE_ORDER 不一致（应为「STAGE_ORDER 去掉 submit」）');
      assert.equal(native.model_upload_count,5);assert.equal(native.model_submit_calls+native.model_draft_calls,0);
    });
  }
  for(const [name,patch] of [
    ['未知控件事实',{known:false}],['未覆盖必填控件',{unownedRequiredCount:1}],
    ['已观察字段不在整页清单',{required:[{label:'发货时间',hitCount:1,supportedReader:true,filled:true,valid:true}]}],
    ['必填未选择',{required:[{label:'发货时间',hitCount:1,supportedReader:true,filled:false,valid:true}]}],
    ['原生范围校验失败',{required:[{label:'一口价',hitCount:1,supportedReader:true,filled:true,valid:false}]}]
  ]) {
    await test(name+'否决矛盾的完整填写声明',async()=>{
      const f=fixture(),result=completeResult();
      result.data.form_verification.visible_form_requirements={known:true,scope:'visible_publish_rows_required',
        completePage:false,rowCount:1,unownedRequiredCount:0,required:[],...patch};
      f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result})});
      await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'warning');
    });
  }
  for(const selected of [false,true]) {
    const filename='required_form_pipeline_'+(selected?'selected':'missing')+'.json';
    const artifactPath=path.join(root,'taobao-publisher/outputs',filename);
    if(fs.existsSync(artifactPath)) {
      const evidence=JSON.parse(fs.readFileSync(artifactPath,'utf8'));
      const source=fs.readFileSync(path.join(root,'taobao-publisher/tests/test_required_form_controls.py'));
      assert.equal(evidence.test_source_sha256,require('crypto').createHash('sha256').update(source).digest('hex'));
      assert.equal(evidence.live_platform_tested,false);
      await test('真实本地任务的额外必填'+(selected?'已选择仍保持局部覆盖':'缺值显示具体字段'),async()=>{
        const f=fixture(),result=evidence.result;
        f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:selected?'succeeded':'failed',result,
          error:evidence.error,message:evidence.error||'本次步骤结束'})});
        await f.s.handlePublishByAccount();await flush();
        assert.equal(f.alerts[0][2].type,selected?'warning':'error');
        if(!selected)assert(f.alerts[0][0].includes('发货时间'));
        assert.equal(f.s.activeUploadTaskId.value,null);assert(!f.calls.some(c=>c[0]==='navigate'));
      });
    }
  }
  await test('附加可见必填事实与整页清单一致时保留完整填写判断',async()=>{
    const f=fixture(),result=completeResult(),proof=result.data.form_verification.required_field_coverage;
    result.data.form_verification.visible_form_requirements={known:true,scope:'visible_publish_rows_required',
      completePage:false,rowCount:1,unownedRequiredCount:0,required:[{label:proof.required[0].label,
      hitCount:1,supportedReader:true,filled:true,valid:true}]};
    f.api.getTaobaoPublishStatus=async()=>({success:true,data:task({status:'succeeded',result})});
    await f.s.handlePublishByAccount();await flush();assert.equal(f.alerts[0][2].type,'success');
  });
  console.log(JSON.stringify({success:true,total:tests.length,tests},null,2));
})().catch(error=>{console.error(error);process.exitCode=1});
