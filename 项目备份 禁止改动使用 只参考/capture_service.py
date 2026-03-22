#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
淘宝商品信息采集服务
基于Flask + Playwright 实现自动化商品信息采集
"""

import asyncio
import json
import os
import re
import time
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import aiohttp
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('capture.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# 全局任务存储
tasks: Dict[str, Dict[str, Any]] = {}

# 配置常量
CONFIG = {
    'max_concurrent_tasks': 3,
    'retry_attempts': 3,
    'timeout_seconds': 300,
    'download_directory': 'uploads/products/',
    'cache_directory': 'cache/',
    'max_cache_age': 86400,  # 24小时
    'rate_limit': {
        'max_requests_per_minute': 10,
        'user_cooldown_seconds': 60
    }
}

@dataclass
class ProductCaptureResult:
    """商品采集结果数据模型"""
    task_id: str
    url: str
    title: str
    price: Dict[str, Any]
    main_image: str
    detail_images: List[str]
    sku_info: List[Dict[str, Any]]
    parameters: List[Dict[str, str]]
    download_path: Optional[str]
    status: str
    error: Optional[str] = None
    captured_at: str = None

    def __post_init__(self):
        if self.captured_at is None:
            self.captured_at = datetime.now().isoformat()

@dataclass
class SKUInfo:
    """SKU信息数据模型"""
    id: str
    name: str
    price: float
    stock: Optional[int] = None
    images: List[str] = None
    attributes: Dict[str, str] = None

    def __post_init__(self):
        if self.images is None:
            self.images = []
        if self.attributes is None:
            self.attributes = {}

@dataclass
class ProductParameter:
    """商品参数数据模型"""
    name: str
    value: str
    category: Optional[str] = None

class RateLimiter:
    """访问频率限制器"""
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}
        self._lock = asyncio.Lock()
    
    async def is_allowed(self, user_id: str) -> bool:
        """检查是否允许访问"""
        async with self._lock:
            now = time.time()
            if user_id not in self.requests:
                self.requests[user_id] = []
            
            # 清理过期请求记录
            self.requests[user_id] = [
                req_time for req_time in self.requests[user_id]
                if now - req_time < self.time_window
            ]
            
            # 检查请求次数
            if len(self.requests[user_id]) >= self.max_requests:
                return False
            
            # 记录当前请求
            self.requests[user_id].append(now)
            return True
    
    async def get_wait_time(self, user_id: str) -> float:
        """获取需要等待的时间"""
        if await self.is_allowed(user_id):
            return 0
        
        if user_id not in self.requests or not self.requests[user_id]:
            return 0
        
        oldest_request = min(self.requests[user_id])
        wait_time = self.time_window - (time.time() - oldest_request)
        return max(0, wait_time)

class CaptureCache:
    """采集结果缓存管理"""
    def __init__(self, cache_dir: str = 'cache/'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_cache_key(self, url: str) -> str:
        """生成缓存键"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def get_cached_result(self, url: str) -> Optional[Dict[str, Any]]:
        """获取缓存结果"""
        cache_key = self.get_cache_key(url)
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    
                # 检查缓存是否过期
                cached_time = datetime.fromisoformat(cached_data.get('cached_at', ''))
                if (datetime.now() - cached_time).total_seconds() < CONFIG['max_cache_age']:
                    return cached_data.get('result')
            except Exception as e:
                logger.warning(f"读取缓存失败: {e}")
        
        return None
    
    def cache_result(self, url: str, result: Dict[str, Any]) -> None:
        """缓存采集结果"""
        try:
            cache_key = self.get_cache_key(url)
            cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
            
            cache_data = {
                'url': url,
                'result': result,
                'cached_at': datetime.now().isoformat()
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.warning(f"缓存结果失败: {e}")

class InputValidator:
    """输入验证器"""
    @staticmethod
    def validate_url(url: str) -> bool:
        """验证URL合法性"""
        try:
            result = urlparse(url)
            
            # 检查是否为淘宝/天猫域名
            allowed_domains = [
                'taobao.com', 'tmall.com',
                'detail.tmall.com', 'item.taobao.com'
            ]
            
            domain_valid = any(domain in result.netloc for domain in allowed_domains)
            if not domain_valid:
                raise ValueError("只允许淘宝/天猫商品链接")
            
            # 检查URL格式
            if not result.scheme or not result.netloc:
                raise ValueError("URL格式不正确")
            
            # 检查商品ID
            if 'id=' not in url:
                raise ValueError("无法识别的商品链接格式")
            
            return True
            
        except Exception as e:
            raise ValueError(f"URL验证失败: {e}")
    
    @staticmethod
    def sanitize_input(input_string: str) -> str:
        """清理输入字符串"""
        dangerous_chars = ['<', '>', '"', "'", '&', '%', '$', '#']
        sanitized = input_string
        
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '')
        
        return sanitized.strip()

