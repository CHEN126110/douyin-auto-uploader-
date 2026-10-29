# -*- coding: utf-8 -*-
"""设置 + 定价的新旧对打场景。"""
import os

from scenarios import SCENARIOS, make_records


def _write_inputs(ctx):
    from PIL import Image
    path = os.path.join(ctx.data_dir, 'src_wash.png')
    Image.new('RGB', (8, 8), 'red').save(path)
    ctx.state['wash_src'] = path
    bad = os.path.join(ctx.data_dir, 'not_image.txt')
    with open(bad, 'w', encoding='utf-8') as fp:
        fp.write('x')
    ctx.state['bad_src'] = bad


def setup(ctx):
    make_records(ctx)
    _write_inputs(ctx)


def build_new(ctx):
    from src.sidecar.pricing_routes import create_pricing_blueprint
    from src.sidecar.settings_routes import create_settings_blueprint
    grp = ctx.mod.get_runtime_data_path
    return [create_settings_blueprint(get_runtime_data_path=grp),
            create_pricing_blueprint(record_model=ctx.Record, get_runtime_data_path=grp)]


def _assets(ctx):
    base = os.path.join(ctx.data_dir, 'automation_assets')
    return sorted(os.listdir(base)) if os.path.isdir(base) else None


def requests(ctx):
    wash_src = ctx.state['wash_src']
    bad_src = ctx.state['bad_src']
    comp_ok = [{'material': '棉', 'percentage': 80}, {'material': '氨纶', 'percentage': 20}]
    after_assets = {'after': lambda c: {'assets': _assets(c)}}
    return [
        ('GET', '/settings', None),
        ('POST', '/settings', {
            'image_naming': {'supported_formats': ['jpg'], 'filename_filters': ['a'], 'case_sensitive': True},
            'ui': {'image_hover_enabled': True, 'theme_mode': 'dark', 'animations_enabled': False},
            'processing': {'auto_detect_folders': True, 'batch_mode_enabled': True,
                           'max_concurrent_operations': 3}}),
        ('POST', '/settings', {'pricing_config': {'target_gross_margin': 33},
                               'cost_items': [{'name': '运费', 'cost_type': 'fixed', 'value': 3}]}),
        ('POST', '/settings', {'automation_config': {'material_compositions': comp_ok,
                                                     'material_options': ['棉', '自定义纤维A']}}),
        ('POST', '/settings', {'automation_config': {'material_compositions': [{'material': '', 'percentage': 100}]}}),
        ('POST', '/settings', {'automation_config': {
            'material_compositions': [{'material': 'x' * 200, 'percentage': 100}]}}),
        ('POST', '/settings', {'automation_config': {'material_compositions': [{'material': '棉', 'percentage': 90}]}}),
        ('POST', '/settings', {'model_configs': [
            {'id': 'm1', 'provider': 'deepseek', 'api_key': 'sk-abc', 'model': 'x'}, 'junk']}),
        ('POST', '/settings', {'model_configs': [
            {'id': 'm1', 'provider': 'deepseek', 'api_key_set': True, 'model': 'y'}]}),
        ('GET', '/settings', None),
        ('GET', '/settings/publish-mode', None),
        ('POST', '/settings/publish-mode', {'publish_mode': 'protocol'}),
        ('POST', '/settings/publish-mode', {'publish_mode': 'bogus'}),
        ('GET', '/settings/publish-mode', None),
        ('GET', '/settings/automation/wash-label/preview', None),
        ('POST', '/settings/automation/wash-label/import', {}),
        ('POST', '/settings/automation/wash-label/import', {'source_path': os.path.join(ctx.data_dir, 'missing.png')}),
        ('POST', '/settings/automation/wash-label/import', {'source_path': bad_src}),
        ('POST', '/settings/automation/wash-label/import', {'source_path': wash_src}, after_assets),
        ('POST', '/settings/automation/wash-label/remove', {'stored_path': wash_src}),
        ('POST', '/settings/automation/wash-label/remove', {}, after_assets),
        ('POST', '/settings/reset', {}),
        ('GET', '/settings', None),
        # ---- pricing ----
        ('GET', '/api/pricing/config', None),
        ('GET', '/api/pricing/cost-items', None),
        ('GET', '/api/pricing/templates', None),
        ('POST', '/api/pricing/reload-config', {'operation': 'x'}),
        ('POST', '/api/pricing/cost-config', {}),
        ('POST', '/api/pricing/cost-config', {'cost_items': []}),
        ('POST', '/api/pricing/cost-config', {'cost_items': 'x', 'target_profit_rate': 0.3}),
        ('POST', '/api/pricing/cost-config', {'cost_items': ['x'], 'target_profit_rate': 0.3}),
        ('POST', '/api/pricing/cost-config', {'cost_items': [{'name': 'a'}], 'target_profit_rate': 0.3}),
        ('POST', '/api/pricing/cost-config', {
            'cost_items': [{'name': 'a', 'cost_type': 'bad', 'value': 1, 'description': 'd'}], 'target_profit_rate': 0.3}),
        ('POST', '/api/pricing/cost-config', {
            'cost_items': [{'name': 'a', 'cost_type': 'fixed', 'value': -1, 'description': 'd'}], 'target_profit_rate': 0.3}),
        ('POST', '/api/pricing/cost-config', {
            'cost_items': [{'name': 'a', 'cost_type': 'fixed', 'value': 1, 'description': 'd'}], 'target_profit_rate': 2}),
        ('POST', '/api/pricing/cost-config', {
            'cost_items': [{'name': '运费', 'cost_type': 'fixed', 'value': 3.0, 'description': '运费', 'is_active': True},
                           {'name': '平台费', 'cost_type': 'percentage', 'value': 0.05, 'description': '平台'}],
            'target_profit_rate': 0.32,
            'marketing_pricing': {'enabled': True, 'strategy': 'weird', 'price_range': 'huge', 'show_savings': 1}}),
        ('GET', '/api/pricing/config', None),
        ('GET', '/api/pricing/cost-items', None),
        ('POST', '/api/pricing/cost-item', {'name': '包装费'}),
        ('POST', '/api/pricing/cost-item', {'name': '包装费', 'cost_type': 'bad', 'value': 1, 'description': 'd'}),
        ('POST', '/api/pricing/cost-item', {'name': '包装费', 'cost_type': 'fixed', 'value': -1, 'description': 'd'}),
        ('POST', '/api/pricing/cost-item', {'name': '包装费', 'cost_type': 'fixed', 'value': 0.5, 'description': '包装'}),
        ('POST', '/api/pricing/cost-item', {'name': '包装费', 'cost_type': 'fixed', 'value': 0.5, 'description': '包装'}),
        ('PUT', '/api/pricing/cost-item/包装费', {'value': 0.8, 'description': '新描述', 'is_active': 0}),
        ('PUT', '/api/pricing/cost-item/包装费', {'cost_type': 'bad'}),
        ('PUT', '/api/pricing/cost-item/不存在', {'value': 1}),
        ('DELETE', '/api/pricing/cost-item/不存在', None),
        ('DELETE', '/api/pricing/cost-item/包装费', None),
        ('POST', '/api/pricing/profit-margin-config', {}),
        ('POST', '/api/pricing/profit-margin-config', {'profit_margin': 'x'}),
        ('POST', '/api/pricing/profit-margin-config', {'profit_margin': 150}),
        ('POST', '/api/pricing/profit-margin-config', {'profit_margin': 35}),
        ('GET', '/api/pricing/cost-items', None),
        ('POST', '/api/pricing/calculate_smart_prices', {}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 101}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 101, 'unit_price': 'x'}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 101, 'unit_price': -3}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 999999, 'unit_price': 2}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 102, 'unit_price': 2}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 101, 'unit_price': 2.2, 'profit_margin': 0.4}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 101, 'unit_price': 2.2, 'profit_margin': 'x'}),
        ('POST', '/api/pricing/calculate_smart_prices', {'record_id': 103, 'unit_price': 2.2}),
    ]


def final(ctx):
    out = {}
    for name in ('pricing_config.json', 'user_settings.json'):
        path = os.path.join(ctx.data_dir, name)
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as fp:
                out[name] = fp.read()
        else:
            out[name] = None
    out['assets'] = _assets(ctx)
    return out


SCENARIOS['settings_pricing'] = dict(
    setup=setup,
    patch_old=lambda ctx: None,
    build_new=build_new,
    requests=requests,
    final=final,
)
