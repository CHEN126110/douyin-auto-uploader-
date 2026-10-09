# -*- coding: utf-8 -*-
"""商品图片接口；依赖由应用入口注入，不反向导入启动入口。"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file

from src import product_media
from .responses import api_ok
from .whitebg_service import WhiteBgService


def create_media_blueprint(*, record_model, active_account, resolve_data_file,
                           edit_blocked, product_revision, account_lock, whitebg: WhiteBgService):
    routes = Blueprint('product_media', __name__)
    Record = record_model

    @routes.get('/api/products/<int:record_id>/media')
    def product_media_list(record_id):
        try:
            record = Record.get_by_id(record_id)
            row = dict(record.__data__)
            profile = request.args.get('account_profile', '')
            platform = None
            receipts = []
            if profile:
                account = active_account()
                if account['profile_name'] != profile:
                    return jsonify(success=False, msg='账户已经变化，请刷新图片列表'), 409
                platform = account['platform']
                if platform == 'taobao':
                    receipts = product_media.read_receipts(resolve_data_file('media_catalog'), row, profile)
            listing = product_media.list_directory(row, request.args.get('path', ''), receipts=receipts,
                                                   offset=int(request.args.get('offset', '0')))
            listing.update(account_profile=profile, platform=platform,
                           white_bg_selection=product_media.white_bg_selection(row))
            return jsonify(success=True, data=listing)
        except Record.DoesNotExist:
            return jsonify(success=False, msg='商品不存在，请刷新商品列表'), 404
        except FileNotFoundError:
            return jsonify(success=False, msg='该目录或文件已移动，请刷新商品目录'), 404
        except (ValueError, OSError) as exc:
            return jsonify(success=False, msg='图片目录读取失败：' + str(exc)), 400

    @routes.put('/api/products/<int:record_id>/media/white-background')
    def product_white_background(record_id):
        with account_lock:
            blocked = edit_blocked(record_id)
            if blocked is not None:
                return blocked
            try:
                data = request.get_json(silent=True)
                if not isinstance(data, dict) or 'path' not in data:
                    return jsonify(success=False, msg='请提供要选择的图片路径'), 400
                record = Record.get_by_id(record_id)
                if whitebg.is_processing(record_id, record.path):
                    return jsonify(success=False, msg='该商品的图片正在生成，请处理结束后再调整白底图'), 409
                relative = product_media.validate_white_bg_selection(dict(record.__data__), data['path'])
                revision = product_revision(dict(record.__data__, white_bg_path=relative))
                with Record._meta.database.atomic('IMMEDIATE'):
                    record.white_bg_path = relative
                    record.update_time = datetime.now()
                    if record.save(only=[Record.white_bg_path, Record.update_time]) != 1:
                        raise ValueError('商品记录已变化，请刷新后重新选择')
                row = dict(record.__data__)
                return api_ok(msg='已指定发布白底图' if relative else '已恢复自动选择白底图', data={
                    'record_id': record.id, 'selection': product_media.white_bg_selection(row),
                    'update_time': record.update_time.strftime('%Y-%m-%d %H:%M'),
                    'record_revision': revision,
                })
            except Record.DoesNotExist:
                return jsonify(success=False, msg='商品不存在'), 404
            except (ValueError, OSError) as exc:
                return jsonify(success=False, msg=str(exc)), 400
            except Exception as exc:
                current_app.logger.exception('保存发布白底图选择失败')
                return jsonify(success=False, msg='保存白底图选择失败：' + str(exc)), 500

    @routes.get('/api/products/<int:record_id>/media/image')
    def product_media_image(record_id):
        try:
            record = Record.get_by_id(record_id)
            image = product_media.preview_image(dict(record.__data__), request.args.get('path', ''),
                                                thumbnail=request.args.get('size', 'thumb') != 'preview')
            response = send_file(image, mimetype='image/jpeg', max_age=0)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        except Record.DoesNotExist:
            return jsonify(success=False, msg='商品不存在'), 404
        except FileNotFoundError:
            return jsonify(success=False, msg='图片已移动，请刷新目录'), 404
        except (ValueError, OSError) as exc:
            return jsonify(success=False, msg=str(exc)), 400

    return routes