class TaobaoProductScraper:
    """淘宝商品信息采集器"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.rate_limiter = RateLimiter()
        self.cache = CaptureCache()
        
        # 选择器配置
        self.selectors = {
            'title': [
                '.mainTitle--R75fTcZL',
                'h1[data-spm="1000983"]',
                '.tb-detail-hd h1',
                '[class*="Title"]',
                'h1'
            ],
            'price': [
                '.highlightPrice--asfw5V1e .text--jyiUrkMu',
                '.tb-rmb-num',
                '.price-current',
                '[class*="price"]',
                '[class*="Price"]'
            ],
            'main_image': [
                '#mainPicImageEl',
                '.mainPic--zxTtQs0P',
                '#J_ImgBooth',
                '.tb-booth img',
                '[id*="main"] img',
                '[class*="main"] img'
            ],
            'detail_images': [
                '.descV8-singleImage img',
                '#description img',
                '.detail-content img',
                '[class*="detail"] img',
                '[data-name="singleImage"]'
            ],
            'sku': [
                '.skuItem--Z2AJB9Ew',
                '.tb-sku',
                '[class*="sku"]',
                '[data-spm="sku"]'
            ],
            'parameters': [
                '.paramsWrap--H4YJB7Yk',
                '.attributes',
                '[class*="param"]',
                '[class*="attribute"]'
            ],
            'login_indicators': [
                '.login-box',
                '#login',
                '.fm-field-mobile',
                'text=登录',
                'text=请登录'
            ]
        }
    
    async def initialize(self) -> None:
        """初始化浏览器环境"""
        try:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=False,  # 显示浏览器界面，便于处理登录
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            logger.info("浏览器环境初始化成功")
            
        except Exception as e:
            logger.error(f"浏览器环境初始化失败: {e}")
            raise e
    
    async def scrape_product(self, url: str, task_id: str, options: Dict[str, bool] = None) -> ProductCaptureResult:
        """采集商品信息主流程"""
        if options is None:
            options = {
                'download_images': True,
                'extract_sku': True,
                'extract_params': True
            }
        
        try:
            # 检查频率限制
            user_id = f"task_{task_id}"
            if not await self.rate_limiter.is_allowed(user_id):
                wait_time = await self.rate_limiter.get_wait_time(user_id)
                raise Exception(f"访问频率限制，请等待 {wait_time:.0f} 秒")
            
            # 检查缓存
            cached_result = self.cache.get_cached_result(url)
            if cached_result:
                logger.info(f"使用缓存结果: {url}")
                return ProductCaptureResult(**cached_result)
            
            # 创建新页面
            self.page = await self.context.new_page()
            
            # 1. 访问商品页面
            await self.update_task_status(task_id, 10, "正在访问商品页面...")
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # 2. 检测登录状态
            if await self.is_login_required():
                await self.update_task_status(task_id, 15, "需要登录，请手动完成登录...")
                await self.wait_for_login()
            
            # 3. 等待页面加载完成
            await self.update_task_status(task_id, 20, "等待页面加载...")
            await self.page.wait_for_load_state('networkidle')
            
            # 4. 提取商品信息
            await self.update_task_status(task_id, 30, "正在提取商品标题...")
            title = await self.extract_title()
            
            await self.update_task_status(task_id, 40, "正在提取价格信息...")
            price_info = await self.extract_price()
            
            await self.update_task_status(task_id, 50, "正在提取主图...")
            main_image = await self.extract_main_image()
            
            await self.update_task_status(task_id, 60, "正在提取详情图片...")
            detail_images = await self.extract_detail_images()
            
            sku_info = []
            if options.get('extract_sku', True):
                await self.update_task_status(task_id, 70, "正在提取SKU信息...")
                sku_info = await self.extract_sku_info()
            
            parameters = []
            if options.get('extract_params', True):
                await self.update_task_status(task_id, 80, "正在提取商品参数...")
                parameters = await self.extract_parameters()
            
            # 5. 下载图片
            download_path = None
            if options.get('download_images', True):
                await self.update_task_status(task_id, 85, "正在下载图片...")
                download_path = await self.download_images(main_image, detail_images, task_id)
            
            # 6. 构建结果
            result = ProductCaptureResult(
                task_id=task_id,
                url=url,
                title=title,
                price=price_info,
                main_image=main_image,
                detail_images=detail_images,
                sku_info=sku_info,
                parameters=parameters,
                download_path=download_path,
                status='completed'
            )
            
            # 缓存结果
            self.cache.cache_result(url, asdict(result))
            
            await self.update_task_status(task_id, 100, "采集完成！", asdict(result))
            
            logger.info(f"商品采集成功: {url}")
            return result
            
        except Exception as e:
            error_msg = f"采集失败: {str(e)}"
            await self.update_task_status(task_id, 0, error_msg, None, 'failed')
            logger.error(f"商品采集失败: {url}, 错误: {error_msg}")
            raise e
            
        finally:
            if self.page:
                await self.page.close()
    
    async def is_login_required(self) -> bool:
        """检测是否需要登录"""
        for selector in self.selectors['login_indicators']:
            try:
                element = await self.page.wait_for_selector(selector, timeout=5000)
                if element and await element.is_visible():
                    logger.info(f"检测到登录需求: {selector}")
                    return True
            except:
                continue
        return False
    
    async def wait_for_login(self, timeout: int = 300) -> bool:
        """等待用户完成登录"""
        logger.info("等待用户完成登录...")
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                # 检查是否还有登录相关元素
                login_element = await self.page.query_selector('.login-box, #login, .fm-field-mobile')
                if not login_element or not await login_element.is_visible():
                    logger.info("登录完成检测成功")
                    return True
                
                # 检查页面URL是否发生变化（登录成功后通常会跳转）
                current_url = self.page.url
                await asyncio.sleep(2)
                if self.page.url != current_url:
                    logger.info("页面URL变化，可能登录成功")
                    return True
                    
            except Exception as e:
                logger.warning(f"登录检测异常: {e}")
                break
                
            await asyncio.sleep(1)
        
        logger.warning("登录等待超时")
        return False
    
    async def extract_title(self) -> str:
        """提取商品标题"""
        for selector in self.selectors['title']:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    title = await element.get_attribute('title') or await element.text_content()
                    if title and title.strip():
                        title = title.strip()
                        logger.info(f"成功提取标题: {title[:50]}...")
                        return title
            except Exception as e:
                logger.debug(f"标题提取尝试失败: {selector}, {e}")
                continue
        
        logger.warning("未获取到商品标题")
        return "未获取到标题"
    
    async def extract_price(self) -> Dict[str, Any]:
        """提取价格信息"""
        for selector in self.selectors['price']:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    price_text = await element.text_content()
                    price_match = re.search(r'(\d+\.?\d*)', price_text)
                    if price_match:
                        price = float(price_match.group(1))
                        logger.info(f"成功提取价格: {price}")
                        return {
                            'current': price,
                            'original': None,
                            'currency': 'CNY'
                        }
            except Exception as e:
                logger.debug(f"价格提取尝试失败: {selector}, {e}")
                continue
        
        logger.warning("未获取到价格信息")
        return {'current': 0, 'original': None, 'currency': 'CNY'}
    
    async def extract_main_image(self) -> str:
        """提取主图"""
        for selector in self.selectors['main_image']:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    src = await element.get_attribute('src')
                    if src and 'http' in src:
                        logger.info(f"成功提取主图: {src[:100]}...")
                        return src
            except Exception as e:
                logger.debug(f"主图提取尝试失败: {selector}, {e}")
                continue
        
        logger.warning("未获取到主图")
        return ""
    
    async def extract_detail_images(self) -> List[str]:
        """提取详情图片"""
        images = []
        
        for selector in self.selectors['detail_images']:
            try:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    src = await element.get_attribute('src')
                    if src and 'http' in src and src not in images:
                        images.append(src)
                        
                if images:  # 如果找到图片就返回
                    logger.info(f"成功提取详情图片: {len(images)} 张")
                    return images[:20]  # 限制最多20张图片
                    
            except Exception as e:
                logger.debug(f"详情图片提取尝试失败: {selector}, {e}")
                continue
        
        logger.warning("未获取到详情图片")
        return images
    
    async def extract_sku_info(self) -> List[Dict[str, Any]]:
        """提取SKU信息"""
        sku_info = []
        
        for selector in self.selectors['sku']:
            try:
                sku_elements = await self.page.query_selector_all(selector)
                
                for element in sku_elements:
                    sku_data = {
                        'id': await element.get_attribute('data-vid') or '',
                        'name': '',
                        'price': 0,
                        'images': [],
                        'attributes': {}
                    }
                    
                    # 提取SKU名称
                    name_element = await element.query_selector('[class*="title"], span')
                    if name_element:
                        sku_data['name'] = await name_element.text_content()
                    
                    # 提取SKU图片
                    img_elements = await element.query_selector_all('img')
                    for img_el in img_elements:
                        src = await img_el.get_attribute('src')
                        if src:
                            sku_data['images'].append(src)
                    
                    sku_info.append(sku_data)
                
                if sku_info:
                    logger.info(f"成功提取SKU信息: {len(sku_info)} 个")
                    break
                    
            except Exception as e:
                logger.debug(f"SKU提取异常: {e}")
                continue
        
        if not sku_info:
            logger.warning("未获取到SKU信息")
        
        return sku_info
    
    async def extract_parameters(self) -> List[Dict[str, str]]:
        """提取商品参数"""
        parameters = []
        
        for selector in self.selectors['parameters']:
            try:
                param_elements = await self.page.query_selector_all(f'{selector} [class*="item"]')
                
                for element in param_elements:
                    # 提取参数名称和值
                    name_el = await element.query_selector('[class*="title"], [class*="name"]')
                    value_el = await element.query_selector('[class*="value"], [class*="content"]')
                    
                    if name_el and value_el:
                        name = await name_el.text_content()
                        value = await value_el.text_content()
                        
                        if name and value:
                            parameters.append({
                                'name': name.strip(),
                                'value': value.strip()
                            })
                
                if parameters:
                    logger.info(f"成功提取商品参数: {len(parameters)} 个")
                    break
                    
            except Exception as e:
                logger.debug(f"参数提取异常: {e}")
                continue
        
        if not parameters:
            logger.warning("未获取到商品参数")
        
        return parameters
    
    async def download_images(self, main_image: str, detail_images: List[str], task_id: str) -> str:
        """下载图片到本地"""
        download_dir = os.path.join(CONFIG['download_directory'], task_id)
        os.makedirs(download_dir, exist_ok=True)
        
        all_images = []
        if main_image and 'http' in main_image:
            all_images.append(main_image)
        all_images.extend([img for img in detail_images if 'http' in img])
        
        if not all_images:
            logger.warning("没有图片需要下载")
            return download_dir
        
        async with aiohttp.ClientSession() as session:
            for i, image_url in enumerate(all_images):
                try:
                    # 更新进度
                    progress = 85 + (i / len(all_images)) * 10
                    await self.update_task_status(task_id, progress, f"下载图片 {i+1}/{len(all_images)}...")
                    
                    # 下载图片
                    async with session.get(image_url, timeout=30) as response:
                        if response.status == 200:
                            # 获取文件扩展名
                            ext = os.path.splitext(urlparse(image_url).path)[1] or '.jpg'
                            filename = f"image_{i+1:03d}{ext}"
                            filepath = os.path.join(download_dir, filename)
                            
                            with open(filepath, 'wb') as f:
                                f.write(await response.read())
                                
                            logger.info(f"图片下载成功: {filename}")
                            
                except Exception as e:
                    logger.error(f"图片下载失败 {image_url}: {e}")
                    continue
        
        logger.info(f"图片下载完成: {len(all_images)} 张")
        return download_dir
    
    async def update_task_status(self, task_id: str, progress: int, message: str, result: Optional[Dict[str, Any]] = None, status: str = 'running') -> None:
        """更新任务状态"""
        if task_id in tasks:
            tasks[task_id]['progress'] = progress
            tasks[task_id]['message'] = message
            tasks[task_id]['status'] = status
            if result:
                tasks[task_id]['result'] = result
        
        logger.info(f"任务 {task_id}: {message} ({progress}%)")

# API路由
@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/capture')
def capture_page():
    """采集控制台页面"""
    return render_template('capture.html')

@app.route('/history')
def history_page():
    """历史记录页面"""
    return render_template('history.html')

@app.route('/api/product/capture/start', methods=['POST'])
def start_capture():
    """开始采集任务"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})
        
        url = data.get('url', '').strip()
        options = data.get('options', {
            'download_images': True,
            'extract_sku': True,
            'extract_params': True
        })
        
        # 验证URL
        if not url:
            return jsonify({'success': False, 'message': '请输入商品链接'})
        
        try:
            InputValidator.validate_url(url)
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)})
        
        # 生成任务ID
        task_id = f"capture_{int(datetime.now().timestamp())}_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        
        # 创建任务
        task = {
            'task_id': task_id,
            'url': url,
            'options': options,
            'status': 'pending',
            'progress': 0,
            'message': '任务创建成功',
            'created_at': datetime.now().isoformat(),
            'result': None
        }
        
        tasks[task_id] = task
        
        # 异步启动采集任务
        def run_capture():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                scraper = TaobaoProductScraper()
                loop.run_until_complete(scraper.initialize())
                
                # 运行采集任务
                result = loop.run_until_complete(
                    scraper.scrape_product(url, task_id, options)
                )
                
                # 更新任务结果
                tasks[task_id]['result'] = asdict(result)
                tasks[task_id]['status'] = 'completed'
                
                logger.info(f"采集任务完成: {task_id}")
                
            except Exception as e:
                logger.error(f"采集任务失败: {task_id}, 错误: {str(e)}")
                tasks[task_id]['status'] = 'failed'
                tasks[task_id]['message'] = f"采集失败: {str(e)}"
            
            finally:
                try:
                    loop.close()
                except:
                    pass
        
        # 在线程池中运行采集任务
        executor = ThreadPoolExecutor(max_workers=1)
        executor.submit(run_capture)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '采集任务已启动'
        })
        
    except Exception as e:
        logger.error(f"启动采集任务失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"启动任务失败: {str(e)}"
        })

