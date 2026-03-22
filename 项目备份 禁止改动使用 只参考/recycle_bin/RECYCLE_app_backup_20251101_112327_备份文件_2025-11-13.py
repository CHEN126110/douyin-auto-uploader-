# -*- coding: utf-8 -*-
# pyright: reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false

import traceback
import time as system_time
from src.thread import Thread
from flask import Flask, render_template, request, jsonify
import pyautogui
from src.gui import Gui
from src.orm import Record
from src.utils import *
from src.config import settings_manager
from src.smart_integration import smart_manager, enable_smart_mode
from src.smart_title_generator import smart_title_generator, ProductInfo
from src.professional_title_generator import get_professional_generator, ProductInfo as ProfessionalProductInfo
from src.enhanced_category_selector import smart_select_category
import os
import json
import base64
import sys  
from datetime import datetime



app = Flask(__name__, template_folder=constants.run_path, static_folder=constants.run_path, static_url_path='')
app.config['JWT_SECRET_KEY'] = constants.secret
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 604800
# 启用调试模式和详细日志
app.config['DEBUG'] = False  # 🔧 修复：禁用调试模式避免多线程信号处理冲突
import logging
logging.basicConfig(level=logging.INFO)  # 🔧 降低日志级别
app.logger.setLevel(logging.INFO)
# 禁用模板缓存
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
open_url_list = ['/admin', '/component', '/login', '/captcha']


@app.route('/delete_sku', methods=['POST'])
def delete_sku():
    data = request.get_json()
    sku_path = data.get('sku_path')
    record_id = data.get('record_id')
    if not sku_path or not record_id:
        return api_error('参数错误')

    try:
        record = Record.get_by_id(record_id)
        sku_list = json.loads(record.content)
        # 过滤掉要删除的 SKU
        sku_list = [sku for sku in sku_list if sku['path'] != sku_path]
        record.content = json.dumps(sku_list)
        record.save()

        return api_ok('SKU 删除成功')
    except Exception as e:
        traceback.print_exc()
        return api_error(f'删除失败：{str(e)}')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.get_json().get('username')
        password = request.get_json().get('password')
        remember = request.get_json().get('remember') == 'on'
        if username == 'your_username' and password == 'your_password':
            update_payload(username, remember)
            return api_ok('登录成功！')
        else:
            return api_error('账号密码不正确！')
    else:
        # gui.window.label.hide()  # 移除这行代码
        return render_template('login.html')


@app.delete('/logout')
def logout():
    try:
        update_payload(None, True)
        return api_ok('注销成功！')
    except:
        pass
    return api_error('注销失败！')


@app.get('/')
def index():
    record_list = []
    for record in Record.select().execute():
        arr = record.name.split('_')
        record_list.append({
            'id': record.id,
            'name': record.name if len(arr) < 4 else arr[3],
            'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
        })
    print(f'🔧 Index route: Found {len(record_list)} records')
    for record in record_list:
        print(f'🔧 Record: ID={record["id"]}, Name={record["name"]}')
    # gui.window.label.show()  # 移除这行代码
    return render_template('/view/operate/index.html', ctx=constants, record_list=record_list)


@app.get('/test_records')
def test_records():
    """测试路由：验证数据库记录是否正确传递到模板"""
    record_list = []
    for record in Record.select().execute():
        arr = record.name.split('_')
        record_list.append({
            'id': record.id,
            'name': record.name if len(arr) < 4 else arr[3],
            'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
        })
    print(f'🔧 Test route: Found {len(record_list)} records')
    for record in record_list:
        print(f'🔧 Test Record: ID={record["id"]}, Name={record["name"]}')
    return render_template('/view/test_records.html', record_list=record_list)


