# -*- coding: utf-8 -*-
"""智能定价与成本配置接口（/api/pricing/*）。"""
import json
import os
import time as system_time
import traceback
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from src.config import settings_manager


DEFAULT_PRICING_TEMPLATE = '默认袜子模板'


def _pricing_cost_items(config):
    """取默认模板的成本项列表。"""
    return config.get('templates', {}).get(DEFAULT_PRICING_TEMPLATE, {}).get('base_cost_items', [])


def create_pricing_blueprint(*, record_model, get_runtime_data_path):
    """``get_runtime_data_path`` 由应用入口注入：它决定 pricing_config.json 落在哪个数据目录。"""
    routes = Blueprint('pricing', __name__)
    Record = record_model

    @routes.post('/api/pricing/calculate_smart_prices')
    def calculate_smart_prices():
        """Runtime smart pricing with dynamic unit price."""
        try:
            data = request.get_json(silent=True) or {}
            record_id = data.get('record_id')

            if not record_id:
                return jsonify({'success': False, 'error': 'missing record_id'})

            try:
                unit_price = float(data.get('unit_price', 0) or 0)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'invalid unit_price'})

            if unit_price <= 0:
                return jsonify({'success': False, 'error': 'unit_price must be greater than 0'})

            try:
                profit_margin = float(data.get('profit_margin', 0) or 0)
            except (TypeError, ValueError):
                profit_margin = 0.0

            record = Record.get_or_none(Record.id == int(record_id))
            if not record:
                return jsonify({'success': False, 'error': 'record not found'})

            sku_list = json.loads(record.content) if record.content else []
            if not sku_list:
                return jsonify({'success': False, 'error': 'sku list is empty'})

            default_cost_items = [
                {'name': '运费', 'cost_type': 'fixed', 'value': 3},
                {'name': '包装费', 'cost_type': 'fixed', 'value': 0.5},
                {'name': '平台佣金', 'cost_type': 'percentage', 'value': 5},
            ]
            default_pricing_config = {'target_gross_margin': 30}

            pricing_config = dict(default_pricing_config)
            cost_items = list(default_cost_items)

            if settings_manager is not None:
                try:
                    user_settings = settings_manager.get_settings()
                    if getattr(user_settings, 'pricing_config', None):
                        pricing_config = dict(user_settings.pricing_config)
                    if getattr(user_settings, 'cost_items', None):
                        cost_items = list(user_settings.cost_items)
                except Exception as settings_error:
                    print(f'failed to load pricing settings, using defaults: {settings_error}')

            if profit_margin > 0:
                pricing_config['target_gross_margin'] = profit_margin if profit_margin > 1 else profit_margin * 100

            from src.smart_pricing_engine import SmartPricingEngine

            config_file = get_runtime_data_path('pricing_config.json')
            engine = SmartPricingEngine(config_file)
            pricing_data = engine.calculate_runtime_pricing(
                sku_list=sku_list,
                unit_price=unit_price,
                pricing_config=pricing_config,
                cost_items=cost_items,
            )

            pricing_results = pricing_data.get('pricing_results', [])
            if not pricing_results:
                return jsonify({'success': False, 'error': 'no pricing results returned'})

            statistics = pricing_data.get('statistics', {})
            config_used = pricing_data.get('config_used', {})
            print(
                f"smart pricing finished: skus={statistics.get('total_skus', 0)}, "
            f"unit_price={unit_price:.2f}, avg_price={statistics.get('average_price', 0):.2f}, "
            f"avg_margin={statistics.get('average_margin', 0):.1f}%"
            )
            print(
                f"pricing config used: target_margin={config_used.get('target_gross_margin', 0)}%, "
            f"fixed={config_used.get('fixed_costs', 0)}, percentage={config_used.get('percentage_costs', 0)}%"
            )

            response_payload = {
                'success': True,
                'message': f"smart pricing finished for {len(pricing_results)} skus",
                'data': pricing_data
            }
            return current_app.response_class(
                response=json.dumps(response_payload, ensure_ascii=False, default=str),
                status=200,
                mimetype='application/json'
            )
        except Exception as e:
            print(f'smart pricing failed: {e}')
            traceback.print_exc()
            response_payload = {
                'success': False,
                'error': f'smart pricing failed: {str(e)}'
            }
            return current_app.response_class(
                response=json.dumps(response_payload, ensure_ascii=False, default=str),
                status=200,
                mimetype='application/json'
            )

    def _load_pricing_config():
        """读取 pricing_config.json；文件不存在时返回 None，由调用方决定补默认结构还是报错。"""
        config_file = get_runtime_data_path('pricing_config.json')
        if not os.path.exists(config_file):
            return None
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_pricing_config(config):
        """打上 last_updated 时间戳后写回 pricing_config.json。"""
        config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        config_file = get_runtime_data_path('pricing_config.json')
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    @routes.post('/api/pricing/cost-config')
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
            config_file = get_runtime_data_path('pricing_config.json')
        
            # 🔧 确保配置目录存在
            config_dir = os.path.dirname(config_file)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
        
            # 读取现有配置
            existing_config = _load_pricing_config()
            if existing_config is None:
                # 如果配置文件不存在，创建一个新的空配置
                existing_config = {}

            # 更新成本配置
            if 'templates' not in existing_config:
                existing_config['templates'] = {}

            if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
                existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {}

            existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['profit_margin'] = target_profit_rate
        
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
                
                    existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['marketing_config'] = validated_marketing
                    print(f"✅ 营销配置已保存: {validated_marketing}")

            # 🔧 添加保存时间戳并保存配置
            _save_pricing_config(existing_config)
            print(f"✅ 配置已保存到: {config_file}")

            # 🔧 验证保存是否成功
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    saved_items = _pricing_cost_items(saved_config)
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
                'details': traceback.format_exc() if current_app.debug else None
            })

    @routes.post('/api/pricing/reload-config')
    def force_reload_pricing_config():
        """配置刷新API（简化版）"""
        try:
            data = request.get_json() or {}
            operation = data.get('operation', 'manual_reload')
        
            current_app.logger.info(f"🔄 收到配置刷新请求: {operation}")
        
            # 🔧 简化：只返回成功状态，不强制重载
            return jsonify({
                'success': True,
                'message': '配置已刷新',
                'operation': operation,
                'reload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        
        except Exception as e:
            current_app.logger.error(f"❌ 配置刷新失败: {e}")
            return jsonify({
                'success': False,
                'error': f'配置刷新失败: {str(e)}'
            }), 500

    @routes.get('/api/pricing/config')
    def get_pricing_config():
        """获取价格配置API"""
        try:
            config = _load_pricing_config()

            if config is None:
                # 返回默认配置
                config = {
                    'templates': {
                        DEFAULT_PRICING_TEMPLATE: {
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

    @routes.post('/api/pricing/cost-item')
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
            existing_config = _load_pricing_config()
            if existing_config is None:
                existing_config = {}

            # 确保配置结构存在
            if 'templates' not in existing_config:
                existing_config['templates'] = {}
            if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
                existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {'base_cost_items': []}

            # 检查是否已存在同名项目
            cost_items = existing_config['templates'][DEFAULT_PRICING_TEMPLATE].get('base_cost_items', [])
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
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items

            # 保存配置
            _save_pricing_config(existing_config)

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

    @routes.put('/api/pricing/cost-item/<item_name>')
    def update_cost_item(item_name):
        """修改单个成本项目API"""
        try:
            data = request.get_json()
        
            # 读取现有配置
            existing_config = _load_pricing_config()
            if existing_config is None:
                return jsonify({'success': False, 'error': '配置文件不存在'})

            # 查找并更新项目
            cost_items = _pricing_cost_items(existing_config)
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
            _save_pricing_config(existing_config)

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

    @routes.delete('/api/pricing/cost-item/<item_name>')
    def delete_cost_item(item_name):
        """删除单个成本项目API"""
        try:
            # 读取现有配置
            existing_config = _load_pricing_config()
            if existing_config is None:
                return jsonify({'success': False, 'error': '配置文件不存在'})

            # 查找并删除项目
            cost_items = _pricing_cost_items(existing_config)
            original_count = len(cost_items)
        
            # 过滤掉要删除的项目
            cost_items = [item for item in cost_items if item['name'] != item_name]
        
            if len(cost_items) == original_count:
                return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
            # 更新配置
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items

            # 保存配置
            _save_pricing_config(existing_config)

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

    @routes.get('/api/pricing/cost-items')
    def get_cost_items():
        """获取成本项目列表API"""
        try:
            config = _load_pricing_config()

            if config is not None:
                cost_items = _pricing_cost_items(config)
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

    @routes.get('/api/pricing/templates')
    def get_pricing_templates():
        """获取所有价格模板API"""
        try:
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

    @routes.post('/api/pricing/profit-margin-config')
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
            existing_config = _load_pricing_config()
            if existing_config is None:
                existing_config = {}

            # 确保配置结构存在
            if 'templates' not in existing_config:
                existing_config['templates'] = {}
            if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
                existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {'base_cost_items': []}

            # 更新毛利率
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['profit_margin'] = profit_margin_decimal

            # 保存配置
            _save_pricing_config(existing_config)

            current_app.logger.info(f"✅ 毛利率已实时保存: {profit_margin}%")
        
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
            current_app.logger.error(error_msg)
            return jsonify({
                'success': False,
                'error': error_msg
            })

    return routes
