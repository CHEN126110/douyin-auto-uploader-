#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
💰 智能价格计算引擎

集成高级数量识别算法，提供智能价格建议。
支持多种SKU格式的数量识别和动态价格计算。
"""

import json
import re
import math
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

@dataclass
class PricingConfig:
    """价格配置数据类"""
    base_cost_per_unit: float = 8.0          # 单位成本（元/双）
    platform_commission: float = 0.06        # 平台佣金率
    shipping_cost: float = 5.0               # 运费（元）
    packaging_cost: float = 1.0              # 包装费（元）
    target_profit_margin: float = 0.30       # 目标利润率
    min_profit_margin: float = 0.15          # 最低利润率
    max_profit_margin: float = 0.50          # 最高利润率

@dataclass
class PricingResult:
    """价格计算结果"""
    sku_name: str                    # SKU名称
    quantity: int                    # 数量
    base_cost: float                 # 基础成本
    total_cost: float               # 总成本
    suggested_price: float          # 建议售价
    profit_margin: float            # 利润率
    competitive_price: float        # 竞争价格
    price_range: Tuple[float, float] # 价格区间（最低，最高）
    calculation_details: Dict[str, Any] # 计算详情
    confidence: float               # 价格建议可信度
    notes: str                      # 备注信息

class AdvancedQuantityExtractor:
    """高级数量提取算法 - 完整版本"""
    
    def extract_quantity(self, sku_name: str) -> Tuple[int, float, str]:
        """
        提取SKU数量
        
        Returns:
            Tuple[int, float, str]: (数量, 置信度, 方法说明)
        """
        sku_name = sku_name.strip()
        
        # 1. 最高优先级：明确的总数量标记
        explicit_result = self._extract_explicit_quantity(sku_name)
        if explicit_result:
            return explicit_result[0], 0.95, f"明确标记: {explicit_result[1]}"
        
        # 2. 特殊模式：X双自选备注
        self_select_result = self._extract_self_select_quantity(sku_name)
        if self_select_result:
            return self_select_result[0], 0.90, f"自选备注: {self_select_result[1]}"
        
        # 3. 组合模式分析
        combination_result = self._extract_combination_quantity(sku_name)
        if combination_result:
            return combination_result[0], 0.85, f"组合模式: {combination_result[1]}"
        
        # 4. 简单数量匹配
        simple_result = self._extract_simple_quantity(sku_name)
        if simple_result:
            return simple_result[0], 0.80, f"简单标记: {simple_result[1]}"
        
        # 5. 默认情况
        return 1, 0.50, "默认值"
    
    def _extract_explicit_quantity(self, sku_name: str) -> Optional[Tuple[int, str]]:
        """提取明确的数量标记"""
        patterns = [
            (r'共(\d+)双', '共X双'),
            (r'(\d+)双装', 'X双装'),
            (r'(\d+)双组合装', 'X双组合装'),
            (r'(\d+)双套装', 'X双套装'),
            (r'(\d+)双混色装', 'X双混色装'),
            (r'(\d+)双礼盒装', 'X双礼盒装'),
            (r'(\d+)双装备注', 'X双装备注'),
            (r'(\d+)双混装', 'X双混装')
        ]
        
        for pattern, desc in patterns:
            match = re.search(pattern, sku_name)
            if match:
                return int(match.group(1)), desc
        
        return None
    
    def _extract_self_select_quantity(self, sku_name: str) -> Optional[Tuple[int, str]]:
        """提取自选备注数量"""
        patterns = [
            (r'(\d+)双自选备注', 'X双自选备注'),
            (r'(\d+)双自选', 'X双自选'),
            (r'(\d+)双可选', 'X双可选'),
            (r'(\d+)双随意选', 'X双随意选')
        ]
        
        for pattern, desc in patterns:
            match = re.search(pattern, sku_name)
            if match:
                return int(match.group(1)), desc
        
        return None
    
    def _extract_combination_quantity(self, sku_name: str) -> Optional[Tuple[int, str]]:
        """提取组合模式数量"""
        # 支持多种分隔符
        separators = ['+', '＋', '/', '，', ',', '、', '|']
        
        for sep in separators:
            if sep in sku_name:
                return self._analyze_combination_with_separator(sku_name, sep)
        
        return None
    
    def _analyze_combination_with_separator(self, sku_name: str, separator: str) -> Optional[Tuple[int, str]]:
        """分析特定分隔符的组合"""
        parts = sku_name.split(separator)
        parts = [part.strip() for part in parts if part.strip()]
        
        if len(parts) <= 1:
            return None
        
        total_quantity = 0
        for part in parts:
            # 尝试提取每部分的数量
            part_quantity = self._extract_part_quantity(part)
            total_quantity += part_quantity
        
        return total_quantity, f"组合分析({separator}分隔)"
    
    def _extract_part_quantity(self, part: str) -> int:
        """提取单个部分的数量"""
        # 模式1: X双Y 或 YX双
        dual_match = re.search(r'(\d+)双', part)
        if dual_match:
            return int(dual_match.group(1))
        
        # 模式2: Y×X 或 Y*X
        multiply_match = re.search(r'[×*×](\d+)', part)
        if multiply_match:
            return int(multiply_match.group(1))
        
        # 模式3: 其他数量表达
        quantity_patterns = [
            r'(\d+)装', r'(\d+)件', r'(\d+)包', 
            r'(\d+)套', r'(\d+)个', r'(\d+)条'
        ]
        
        for pattern in quantity_patterns:
            match = re.search(pattern, part)
            if match:
                return int(match.group(1))
        
        # 默认为1双
        return 1
    
    def _extract_simple_quantity(self, sku_name: str) -> Optional[Tuple[int, str]]:
        """提取简单数量"""
        patterns = [
            (r'(\d+)双', 'X双'),  # 添加对"X双"模式的支持
            (r'(\d+)件', 'X件'),
            (r'(\d+)包', 'X包'),
            (r'(\d+)套', 'X套'),
            (r'(\d+)个', 'X个'),
            (r'(\d+)条', 'X条')
        ]
        
        for pattern, desc in patterns:
            match = re.search(pattern, sku_name)
            if match:
                return int(match.group(1)), desc
        
        return None

class SmartPricingEngine:
    """智能价格计算引擎"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config = self._load_config(config_file)
        self.quantity_extractor = AdvancedQuantityExtractor()
        self.market_data = self._load_market_data()
        
    def _load_config(self, config_file: Optional[str]) -> PricingConfig:
        """加载价格配置"""
        if config_file and Path(config_file).exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 从配置文件中提取默认袜子模板的配置
                template_config = data.get('templates', {}).get('默认袜子模板', {})
                
                # 构建PricingConfig对象
                config = PricingConfig()
                
                # 基础配置
                config.base_cost_per_unit = template_config.get('base_cost', 8.0)
                config.platform_commission = template_config.get('commission', 0.06)
                config.shipping_cost = template_config.get('shipping_cost', 5.0)
                config.packaging_cost = template_config.get('packaging_cost', 1.0)
                config.target_profit_margin = template_config.get('profit_margin', 0.30)
                

                
                # 加载自定义成本项目
                self.custom_cost_items = template_config.get('base_cost_items', [])
                
                print(f"✅ 从配置文件加载配置成功: {len(self.custom_cost_items)}个自定义成本项目")
                return config
                
            except Exception as e:
                print(f"⚠️ 配置文件加载失败: {e}，使用默认配置")
        
        # 使用默认配置
        self.custom_cost_items = []
        return PricingConfig()
    
    def _load_market_data(self) -> Dict[str, Any]:
        """加载市场数据"""
        # 这里可以加载实际的市场价格数据
        return {
            'competitor_prices': {
                1: {'min': 15, 'max': 25, 'avg': 20},
                2: {'min': 28, 'max': 45, 'avg': 35},
                3: {'min': 40, 'max': 65, 'avg': 50},
                5: {'min': 65, 'max': 95, 'avg': 80},
            },
            'seasonal_factor': 1.0,  # 季节性因子
            'demand_factor': 1.0,    # 需求因子
        }
    
    def calculate_price(self, sku_name: str, custom_config: Optional[Dict] = None) -> PricingResult:
        """
        计算SKU的智能价格
        
        Args:
            sku_name: SKU名称
            custom_config: 自定义配置覆盖
            
        Returns:
            PricingResult: 详细的价格计算结果
        """
        # 1. 提取数量
        quantity, qty_confidence, qty_method = self.quantity_extractor.extract_quantity(sku_name)
        
        # 2. 应用自定义配置
        config = self.config
        if custom_config:
            config_dict = asdict(config)
            config_dict.update(custom_config)
            config = PricingConfig(**config_dict)
        
        # 3. 计算基础成本
        base_cost = self._calculate_base_cost(quantity, config)
        
        # 4. 计算总成本
        total_cost = self._calculate_total_cost(base_cost, quantity, config)
        
        # 5. 计算建议价格
        suggested_price = self._calculate_suggested_price(total_cost, quantity, config)
        
        # 6. 计算利润率
        profit_margin = self._calculate_profit_margin(suggested_price, total_cost)
        
        # 7. 获取竞争价格
        competitive_price = self._get_competitive_price(quantity)
        
        # 8. 计算价格区间
        price_range = self._calculate_price_range(total_cost, competitive_price, config)
        
        # 9. 计算总体可信度
        confidence = self._calculate_overall_confidence(qty_confidence, quantity)
        
        # 10. 计算平台扣点费用
        platform_fee_amount = 0.0
        platform_fee_rate = 0.0
        if hasattr(self, 'custom_cost_items') and self.custom_cost_items:
            for item in self.custom_cost_items:
                if item.get('cost_type') == 'platform_fee':
                    platform_fee_rate += item.get('value', 0.0) / 100.0
        if platform_fee_rate > 0:
            platform_fee_amount = suggested_price * platform_fee_rate
        
        # 11. 生成详细的成本分解信息 - 只包含用户配置的成本项目
        cost_breakdown = {
            'unit_cost': config.base_cost_per_unit,
            'platform_commission': suggested_price * config.platform_commission,
            'platform_fee': platform_fee_amount,
            'platform_fee_rate': platform_fee_rate,
            'custom_costs': []
        }
        
        # 添加自定义成本项目详情
        if hasattr(self, 'custom_cost_items') and self.custom_cost_items:
            for item in self.custom_cost_items:
                item_cost = item.get('value', 0.0)
                cost_type = item.get('cost_type', 'fixed')
                cost_name = item.get('name', '未知成本')
                
                if cost_type == 'per_unit':
                    actual_cost = item_cost * quantity
                elif cost_type == 'percentage':
                    actual_cost = base_cost * (item_cost / 100.0)
                elif cost_type == 'platform_fee':
                    actual_cost = suggested_price * (item_cost / 100.0)
                else:
                    actual_cost = item_cost
                
                cost_breakdown['custom_costs'].append({
                    'name': cost_name,
                    'type': cost_type,
                    'unit_value': item_cost,
                    'total_cost': actual_cost,
                    'description': item.get('description', '')
                })
        
        # 12. 生成计算详情
        calculation_details = {
            'quantity_extraction': {
                'method': qty_method,
                'confidence': qty_confidence,
                'extracted_quantity': quantity
            },
            'cost_breakdown': cost_breakdown,
            'pricing_strategy': {
                'target_margin': config.target_profit_margin,
                'quantity_tier': self._get_quantity_tier(quantity, config),
                'market_factor': self.market_data.get('seasonal_factor', 1.0)
            }
        }
        
        # 12. 生成备注
        notes = self._generate_notes(quantity, profit_margin, competitive_price, suggested_price)
        
        return PricingResult(
            sku_name=sku_name,
            quantity=quantity,
            base_cost=base_cost,
            total_cost=total_cost,
            suggested_price=suggested_price,
            profit_margin=profit_margin,
            competitive_price=competitive_price,
            price_range=price_range,
            calculation_details=calculation_details,
            confidence=confidence,
            notes=notes
        )
    
    def _calculate_base_cost(self, quantity: int, config: PricingConfig) -> float:
        """计算基础成本"""
        return quantity * config.base_cost_per_unit
    
    def _calculate_total_cost(self, base_cost: float, quantity: int, config: PricingConfig) -> float:
        """计算总成本，包括基础成本、运费、包装费和自定义成本项目"""
        total_cost = base_cost
        
        # 添加配置中的运费和包装费
        total_cost += config.shipping_cost + config.packaging_cost
        
        # 自定义成本项目
        custom_costs = 0.0
        if hasattr(self, 'custom_cost_items') and self.custom_cost_items:
            for item in self.custom_cost_items:
                item_cost = item.get('value', 0.0)  # 使用value字段
                cost_type = item.get('cost_type', 'fixed')  # 使用cost_type字段
                
                if cost_type == 'per_unit':
                    # 按单位计算的成本
                    custom_costs += item_cost * quantity
                elif cost_type == 'percentage':
                    # 按百分比计算的成本(基于基础成本)
                    custom_costs += base_cost * (item_cost / 100.0)
                elif cost_type == 'platform_fee':
                    # 平台扣点将在价格计算时处理，这里不计入成本
                    continue
                else:
                    # 固定成本
                    custom_costs += item_cost
        
        return total_cost + custom_costs
    
    def _calculate_suggested_price(self, total_cost: float, quantity: int, config: PricingConfig) -> float:
        """计算建议价格"""
        # 基于目标利润率计算价格（与毛利计算器保持一致）
        base_price = total_cost / (1 - config.target_profit_margin)
        
        # 四舍五入到合理价格点
        final_price = self._round_to_price_point(base_price)
        
        return final_price
    
    def _get_quantity_tier(self, quantity: int, config: PricingConfig) -> str:
        """获取数量等级描述"""
        if quantity >= 10:
            return "批量订单(10+双)"
        elif quantity >= 5:
            return "大额订单(5-9双)"
        elif quantity >= 3:
            return "中等订单(3-4双)"
        elif quantity >= 2:
            return "小额订单(2双)"
        else:
            return "单品订单(1双)"
    
    def _calculate_profit_margin(self, selling_price: float, total_cost: float) -> float:
        """计算利润率"""
        if selling_price <= 0:
            return 0.0
        return (selling_price - total_cost) / selling_price
    
    def _get_competitive_price(self, quantity: int) -> float:
        """获取竞争对手价格"""
        # 查找最接近的数量等级
        competitor_data = self.market_data.get('competitor_prices', {})
        
        if quantity in competitor_data:
            return competitor_data[quantity]['avg']
        
        # 找最接近的等级
        available_quantities = sorted(competitor_data.keys())
        closest_qty = min(available_quantities, key=lambda x: abs(x - quantity))
        
        if closest_qty in competitor_data:
            base_price = competitor_data[closest_qty]['avg']
            # 根据数量差异调整价格
            ratio = quantity / closest_qty
            return base_price * ratio
        
        # 默认估算
        return quantity * 18  # 每双18元的默认估算
    
    def _calculate_price_range(self, total_cost: float, competitive_price: float, config: PricingConfig) -> Tuple[float, float]:
        """计算价格区间"""
        # 最低价格：保证最低利润率
        min_price = total_cost / (1 - config.min_profit_margin)
        min_price = self._round_to_price_point(min_price)
        
        # 最高价格：基于最高利润率或竞争价格
        max_price_by_margin = total_cost / (1 - config.max_profit_margin)
        max_price_by_competition = competitive_price * 1.1  # 不超过竞品价格10%
        max_price = min(max_price_by_margin, max_price_by_competition)
        max_price = self._round_to_price_point(max_price)
        
        return (min_price, max_price)
    
    def _round_to_price_point(self, price: float) -> float:
        """将价格调整到合理的价格点"""
        if price < 20:
            # 小于20元，调整到0.9结尾
            return math.floor(price) + 0.9
        elif price < 50:
            # 20-50元，调整到0.8结尾
            return math.floor(price) + 0.8
        elif price < 100:
            # 50-100元，调整到0.5结尾
            return math.floor(price) + 0.5
        else:
            # 大于100元，调整到整数
            return round(price)
    
    def _calculate_overall_confidence(self, qty_confidence: float, quantity: int) -> float:
        """计算总体可信度"""
        base_confidence = qty_confidence
        
        # 根据数量调整可信度
        if quantity in [1, 2, 3, 5]:
            # 常见数量，提高可信度
            quantity_factor = 1.1
        elif quantity > 10:
            # 异常数量，降低可信度
            quantity_factor = 0.9
        else:
            quantity_factor = 1.0
        
        # 综合可信度
        overall_confidence = min(1.0, base_confidence * quantity_factor)
        return round(overall_confidence, 2)
    
    def _generate_notes(self, quantity: int, profit_margin: float, 
                       competitive_price: float, suggested_price: float) -> str:
        """生成价格建议备注"""
        notes = []
        
        # 数量相关备注
        if quantity >= 5:
            notes.append(f"💼 批量订单({quantity}双)，标准定价")
        elif quantity >= 3:
            notes.append(f"📦 中等订单({quantity}双)，标准定价")
        elif quantity == 2:
            notes.append(f"👥 2双装订单，标准定价")
        else:
            notes.append("👤 单双订单，标准定价")
        
        # 利润率相关备注
        if profit_margin >= 0.35:
            notes.append("💰 高利润率定价，建议关注竞争对手反应")
        elif profit_margin <= 0.20:
            notes.append("⚠️ 利润率较低，建议谨慎调整成本")
        else:
            notes.append("✅ 利润率合理，平衡收益与竞争力")
        
        # 竞争价格比较
        price_diff = suggested_price - competitive_price
        if price_diff > 5:
            notes.append("📈 定价高于市场均价，突出产品差异化价值")
        elif price_diff < -5:
            notes.append("📉 定价低于市场均价，具有价格竞争优势")
        else:
            notes.append("🎯 定价贴近市场均价，竞争力均衡")
        
        return " | ".join(notes)
    
    def batch_calculate(self, sku_list: List[str]) -> List[PricingResult]:
        """批量计算SKU价格"""
        results = []
        for sku_name in sku_list:
            try:
                result = self.calculate_price(sku_name)
                results.append(result)
            except Exception as e:
                print(f"❌ 计算SKU '{sku_name}' 价格时出错: {e}")
        
        return results
    
    def save_config(self, file_path: str):
        """保存当前配置"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self.config), f, ensure_ascii=False, indent=2)
        print(f"✅ 配置已保存到: {file_path}")
    
    def generate_pricing_report(self, results: List[PricingResult], output_file: str):
        """生成价格分析报告"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 统计信息
        total_skus = len(results)
        avg_margin = sum(r.profit_margin for r in results) / total_skus if total_skus > 0 else 0
        high_confidence = len([r for r in results if r.confidence > 0.8])
        
        # 生成报告内容
        report_content = f"""# 💰 智能价格计算报告

> 生成时间: {timestamp}  
> 分析SKU数量: {total_skus}个  
> 平均利润率: {avg_margin:.1%}  
> 高可信度比例: {high_confidence}/{total_skus} ({high_confidence/total_skus*100:.1f}%)

---

## 📊 **价格统计摘要**

| 指标 | 数值 |
|------|------|
| **总SKU数量** | {total_skus} |
| **平均利润率** | {avg_margin:.1%} |
| **高可信度SKU** | {high_confidence} ({high_confidence/total_skus*100:.1f}%) |
| **平均建议价格** | {sum(r.suggested_price for r in results)/total_skus:.1f}元 |

## 🎯 **详细价格分析**

| SKU名称 | 数量 | 建议价格 | 利润率 | 可信度 | 价格区间 | 备注 |
|---------|------|----------|--------|--------|----------|------|"""

        for result in results[:20]:  # 显示前20个结果
            price_range = f"{result.price_range[0]:.1f}-{result.price_range[1]:.1f}元"
            report_content += f"""
| {result.sku_name} | {result.quantity}双 | {result.suggested_price:.1f}元 | {result.profit_margin:.1%} | {result.confidence:.1%} | {price_range} | {result.notes[:50]}... |"""

        report_content += f"""

---

📈 **完整数据请查看对应的JSON文件**
"""

        # 保存报告
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        print(f"📊 价格分析报告已生成: {output_file}")

def main():
    """演示智能价格计算功能"""
    print("💰 智能价格计算引擎演示")
    print("=" * 50)
    
    # 创建价格引擎
    engine = SmartPricingEngine()
    
    # 测试用例
    test_skus = [
        "2双白色+2双白色+黑色",
        "2双自选备注", 
        "白色+奶白+黑色",
        "3双装",
        "1双装",
        "5双混色装",
        "白色+2双黑色+奶白"
    ]
    
    print("🔍 开始计算价格...")
    results = engine.batch_calculate(test_skus)
    
    print("\n📊 价格计算结果:")
    print("-" * 80)
    
    for result in results:
        print(f"📌 {result.sku_name}")
        print(f"   数量: {result.quantity}双 | 建议价格: {result.suggested_price:.1f}元")
        print(f"   利润率: {result.profit_margin:.1%} | 可信度: {result.confidence:.1%}")
        print(f"   价格区间: {result.price_range[0]:.1f}-{result.price_range[1]:.1f}元")
        print(f"   备注: {result.notes}")
        print()
    
    # 生成报告
    engine.generate_pricing_report(results, "smart_pricing_report.md")
    
    print("✅ 智能价格计算演示完成！")

if __name__ == "__main__":
    main()