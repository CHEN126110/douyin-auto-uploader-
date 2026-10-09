# -*- coding: utf-8 -*-
"""研究目录输入与拖入：只操作隔离浏览器的本地文件或自建内存 HTTP 页面。"""
import json
import time
import hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import pytest

from test_candidate_form_adapters import browser


def test_native_directory_input_keeps_nested_relative_paths(browser, tmp_path):
    parent = tmp_path / '123'
    for group in ('主图', 'SKU', '详情页'):
        path = parent / group / (group + '.jpg')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'local directory capability fixture')
    browser.evaluate("document.body.innerHTML='<input type=file webkitdirectory multiple>'")
    browser.set_file_input_files([str(parent)], 'input[type=file]')
    deadline = time.monotonic() + 3
    while True:
        files = browser.evaluate("Array.from(document.querySelector('input').files).map(f=>f.webkitRelativePath).sort()")
        if files or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    assert files == sorted('123/' + group + '/' + group + '.jpg' for group in ('主图', 'SKU', '详情页'))
    assert browser.evaluate('location.protocol') == 'file:'


def test_native_multiple_input_accepts_all_files_in_one_change(browser, tmp_path):
    files = []
    for number in range(5):
        path = tmp_path / ('本地%d.jpg' % number)
        path.write_bytes(b'local multiple input fixture')
        files.append(str(path))
    browser.evaluate("document.body.innerHTML='<input type=file multiple>';window.changes=0;document.querySelector('input').onchange=()=>window.changes++")
    browser.set_file_input_files(files, 'input[type=file]')
    assert browser.evaluate('document.querySelector("input").files.length') == 5
    assert browser.evaluate('window.changes') == 1


@pytest.fixture
def local_http_browser(browser):
    """目录 Entry API 使用正常HTTP来源；仅提供内存HTML，不暴露磁盘目录。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<!doctype html><html><body>isolated folder drop model</body></html>')
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url='http://127.0.0.1:%d/' % server.server_port
    try:
        navigation=browser.send('Page.navigate',{'url':url})
        assert not navigation.get('errorText'),navigation
        deadline=time.monotonic()+5
        while browser.evaluate('location.href')!=url or browser.evaluate('document.readyState')!='complete':
            assert time.monotonic()<deadline, (browser.evaluate('location.href'),browser.evaluate('document.readyState'))
            time.sleep(0.05)
        yield browser,url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('browser',['memory_http_only'],indirect=True)
def test_native_folder_drop_preserves_nested_directories_and_reads_over_100_files(local_http_browser,tmp_path):
    """验证目录拖入能力；只给自建内存 HTTP 页面发送合成目录，不访问淘宝。"""
    browser,url=local_http_browser
    parent=tmp_path/'123'
    wanted=[]
    for group,count in [('主图',2),('SKU',105),('详情页',2)]:
        directory=parent/group
        directory.mkdir(parents=True)
        for index in range(count):
            path=directory/('%03d.jpg' % index)
            path.write_bytes(b'isolated local directory entry')
            wanted.append('/123/'+group+'/'+path.name)
    browser.evaluate('''document.body.innerHTML='<div id="drop" style="width:400px;height:300px;border:1px solid">本地目录研究</div>';
      window.directoryResult={done:false,paths:[],roots:[]};
      const visit=async entry=>{
        if(entry.isFile){window.directoryResult.paths.push(entry.fullPath);return;}
        const reader=entry.createReader();
        while(true){const children=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));
          if(!children.length)break;for(const child of children)await visit(child);}
      };
      const target=document.getElementById('drop');
      target.ondragover=e=>e.preventDefault();
      target.ondrop=async e=>{e.preventDefault();
        const roots=Array.from(e.dataTransfer.items).map(item=>item.webkitGetAsEntry());
        window.directoryResult.roots=roots.map(entry=>({name:entry.name,isDirectory:entry.isDirectory}));
        try{for(const root of roots)await visit(root);window.directoryResult.done=true;}
        catch(error){window.directoryResult.error=String(error);}
      };''')
    data={'items':[],'files':[str(parent)],'dragOperationsMask':1}
    for event in ('dragEnter','dragOver','drop'):
        browser.send('Input.dispatchDragEvent',{'type':event,'x':100,'y':100,'data':data})
    deadline=time.monotonic()+5
    while True:
        result=browser.evaluate('window.directoryResult')
        if result['done'] or result.get('error') or time.monotonic()>=deadline:
            break
        time.sleep(0.05)
    assert result.get('error') is None
    assert result['done'] is True
    assert result['roots']==[{'name':'123','isDirectory':True}]
    assert sorted(result['paths'])==sorted(wanted)
    assert browser.evaluate('location.href')==url
    from taobao_publish.sanitize import assert_clean
    artifact={'scope':'isolated_browser_and_memory_only_loopback_http_folder_drop','live_platform_tested':False,
        'root_is_directory':True,'groups':{'主图':2,'SKU':105,'详情页':2},
        'file_count':len(result['paths']),'all_relative_paths_matched':True,
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/native_folder_drop_capability.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
