# -*- coding: utf-8 -*-
"""本地文件夹导入接口（/api/import/folders）：把含 SKU 图片的文件夹整理成商品记录。

每个文件夹里要有名字含 ``SKU`` 的子目录；其中的图片文件名决定 SKU 名称，同名（忽略大小写）只保留第一个。"""
import json
import os
import traceback
from datetime import datetime

from flask import Blueprint, current_app, request

from .responses import api_error, api_ok


def _find_sku_folder(base_dir: str) -> str:
    for item in os.listdir(base_dir):
        if 'SKU' in item.upper():
            candidate = os.path.join(base_dir, item)
            if os.path.isdir(candidate):
                return candidate
    return ''


def _collect_image_files(start_dir: str):
    valid_ext = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
    files = []
    for root, _, names in os.walk(start_dir):
        for name in sorted(names):
            if name.lower().endswith(valid_ext):
                files.append(os.path.join(root, name))
    return files


def _dedup_sku_list(sku_list):
    """按名称去重SKU，保留每个名称的第一个。返回 (去重后列表, 移除数量)"""
    seen_names = {}
    deduped = []
    removed = 0
    for sku in sku_list:
        key = str(sku.get('name', '')).strip().lower()
        if not key:
            deduped.append(sku)
            continue
        if key in seen_names:
            removed += 1
            continue
        seen_names[key] = True
        deduped.append(sku)
    return deduped, removed


def _build_duplicate_groups(sku_list):
    groups = {}
    for sku in sku_list:
        key = str(sku.get('name', '')).strip().lower()
        if not key:
            continue
        groups.setdefault(key, []).append(str(sku.get('path', '')))
    duplicate_groups = []
    for key, paths in groups.items():
        if len(paths) > 1:
            duplicate_groups.append({
                'display_name': key,
                'count': len(paths),
                'paths': paths
            })
    return duplicate_groups


def create_import_blueprint(*, record_model, split_number_prefix):
    """``split_number_prefix`` 由应用入口注入：它在 ``src.utils`` 里，而 ``src.utils`` 会连带导入浏览器库，接口模块不该为一个 8 行的纯函数依赖它。"""
    routes = Blueprint('folder_import', __name__)
    Record = record_model

    def _derive_sku_name(file_name: str, dir_name: str, folder_name: str = '', sku_file_path: str = '') -> str:
        import re
        if folder_name.upper().startswith('C-'):
            normalized_path = sku_file_path.replace('\\', '/')
            if '自选备注' in dir_name or '/自选备注/' in normalized_path:
                return (dir_name or '自选备注').strip()
        arr = re.findall(r'\((.*?)\)', file_name)
        if arr:
            return str(arr[0]).strip()
        _, rest = split_number_prefix(file_name)
        candidate = (rest or file_name).replace('-', '+').strip()
        return candidate or dir_name

    @routes.route('/api/import/folders', methods=['POST'])
    def import_folders():
        try:
            data = request.get_json(silent=True) or {}
            paths = data.get('paths') or []
            if not isinstance(paths, list) or len(paths) == 0:
                return api_error('没有选择文件夹')

            normalized_paths = []
            seen = set()
            for raw in paths:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                abs_path = os.path.abspath(os.path.normpath(raw))
                path_key = abs_path.lower() if os.name == 'nt' else abs_path
                if path_key not in seen:
                    seen.add(path_key)
                    normalized_paths.append(abs_path)

            if len(normalized_paths) == 0:
                return api_error('没有有效的文件夹路径')

            imported_count = 0
            errors = []
            records_to_insert = []
            duplicate_sku_products = []

            for dir_path in normalized_paths:
                try:
                    if not os.path.isdir(dir_path):
                        errors.append(f'{dir_path} 不是有效的文件夹')
                        continue

                    sku_path = _find_sku_folder(dir_path)
                    if not sku_path:
                        errors.append(f'{os.path.basename(dir_path)} 未找到SKU文件夹')
                        continue

                    image_files = _collect_image_files(sku_path)
                    if len(image_files) == 0:
                        errors.append(f'{os.path.basename(dir_path)} 未找到有效的SKU图片')
                        continue

                    folder_name = os.path.basename(dir_path)
                    sku_list = []
                    seen_sku_path = set()
                    for sku_file in image_files:
                        file_key = sku_file.lower() if os.name == 'nt' else sku_file
                        if file_key in seen_sku_path:
                            continue
                        seen_sku_path.add(file_key)
                        file_name = os.path.splitext(os.path.basename(sku_file))[0]
                        dir_name = os.path.basename(os.path.dirname(sku_file))
                        sku_list.append({
                            'file_name': file_name,
                            'dir_name': dir_name,
                            'name': _derive_sku_name(file_name, dir_name, folder_name, sku_file),
                            'path': sku_file,
                            'price': ''
                        })
                    sku_list, dedup_count = _dedup_sku_list(sku_list)
                    if dedup_count > 0:
                        current_app.logger.info(f'SKU去重: {folder_name} 移除了 {dedup_count} 个重复项')
                    duplicate_groups = _build_duplicate_groups(sku_list)
                    if duplicate_groups:
                        duplicate_sku_products.append({
                            'product_name': folder_name,
                            'path': dir_path,
                            'duplicate_groups': duplicate_groups
                        })

                    records_to_insert.append({
                        'name': folder_name,
                        'path': dir_path,
                        'type': 2 if 'ID' in folder_name.upper() else 1,
                        'status': 0,
                        'repo': 100,
                        'title': '',
                        'clazz': 2,
                        'remark': '',
                        # 已删除 'notice': ''：那一列已退役（列本身在 ORM 里保留，删列是
                        # 破坏性操作），它也不再参与"资料指纹"，新建商品不必再为它写空串。
                        'content': json.dumps(sku_list, ensure_ascii=False),
                        'update_time': datetime.now(),
                        'import_source': 'manual',
                        'source_url': '',
                        'managed_files': False,
                    })
                    imported_count += 1
                except Exception as folder_error:
                    errors.append(f'{os.path.basename(dir_path)}: {str(folder_error)}')

            if records_to_insert:
                db = Record._meta.database
                with db.atomic():
                    paths_to_delete = [row['path'] for row in records_to_insert]
                    Record.delete().where(Record.path.in_(paths_to_delete)).execute()
                    Record.insert_many(records_to_insert).execute()

            result_msg = f'成功导入 {imported_count} 个文件夹'
            if errors:
                result_msg += f'，失败 {len(errors)} 个'
            if duplicate_sku_products:
                result_msg += f'，{len(duplicate_sku_products)} 个商品存在重复SKU名称'

            return api_ok(result_msg, {
                'imported_count': imported_count,
                'errors': errors,
                'duplicate_sku_products': duplicate_sku_products
            })
        except Exception as e:
            traceback.print_exc()
            return api_error(f'导入失败: {str(e)}')

    return routes
