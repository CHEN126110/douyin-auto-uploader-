import logging
import os
import json
from ruamel.yaml import YAML
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from .runtime_paths import resolve_data_file

default = "\nbase:\n  name: 抖音袜子发布工具\n  version: 4.0.0\n  access_token: ''\n"

# 材质名称长度上限（防脏数据写入配置；平台真实材质名远短于此）
MATERIAL_NAME_MAX_LENGTH = 40

# 初始默认材质选项。**不再作为白名单**——用户可自定义输入，
# 也可由发布流程从平台实时采集后覆盖（见 material_options）。
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


# 发布信息优化允许接入的 LLM 厂商（仅用于标题/属性/卖点优化；
# 运营决策 ops 仍只用本地规则，见 ops_engine.AI_POLICY，经营数据不外泄）。
ALLOWED_PUBLISH_AI_PROVIDERS = ('deepseek', 'xiaomi')

# 厂商预设：base_url / 可选模型。多数国产大模型提供 OpenAI 兼容接口。
# 小米大模型对外端点未官方确认，base_url 留空由用户在设置中填写（按小米开放平台实际端点）。
LLM_PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    'deepseek': {
        'label': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'models': ['deepseek-chat', 'deepseek-reasoner'],
        'openai_compatible': True,
    },
    'xiaomi': {
        'label': '小米大模型(MiMo)',
        # 小米 MiMo 开放平台，OpenAI 兼容（实证 https://api.xiaomimimo.com/v1/chat/completions 返回标准 401）
        'base_url': 'https://api.xiaomimimo.com/v1',
        'models': ['mimo-v2.5-pro', 'mimo-v2.5-pro-ultraspeed'],
        'openai_compatible': True,
    },
}


def external_ai_policy() -> Dict[str, Any]:
    """运营决策(ops)的 AI 政策：仍只用本地规则，不调外部 AI，经营数据不外泄。
    注意：发布信息优化的 LLM 接入是独立开关，见 ALLOWED_PUBLISH_AI_PROVIDERS。"""
    return {
        'external_ai_disabled': True,
        'decision_source': 'codex_only',
        'scope': 'ops_decision_only',
        'blocked_providers': ['openai', 'ollama', 'claude', 'third_party'],
        'publish_ai_providers_allowed': list(ALLOWED_PUBLISH_AI_PROVIDERS),
    }


