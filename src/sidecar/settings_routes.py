# -*- coding: utf-8 -*-
"""用户设置接口（/settings*）：读取 / 保存 / 重置设置、发布模式、水洗标 / 吊牌图管理。"""
import os
import shutil
import traceback

from flask import Blueprint, request, send_file

from src.config import (
    LLM_PROVIDER_PRESETS,
    MATERIAL_NAME_MAX_LENGTH,
    resolve_publish_submit_mode,
    settings_manager,
)
from src.ops_engine import enforce_no_external_ai_settings
from .responses import api_error, api_ok


_AUTOMATION_ASSETS_DIR_NAME = 'automation_assets'
_WASH_LABEL_TAG_IMAGE_BASENAME = 'wash_label_tag_image'
_ALLOWED_AUTOMATION_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def _is_path_within_dir(path_value, directory):
    try:
        resolved_path = os.path.abspath(path_value)
        resolved_dir = os.path.abspath(directory)
        return os.path.commonpath([resolved_path, resolved_dir]) == resolved_dir
    except Exception:
        return False


def _settings_to_payload(settings, automation_config: dict) -> dict:
    """把 UserSettings 拍平成设置接口回传的字段结构。

    `get_settings` 和 `reset_settings` 各写过一份，字段逐字相同。这里只收敛「拍平」这一步：
    两边后续的净化并不一样——`get_settings` 还会过 `enforce_no_external_ai_settings`
    并屏蔽 model_configs 里的 api_key 明文，`reset_settings` 没有。保持原样，不在这里顺手改。
    """
    return {
        'pricing_config': settings.pricing_config,
        'cost_items': settings.cost_items,
        'model_configs': settings.model_configs,
        'automation_config': automation_config,
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
        },
    }


