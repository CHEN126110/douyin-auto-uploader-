import logging
import os
import json
from ruamel.yaml import YAML
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from .runtime_paths import resolve_data_file

default = "\nbase:\n  name: 抖音袜子发布工具\n  version: 4.0.0\n  access_token: ''\n"

PLATFORM_MATERIAL_OPTIONS = [
    '棉',
    '氨纶',
    '锦纶',
    '聚酯纤维',
    '涤纶',
    '粘纤',
    '莫代尔',
    '腈纶',
    '羊毛',
    '兔毛',
    '桑蚕丝',
    '再生纤维素纤维'
]


class Config():
    '"""Config类.\n"""'

    def __init__(self, file: str, data: str = default) -> None:
        '"""__init__函数.\n\n:param args:\n:param kwargs:\n:return:\n"""'
        self.factory = YAML()
        legacy_path = file if os.path.isabs(file) else file
        self.file = str(resolve_data_file(file, legacy_fallback=legacy_path))
        self.data = self.factory.load(data)
        (self.load() if os.path.exists(self.file) else self.dump())

    def load(self) -> None:
        '"""load函数.\n\n:param args:\n:param kwargs:\n:return:\n"""'
        with open(self.file, 'r', encoding='utf-8') as f:
            self.data = self.factory.load(f)

    def dump(self) -> None:
        '"""dump函数.\n\n:param args:\n:param kwargs:\n:return:\n"""'
        path = os.path.dirname(self.file)
        if path:
            os.makedirs(path, exist_ok=True)
        with open(self.file, 'w', encoding='utf-8') as f:
            self.factory.dump(self.data, f)


@dataclass
class ImageNamingSettings:
    """图片命名设置"""
    # 支持的图片格式
    supported_formats: Optional[List[str]] = None
    # 图片名称过滤规则
    name_filters: Optional[List[str]] = None
    # 是否忽略大小写
    ignore_case: bool = True
    
    def __post_init__(self):
        if self.supported_formats is None:
            self.supported_formats = ['.jpg', '.jpeg', '.png', '.bmp', '.webp']
        if self.name_filters is None:
            self.name_filters = []


@dataclass
class UISettings:
    """界面设置"""
    # 是否启用悬浮大图
    enable_image_hover: bool = True
    # 悬浮图片大小
    hover_image_size: int = 400
    # 悬浮延迟时间(毫秒)
    hover_delay: int = 300
    # 主题模式 (light/dark/auto)
    theme_mode: str = "light"
    # 是否启用动画效果
    enable_animations: bool = True


@dataclass
class ProcessingSettings:
    """处理设置"""
    # 自动识别ID类型文件夹
    auto_detect_id_folders: bool = True
    # 批量处理模式
    batch_processing_mode: bool = False
    # 最大并发处理数
    max_concurrent_tasks: int = 3


@dataclass
class PricingConfig:
    """定价配置"""
    target_gross_margin: float = 30  # 目标毛利率（百分比，如30表示30%）


@dataclass
class CostItem:
    """成本项目"""
    id: str = ""
    name: str = ""
    cost_type: str = "fixed"  # fixed | per_unit | percentage
    value: float = 0
    description: str = ""


@dataclass
class AutomationConfig:
    """自动化配置"""
    shipping_template: str = "中通包邮"  # 当前选中的运费模板
    shipping_templates: Optional[List[str]] = None  # 运费模板列表
    material_compositions: Optional[List[Dict[str, Any]]] = None
    material_options: Optional[List[str]] = None
    qualification_certificate_path: Optional[str] = None
    
    def __post_init__(self):
        if self.shipping_templates is None:
            self.shipping_templates = ["中通包邮"]
        if self.material_compositions is None:
            self.material_compositions = [
                {"material": "棉", "percentage": 75},
                {"material": "氨纶", "percentage": 25},
            ]
        if self.material_options is None:
            self.material_options = list(PLATFORM_MATERIAL_OPTIONS)
        if self.qualification_certificate_path:
            self.qualification_certificate_path = str(self.qualification_certificate_path).strip() or None


