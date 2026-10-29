# -*- coding: utf-8 -*-
"""生成隔离测试用的假商品文件夹（SKU 小图），只写入你传入的目录（通常是 <AB_WORK>/fixtures）。"""
import os, sys
from PIL import Image, ImageDraw

root = sys.argv[1]
products = {
    "ID-1000001 测试船袜": ["(黑色)", "(白色)", "(灰色)", "(藏青)"],
    "ID-1000002 测试中筒袜": ["(红色)", "(蓝色)", "(绿色)"],
    "ID-1000003 重复规格袜": ["(同名)", "(同名)"],
}
colors = [(30, 30, 30), (240, 240, 240), (140, 140, 140), (20, 30, 90), (200, 40, 40), (40, 80, 200), (40, 160, 80)]
for pi, (name, skus) in enumerate(products.items()):
    sku_dir = os.path.join(root, name, "SKU")
    os.makedirs(sku_dir, exist_ok=True)
    for si, sku in enumerate(skus):
        img = Image.new("RGB", (200, 200), colors[(pi * 3 + si) % len(colors)])
        ImageDraw.Draw(img).rectangle([40, 40, 160, 160], outline=(255, 255, 255), width=4)
        # 重复规格：用不同的文件名前缀，名称相同(括号内一致)
        img.save(os.path.join(sku_dir, f"{si + 1:02d}{sku}.jpg"), quality=80)
print("fixtures ok:", root)