def create_settings_blueprint(*, get_runtime_data_path):
    """``get_runtime_data_path`` 由应用入口注入：它决定设置与素材落在哪个数据目录。"""
    routes = Blueprint('settings', __name__)

    def _get_automation_assets_dir():
        assets_dir = get_runtime_data_path(_AUTOMATION_ASSETS_DIR_NAME)
        os.makedirs(assets_dir, exist_ok=True)
        return assets_dir

    def _delete_managed_automation_image_files(base_name):
        assets_dir = _get_automation_assets_dir()
        for file_name in os.listdir(assets_dir):
            if not file_name.startswith(f'{base_name}.'):
                continue
            file_path = os.path.join(assets_dir, file_name)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception:
                continue

    def _resolve_managed_automation_image_path(source_path, base_name, label):
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in _ALLOWED_AUTOMATION_IMAGE_EXTENSIONS:
            raise ValueError(f'仅支持 jpg、jpeg、png、bmp、webp 格式的{label}')
        file_name = f'{base_name}{extension}'
        return os.path.join(_get_automation_assets_dir(), file_name)

    def _delete_managed_wash_label_tag_image_files():
        _delete_managed_automation_image_files(_WASH_LABEL_TAG_IMAGE_BASENAME)

    def _resolve_managed_wash_label_tag_image_path(source_path):
        return _resolve_managed_automation_image_path(source_path, _WASH_LABEL_TAG_IMAGE_BASENAME, '水洗标/吊牌图')

    @routes.get('/settings')
    def get_settings():
        """获取用户设置"""
        try:
            settings = settings_manager.get_settings()
            automation_config = settings_manager.normalize_automation_config(settings.automation_config)

            # 材质选项以「平台实采列表」为准：发布流程打开材质下拉时会顺带采集并缓存。
            # 缓存缺失（还没发过货）时退回内置默认，下拉本身支持自定义输入，不会卡住用户。
            material_meta = {}
            try:
                from src.material_options_cache import load_meta, load_options
                platform_options = load_options()
                material_meta = load_meta()
                if platform_options:
                    merged = list(platform_options)
                    seen = set(merged)
                    for name in (automation_config.get('material_options') or []):
                        if name not in seen:
                            seen.add(name)
                            merged.append(name)
                    automation_config = dict(automation_config)
                    automation_config['material_options'] = merged
            except Exception as exc:
                material_meta = {'last_error': f'读取平台材质缓存失败: {exc}'}
            automation_config = dict(automation_config)
            automation_config['platform_material_options_meta'] = material_meta
            automation_config['publish_submit_mode_effective'] = resolve_publish_submit_mode(
                automation_config.get('publish_submit_mode')
            )

            sanitized_settings = enforce_no_external_ai_settings(
                _settings_to_payload(settings, automation_config)
            )
            # 发布优化模型配置允许保留(仅小米/DeepSeek)，覆盖 ops 净化对它的清空；
            # 回传时隐藏 api_key 明文，只标记是否已配置，避免密钥随设置接口外泄。
            masked_configs = []
            for cfg in (settings.model_configs or []):
                c = dict(cfg)
                c['api_key_set'] = bool(c.get('api_key'))
                c.pop('api_key', None)
                masked_configs.append(c)
            sanitized_settings['model_configs'] = masked_configs
            sanitized_settings['llm_provider_presets'] = LLM_PROVIDER_PRESETS
            return api_ok(msg='获取设置成功', data={'settings': sanitized_settings})
        except Exception as e:
            return api_error(f'获取设置失败: {str(e)}')

    @routes.post('/settings')
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

            if 'pricing_config' in data:
                backend_data['pricing_config'] = data.get('pricing_config')

            if 'cost_items' in data:
                backend_data['cost_items'] = data.get('cost_items')

            if 'model_configs' in data:
                # 发布优化模型配置：交由 config.sanitize_model_configs 校验(仅放行小米/DeepSeek)。
                # 前端未改密钥时可传 api_key_set 占位，此处与已存配置做合并保留旧密钥。
                incoming = data.get('model_configs') or []
                existing = {c.get('id'): c for c in (settings_manager.get_settings().model_configs or [])}
                merged = []
                for c in incoming:
                    if not isinstance(c, dict):
                        continue
                    c = dict(c)
                    # 未提交新密钥(只回传占位)时，沿用已存密钥
                    if not c.get('api_key') and c.get('id') in existing:
                        c['api_key'] = existing[c['id']].get('api_key', '')
                    merged.append(c)
                backend_data['model_configs'] = merged

            if 'automation_config' in data:
                automation_config = data.get('automation_config') or {}
                normalized_automation = settings_manager.normalize_automation_config(automation_config)
                material_compositions = automation_config.get('material_compositions') or []
                if isinstance(material_compositions, list) and len(material_compositions) > 0:
                    total_percentage = 0.0
                    for item in material_compositions:
                        if not isinstance(item, dict):
                            continue
                        material_name = str(item.get('material') or '').strip()
                        # 允许自定义材质：平台会持续新增面料，按内置白名单拒绝会把新材质挡在外面。
                        # 这里只校验名称非空与长度，名称能否被平台接受由发布流程在真实页面上校验并报错。
                        if not material_name:
                            return api_error('材质名称不能为空')
                        if len(material_name) > MATERIAL_NAME_MAX_LENGTH:
                            return api_error(f'材质名称过长（上限 {MATERIAL_NAME_MAX_LENGTH} 字）：{material_name[:20]}…')
                        try:
                            total_percentage += float(item.get('percentage', 0) or 0)
                        except (TypeError, ValueError):
                            continue
                    if abs(total_percentage - 100.0) > 0.000001:
                        return api_error('材质面料含量总和必须等于100')
                backend_data['automation_config'] = normalized_automation
        
            if settings_manager.update_settings(backend_data):
                return api_ok(msg='设置保存成功')
            else:
                return api_error('设置保存失败')
        except Exception as e:
            return api_error(f'设置更新失败: {str(e)}')

    @routes.post('/settings/automation/wash-label/import')
    def import_automation_wash_label_tag_image():
        """导入自动化设置中的水洗标/吊牌图到应用数据目录"""
        try:
            data = request.get_json(silent=True) or {}
            source_path = os.path.abspath(str(data.get('source_path') or '').strip())
            if not source_path:
                return api_error('缺少水洗标/吊牌图路径')
            if not os.path.isfile(source_path):
                return api_error('水洗标/吊牌图不存在')

            try:
                target_path = _resolve_managed_wash_label_tag_image_path(source_path)
            except ValueError as exc:
                return api_error(str(exc))

            _delete_managed_wash_label_tag_image_files()
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)

            return api_ok(msg='水洗标/吊牌图导入成功', data={
                'stored_path': target_path,
                'file_name': os.path.basename(target_path),
            })
        except Exception as e:
            traceback.print_exc()
            return api_error(f'导入水洗标/吊牌图失败: {str(e)}')

    @routes.get('/settings/automation/wash-label/preview')
    def preview_automation_wash_label_tag_image():
        """返回当前配置的水洗标/吊牌图文件"""
        try:
            user_settings = settings_manager.get_settings()
            ac = settings_manager.normalize_automation_config(user_settings.automation_config)
            img_path = str(ac.get('wash_label_tag_image_path') or '').strip()
            if not img_path or not os.path.isfile(img_path):
                return '', 404
            return send_file(img_path)
        except Exception:
            return '', 404

    @routes.post('/settings/automation/wash-label/remove')
    def remove_automation_wash_label_tag_image():
        """删除自动化设置中的水洗标/吊牌图"""
        try:
            data = request.get_json(silent=True) or {}
            stored_path = os.path.abspath(str(data.get('stored_path') or '').strip()) if data.get('stored_path') else ''
            assets_dir = _get_automation_assets_dir()

            if stored_path:
                if not _is_path_within_dir(stored_path, assets_dir):
                    return api_error('只能删除应用数据目录中的水洗标/吊牌图')
                if os.path.isfile(stored_path):
                    os.remove(stored_path)
            else:
                _delete_managed_wash_label_tag_image_files()

            return api_ok(msg='水洗标/吊牌图已删除')
        except Exception as e:
            traceback.print_exc()
            return api_error(f'删除水洗标/吊牌图失败: {str(e)}')

    @routes.route('/settings/publish-mode', methods=['GET', 'POST'])
    def publish_mode():
        """获取或设置发布模式: protocol / official / dom"""
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            mode = str(data.get('publish_mode', 'dom')).strip().lower()
            if mode not in ('protocol', 'official', 'dom'):
                return api_error(msg=f'无效的发布模式: {mode}，可选值: protocol, official, dom')
            user_settings = settings_manager.get_settings()
            ac = settings_manager.normalize_automation_config(user_settings.automation_config)
            ac['publish_mode'] = mode
            user_settings.automation_config = ac
            settings_manager.save_settings(user_settings)
            return api_ok(msg=f'发布模式已设为: {mode}', data={'publish_mode': mode})
        else:
            user_settings = settings_manager.get_settings()
            ac = settings_manager.normalize_automation_config(user_settings.automation_config)
            mode = ac.get('publish_mode', 'dom')
            return api_ok(msg='获取发布模式', data={'publish_mode': mode})

    @routes.post('/settings/reset')
    def reset_settings():
        """重置为默认设置"""
        try:
            if settings_manager.reset_to_defaults():
                settings = settings_manager.get_settings()
                automation_config = settings_manager.normalize_automation_config(settings.automation_config)
                return api_ok(msg='设置已重置为默认值', data={
                    'settings': _settings_to_payload(settings, automation_config)
                })
            else:
                return api_error('重置设置失败')
        except Exception as e:
            return api_error(f'重置设置失败: {str(e)}')

    return routes