@app.route('/api/product/capture/status/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """获取任务状态"""
    task = tasks.get(task_id)
    
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        })
    
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'result': task.get('result'),
        'created_at': task['created_at']
    })

@app.route('/api/product/capture/cancel/<task_id>', methods=['POST'])
def cancel_capture(task_id: str):
    """取消采集任务"""
    task = tasks.get(task_id)
    
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        })
    
    # 更新任务状态
    task['status'] = 'cancelled'
    task['message'] = '任务已取消'
    
    logger.info(f"采集任务已取消: {task_id}")
    
    return jsonify({
        'success': True,
        'message': '任务已取消'
    })

@app.route('/api/product/capture/import', methods=['POST'])
def import_capture_result():
    """导入采集结果"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})
        
        task_id = data.get('task_id')
        product_data = data.get('product_data')
        
        if not task_id or not product_data:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
        
        # 验证数据完整性
        required_fields = ['title', 'price', 'main_image']
        for field in required_fields:
            if not product_data.get(field):
                return jsonify({
                    'success': False,
                    'message': f'缺少必要字段: {field}'
                })
        
        # 模拟导入过程（实际项目中这里应该连接到数据库）
        product_id = f"product_{int(datetime.now().timestamp())}"
        
        logger.info(f"商品数据导入成功: {task_id} -> {product_id}")
        
        return jsonify({
            'success': True,
            'message': '数据导入成功',
            'product_id': product_id
        })
        
    except Exception as e:
        logger.error(f"导入采集结果失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"导入失败: {str(e)}"
        })

@app.route('/api/product/capture/download/<task_id>', methods=['GET'])
def download_images(task_id: str):
    """下载图片压缩包"""
    task = tasks.get(task_id)
    
    if not task or not task.get('result', {}).get('download_path'):
        return jsonify({
            'success': False,
            'message': '没有找到图片文件'
        })
    
    download_path = task['result']['download_path']
    
    if not os.path.exists(download_path):
        return jsonify({
            'success': False,
            'message': '图片目录不存在'
        })
    
    # 这里应该创建压缩包并提供下载
    # 为简化实现，这里返回目录路径
    return jsonify({
        'success': True,
        'download_path': download_path,
        'message': '图片目录已准备好'
    })

@app.route('/api/product/capture/history', methods=['GET'])
def get_capture_history():
    """获取采集历史"""
    try:
        # 返回所有已完成的任务
        completed_tasks = [
            {
                'task_id': task['task_id'],
                'url': task['url'],
                'title': task.get('result', {}).get('title', '未知商品'),
                'price': task.get('result', {}).get('price', {}).get('current', 0),
                'status': task['status'],
                'created_at': task['created_at'],
                'captured_at': task.get('result', {}).get('captured_at')
            }
            for task in tasks.values()
            if task['status'] in ['completed', 'failed']
        ]
        
        # 按创建时间倒序排列
        completed_tasks.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'success': True,
            'history': completed_tasks,
            'total': len(completed_tasks)
        })
        
    except Exception as e:
        logger.error(f"获取采集历史失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"获取历史失败: {str(e)}"
        })

@app.route('/api/product/capture/history/<task_id>', methods=['DELETE'])
def delete_capture_history_item(task_id: str):
    try:
        task = tasks.get(task_id)
        if not task:
            return jsonify({'success': False, 'message': '记录不存在'})
        if task.get('status') == 'running':
            return jsonify({'success': False, 'message': '运行中的任务不可删除'})
        del tasks[task_id]
        return jsonify({'success': True, 'task_id': task_id})
    except Exception as e:
        logger.error(f"删除历史失败: {str(e)}")
        return jsonify({'success': False, 'message': f"删除失败: {str(e)}"})

@app.route('/api/product/capture/history', methods=['DELETE'])
def delete_capture_history():
    try:
        data = request.get_json(silent=True) or {}
        ids = data.get('ids')
        deleted_count = 0
        if ids and isinstance(ids, list):
            for tid in list(tasks.keys()):
                if tid in ids and tasks[tid].get('status') in ['completed', 'failed']:
                    del tasks[tid]
                    deleted_count += 1
        else:
            for tid in list(tasks.keys()):
                if tasks[tid].get('status') in ['completed', 'failed']:
                    del tasks[tid]
                    deleted_count += 1
        return jsonify({'success': True, 'deleted_count': deleted_count})
    except Exception as e:
        logger.error(f"清空历史失败: {str(e)}")
        return jsonify({'success': False, 'message': f"清空失败: {str(e)}"})

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        'success': True,
        'message': '服务运行正常',
        'timestamp': datetime.now().isoformat(),
        'active_tasks': len([t for t in tasks.values() if t['status'] == 'running'])
    })

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': '接口不存在'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"服务器内部错误: {str(error)}")
    return jsonify({
        'success': False,
        'message': '服务器内部错误'
    }), 500

# 创建必要的目录
def create_directories():
    """创建必要的目录"""
    directories = [
        CONFIG['download_directory'],
        CONFIG['cache_directory'],
        'logs',
        'static/images'
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

if __name__ == '__main__':
    # 创建目录
    create_directories()
    
    logger.info("淘宝商品采集服务启动...")
    logger.info(f"服务端口: 5000")
    logger.info(f"下载目录: {CONFIG['download_directory']}")
    logger.info(f"缓存目录: {CONFIG['cache_directory']}")
    
    # 启动服务
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )