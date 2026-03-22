import requests
import json
import logging
from typing import Dict, Any, Optional
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

class APIClient:
    """抖音开放平台API客户端"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.base_url = "https://open.douyin.com"
        self.access_token = None
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.load_credentials()
    
    def load_credentials(self):
        """加载API凭证"""
        try:
            credentials = self.config.get("api_credentials", {})
            self.app_key = credentials.get("app_key")
            self.app_secret = credentials.get("app_secret")
            if not (self.app_key and self.app_secret):
                raise ValueError("缺少API凭证配置")
        except Exception as e:
            logger.error(f"加载API凭证失败: {e}")
            raise

    async def refresh_token(self):
        """刷新访问令牌"""
        try:
            url = f"{self.base_url}/oauth/client_token"
            data = {
                "client_key": self.app_key,
                "client_secret": self.app_secret,
                "grant_type": "client_credentials"
            }
            response = await self._make_request("POST", url, json=data)
            self.access_token = response["access_token"]
            self.headers["Authorization"] = f"Bearer {self.access_token}"
        except Exception as e:
            logger.error(f"刷新令牌失败: {e}")
            raise

    async def get_product_list(self, page: int = 1, size: int = 20) -> Dict[str, Any]:
        """获取商品列表"""
        url = f"{self.base_url}/shop/product/list"
        params = {
            "page": page,
            "size": size
        }
        return await self._make_request("GET", url, params=params)

    async def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建商品"""
        url = f"{self.base_url}/shop/product/add"
        return await self._make_request("POST", url, json=product_data)

    async def update_product(self, product_id: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新商品信息"""
        url = f"{self.base_url}/shop/product/edit"
        data = {"product_id": product_id, **product_data}
        return await self._make_request("POST", url, json=data)

    async def delete_product(self, product_id: str) -> Dict[str, Any]:
        """删除商品"""
        url = f"{self.base_url}/shop/product/del"
        data = {"product_id": product_id}
        return await self._make_request("POST", url, json=data)

    async def _make_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """发送API请求"""
        try:
            kwargs["headers"] = {**self.headers, **kwargs.get("headers", {})}
            response = await requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            raise