@dataclass
class UserSettings:
    """用户设置总配置"""
    image_naming: Optional[ImageNamingSettings] = None
    ui_settings: Optional[UISettings] = None
    processing: Optional[ProcessingSettings] = None
    pricing_config: Optional[Dict[str, Any]] = None  # 定价配置
    cost_items: Optional[List[Dict[str, Any]]] = None  # 成本项目列表
    model_configs: Optional[List[Dict[str, Any]]] = None  # 模型配置
    automation_config: Optional[Dict[str, Any]] = None  # 自动化配置
    
    def __post_init__(self):
        if self.image_naming is None:
            self.image_naming = ImageNamingSettings()
        if self.ui_settings is None:
            self.ui_settings = UISettings()
        if self.processing is None:
            self.processing = ProcessingSettings()
        if self.pricing_config is None:
            self.pricing_config = {'target_gross_margin': 30}
        if self.cost_items is None:
            self.cost_items = [
                {'id': '1', 'name': '单双成本', 'cost_type': 'per_unit', 'value': 0, 'description': '每双袜子基础成本'},
                {'id': '2', 'name': '运费', 'cost_type': 'fixed', 'value': 3, 'description': '固定运费'},
                {'id': '3', 'name': '包装费', 'cost_type': 'fixed', 'value': 0.5, 'description': '包装材料成本'},
                {'id': '4', 'name': '平台佣金', 'cost_type': 'percentage', 'value': 5, 'description': '平台抽成百分比'}
            ]
        if self.model_configs is None:
            self.model_configs = []
        if self.automation_config is None:
            self.automation_config = {
                'shipping_template': '中通包邮',
                'shipping_templates': ['中通包邮'],
                'material_compositions': [
                    {'material': '棉', 'percentage': 75},
                    {'material': '氨纶', 'percentage': 25}
                ],
                'material_options': list(PLATFORM_MATERIAL_OPTIONS),
                'qualification_certificate_path': None,
            }