@app.get('/load_detail')
def load_detail():
    try:
        record_id = request.args.get('_id')
        load_images = request.args.get('images', 'true').lower() == 'true'
        
        record = Record.get_by_id(record_id)
        arr = record.name.split('_')
        sku_list = json.loads(record.content)
        
        # 根据images参数决定是否加载图片的Base64数据
        for sku in sku_list:
            if load_images:
                # 完整模式：加载Base64图片
                try:
                    if os.path.exists(sku['path']):
                        with open(sku['path'], 'rb') as img_file:
                            encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
                            sku['url'] = f"data:image/jpeg;base64,{encoded_string}"
                    else:
                        # 图片文件不存在，使用占位符
                        sku['url'] = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+SW1hZ2UgTm90IEZvdW5kPC90ZXh0Pjwvc3ZnPg=='
                        print(f"⚠️ 图片文件不存在: {sku['path']}")
                except Exception as img_error:
                    # 图片加载失败，使用占位符
                    sku['url'] = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+TG9hZCBFcnJvcjwvdGV4dD48L3N2Zz4K'
                    print(f"⚠️ 图片加载失败: {sku['path']}, 错误: {img_error}")
            else:
                # 🔧 快速模式：不加载图片，只设置占位符
                sku['url'] = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+Tm8gSW1hZ2U8L3RleHQ+PC9zdmc+'
        
        return api_ok(msg='操作成功！', data={
            'id': record.id,
            'title': record.title,
            'repo': record.repo,
            'name': record.name if len(arr) < 4 else arr[3],
            'clazz': record.clazz,
            'remark': record.remark,
            'content': sku_list
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(msg=f'操作失败：{str(e)}')


@app.delete('/delete_all')
def delete_all():
    try:
        Record.delete().execute()
        return api_ok(msg='清空成功！')
    except:
        pass
    return api_error(msg='清空失败！')


@app.post('/save_info')
def save_info():
    try:
        request_data = request.get_json()
        if not request_data:
            return api_error(msg='请求数据为空！')
        
        _id = request_data.get('_id')
        if not _id:
            return api_error(msg='记录ID不能为空！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        # 更新类目
        try:
            clazz = request_data.get('clazz')
            if clazz is not None and str(clazz).strip():
                record.clazz = int(clazz)
        except (ValueError, TypeError) as e:
            print(f"⚠️ 类目转换失败: {e}")
        
        # 更新基本信息
        record.title = request_data.get('title', '')
        record.remark = request_data.get('remark', '')
        
        # 更新仓库
        try:
            repo = request_data.get('repo')
            if repo is not None and str(repo).strip():
                record.repo = int(repo)
        except (ValueError, TypeError) as e:
            print(f"⚠️ 仓库转换失败: {e}")
        
        # 更新SKU数据
        try:
            original_content = json.loads(record.content)
            arr = {}
            for dt in original_content:
                arr[dt['path']] = dt
            
            attr_size = int(request_data.get('attr_size', 0))
            for i in range(attr_size):
                path_key = f'attr_path_{i + 1}'
                name_key = f'attr_name_{i + 1}'
                price_key = f'attr_price_{i + 1}'
                
                attr_path = request_data.get(path_key)
                if attr_path and attr_path in arr:
                    arr[attr_path]['name'] = request_data.get(name_key, '')
                    # 价格处理，确保是数字
                    try:
                        price_value = request_data.get(price_key, '0')
                        arr[attr_path]['price'] = float(price_value) if price_value else 0.0
                    except (ValueError, TypeError):
                        arr[attr_path]['price'] = 0.0
                        print(f"⚠️ 价格转换失败，使用默认值0: {price_key}")
            
            record.content = json.dumps(list(arr.values()))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"❌ SKU数据处理失败: {str(e)}")
            return api_error(msg=f'SKU数据处理失败：{str(e)}')
        
        # 更新时间并保存
        try:
            record.update_time = time.now()
            record.save()
            print(f"✅ 记录保存成功: ID={record.id}, 标题={record.title}")
            
            return api_ok(msg='保存成功！', data={
                'id': record.id,
                'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
            })
        except Exception as save_error:
            print(f"❌ 数据库保存失败: {str(save_error)}")
            return api_error(msg=f'数据库保存失败：{str(save_error)}')
        
    except Exception as e:
        print(f"❌ 保存操作异常: {str(e)}")
        traceback.print_exc()
        return api_error(msg=f'保存失败：{str(e)}')


@app.post('/start')
def start():
    msg_list = []
    try:
        # 🚀 启用智能模式
        enable_smart_mode()
        print("🤖 AI辅助模式已启动")
        
        record_list = Record.select().execute()
        if len(record_list) == 0:
            return api_error(msg='没有待上传数据！')
        
        # 确保 gui.page 存在且不为 None
        if not gui.page:
            gui.page = get_page('https://fxg.jinritemai.com/login/common')
            # 🔧 包装页面为智能页面
            smart_manager.wrap_page(gui.page, "main_page")
            login_ok = False
            for _ in range(30):
                if '/homepage' in gui.page.url:
                    login_ok = True
                    break
                time.sleep(1)
            if not login_ok:
                return api_error('超时未登录！！！')
        
        try:
            main_tab = gui.page.get_tab(gui.page.latest_tab)
            # 🔧 为标签页添加智能功能
            main_tab = smart_manager.wrap_tab(main_tab, "main_tab")
        except:
            gui.page = get_page('https://fxg.jinritemai.com/login/common')
            # 🔧 包装页面为智能页面
            smart_manager.wrap_page(gui.page, "main_page")
            login_ok = False
            for _ in range(30):
                if '/homepage' in gui.page.url:
                    login_ok = True
                    break
                time.sleep(1)
            if not login_ok:
                return api_error('超时未登录！！！')
            main_tab = gui.page.get_tab(gui.page.latest_tab)
            # 🔧 为标签页添加智能功能
            main_tab = smart_manager.wrap_tab(main_tab, "main_tab")
        gui.page.close_tabs(main_tab, others=True)
        for record in record_list:
            record_ok = False
            error_tip = ''

            try:
                if not record.title:
                    error_tip = '标题为空！！！'
                    continue
                if not record.clazz:
                    error_tip = '类目为空！！！'
                    continue
                if not str(record.repo):
                    error_tip = '库存为空！！！'
                    continue
                try:
                    main_pic_list = get_pic_list(record, '800')
                except:
                    error_tip = '未找到主图或者主图不全！！！'
                    continue
                try:
                    sub_pic_list = get_pic_list(record, '750')
                    # 🔧 ID模式下，如果返回空列表，说明没有3:4主图，这是正常的
                    if record.type == 2 and len(sub_pic_list) == 0:
                        print("ID模式：没有3:4主图，将使用平台自带的1:1导入功能")
                except:
                    # 标准模式下仍然需要3:4主图
                    if record.type == 1:
                        error_tip = '未找到4:3主图或者4:3主图不全！！！'
                        continue
                    else:
                        # ID模式下出现异常，设置为空列表
                        sub_pic_list = []
                        print("ID模式：获取3:4主图时出现异常，将使用平台自带的1:1导入功能")
                try:    
                    detail_pic_list = get_detail_pic_list(record)
                except:
                    error_tip = '未找到详情图！！！'
                    continue
                diaopai_pic = get_diaopai_pic(record)
                
                # 获取视频文件
                my_video = get_my_video(record)

                sku_list = json.loads(record.content)
                if len(sku_list) == 0:
                    error_tip = '未找到sku信息！！！'
                    continue
                sku_flag = False
                for sku_item in sku_list:
                    # 🔧 修复：价格可以为0，只需要检查name是否存在，price是否是数字
                    if not sku_item['name'] or sku_item['price'] is None:
                        sku_flag = True
                        break
                    # 检查price是否是有效数字（包括0）
                    try:
                        float(sku_item['price'])
                    except (ValueError, TypeError):
                        sku_flag = True
                        break
                if sku_flag:
                    error_tip = 'sku信息不全！！！'
                    continue
                white_pic = get_white_pic(record, sku_list)

                print('打开商品发布页面...')
                main_tab.handle_alert(next_one=True)
                main_tab.get('https://fxg.jinritemai.com/ffa/g/create')
                time.sleep(3)

                try:
                    main_tab.ele('xpath://span[text()="重新发布"]/../..', timeout=3).click(by_js=True)
                    time.sleep(1)
                    main_tab.ele('xpath://*[text()="我知道了"]', timeout=1)
                    time.sleep(0.5)
                except:
                    pass
                input_element = main_tab.ele('xpath://input[@placeholder="请输入2-60个字符（1-30个汉字）"]')
                input_element.click()
                time.sleep(0.1)
                input_element.input(record.title)
                time.sleep(0.1)
                try:
                    main_tab.remove_ele(main_tab.ele('xpath://div[contains(@class,"index_DragController__")]', timeout=1))
                except:
                    pass

                upload_file(main_tab, main_pic_list, '主图', error_size='长宽比需为1:1' if record.type == 2 else None)

                # 🚀 使用增强的类目选择器
                print(f'开始智能类目选择: {wazi_dict.get(record.clazz)}')
                if not smart_select_category(main_tab, record.clazz):
                    print("❌ 智能类目选择失败，尝试传统方式")
                    # 备用传统方式
                    try:
                        # 点击更多推荐两次以展开完整类目列表
                        for _ in range(2):
                            try:
                                more_recommend = main_tab.ele('xpath://span[text()="更多推荐"]', timeout=3)
                                more_recommend.click(by_js=True)
                                time.sleep(0.5)
                            except:
                                print("更多推荐按钮未找到，尝试备用选择器")
                                more_recommend = main_tab.ele('xpath://div[contains(@class,"more-recommend")]', timeout=3)
                                more_recommend.click(by_js=True)
                                time.sleep(0.5)

                        # 点击手动选择按钮
                        try:
                            manual_select = main_tab.ele('xpath://span[text()="手动选择"]', timeout=3)
                            manual_select.click(by_js=True)
                            time.sleep(0.5)
                        except:
                            print("手动选择按钮未找到，尝试备用选择器")
                            manual_select = main_tab.ele('xpath://div[contains(@class,"manual-select")]', timeout=3)
                            manual_select.click(by_js=True)
                            time.sleep(0.5)

                        wazi_type = wazi_dict.get(record.clazz)
                        print(f'选择类型 -> 内衣裤袜 > 袜子 > {wazi_type}')
                        
                        # 选择一级类目：内衣裤袜
                        main_tab.ele('xpath://span[text()="内衣裤袜"]').click(by_js=True)
                        time.sleep(0.3)
                        
                        # 选择二级类目：袜子
                        main_tab.ele('xpath://span[text()="袜子"]').click(by_js=True)
                        time.sleep(0.3)
                        
                        # 处理可能的tooltip遮挡问题
                        try:
                            search_box = main_tab.ele('xpath://input[@placeholder="搜索三级类目"]', timeout=1)
                            search_box.click()
                            time.sleep(0.1)
                        except:
                            pass
                        
                        # 选择三级类目
                        main_tab.ele(f'xpath://span[text()="{wazi_type}"]').click(by_js=True)
                        time.sleep(0.3)

                        print('点击下一步...')
                        main_tab.ele('xpath://span[text()="下一步"]/..').click()
                        time.sleep(0.5)
                        try:
                            main_tab.ele('xpath://*[text()="我知道了"]', timeout=1)
                        except:
                            pass
                    except Exception as e:
                        print(f"传统类目选择方式也失败: {str(e)}")
                        raise e
                else:
                    print("✅ 智能类目选择成功")

                gen_btn = main_tab.ele(
                    'xpath://div[@data-better-log-outer-key="short_product_name"]'
                    + '//span[contains(@class,"ecom-g-input-suffix")]//img',
                    timeout=3
                )

                # 2. 如果找到了，就点击；否则打印提示
                if gen_btn:
                    # 可选：滚动到中央，确保可见
                    gen_btn.scroll.to_center()
                    # 点击
                    gen_btn.click(by_js=True)
                    print("已点击生成短标题按钮")
                else:
                    print("未找到生成短标题按钮，检查 XPath 或页面结构是否变化")
                
                try:
                    main_tab.ele('xpath://*[text()="我知道了"]', timeout=1)
                except:
                    pass

                # 处理吊牌识别（仅非船袜类目）
                if diaopai_pic and str(record.clazz) != '0':
                    print('处理其他类目吊牌上传...')
                    upload_file(main_tab, [diaopai_pic], '吊牌')
                    for _ in range(30):
                        if main_tab.ele('吊牌识别成功', timeout=0.1):
                            break
                        if main_tab.ele('吊牌识别失败', timeout=0.1):
                            break
                        time.sleep(0.1)

                # 根据类目处理属性填写
                if str(record.clazz) == '0':  # 船袜类目
                    print('处理船袜类目属性...')
                    main_tab.ele('xpath://span[text()="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    
                    # 船袜类目专门处理品牌和材质
                    select_text(main_tab, '品牌', '无品牌')
                    time.sleep(0.1)
                    # 针对船袜类目的材质输入框处理
                    try:
                        material_input = main_tab.ele('xpath://div[@attr-field-id="材质"]//input[@placeholder="请输入"]')
                        material_input.scroll.to_center()
                        material_input.click()
                        time.sleep(0.1)
                        material_input.input('棉')
                        time.sleep(0.1)
                        print('船袜类目：已填写材质为棉')
                    except Exception as e:
                        print(f'船袜类目材质填写失败: {str(e)}')
                        
                elif diaopai_pic:  # 其他类目且有吊牌
                    print('处理其他类目属性（有吊牌）...')
                    main_tab.ele('xpath://span[text()="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    
                    # 删除现有面料材质，让吊牌识别结果生效
                    ss = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=1)
                    for del_btn in ss:
                        del_btn.click(by_js=True)   
                        time.sleep(0.3)
                    
                    # 填写其他必要属性
                    select_text(main_tab, '品牌', '无品牌')
                    select_text(main_tab, '适用人群', '成人')
                    select_text(main_tab, '适用性别', get_sex(record.title))
                    select_text(main_tab, '筒高', wazi_dict_2.get(record.clazz, '短筒袜'))
                    
                else:  # 其他类目且没有吊牌
                    print('处理其他类目属性（无吊牌）...')
                    main_tab.ele('xpath://span[text()="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    caizhi_select(main_tab, '棉', '', 0)
                    select_text(main_tab, '品牌', '无品牌')
                    select_text(main_tab, '适用人群', '成人')
                    select_text(main_tab, '适用性别', get_sex(record.title))
                    select_text(main_tab, '面料材质成分含量', '棉')
                    select_text(main_tab, '筒高', wazi_dict_2.get(record.clazz, '短筒袜'))


                # 🔧 只有当sub_pic_list不为空时才上传3:4主图
                if len(sub_pic_list) > 0:
                    upload_file(main_tab, sub_pic_list, '主图', error_size='长宽比需为3:4')
                else:
                    print("跳过3:4主图上传，尝试自动点击'从1:1主图一键填入'按钮")
                    try:
                        # 滚动到主图3:4区域
                        main_tab.ele('xpath://span[text()="主图3:4"]').scroll.to_center()
                        time.sleep(0.5)
                        
                        # 查找并点击"从1:1主图一键填入"按钮
                        fill_button = main_tab.ele('xpath://span[text()="从1:1主图一键填入"]', timeout=3)
                        if fill_button:
                            fill_button.click()
                            print("✅ 成功点击'从1:1主图一键填入'按钮")
                            time.sleep(2)  # 等待填入完成
                        else:
                            print("❌ 未找到'从1:1主图一键填入'按钮")
                    except Exception as e:
                        print(f"❌ 自动点击'从1:1主图一键填入'按钮失败: {str(e)}")
                        print("请手动点击'从1:1主图一键填入'按钮")
                main_tab.ele('xpath://span[text()="主图视频"]').scroll.to_see()
                time.sleep(0.1)

                if my_video:
                    print('开始上传主图视频...')
                    upload_file(main_tab, [my_video], '主图视频')
                else:
                    print('没有主图视频')

                # 定位并点击一键生成按钮
                print('一键生成主图视频等待10秒')
                try:
                    generate_button = main_tab.ele("xpath://span[text()='一键生成']")
                    generate_button.click()
                    time.sleep(0.5)
                except:
                    print('未找到生成按钮，或已上传视频')

                upload_file(main_tab, [white_pic], '白底图')
                time.sleep(0.5)
                try:
                    apply_btn_list = main_tab.eles('xpath://div[text()="AI智能做主图"]/../../../..//span[text()="应用"]/..', timeout=1)
                    for item in apply_btn_list:
                        if item.states.is_displayed:
                            item.click()
                            time.sleep(3)
                            break
                    if len(apply_btn_list) > 0:
                        main_tab.ele('xpath://div[text()="AI智能做主图"]/../../../..//span[text()="上传"]/..', timeout=1).click()
                        time.sleep(0.5)
                except:
                    pass
                upload_file(main_tab, detail_pic_list, '图片', extra=True)

                main_tab.ele('xpath://span[text()="价格与库存"]').scroll.to_see()
                time.sleep(0.1)

                print('选择发货时间 -> 48小时')
                main_tab.ele('xpath://span[text()="48小时"]').click()
                time.sleep(0.1)

                print('勾选添加规格图片')
                main_tab.ele('xpath://span[text()="添加规格图"]').click(by_js=True)
                time.sleep(0.1)

                ss = main_tab.eles('xpath://div[@id="skuValue-颜色分类"]//span[@data-kora="删除规格值"]', timeout=1)
                for del_btn in ss:
                    del_btn.click(by_js=True)
                    time.sleep(0.1)

                for i, sku in enumerate(sku_list):
                    set_sku_info(main_tab, i, sku, record.remark)

                print('选择均码')
                main_tab.ele('xpath://div[@id="skuValue-码数"]//input').scroll.to_center()
                time.sleep(0.1)
                main_tab.ele('xpath://div[@id="skuValue-码数"]//input').click()
                time.sleep(0.1)
                main_tab.ele('xpath://li[@title="均码"]').click()
                time.sleep(0.1)
                main_tab.eles('xpath://li[@title="均码"]')[1].click()
                time.sleep(0.5)
                try:

                    confirm_button = main_tab.ele('xpath://div[contains(@class,"styles_popupFooter__")]//button[.//span[starts-with(text(), "确定")]]', timeout=0.5)
                    confirm_button.click()
                except:
                    pass

                print('设置价格和库存...')
                main_tab.ele('xpath://div[@attr-field-id="价格与库存"]')
                for i, sku in enumerate(sku_list):
                    tr = main_tab.eles('xpath://div[contains(@class,"styles_specName__")][text()="{}"]/../..'.format(sku['name']))[-1]
                    tr.scroll.to_center()
                    time.sleep(0.1)
                    tr.ele('xpath:./td[3]//input').input(sku['price'])
                    time.sleep(0.1)
                    tr.ele('xpath:./td[4]//input').input(record.repo)
                    time.sleep(0.1)
                
                main_tab.ele('xpath://span[text()="售后服务承诺"]').scroll.to_see()
                time.sleep(0.1)

                select_text(main_tab, '运费模板', '中通包邮', '包邮')
                time.sleep(0.1)
                youhui_btn = main_tab.ele('xpath://button[contains(@class,"marketing_sylva-switch-checked")]', timeout=1)
                if youhui_btn:
                    print('取消商品优惠券勾选')
                    youhui_btn.click(by_js=True)

                print('选择商品状态 -> 上架')
                main_tab.ele('xpath://span[text()="上架"]').click(by_js=True)
                time.sleep(0.1)

                print('勾选支持联盟达人带货')
                main_tab.ele('xpath://button[@dropdownclassname="auto-dropdown-id-支持联盟达人带货"]').click(by_js=True)
                time.sleep(0.1)

                print('输入佣金率：20%')
                main_tab.ele('xpath://label[@title="佣金率"]/../..//input').input('20')
                time.sleep(0.1)
                

                print('发布商品')
                main_tab.ele('xpath://span[text()="发布商品"]/..').click()
                time.sleep(0.5)

                try:
                    # 等待弹窗出现（最多等5秒）
                    modal = main_tab.ele('xpath://div[@class="ecom-g-modal-title"][text()="发布提醒"]/../..', timeout=5)
                    
                    # 定位目标按钮（通过文本精准定位）
                    continue_btn = modal.ele('xpath:.//div[text()="不修改，继续发布"]/ancestor::button')
                    
                    # 确保按钮可见后点击
                    continue_btn.scroll.to_center()
                    continue_btn.click()
                    print('已处理发布提醒弹窗')
                except Exception as e:
                    print(f'未出现弹窗或处理失败: {str(e)}')
                publish_ok = False
                for _ in range(30):
                    if main_tab.ele('商品提交成功，继续发布商品视频，分享到抖音', timeout=0.5):
                        publish_ok = True
                        break
                    time.sleep(0.5)

                if publish_ok:
                    print('发布成功！')
                    record_ok = True
                    record.status = 1
                    record.publish_time = time.now()
                    record.save()
                else:
                    print('发布失败！！！')

            except Exception as e:
                # 获取完整的错误追踪信息
                detailed_error = traceback.format_exc()
                print("------------- 详细错误报告 -------------")
                print(detailed_error)
                print("------------------------------------")
                
                # 如果是脚本预设的错误提示，直接使用
                if not error_tip:
                    # 否则，使用异常的文本信息作为错误提示
                    error_tip = str(e)
            
            finally:
                fi_arr = record.name.split('_')
                # 确保 fi_name 是一个字符串
                fi_name_tuple = record.name if len(fi_arr) < 4 else fi_arr[3],
                fi_name = fi_name_tuple[0] if isinstance(fi_name_tuple, tuple) else fi_name_tuple

                if record_ok:
                    msg_list.append(f'{fi_name} -> 操作成功！')
                else:
                    msg_list.append(f'{fi_name} -> 操作失败[{error_tip}]！')
                time.sleep(3)
    except:
        print("------------- 致误报告 -------------")
        print(traceback.format_exc())
        print("------------------------------------")
        msg_list.append('发生了一个意外的错误，请检查控制台日志。')
        
    # 🔧 修复：检查是否有失败消息，决定返回成功还是失败
    combined_msg = '\n'.join(msg_list)
    if '操作失败' in combined_msg or '意外的错误' in combined_msg:
        return api_error(msg=combined_msg)
    else:
        return api_ok(msg=combined_msg)



@app.get('/menu_open')
def menu_open():
    try:
        _id = request.args.get('_id')
        if not _id:
            return api_error(msg='参数错误！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        # 打开文件夹
        import subprocess
        import platform
        
        folder_path = os.path.dirname(record.path)
        if platform.system() == 'Windows':
            os.startfile(folder_path)
        elif platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', folder_path])
        else:  # Linux
            subprocess.run(['xdg-open', folder_path])
        
        return api_ok(msg='文件夹已打开！')
    except Exception as e:
        print(f"打开文件夹失败: {str(e)}")
        return api_error(msg=f'打开失败：{str(e)}')


@app.get('/menu_delete')
def menu_delete():
    try:
        _id = request.args.get('_id')
        if not _id:
            return api_error(msg='参数错误！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        Record.delete_by_id(_id)
        return api_ok(msg='产品删除成功！')
    except Exception as e:
        print(f"删除产品失败: {str(e)}")
        return api_error(msg=f'删除失败：{str(e)}')


# ====== 设置管理 API ======

@app.get('/settings')
def get_settings():
    """获取用户设置"""
    try:
        settings = settings_manager.get_settings()
        return api_ok(msg='获取设置成功', data={'settings': {
            'image_naming': {
                'supported_formats': settings.image_naming.supported_formats,
                'filename_filters': settings.image_naming.name_filters,
                'case_sensitive': not settings.image_naming.ignore_case,
            },
            'ui': {
                'image_hover_enabled': settings.ui_settings.enable_image_hover,
                'theme_mode': settings.ui_settings.theme_mode,
                'animations_enabled': settings.ui_settings.enable_animations,
            },
            'processing': {
                'auto_detect_folders': settings.processing.auto_detect_id_folders,
                'batch_mode_enabled': settings.processing.batch_processing_mode,
                'max_concurrent_operations': settings.processing.max_concurrent_tasks,
            }
        }})
    except Exception as e:
        return api_error(f'获取设置失败: {str(e)}')


@app.post('/settings')
def update_settings():
    """更新用户设置"""
    try:
        data = request.get_json()
        
        # 转换前端字段名到后端字段名
        backend_data = {}
        
        if 'image_naming' in data:
            backend_data['image_naming'] = {
                'supported_formats': data['image_naming'].get('supported_formats'),
                'name_filters': data['image_naming'].get('filename_filters'),
                'ignore_case': not data['image_naming'].get('case_sensitive', False),
            }
        
        if 'ui' in data:
            backend_data['ui_settings'] = {
                'enable_image_hover': data['ui'].get('image_hover_enabled'),
                'theme_mode': data['ui'].get('theme_mode'),
                'enable_animations': data['ui'].get('animations_enabled'),
            }
        
        if 'processing' in data:
            backend_data['processing'] = {
                'auto_detect_id_folders': data['processing'].get('auto_detect_folders'),
                'batch_processing_mode': data['processing'].get('batch_mode_enabled'),
                'max_concurrent_tasks': data['processing'].get('max_concurrent_operations'),
            }
        
        if settings_manager.update_settings(backend_data):
            return api_ok(msg='设置保存成功')
        else:
            return api_error('设置保存失败')
    except Exception as e:
        return api_error(f'设置更新失败: {str(e)}')


@app.post('/settings/reset')
def reset_settings():
    """重置为默认设置"""
    try:
        if settings_manager.reset_to_defaults():
            settings = settings_manager.get_settings()
            return api_ok(msg='设置已重置为默认值', data={'settings': {
                'image_naming': {
                    'supported_formats': settings.image_naming.supported_formats,
                    'filename_filters': settings.image_naming.name_filters,
                    'case_sensitive': not settings.image_naming.ignore_case,
                },
                'ui': {
                    'image_hover_enabled': settings.ui_settings.enable_image_hover,
                    'theme_mode': settings.ui_settings.theme_mode,
                    'animations_enabled': settings.ui_settings.enable_animations,
                },
                'processing': {
                    'auto_detect_folders': settings.processing.auto_detect_id_folders,
                    'batch_mode_enabled': settings.processing.batch_processing_mode,
                    'max_concurrent_operations': settings.processing.max_concurrent_tasks,
                }
            }})
        else:
            return api_error('重置设置失败')
    except Exception as e:
        return api_error(f'重置设置失败: {str(e)}')


@app.get('/settings/page')
def settings_page():
    """设置页面"""
    try:
        return render_template('/view/settings/index.html', ctx=constants)
    except Exception as e:
        traceback.print_exc()
        return api_error(f'页面加载失败：{str(e)}')


@app.post('/api/generate_smart_title')
def generate_smart_title():
    """🧠 智能产品标题生成API"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        # 构建产品信息对象
        product_info = ProductInfo(
            name=record.name,
            category=record.clazz if record.clazz else 1,
            remark=record.remark if record.remark else "",
            sku_list=sku_list
        )
        
        # 调用智能标题生成器
        title_suggestions = smart_title_generator.generate_titles(product_info)
        
        # 格式化返回结果
        suggestions_data = []
        for suggestion in title_suggestions:
            suggestions_data.append({
                'title': suggestion.title,
                'confidence': round(suggestion.confidence, 3),
                'reasoning': suggestion.reasoning,
                'tags': suggestion.tags,
                'character_count': suggestion.character_count
            })
        
        return api_ok(msg='智能标题生成成功！', data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': product_info.name,
                'category': product_info.category,
                'sku_count': len(product_info.sku_list)
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'智能标题生成失败：{str(e)}')


@app.post('/api/generate_smart_title_enhanced')
def generate_smart_title_enhanced():
    """🔥 增强版智能产品标题生成API（集成热门词抓取 + 网络稳定性）"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        use_trending = data.get('use_trending', True)  # 是否使用热门词抓取
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        # 构建产品信息对象
        product_info = ProductInfo(
            name=record.name,
            category=record.clazz if record.clazz else 1,
            remark=record.remark if record.remark else "",
            sku_list=sku_list
        )
        
        # 🔥 调用增强版智能标题生成器
        import asyncio
        
        async def generate_async():
            return await smart_title_generator.generate_titles_enhanced(product_info)
        
        # 在新的事件循环中运行异步函数
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            title_suggestions = loop.run_until_complete(generate_async())
        finally:
            loop.close()
        
        # 获取网络状态信息
        from src.network_stability_manager import get_network_status_info
        network_status = get_network_status_info()
        
        # 🔥 获取热门关键词信息
        trending_keywords = []
        try:
            trending_data = smart_title_generator.trending_scraper.get_trending_keywords_for_category(
                product_info.category, limit=8
            )
            trending_keywords = [
                {
                    'keyword': kw.keyword,
                    'trend_score': round(kw.trend_score, 3),
                    'platform': kw.platform
                } for kw in trending_data
            ]
        except Exception as e:
            print(f"获取热门词失败: {e}")
        
        # 格式化返回结果
        suggestions_data = []
        for suggestion in title_suggestions:
            suggestions_data.append({
                'title': suggestion.title,
                'confidence': round(suggestion.confidence, 3),
                'reasoning': suggestion.reasoning,
                'tags': suggestion.tags,
                'character_count': suggestion.character_count
            })
        
        return api_ok(msg='增强版智能标题生成成功！', data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': product_info.name,
                'category': product_info.category,
                'sku_count': len(product_info.sku_list)
            },
            'trending_keywords': trending_keywords,
            'network_status': network_status,
            'generation_method': 'enhanced_ai_with_trending'
        })
        
    except Exception as e:
        traceback.print_exc()
        # 如果增强版失败，降级到标准版
        try:
            return generate_smart_title()
        except:
            return api_error(f'智能标题生成失败：{str(e)}')


@app.get('/api/trending_keywords/<int:category_id>')
def get_trending_keywords(category_id):
    """🔥 获取指定类目的热门关键词"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        trending_data = smart_title_generator.trending_scraper.get_trending_keywords_for_category(
            category_id, limit=limit
        )
        
        keywords_data = []
        for kw in trending_data:
            keywords_data.append({
                'keyword': kw.keyword,
                'trend_score': round(kw.trend_score, 3),
                'search_volume': kw.search_volume,
                'platform': kw.platform,
                'related_keywords': kw.related_keywords,
                'timestamp': kw.timestamp.isoformat()
            })
        
        return api_ok(msg='热门关键词获取成功！', data={
            'keywords': keywords_data,
            'category_id': category_id,
            'total_count': len(keywords_data)
        })
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'获取热门关键词失败：{str(e)}')


@app.post('/api/refresh_trending_keywords')
def refresh_trending_keywords():
    """🔄 手动刷新热门关键词"""
    try:
        data = request.get_json()
        category_id = data.get('category_id', 1)
        
        # 异步刷新关键词
        import threading
        
        def refresh_async():
            try:
                category_name = smart_title_generator.category_map.get(category_id, "袜子")
                
                # 从各平台抓取
                scraper = smart_title_generator.trending_scraper
                all_keywords = []
                
                all_keywords.extend(scraper.scrape_douyin_trending(category_name))
                all_keywords.extend(scraper.scrape_taobao_trending(category_name))
                all_keywords.extend(scraper.scrape_jd_trending(category_name))
                
                print(f"🔄 后台刷新 {category_name} 热门关键词完成，共获取 {len(all_keywords)} 个")
                
            except Exception as e:
                print(f"后台刷新热门关键词失败: {e}")
        
        refresh_thread = threading.Thread(target=refresh_async, daemon=True)
        refresh_thread.start()
        
        return api_ok(msg='热门关键词刷新已启动，请稍后查看最新数据')
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'刷新热门关键词失败：{str(e)}')


@app.get('/api/network_status')
def get_network_status():
    """🌐 获取网络状态信息"""
    try:
        from src.network_stability_manager import get_network_status_info
        network_info = get_network_status_info()
        
        return api_ok(msg='网络状态获取成功！', data=network_info)
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'获取网络状态失败：{str(e)}')


# 🔧 新增：控制GUI拖拽区域显示/隐藏的API
@app.post('/gui/toggle_drag_area')
def toggle_drag_area():
    """控制GUI拖拽区域的显示和隐藏"""
    try:
        data = request.get_json()
        show = data.get('show', True)  # 默认显示
        
        if hasattr(gui, 'window') and gui.window and hasattr(gui.window, 'label'):
            if show:
                gui.window.label.show()
                print('GUI拖拽区域已显示')
            else:
                gui.window.label.hide()
                print('GUI拖拽区域已隐藏')
            return api_ok('操作成功')
        else:
            return api_error('GUI窗口未初始化')
    except Exception as e:
        print(f'控制GUI拖拽区域失败: {str(e)}')
        return api_error(f'操作失败: {str(e)}')


def wakeup_listen():
    wakeup_flag = False
    while 1:
        try:
            pyautogui.moveRel(xOffset=1 if wakeup_flag else -1)
            wakeup_flag = not wakeup_flag
        except:
            pass
        finally:
            time.sleep(30)


# 🚀 智能价格计算API - 重新实现

@app.post('/api/pricing/calculate_smart_prices')
def calculate_smart_prices():
    """智能价格计算API - 支持动态单价"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        unit_price = data.get('unit_price', 0)  # 获取单价参数
        profit_margin = data.get('profit_margin', 0)  # 获取毛利率参数
        
        if not record_id:
            return jsonify({'success': False, 'error': '缺少产品ID参数'})
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return jsonify({'success': False, 'error': '产品不存在'})
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        if not sku_list:
            return jsonify({'success': False, 'error': '该产品没有SKU信息'})
        
        # 导入智能定价引擎
        from src.smart_pricing_engine import SmartPricingEngine
        
        # 创建定价引擎实例
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        engine = SmartPricingEngine(config_file)
        
        # 🔧 新增：成本验证逻辑
        if unit_price <= 0:
            return jsonify({
                'success': False, 
                'error': '袜子成本不能为0或负数！袜子成本是必不可少的产品成本，请输入正确的成本价格。'
            })
        
        # 准备自定义配置（如果提供了单价或毛利率）
        custom_config = {}
        if unit_price > 0:
            custom_config['base_cost_per_unit'] = unit_price
            print(f"🎯 使用自定义单价: {unit_price}元")
        if profit_margin > 0:
            custom_config['target_profit_margin'] = profit_margin
            print(f"🎯 使用自定义毛利率: {profit_margin*100:.1f}%")
        
        # 计算每个SKU的价格
        pricing_results = []
        for sku in sku_list:
            sku_name = sku.get('name', '')
            if sku_name:
                try:
                    # 使用自定义配置计算价格
                    result = engine.calculate_price(sku_name, custom_config if custom_config else None)
                    pricing_results.append({
                        'sku_name': result.sku_name,
                        'quantity': result.quantity,
                        'base_cost': result.base_cost,
                        'total_cost': result.total_cost,
                        'suggested_price': result.suggested_price,
                        'profit_margin': result.profit_margin,
                        'confidence': result.confidence,
                        'price_range': result.price_range,
                        'notes': result.notes,
                        'calculation_details': result.calculation_details
                    })
                except Exception as e:
                    print(f"计算SKU '{sku_name}' 价格时出错: {e}")
                    # 添加错误信息但继续处理其他SKU
                    pricing_results.append({
                        'sku_name': sku_name,
                        'quantity': 1,
                        'suggested_price': 0,
                        'profit_margin': 0,
                        'confidence': 0,
                        'price_range': [0, 0],
                        'notes': f'计算失败: {str(e)}',
                        'calculation_details': {}
                    })
        
        if not pricing_results:
            return jsonify({'success': False, 'error': '没有成功计算任何SKU价格'})
        
        # 计算统计信息
        successful_results = [r for r in pricing_results if r['suggested_price'] > 0]
        avg_price = sum(r['suggested_price'] for r in successful_results) / len(successful_results) if successful_results else 0
        avg_margin = sum(r['profit_margin'] for r in successful_results) / len(successful_results) if successful_results else 0
        high_confidence_count = len([r for r in successful_results if r['confidence'] > 0.8])
        
        return jsonify({
            'success': True,
            'message': f'智能价格计算完成！成功计算 {len(successful_results)}/{len(pricing_results)} 个SKU',
            'data': {
                'pricing_results': pricing_results,
                'statistics': {
                    'total_skus': len(pricing_results),
                    'successful_calculations': len(successful_results),
                    'average_price': round(avg_price, 2),
                    'average_margin': round(avg_margin * 100, 1),  # 转换为百分比
                    'high_confidence_count': high_confidence_count,
                    'high_confidence_rate': round(high_confidence_count / len(successful_results) * 100, 1) if successful_results else 0
                }
            }
        })
        
    except Exception as e:
        print(f"智能价格计算失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'智能价格计算失败: {str(e)}'
        })


@app.post('/api/generate_professional_title')
def generate_professional_title():
    """🏆 专业产品标题生成API (60字符无重复)"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        # 构建产品信息对象
        product_info = ProfessionalProductInfo(
            name=record.name,
            category=record.clazz if record.clazz else 2,
            remark=record.remark if record.remark else "",
            sku_list=sku_list
        )
        
        # 调用专业标题生成器
        professional_generator = get_professional_generator()
        title_suggestions = professional_generator.generate_professional_titles(product_info)
        
        # 格式化响应数据
        suggestions_data = []
        for suggestion in title_suggestions:
            suggestions_data.append({
                'title': suggestion.title,
                'confidence': suggestion.confidence,
                'character_count': suggestion.character_count,
                'tags': suggestion.tags,
                'reasoning': suggestion.reasoning,
                'blue_ocean_words': suggestion.blue_ocean_words
            })
        
        return api_ok(msg=f"专业标题生成成功！生成了 {len(suggestions_data)} 个60字符标题", data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': product_info.name,
                'category': product_info.category,
                'sku_count': len(product_info.sku_list)
            },
            'generation_method': 'professional_60_chars'
        })
        
    except Exception as e:
        logger.error(f"专业标题生成失败: {e}")
        return api_error(f'生成失败: {str(e)}')


@app.post('/api/pricing/cost-config')
def save_cost_config():
    """保存成本配置API - 增强版"""
    try:
        data = request.get_json()
        
        # 🔧 增强数据验证
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        if 'cost_items' not in data:
            return jsonify({'success': False, 'error': '缺少成本项目数据'})
            
        if 'target_profit_rate' not in data:
            return jsonify({'success': False, 'error': '缺少目标利润率数据'})
        
        cost_items = data['cost_items']
        target_profit_rate = data['target_profit_rate']
        
        # 🔧 验证成本项目数据
        if not isinstance(cost_items, list):
            return jsonify({'success': False, 'error': '成本项目数据格式错误'})
            
        # 🔧 修复：允许空的成本项目列表（用户可能删除了所有项目）
        print(f"💾 保存成本配置: {len(cost_items)}个项目, 利润率: {target_profit_rate*100:.1f}%")
        
        # 🔧 验证每个成本项目的数据完整性（仅在有项目时验证）
        for i, item in enumerate(cost_items):
            if not isinstance(item, dict):
                return jsonify({'success': False, 'error': f'成本项目{i+1}数据格式错误'})
                
            required_fields = ['name', 'cost_type', 'value', 'description']
            for field in required_fields:
                if field not in item:
                    return jsonify({'success': False, 'error': f'成本项目{i+1}缺少{field}字段'})
            
            # 验证数值类型
            if not isinstance(item['value'], (int, float)):
                return jsonify({'success': False, 'error': f'成本项目{i+1}的值必须是数字'})
                
            if item['value'] < 0:
                return jsonify({'success': False, 'error': f'成本项目{i+1}的值不能为负数'})
                
            # 验证成本类型
            if item['cost_type'] not in ['fixed', 'percentage', 'per_unit']:
                return jsonify({'success': False, 'error': f'成本项目{i+1}的类型无效'})
        
        # 🔧 验证利润率
        if not isinstance(target_profit_rate, (int, float)):
            return jsonify({'success': False, 'error': '目标利润率必须是数字'})
            
        if target_profit_rate < 0 or target_profit_rate > 1:
            return jsonify({'success': False, 'error': '目标利润率必须在0-100%之间'})
        
        # 保存到配置文件
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        # 🔧 确保配置目录存在
        config_dir = os.path.dirname(config_file)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        # 读取现有配置
        existing_config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        else:
            # 如果配置文件不存在，创建一个新的空配置
            existing_config = {}
        
        # 更新成本配置
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {}
        
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['templates']['默认袜子模板']['profit_margin'] = target_profit_rate
        
        # 🔧 修复：保存营销价格配置，使用正确的字段名
        if 'marketing_pricing' in data:
            marketing_config = data['marketing_pricing']
            
            # 验证营销配置
            if isinstance(marketing_config, dict):
                # 设置默认值并验证
                validated_marketing = {
                    'enabled': bool(marketing_config.get('enabled', True)),
                    'strategy': marketing_config.get('strategy', 'charm'),
                    'price_range': marketing_config.get('price_range', 'low'),
                    'show_savings': bool(marketing_config.get('show_savings', False)),
                    'competitor_analysis': bool(marketing_config.get('competitor_analysis', False))
                }
                
                # 验证策略值
                valid_strategies = ['charm', 'prestige', 'bundle', 'competitive', 'none']
                if validated_marketing['strategy'] not in valid_strategies:
                    validated_marketing['strategy'] = 'charm'
                
                # 验证价格区间
                valid_ranges = ['low', 'mid', 'high', 'premium']
                if validated_marketing['price_range'] not in valid_ranges:
                    validated_marketing['price_range'] = 'low'
                
                existing_config['templates']['默认袜子模板']['marketing_config'] = validated_marketing
                print(f"✅ 营销配置已保存: {validated_marketing}")
        
        # 🔧 添加保存时间戳
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        print(f"✅ 配置已保存到: {config_file}")
        
        # 🔧 验证保存是否成功
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                saved_items = saved_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
                if len(saved_items) != len(cost_items):
                    print(f"⚠️ 保存验证失败: 期望{len(cost_items)}个项目，实际保存{len(saved_items)}个")
                else:
                    print(f"✅ 保存验证成功: {len(saved_items)}个成本项目")
        except Exception as e:
            print(f"⚠️ 保存验证失败: {e}")
        
        return jsonify({
            'success': True,
            'message': f'成本配置保存成功，包含{len(cost_items)}个成本项目',
            'data': {
                'cost_items_count': len(cost_items),
                'profit_margin': target_profit_rate,
                'saved_at': existing_config.get('last_updated')
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        error_msg = f'保存成本配置失败：{str(e)}'
        print(f"❌ {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg,
            'details': traceback.format_exc() if app.debug else None
        })


@app.post('/api/pricing/reload-config')
def force_reload_pricing_config():
    """配置刷新API（简化版）"""
    try:
        data = request.get_json() or {}
        operation = data.get('operation', 'manual_reload')
        
        logger.info(f"🔄 收到配置刷新请求: {operation}")
        
        # 🔧 简化：只返回成功状态，不强制重载
        return jsonify({
            'success': True,
            'message': '配置已刷新',
            'operation': operation,
            'reload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        logger.error(f"❌ 配置刷新失败: {e}")
        return jsonify({
            'success': False,
            'error': f'配置刷新失败: {str(e)}'
        }), 500


@app.get('/api/pricing/config')
def get_pricing_config():
    """获取价格配置API"""
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            # 返回默认配置
            config = {
                'templates': {
                    '默认袜子模板': {
                        'base_cost_items': [
                            {
                                'name': '原材料',
                                'cost_type': 'fixed',
                                'value': 5.0,
                                'description': '每双袜子的原材料成本',
                                'is_active': True
                            },
                            {
                                'name': '人工费',
                                'cost_type': 'fixed',
                                'value': 2.0,
                                'description': '每双袜子的人工成本',
                                'is_active': True
                            },
                            {
                                'name': '包装费',
                                'cost_type': 'fixed',
                                'value': 0.5,
                                'description': '每双袜子的包装成本',
                                'is_active': True
                            },
                            {
                                'name': '运费',
                                'cost_type': 'fixed',
                                'value': 1.5,
                                'description': '每双袜子的运费成本',
                                'is_active': True
                            },
                            {
                                'name': '平台费',
                                'cost_type': 'percentage',
                                'value': 0.08,
                                'description': '平台收取的费用比例',
                                'is_active': True
                            },
                            {
                                'name': '推广费',
                                'cost_type': 'percentage',
                                'value': 0.05,
                                'description': '推广营销费用比例',
                                'is_active': True
                            }
                        ],
                        'profit_margin': 0.30
                    }
                }
            }
        
        return jsonify({
            'success': True,
            'data': config
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取价格配置失败：{str(e)}'
        })


# 🚀 新增：成本项目精细化管理API

@app.post('/api/pricing/cost-item')
def add_cost_item():
    """添加单个成本项目API"""
    try:
        data = request.get_json()
        
        # 验证必需字段
        required_fields = ['name', 'cost_type', 'value', 'description']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'缺少必需字段: {field}'})
        
        # 验证成本类型
        if data['cost_type'] not in ['fixed', 'percentage', 'per_unit', 'platform_fee']:
            return jsonify({'success': False, 'error': '无效的成本类型'})
        
        # 验证数值
        if not isinstance(data['value'], (int, float)) or data['value'] < 0:
            return jsonify({'success': False, 'error': '成本值必须是非负数'})
        
        # 读取现有配置
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        existing_config = {}
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        
        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {'base_cost_items': []}
        
        # 检查是否已存在同名项目
        cost_items = existing_config['templates']['默认袜子模板'].get('base_cost_items', [])
        for item in cost_items:
            if item['name'] == data['name']:
                return jsonify({'success': False, 'error': f'成本项目 "{data["name"]}" 已存在'})
        
        # 添加新项目
        new_item = {
            'name': data['name'],
            'cost_type': data['cost_type'],
            'value': data['value'],
            'description': data['description'],
            'is_active': data.get('is_active', True)
        }
        
        cost_items.append(new_item)
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
        # 🧹 价格计算器重载已移除 - 准备重构
        # from src.pricing_calculator_main import pricing_calculator
        # pricing_calculator.templates.clear()
        # pricing_calculator.load_pricing_config()
        
        return jsonify({
            'success': True,
            'message': f'成本项目 "{data["name"]}" 添加成功',
            'data': new_item
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'添加成本项目失败: {str(e)}'
        })


@app.put('/api/pricing/cost-item/<item_name>')
def update_cost_item(item_name):
    """修改单个成本项目API"""
    try:
        data = request.get_json()
        
        # 读取现有配置
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        if not os.path.exists(config_file):
            return jsonify({'success': False, 'error': '配置文件不存在'})
        
        with open(config_file, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)
        
        # 查找并更新项目
        cost_items = existing_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
        item_found = False
        
        for item in cost_items:
            if item['name'] == item_name:
                # 更新字段
                if 'cost_type' in data:
                    if data['cost_type'] not in ['fixed', 'percentage', 'per_unit', 'platform_fee']:
                        return jsonify({'success': False, 'error': '无效的成本类型'})
                    item['cost_type'] = data['cost_type']
                
                if 'value' in data:
                    if not isinstance(data['value'], (int, float)) or data['value'] < 0:
                        return jsonify({'success': False, 'error': '成本值必须是非负数'})
                    item['value'] = data['value']
                
                if 'description' in data:
                    item['description'] = data['description']
                
                if 'is_active' in data:
                    item['is_active'] = bool(data['is_active'])
                
                item_found = True
                break
        
        if not item_found:
            return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
        # 保存配置
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
        # 🧹 价格计算器重载已移除 - 准备重构
        # from src.pricing_calculator_main import pricing_calculator
        # pricing_calculator.templates.clear()
        # pricing_calculator.load_pricing_config()
        
        return jsonify({
            'success': True,
            'message': f'成本项目 "{item_name}" 更新成功'
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'更新成本项目失败: {str(e)}'
        })


@app.delete('/api/pricing/cost-item/<item_name>')
def delete_cost_item(item_name):
    """删除单个成本项目API"""
    try:
        # 读取现有配置
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        if not os.path.exists(config_file):
            return jsonify({'success': False, 'error': '配置文件不存在'})
        
        with open(config_file, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)
        
        # 查找并删除项目
        cost_items = existing_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
        original_count = len(cost_items)
        
        # 过滤掉要删除的项目
        cost_items = [item for item in cost_items if item['name'] != item_name]
        
        if len(cost_items) == original_count:
            return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
        # 更新配置
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
        # 🧹 价格计算器重载已移除 - 准备重构
        # from src.pricing_calculator_main import pricing_calculator
        # pricing_calculator.templates.clear()
        # pricing_calculator.load_pricing_config()
        
        return jsonify({
            'success': True,
            'message': f'成本项目 "{item_name}" 删除成功',
            'remaining_items': len(cost_items)
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'删除成本项目失败: {str(e)}'
        })


@app.get('/api/pricing/cost-items')
def get_cost_items():
    """获取成本项目列表API"""
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            cost_items = config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
        else:
            cost_items = []
        
        return jsonify({
            'success': True,
            'data': {
                'cost_items': cost_items,
                'total_count': len(cost_items),
                'active_count': len([item for item in cost_items if item.get('is_active', True)])
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取成本项目列表失败: {str(e)}'
        })


# 🚀 新增：模板管理API

@app.get('/api/pricing/templates')
def get_pricing_templates():
    """获取所有价格模板API"""
    try:
        # 🧹 价格计算器引用已移除 - 准备重构
        # from src.pricing_calculator_main import pricing_calculator
        
        # 暂时返回空列表，等待重构
        templates_info = []
        
        return jsonify({
            'success': True,
            'data': {
                'templates': templates_info,
                'total_count': len(templates_info)
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取模板列表失败: {str(e)}'
        })


# 🚀 新增：智能价格计算API

# 🚀 新增：AI配置管理API

@app.get('/api/ai/config')
def get_ai_config():
    """获取AI配置API"""
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'ai_config.json')
        
        # 默认配置
        default_config = {
            'deepseek': {
                'enabled': True,
                'api_key': '',
                'model': 'deepseek-chat',
                'priority': 1
            },
            'openai': {
                'enabled': False,
                'api_key': '',
                'model': 'gpt-4',
                'priority': 2
            },
            'claude': {
                'enabled': False,
                'api_key': '',
                'model': 'claude-3-sonnet-20240229',
                'priority': 3
            }
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置，确保所有字段都存在
                for provider in default_config:
                    if provider not in config:
                        config[provider] = default_config[provider]
                    else:
                        for key in default_config[provider]:
                            if key not in config[provider]:
                                config[provider][key] = default_config[provider][key]
        else:
            config = default_config
        
        # 隐藏API密钥的敏感信息
        safe_config = {}
        for provider, settings in config.items():
            safe_config[provider] = settings.copy()
            if safe_config[provider]['api_key']:
                # 只显示前4位和后4位
                key = safe_config[provider]['api_key']
                if len(key) > 8:
                    safe_config[provider]['api_key'] = key[:4] + '*' * (len(key) - 8) + key[-4:]
        
        return jsonify({
            'success': True,
            'data': safe_config
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取AI配置失败: {str(e)}'
        })


@app.post('/api/ai/config')
def save_ai_config():
    """保存AI配置API"""
    try:
        data = request.get_json()
        
        # 验证配置数据
        required_providers = ['deepseek', 'openai', 'claude']
        for provider in required_providers:
            if provider not in data:
                return jsonify({
                    'success': False,
                    'error': f'缺少{provider}配置'
                })
            
            provider_config = data[provider]
            required_fields = ['enabled', 'api_key', 'model', 'priority']
            for field in required_fields:
                if field not in provider_config:
                    return jsonify({
                        'success': False,
                        'error': f'{provider}配置缺少{field}字段'
                    })
        
        # 验证至少启用一个服务
        enabled_services = [p for p in data.values() if p.get('enabled')]
        if not enabled_services:
            return jsonify({
                'success': False,
                'error': '至少需要启用一个AI服务'
            })
        
        # 验证启用的服务都有API密钥
        for provider, config in data.items():
            if config.get('enabled') and not config.get('api_key'):
                provider_names = {
                    'deepseek': 'DeepSeek',
                    'openai': 'OpenAI',
                    'claude': 'Claude'
                }
                return jsonify({
                    'success': False,
                    'error': f'请填写{provider_names.get(provider, provider)}的API密钥'
                })
        
        # 保存配置
        config_file = os.path.join(os.path.dirname(__file__), 'ai_config.json')
        
        # 添加时间戳
        data['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 更新多AI管理器配置
        try:
            from src.multi_ai_manager import MultiAIManager
            # 重新初始化AI管理器以应用新配置
            # 这里可以添加配置热重载逻辑
            print("🔄 AI配置已更新，建议重启应用以应用新配置")
        except Exception as e:
            print(f"更新AI管理器配置时出错: {e}")
        
        return jsonify({
            'success': True,
            'message': 'AI配置保存成功'
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'保存AI配置失败: {str(e)}'
        })


@app.post('/api/ai/test')
def test_ai_connection():
    """测试AI连接API"""
    try:
        data = request.get_json()
        
        test_results = {}
        
        # 测试每个启用的AI服务
        for provider, config in data.items():
            if not config.get('enabled'):
                continue
                
            provider_names = {
                'deepseek': 'DeepSeek',
                'openai': 'OpenAI',
                'claude': 'Claude'
            }
            
            try:
                api_key = config.get('api_key', '').strip()
                model = config.get('model', '')
                
                if not api_key:
                    test_results[provider] = {
                        'success': False,
                        'error': 'API密钥为空'
                    }
                    continue
                
                # 根据不同提供商测试连接
                if provider == 'deepseek':
                    success, error = test_deepseek_connection(api_key, model)
                elif provider == 'openai':
                    success, error = test_openai_connection(api_key, model)
                elif provider == 'claude':
                    success, error = test_claude_connection(api_key, model)
                else:
                    success, error = False, '未知的AI提供商'
                
                test_results[provider] = {
                    'success': success,
                    'error': error if not success else None
                }
                
            except Exception as e:
                test_results[provider] = {
                    'success': False,
                    'error': f'测试连接时出错: {str(e)}'
                }
        
        return jsonify({
            'success': True,
            'data': test_results
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'测试AI连接失败: {str(e)}'
        })


def test_deepseek_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试DeepSeek连接"""
    try:
        import requests
        
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


def test_openai_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试OpenAI连接"""
    try:
        import requests
        
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


def test_claude_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试Claude连接"""
    try:
        import requests
        
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": model,
            "max_tokens": 10,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


# 🚀 新增：毛利率配置API

@app.post('/api/pricing/profit-margin-config')
def save_profit_margin_config():
    """保存毛利率配置API - 实时保存"""
    try:
        data = request.get_json()
        
        # 验证请求数据
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        if 'profit_margin' not in data:
            return jsonify({'success': False, 'error': '缺少毛利率数据'})
        
        profit_margin = data['profit_margin']
        
        # 验证毛利率值
        if not isinstance(profit_margin, (int, float)):
            return jsonify({'success': False, 'error': '毛利率必须是数字'})
            
        if profit_margin < 0 or profit_margin > 100:
            return jsonify({'success': False, 'error': '毛利率必须在0-100%之间'})
        
        # 转换为小数形式
        profit_margin_decimal = profit_margin / 100.0
        
        # 读取现有配置
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        existing_config = {}
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        
        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {'base_cost_items': []}
        
        # 更新毛利率
        existing_config['templates']['默认袜子模板']['profit_margin'] = profit_margin_decimal
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ 毛利率已实时保存: {profit_margin}%")
        
        return jsonify({
            'success': True,
            'message': f'毛利率已保存为 {profit_margin}%',
            'data': {
                'profit_margin': profit_margin,
                'profit_margin_decimal': profit_margin_decimal,
                'saved_at': existing_config.get('last_updated')
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        error_msg = f'保存毛利率配置失败：{str(e)}'
        logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': error_msg
        })


# 🚀 新增：配置验证API

@app.post('/api/pricing/validate-config')
def validate_pricing_config():
    """验证价格配置有效性API"""
    try:
        data = request.get_json()
        
        validation_results = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        # 验证成本项目
        cost_items = data.get('cost_items', [])
        
        if len(cost_items) == 0:
            validation_results['warnings'].append('没有配置任何成本项目，可能影响价格计算准确性')
        
        # 验证每个成本项目
        for i, item in enumerate(cost_items):
            if not item.get('name'):
                validation_results['errors'].append(f'成本项目{i+1}缺少名称')
                validation_results['is_valid'] = False
            
            if item.get('cost_type') not in ['fixed', 'percentage', 'per_unit']:
                validation_results['errors'].append(f'成本项目{i+1}的类型无效')
                validation_results['is_valid'] = False
            
            if not isinstance(item.get('value'), (int, float)) or item.get('value', 0) < 0:
                validation_results['errors'].append(f'成本项目{i+1}的值无效')
                validation_results['is_valid'] = False
        
        # 验证利润率
        profit_margin = data.get('target_profit_rate', 0)
        if not isinstance(profit_margin, (int, float)) or profit_margin < 0 or profit_margin > 1:
            validation_results['errors'].append('利润率必须在0-100%之间')
            validation_results['is_valid'] = False
        elif profit_margin < 0.1:
            validation_results['warnings'].append('利润率过低，可能影响盈利能力')
        elif profit_margin > 0.5:
            validation_results['warnings'].append('利润率过高，可能影响产品竞争力')
        
        # 提供优化建议
        if len(cost_items) > 0:
            fixed_costs = [item for item in cost_items if item.get('cost_type') == 'fixed']
            percentage_costs = [item for item in cost_items if item.get('cost_type') == 'percentage']
            
            if len(fixed_costs) == 0:
                validation_results['suggestions'].append('建议添加一些固定成本项目（如包装、运费等）')
            
            if len(percentage_costs) == 0:
                validation_results['suggestions'].append('建议添加一些百分比成本项目（如平台费、推广费等）')
        
        return jsonify({
            'success': True,
            'data': validation_results
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'配置验证失败: {str(e)}'
        })




if __name__ == '__main__':
    # 启用Flask调试日志
    import logging
    logging.basicConfig(level=logging.INFO)  # 🔧 使用INFO级别
    app.logger.setLevel(logging.INFO)
    
    # 检查logo文件路径
    logo_path = os.path.join(constants.run_path, 'admin', 'images', 'logo.png')
    
    # 如果logo不存在，使用备用路径
    if not os.path.exists(logo_path):
        alternative_paths = [
            os.path.join(os.path.dirname(__file__), 'web', 'admin', 'images', 'logo.png'),
            os.path.join(constants.root_path, 'web', 'admin', 'images', 'logo.png'),
            'web/admin/images/logo.png'
        ]
        
        for alt_path in alternative_paths:
            if os.path.exists(alt_path):
                logo_path = alt_path
                break
        else:
            logo_path = None
    
    try:
        # 🔧 优化GUI初始化，增加异常处理
        gui = Gui(
            title=f'{constants.name}（v{constants.version}）',
            logo=logo_path,
            width=1200,
            height=900,
            app=app
        )
        
        # 异步初始化浏览器页面，避免阻塞GUI启动
        def init_browser():
            try:
                print("🔧 初始化浏览器页面...")
                gui.page = get_page('https://fxg.jinritemai.com/login/common')
                print("✅ 浏览器页面初始化成功")
            except Exception as e:
                print(f"⚠️ 浏览器初始化失败: {e}")
                # 浏览器初始化失败不影响GUI显示
        
        # 在后台线程中初始化浏览器
        Thread(init_browser).start()
        
        # Thread(wakeup_listen).start()  # 🔧 暂时禁用自动唤醒功能
        print("💡 启动GUI界面...")
        gui.start()
        
    except Exception as gui_error:
        print(f"❌ GUI启动失败: {gui_error}")
        print("🔧 尝试仅启动Flask Web服务...")
        
        # 如果GUI启动失败，至少启动Flask服务
        try:
            print(f"🌐 Flask服务将在 http://127.0.0.1:9682 运行")
            print("💡 请在浏览器中手动打开上述地址使用Web界面")
            app.run(
                host='127.0.0.1',
                port=9682, 
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as flask_error:
            print(f"❌ Flask服务启动也失败: {flask_error}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