def sanitize_model_configs(configs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """仅保留发布优化允许厂商(小米/DeepSeek)且字段合法的模型配置；过滤其它厂商。
    运营决策(ops)不读取这些配置。"""
    if not isinstance(configs, list):
        return []
    out: List[Dict[str, Any]] = []
    for c in configs:
        if not isinstance(c, dict):
            continue
        provider = str(c.get('provider') or '').strip().lower()
        if provider not in ALLOWED_PUBLISH_AI_PROVIDERS:
            continue
        preset = LLM_PROVIDER_PRESETS.get(provider, {})
        api_key = str(c.get('api_key') or '').strip()
        # 兼容前端字段名(api_base/model_name)与后端字段名(base_url/model)
        base_url = str(c.get('base_url') or c.get('api_base') or preset.get('base_url') or '').strip().rstrip('/')
        preset_models = preset.get('models') or []
        model = str(c.get('model') or c.get('model_name') or '').strip() or (preset_models[0] if preset_models else '')
        name = str(c.get('name') or preset.get('label') or provider)
        enabled = bool(c.get('enabled', True)) and bool(api_key) and bool(base_url)
        out.append({
            'id': str(c.get('id') or provider),
            'name': name,
            'provider': provider,
            'label': str(c.get('label') or preset.get('label') or provider),
            'api_key': api_key,
            # 同时输出两套字段名，前端读 api_base/model_name，后端用 base_url/model
            'base_url': base_url,
            'api_base': base_url,
            'model': model,
            'model_name': model,
            'enabled': enabled,
        })
    return out


def default_automation_config() -> Dict[str, Any]:
    return {
        'shipping_template': '中通包邮',
        'shipping_templates': ['中通包邮'],
        'material_compositions': [
            {'material': '棉', 'percentage': 75},
            {'material': '氨纶', 'percentage': 25}
        ],
        'material_options': list(PLATFORM_MATERIAL_OPTIONS),
        'wash_label_tag_image_path': None,
        'qualification_certificate_path': None,
        'runtime_category_keyword': None,
        'runtime_matrix_keywords': None,
        # 提交模式：publish = 直接提交上架，stop = 全部填好后停下不提交
        'publish_submit_mode': 'publish',
    }


def resolve_publish_submit_mode(configured: Optional[str]) -> str:
    """解析提交模式：'publish' 直接提交上架，'stop' 全部填好后停下不提交。

    这里不按「是不是打包产物」自动切换。本项目的开发命令是
    `tauri dev -- --release`，Rust 按 release 编译、sidecar 用的也是冻结后的
    python-backend.exe，所以 `sys.frozen` 在日常开发时同样为真，
    拿它区分开发与正式安装只会得出错误结论。提交与否由用户显式配置决定。

    历史配置里的 'auto' 按直接发布处理，保持升级后行为与设置界面一致。
    """
    mode = str(configured or '').strip().lower()
    return 'stop' if mode == 'stop' else 'publish'


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
    wash_label_tag_image_path: Optional[str] = None
    qualification_certificate_path: Optional[str] = None
    runtime_category_keyword: Optional[str] = None
    runtime_matrix_keywords: Optional[str] = None
    publish_mode: str = "dom"  # "protocol" | "official" | "dom"
    capture_mode: str = "dom"  # "protocol" | "dom" — 采集方式
    publish_submit_mode: str = "publish"  # "publish" 直接提交上架 | "stop" 填好后停下不提交

    def __post_init__(self):
        defaults = default_automation_config()
        if self.shipping_templates is None:
            self.shipping_templates = list(defaults['shipping_templates'])
        if self.material_compositions is None:
            self.material_compositions = list(defaults['material_compositions'])
        if self.material_options is None:
            self.material_options = list(defaults['material_options'])
        if self.wash_label_tag_image_path:
            self.wash_label_tag_image_path = str(self.wash_label_tag_image_path).strip() or None
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
        else:
            self.model_configs = sanitize_model_configs(self.model_configs)
        if self.automation_config is None:
            self.automation_config = default_automation_config()


class SettingsManager:
    """设置管理器"""
    
    def __init__(self, settings_file='user_settings.json'):
        legacy_path = settings_file if os.path.isabs(settings_file) else settings_file
        self.settings_file = str(resolve_data_file(settings_file, legacy_fallback=legacy_path))
        self.settings = self.load_settings()

    @staticmethod
    def normalize_automation_config(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        default_config = default_automation_config()
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

        # 材质选项不再按内置白名单过滤：平台会持续新增面料，
        # 写死白名单会把「从平台拉取的新材质」和「用户自定义材质」一起静默丢掉。
        # 这里只做去空白/去重/长度保护，PLATFORM_MATERIAL_OPTIONS 退化为初始默认值。
        material_options = data.get('material_options')
        if isinstance(material_options, list) and len(material_options) > 0:
            seen = set()
            cleaned_options = []
            for item in material_options:
                name = str(item).strip()
                if not name or len(name) > MATERIAL_NAME_MAX_LENGTH or name in seen:
                    continue
                seen.add(name)
                cleaned_options.append(name)
            material_options = cleaned_options
        else:
            material_options = list(default_config['material_options'])
        if len(material_options) == 0:
            material_options = list(default_config['material_options'])

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
                # 允许自定义材质：不再要求命中 material_options，
                # 名称是否被平台接受由发布流程在真实页面上校验并报错。
                if material and len(material) <= MATERIAL_NAME_MAX_LENGTH and percentage > 0:
                    normalized_materials.append({'material': material, 'percentage': percentage})
        if len(normalized_materials) == 0:
            normalized_materials = default_config['material_compositions']

        wash_label_tag_image_path = str(data.get('wash_label_tag_image_path') or '').strip() or None
        qualification_certificate_path = str(data.get('qualification_certificate_path') or '').strip() or None
        runtime_category_keyword = str(data.get('runtime_category_keyword') or '').strip() or None
        runtime_matrix_keywords = str(data.get('runtime_matrix_keywords') or '').strip() or None
        if not wash_label_tag_image_path and qualification_certificate_path:
            # 历史版本只有合格证图片入口，用户可能已把水洗标/吊牌图配置在该字段中。
            wash_label_tag_image_path = qualification_certificate_path

        # 采集偏好：分平台独立保存。1688 和 淘宝/天猫 是两个独立平台，采集协议互不交叉。
        legacy_capture_mode = str(data.get('capture_mode') or 'dom').strip().lower()
        if legacy_capture_mode not in ('dom', 'protocol'):
            legacy_capture_mode = 'dom'

        raw_prefs = data.get('capture_preferences')
        if not isinstance(raw_prefs, dict):
            raw_prefs = {}

        def _normalize_mode(value: Any, fallback: str) -> str:
            v = str(value or '').strip().lower()
            return v if v in ('dom', 'protocol') else fallback

        capture_preferences = {
            'alibaba_1688_mode': _normalize_mode(raw_prefs.get('alibaba_1688_mode'), legacy_capture_mode),
            'taobao_tmall_mode': _normalize_mode(raw_prefs.get('taobao_tmall_mode'), legacy_capture_mode),
        }

        # 提交模式：只决定「走到提交前停下」还是「真实提交上架」。
        publish_submit_mode = resolve_publish_submit_mode(data.get('publish_submit_mode'))

        return {
            'shipping_template': shipping_template,
            'shipping_templates': shipping_templates,
            'material_compositions': normalized_materials,
            'material_options': material_options,
            'wash_label_tag_image_path': wash_label_tag_image_path,
            'qualification_certificate_path': qualification_certificate_path,
            'runtime_category_keyword': runtime_category_keyword,
            'runtime_matrix_keywords': runtime_matrix_keywords,
            'publish_mode': str(data.get('publish_mode') or 'dom').strip(),
            # 旧字段：保留兼容，新调用方应使用 capture_preferences 分平台读取
            'capture_mode': legacy_capture_mode,
            'capture_preferences': capture_preferences,
            'publish_submit_mode': publish_submit_mode,
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
                model_configs = sanitize_model_configs(data.get('model_configs'))
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
                self.settings.model_configs = sanitize_model_configs(settings_dict['model_configs'])
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