class SettingsManager:
    """设置管理器"""
    
    def __init__(self, settings_file='user_settings.json'):
        legacy_path = settings_file if os.path.isabs(settings_file) else settings_file
        self.settings_file = str(resolve_data_file(settings_file, legacy_fallback=legacy_path))
        self.settings = self.load_settings()

    @staticmethod
    def normalize_automation_config(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        default_config = {
            'shipping_template': '中通包邮',
            'shipping_templates': ['中通包邮'],
            'material_compositions': [
                {'material': '棉', 'percentage': 75},
                {'material': '氨纶', 'percentage': 25}
            ],
            'material_options': list(PLATFORM_MATERIAL_OPTIONS),
            'qualification_certificate_path': None,
        }
        if not isinstance(data, dict):
            return default_config

        shipping_templates = data.get('shipping_templates')
        if not isinstance(shipping_templates, list) or len(shipping_templates) == 0:
            shipping_templates = default_config['shipping_templates']
        shipping_templates = [str(item).strip() for item in shipping_templates if str(item).strip()]
        if len(shipping_templates) == 0:
            shipping_templates = default_config['shipping_templates']

        shipping_template = str(data.get('shipping_template') or '').strip()
        if not shipping_template:
            shipping_template = shipping_templates[0]
        if shipping_template not in shipping_templates:
            shipping_templates.append(shipping_template)

        material_options = data.get('material_options')
        if isinstance(material_options, list) and len(material_options) > 0:
            material_options = [
                str(item).strip()
                for item in material_options
                if str(item).strip() in default_config['material_options']
            ]
        else:
            material_options = list(default_config['material_options'])
        if len(material_options) == 0:
            material_options = list(default_config['material_options'])

        option_set = set(material_options)
        materials = data.get('material_compositions')
        normalized_materials = []
        if isinstance(materials, list):
            for item in materials:
                if not isinstance(item, dict):
                    continue
                material = str(item.get('material') or '').strip()
                try:
                    percentage = int(float(item.get('percentage')))
                except Exception:
                    percentage = 0
                if material and material in option_set and percentage > 0:
                    normalized_materials.append({'material': material, 'percentage': percentage})
        if len(normalized_materials) == 0:
            normalized_materials = default_config['material_compositions']

        qualification_certificate_path = str(data.get('qualification_certificate_path') or '').strip() or None

        return {
            'shipping_template': shipping_template,
            'shipping_templates': shipping_templates,
            'material_compositions': normalized_materials,
            'material_options': material_options,
            'qualification_certificate_path': qualification_certificate_path,
        }
    
    def load_settings(self) -> UserSettings:
        """加载设置"""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 转换为dataclass对象
                image_naming = ImageNamingSettings(**data.get('image_naming', {}))
                ui_settings = UISettings(**data.get('ui_settings', {}))
                processing = ProcessingSettings(**data.get('processing', {}))
                
                # 加载定价相关配置
                pricing_config = data.get('pricing_config')
                cost_items = data.get('cost_items')
                model_configs = data.get('model_configs')
                automation_config = data.get('automation_config')
                automation_config = self.normalize_automation_config(automation_config)
                
                print(f"[Config] 加载设置 - pricing_config: {pricing_config}, cost_items: {len(cost_items) if cost_items else 0}个")
                
                return UserSettings(
                    image_naming=image_naming,
                    ui_settings=ui_settings,
                    processing=processing,
                    pricing_config=pricing_config,
                    cost_items=cost_items,
                    model_configs=model_configs,
                    automation_config=automation_config
                )
            except Exception as e:
                print(f"加载设置失败: {e}")
                return UserSettings()
        else:
            return UserSettings()
    
    def save_settings(self, settings: Optional[UserSettings] = None):
        """保存设置"""
        if settings:
            self.settings = settings
        
        try:
            data = {
                'image_naming': asdict(self.settings.image_naming) if self.settings.image_naming else {},
                'ui_settings': asdict(self.settings.ui_settings) if self.settings.ui_settings else {},
                'processing': asdict(self.settings.processing) if self.settings.processing else {},
                'pricing_config': self.settings.pricing_config,
                'cost_items': self.settings.cost_items,
                'model_configs': self.settings.model_configs,
                'automation_config': self.settings.automation_config
            }
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            return True
        except Exception as e:
            print(f"保存设置失败: {e}")
            return False
    
    def get_settings(self) -> UserSettings:
        """获取当前设置"""
        return self.settings
    
    def update_settings(self, settings_dict: Dict[str, Any]) -> bool:
        """更新设置"""
        try:
            # 更新图片命名设置
            if 'image_naming' in settings_dict:
                for key, value in settings_dict['image_naming'].items():
                    if hasattr(self.settings.image_naming, key):
                        setattr(self.settings.image_naming, key, value)
            
            # 更新UI设置
            if 'ui_settings' in settings_dict:
                for key, value in settings_dict['ui_settings'].items():
                    if hasattr(self.settings.ui_settings, key):
                        setattr(self.settings.ui_settings, key, value)
            
            # 更新处理设置
            if 'processing' in settings_dict:
                for key, value in settings_dict['processing'].items():
                    if hasattr(self.settings.processing, key):
                        setattr(self.settings.processing, key, value)
            
            # 更新定价配置
            if 'pricing_config' in settings_dict:
                self.settings.pricing_config = settings_dict['pricing_config']
                print(f"[Config] 更新定价配置: {self.settings.pricing_config}")
            
            # 更新成本项目
            if 'cost_items' in settings_dict:
                self.settings.cost_items = settings_dict['cost_items']
                print(f"[Config] 更新成本项目: {len(self.settings.cost_items)} 个")
            
            # 更新模型配置
            if 'model_configs' in settings_dict:
                self.settings.model_configs = settings_dict['model_configs']
                print(f"[Config] 更新模型配置: {len(self.settings.model_configs)} 个")
            
            # 更新自动化配置
            if 'automation_config' in settings_dict:
                self.settings.automation_config = self.normalize_automation_config(settings_dict['automation_config'])
                print(f"[Config] 更新自动化配置: {self.settings.automation_config}")
            
            return self.save_settings()
        except Exception as e:
            print(f"更新设置失败: {e}")
            return False
    
    def reset_to_defaults(self) -> bool:
        """重置为默认设置"""
        self.settings = UserSettings()
        return self.save_settings()


# 全局设置管理器实例
settings_manager = SettingsManager()
