# -*- coding: utf-8 -*-
"""属性一次展开并提交的本地 DOM 模型；不连接账户页面。"""
import json
import pytest
from test_candidate_form_adapters import browser
from taobao_publish import required_attrs as R, page


def setup(browser, *, delay=180, commit=True, duplicate=False):
    browser.evaluate(r'''(() => {
      document.body.replaceChildren();
      window.opens=[]; window.picks=[];
      window.installAttribute=(name, options, initial='请选择')=>{
        const row=document.createElement('div'); row.className='sell-component-info-wrapper-wrap';
        const label=document.createElement('span'); label.className='sell-component-info-wrapper-label'; label.textContent=name;
        const star=document.createElement('span'); star.className='sell-component-info-wrapper-required'; star.textContent='*';
        const select=document.createElement('div'); select.className='next-select';
        select.style.cssText='width:300px;height:40px;border:1px solid black';
        const holder=document.createElement('div'); holder.className='next-select-values'; holder.textContent=initial;
        select.append(holder); row.append(label,star,select); document.body.append(row);
        select.onclick=()=>{
          window.opens.push(name);
          const menu=document.createElement('div'); menu.className='next-select-popup-wrap';
          for(const value of options){
            const option=document.createElement('div'); option.className='options-item';
            const text=document.createElement('span'); text.className='info-content'; text.textContent=value;
            option.append(text); menu.append(option);
            option.onclick=()=>{
              window.picks.push(name+':'+value);
              menu.remove();
              if(window.allowCommit) setTimeout(()=>{holder.textContent=value},window.commitDelay);
            };
          }
          document.body.append(menu);
          if(window.duplicateMenu) document.body.append(menu.cloneNode(true));
        };
      };
      document.addEventListener('keydown',event=>{
        if(event.key==='Escape') for(const menu of document.querySelectorAll('.next-select-popup-wrap')) menu.remove();
      });
    })()''')
    browser.evaluate('Object.assign(window,%s)' % json.dumps({'commitDelay':delay,'allowCommit':commit,'duplicateMenu':duplicate}))


def test_options_are_chosen_during_first_open_with_delayed_commit(browser):
    setup(browser)
    browser.evaluate("installAttribute('适用季节',['冬季','四季通用']);installAttribute('适用性别',['男','女','男女通用']);installAttribute('品牌',[],'无品牌')")
    result=R.fill_required_attrs(browser, per_field_wait=0)
    assert result['failed'] == []
    assert [entry['after'] for entry in result['filled']] == ['四季通用','男女通用']
    assert browser.evaluate('window.opens') == ['适用季节','适用性别']
    assert browser.evaluate('window.picks') == ['适用季节:四季通用','适用性别:男女通用']
    assert result['already'] == [{'name':'品牌','value':'无品牌'}]
    # 重复调用保持已填值，不重复展开/选值。
    again=R.fill_required_attrs(browser, per_field_wait=0)
    assert again['filled'] == [] and len(again['already']) == 3
    assert browser.evaluate('window.opens.length') == 2


def test_ambiguous_menu_is_reported_without_clicking_options(browser):
    setup(browser, duplicate=True)
    browser.evaluate("installAttribute('适用季节',['四季通用'])")
    result=R.fill_required_attrs(browser, per_field_wait=0)
    assert result['filled'] == []
    assert result['failed'][0]['name'] == '适用季节'
    assert '不是唯一' in result['failed'][0]['error']
    assert browser.evaluate('window.picks') == []


def test_uncommitted_selection_fails_without_click_retry(browser):
    setup(browser, commit=False)
    browser.evaluate("installAttribute('适用季节',['四季通用'])")
    R.read_dropdown_options(browser,'适用季节',wait=0,close=False)
    with pytest.raises(page.FieldMismatchError,match='回读不一致'):
        R.fill_required_attr(browser,'适用季节','四季通用',dropdown_open=True,readback_timeout=0.2)
    assert browser.evaluate('window.opens') == ['适用季节']
    assert browser.evaluate('window.picks') == ['适用季节:四季通用']
