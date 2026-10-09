// 实际 Pinia/API 源码的异步目录状态测试；没有网络或运行中应用访问。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const frontend = path.resolve(__dirname, '../../tauri-app');
const vue = require(path.join(frontend, 'node_modules/vue'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
const defer = () => { let resolve, reject; const promise = new Promise((r, j) => {resolve=r;reject=j}); return {promise,resolve,reject}; };
function load(relative, dependencies) {
  const source=fs.readFileSync(path.join(frontend, relative), 'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
  const module={exports:{}};
  vm.runInNewContext(code,{module,exports:module.exports,require:name=>{
    if (!(name in dependencies)) throw Error('未配置依赖 '+name); return dependencies[name];
  },console,URLSearchParams});
  return module.exports;
}
function fixture() {
  const requests=[];
  const http={get:(url, options)=>{const pending=defer(); requests.push({url,options,...pending}); return pending.promise},interceptors:{response:{use:()=>{}}}};
  const service=load('src/services/api.ts',{'axios':{default:{create:()=>http},__esModule:true},'@tauri-apps/api/core':{},'@/types':{}});
  const store=load('src/stores/productStore.ts',{'vue':vue,'pinia':{defineStore:(_,setup)=>setup},'element-plus':{},'@/services/api':service}).useProductStore();
  store.setShopSession({active_profile:'A',platform:'taobao'});
  const answer=(index,path,recordId=7)=>requests[index].resolve({success:true,data:{record_id:recordId,path,account_profile:'A',entries:[]}});
  return {store,requests,answer,service};
}
(async()=>{
  let f=fixture();
  const old=f.store.loadMediaDirectory(7,'主图'), recent=f.store.loadMediaDirectory(7,'SKU');
  f.answer(1,'SKU'); await recent; f.answer(0,'主图'); await old;
  assert.equal(f.store.mediaListing.value.path,'SKU');
  assert.equal(f.requests[1].url,'/api/products/7/media');
  assert.equal(f.requests[1].options.params.account_profile,'A');
  f=fixture(); const closed=f.store.loadMediaDirectory(7); f.store.clearMediaListing(); f.answer(0,''); await closed;
  assert.equal(f.store.mediaListing.value,null); assert.equal(f.store.mediaLoading.value,false);
  f=fixture(); const changed=f.store.loadMediaDirectory(7); f.store.setShopSession({active_profile:'B',platform:'taobao'}); f.answer(0,''); await changed;
  assert.equal(f.store.mediaListing.value,null); assert.match(f.store.mediaError.value,/账户已经变化/);
  f=fixture(); const failed=f.store.loadMediaDirectory(7); f.requests[0].reject({response:{data:{msg:'图片目录已移动'}}}); await failed;
  assert.equal(f.store.mediaError.value,'图片目录已移动'); assert.equal(f.store.mediaLoading.value,false);
  const url=f.service.productMediaImageUrl(7,'主图/800/黑 白.jpg','2026-10-05',true);
  assert.equal(new URL(url).searchParams.get('path'),'主图/800/黑 白.jpg');
  assert.equal(new URL(url).searchParams.get('size'),'preview');
  console.log(JSON.stringify({success:true,tests:5,scope:'actual_frontend_store_and_api_without_network'},null,2));
})().catch(error=>{console.error(error);process.exitCode=1});
