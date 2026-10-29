# -*- coding: utf-8 -*-
"""淘宝发布接口（/api/taobao/*）：就绪度 / 资料检查 / 导出资料包 / 启动发布 / 批量发布 / 进度 / 取消 / 任务列表。

这些接口只做 HTTP 适配和请求校验；任务字典、互斥锁、淘宝模块的加载、浏览器和 worker 在 ``TaobaoPublishService``，账户门禁在 ``ShopAccountGuard``，发布开关的解析在 ``taobao_helpers``。

与 app.py 旧名字的对应：
  _taobao_product_request（请求体解析）-> create_taobao_blueprint 里的同名小函数
  _with_shop_account_lock / _require_publish_platform / _account_change_blocked / _active_shop_account
                                       -> accounts.with_lock / require_publish_platform / account_change_blocked / active_account
  _require_product_revision            -> 工厂参数 require_product_revision（保存商品、抖店上传也在用，留在应用入口）"""
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .responses import api_error, api_ok
from .taobao_helpers import _parse_taobao_publish_options


def create_taobao_blueprint(
        *, service,
        accounts,
        record_model,
        resolve_data_file,
        require_product_revision
):
    """``service`` 是 ``TaobaoPublishService``（任务状态、淘宝模块、浏览器、worker）；``accounts`` 是 ``ShopAccountGuard``（账户锁与平台门禁）；
    ``record_model`` 是商品表；``resolve_data_file`` 决定资料包落在哪个数据目录；``require_product_revision`` 校验界面带来的商品资料版本（保存商品、抖店上传也在用，所以留在应用入口）。"""
    routes = Blueprint('taobao', __name__)
    Record = record_model

    def _taobao_product_request():
        """只接收商品编号与资料覆盖值，不接受调用方传入磁盘或浏览器路径。"""
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, None, (jsonify(success=False, msg='请求必须是 JSON 对象'), 400)
        if set(data) - {'record_id', 'overrides', 'platform', 'account_profile'}:
            return None, None, (jsonify(success=False, msg='请求包含不支持的参数'), 400)
        if data.get('platform', 'taobao') != 'taobao':
            return None, None, (jsonify(success=False, msg='淘宝接口只能处理淘宝资料'), 400)
        record_id = data.get('record_id')
        if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
            return None, None, (jsonify(success=False, msg='请选择有效的商品编号'), 400)
        overrides = data.get('overrides', {})
        if not isinstance(overrides, dict):
            return None, None, (jsonify(success=False, msg='资料覆盖值必须是 JSON 对象'), 400)
        error = accounts.require_publish_platform('taobao', data.get('account_profile'))
        if error is not None:
            return None, None, error
        try:
            record = Record.get_by_id(record_id)
        except Record.DoesNotExist:
            return None, None, (jsonify(success=False, msg='商品不存在，请刷新商品列表'), 404)
        return dict(record.__data__), overrides, None

    @routes.get('/api/taobao/readiness')
    def taobao_readiness():
        try:
            data = service.load_desktop().desktop_readiness()
            return jsonify(success=True, data=data)
        except (ImportError, OSError, ValueError) as exc:
            current_app.logger.exception('淘宝资料模块就绪度检查失败')
            return jsonify(success=False, msg=f'淘宝模块不可用：{exc}'), 503

    @routes.post('/api/taobao/publish/prepare')
    @accounts.with_lock
    def taobao_prepare():
        record, overrides, error = _taobao_product_request()
        if error is not None:
            return error
        try:
            data = service.load_desktop().prepare_product(record, overrides)
            data['account_profile'] = accounts.active_account()['profile_name']
            return jsonify(success=True, data=data, msg='淘宝资料检查完成，尚未向平台发布')
        except ValueError as exc:
            return jsonify(success=False, msg=str(exc)), 400
        except (ImportError, OSError) as exc:
            current_app.logger.exception('淘宝资料检查失败')
            return jsonify(success=False, msg=f'淘宝资料检查失败：{exc}'), 503

    @routes.post('/api/taobao/publish/export')
    @accounts.with_lock
    def taobao_export():
        record, overrides, error = _taobao_product_request()
        if error is not None:
            return error
        try:
            output_base = resolve_data_file('taobao_publish_packets')
            data = service.load_desktop().export_packet(record, overrides, output_base)
            data['account_profile'] = accounts.active_account()['profile_name']
            return jsonify(success=True, data=data, msg='本地淘宝资料包已生成，尚未向平台发布')
        except ValueError as exc:
            return jsonify(success=False, msg=str(exc)), 400
        except (ImportError, OSError) as exc:
            current_app.logger.exception('淘宝资料包生成失败')
            return jsonify(success=False, msg=f'淘宝资料包生成失败：{exc}'), 503

    @routes.post('/api/taobao/publish/start')
    @accounts.with_lock
    def taobao_publish_start():
        """启动淘宝发布流水线。

        .. warning::
            **默认 dry-run。** ``dry_run`` 缺省为 ``True``——所有会写平台的阶段全部跳过，
            只验证数据与前置条件。主页面 ``fill_only:true`` 只授予本次上传/表单输入，
            并强制 ``dry_run:false`` 与 ``stop_before_submit:true``；不点击草稿保存。
            其它写入入口仍需 ``TAOBAO_UPLOAD_ALLOW_WRITE``；
            真提交还需要 ``TAOBAO_UPLOAD_ALLOW_SUBMIT`` 精确为 ``"1"``，且
            ``stop_before_submit`` 必须显式传 ``False``。

        返回的 ``task_id`` 用于 ``/api/taobao/publish/status/<id>`` 轮询，
        形状与抖店的 ``/api/upload/*`` 一致。
        """
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(success=False, msg='请求必须是 JSON 对象'), 400
        if data.get('platform', 'taobao') != 'taobao':
            return jsonify(success=False, msg='淘宝接口只能处理淘宝商品'), 400

        # 参数解析与校验走**纯函数**（可脱离账户状态单测）。
        parsed, options_error = _parse_taobao_publish_options(data)
        if options_error is not None:
            return jsonify(success=False, msg=options_error), 400
        options_raw = {'dry_run': parsed['dry_run'],
                       'stop_before_submit': parsed['stop_before_submit'],
                       'fill_only': parsed['fill_only'],
                       'save_draft': parsed['save_draft']}
        listing_mode = parsed['listing_mode']

        record_id = data.get('record_id')
        if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
            return jsonify(success=False, msg='请选择有效的商品编号'), 400

        error = accounts.require_publish_platform('taobao', data.get('account_profile'))
        if error is not None:
            return error

        if options_raw['fill_only'] and (
            options_raw['dry_run'] is not False or options_raw['stop_before_submit'] is not True
        ):
            return jsonify(success=False, msg='填写任务必须真实填写并在提交前停止'), 400

        try:
            record = Record.get_by_id(record_id)
        except Record.DoesNotExist:
            return jsonify(success=False, msg='商品不存在，请刷新商品列表'), 404

        row = dict(record.__data__)
        if 'expected_record_revision' in data:
            error = require_product_revision(row, data['expected_record_revision'])
            if error is not None:
                return error
        request_payload = {'record_id': record_id, 'record_name': row.get('name') or '商品{}'.format(record_id)}

        # **把界面收集的商品资料带进流水线**。以前这里只有 record_id —— 界面填的
        # 标题/价格/库存/类目根本到不了流水线，于是静态预检永远报「标题为空」。
        product = data.get('product')
        if product is not None:
            try:
                translated = service.product_request_payload(product, record=row)
            except ValueError as exc:
                return jsonify(success=False, msg=str(exc)), 400
            if translated is None:
                return jsonify(success=False, msg='product 必须是 JSON 对象'), 400
            translated['record_id'] = record_id
            translated['record_name'] = request_payload['record_name']
            request_payload = translated

        # ⚠️ **准入检查只有一处，在下面拿 `service.lock` 的那个块里**（与"插入任务"同一把锁）。
        #
        # 这里曾经还有一处"先加锁查一次、出了锁再走"的早期检查。它有两个问题：
        # ① 那是 **TOCTOU 形态**——两个并发请求可以同时通过它，真正拦住的只有锁内那处，
        #   所以它只是**看起来**在防并发；
        # ② 让"检查与插入必须在同一把锁里"这条不变量变成"有两处检查"，审查时说不清哪处才算数。
        #
        # 代价是"起浏览器"发生在准入之前：并发请求会各自起一次浏览器，然后其中一个
        # 在锁内被 409 挡下。这个代价是**刻意接受**的——`service.ensure_fill_browser()`
        # 是幂等的（已登录就直接复用），而换来的是**只有一处、且真正原子**的准入。
        if options_raw['fill_only']:
            error = accounts.account_change_blocked()
            if error is not None:
                return error
            try:
                cdp_list_url = service.ensure_fill_browser()
            except (OSError, ValueError, RuntimeError) as exc:
                return jsonify(success=False, msg='启动淘宝浏览器失败：{}'.format(exc)), 503
        else:
            # legacy 校对/研究入口不改变浏览器状态。
            cdp_list_url = service.cdp_list_url()
            if not cdp_list_url:
                return api_error('没有找到淘宝账户的浏览器；请先在账户菜单里登录淘宝店铺')

        import uuid
        task_id = str(uuid.uuid4())[:8]
        options = {
            'dry_run': options_raw['dry_run'],
            'stop_before_submit': options_raw['stop_before_submit'],
            'fill_only': options_raw['fill_only'],
            'save_draft': options_raw['save_draft'],
            'listing_mode': listing_mode,
            'cdp_list_url': cdp_list_url,
        }
        task = {
            'task_id': task_id,
            'platform': 'taobao',
            'account_profile': accounts.active_account()['profile_name'],
            'record_id': record_id,
            'record_name': request_payload['record_name'],
            'status': 'pending',
            'progress': 0,
            'message': '任务已创建',
            'current_step': None,
            'steps': [],
            'error': None,
            'blockers': [],
            'result': None,
            'dry_run': options['dry_run'],
            'stop_before_submit': options['stop_before_submit'],
            'fill_only': options['fill_only'],
            'save_draft': options['save_draft'],
            'listing_mode': options['listing_mode'],
            # 与抖店一致：任务完成 ≠ 商品已上架。这个字段永远由人工核对后另行确认。
            'publish_confirmed': False,
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'finished_at': None,
        }
        # ⚠️ **一次只允许一个淘宝发布任务。**
        #
        # 流水线驱动的是**同一个浏览器页面**（同一个 CDP target）。两个任务同时跑会
        # 互相把页面导航来导航去、交叉写表单，而各自还在按自己的期望值回读——
        # 于是可能拿 A 的期望值去核对 B 写出来的页面。若 submit 已授权，
        # 两个任务甚至可能都去点提交。
        #
        # **检查与插入必须在同一把锁里**：分开写就是 TOCTOU 竞态——
        # 两个请求可以同时通过检查，然后都插入。
        with service.lock:
            in_flight = [t for t in service.tasks.values()
                         if t.get('status') in ('pending', 'running')]
            if in_flight:
                busy = in_flight[0]
                return jsonify(
                    success=False,
                    msg='已有一个淘宝发布任务在进行中（{}，{}），请等它结束后再发起'.format(
                        busy.get('task_id'), busy.get('record_name') or ''),
                ), 409
            service.tasks[task_id] = task

        worker = threading.Thread(
            target=service.run_publish_task,
            args=(task_id, row, request_payload, options),
            daemon=True,
        )
        worker.start()

        mode = '校对（dry-run，不写平台）' if options['dry_run'] else '写入'
        return api_ok(msg='淘宝{}任务已启动'.format(mode), data={
            'task_id': task_id,
            'dry_run': options['dry_run'],
            'stop_before_submit': options['stop_before_submit'],
        })

    @routes.post('/api/taobao/publish/start-all')
    @accounts.with_lock
    def taobao_publish_start_all():
        """一键批量淘宝发布全部待上传商品（status=0）。

        准入规则与 ``taobao_publish_start`` 相同：批量任务同样要拉起账户的素材中心浏览器、同样驱动同一个浏览器页面，
        所以先过账户切换互斥，再在同一把 ``service.lock`` 里「查有没有未结束的任务 + 登记任务」。
        """
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(success=False, msg='请求必须是 JSON 对象'), 400
        if data.get('platform', 'taobao') != 'taobao':
            return jsonify(success=False, msg='淘宝接口只能处理淘宝商品'), 400

        parsed, options_error = _parse_taobao_publish_options(data)
        if options_error is not None:
            return jsonify(success=False, msg=options_error), 400

        error = accounts.require_publish_platform('taobao', data.get('account_profile'))
        if error is not None:
            return error

        records = list(Record.select().where(Record.status == 0).order_by(Record.id))
        if not records:
            return api_error(msg='没有待上传的商品（status=0）')

        # ``service.ensure_fill_browser()`` 会拉起账户的浏览器，它的前提是「没有发布任务在跑」，所以先过账户切换互斥。
        # ⚠️ 不能放进下面的 ``with service.lock:``：这个检查内部也要拿 ``service.lock``（读任务表），那把锁不可重入。
        error = accounts.account_change_blocked()
        if error is not None:
            return error

        import uuid
        task_id = str(uuid.uuid4())[:8]
        account_profile = data.get('account_profile') or ''
        options = {
            'dry_run': parsed['dry_run'],
            'stop_before_submit': parsed['stop_before_submit'],
            'fill_only': parsed['fill_only'],
            'save_draft': parsed['save_draft'],
            'listing_mode': parsed['listing_mode'],
            'account_profile': account_profile,
        }
        try:
            options['cdp_list_url'] = service.ensure_fill_browser()
        except (OSError, ValueError, RuntimeError) as exc:
            return jsonify(success=False, msg='启动淘宝浏览器失败：{}'.format(exc)), 503

        # 与 ``taobao_publish_start`` 同一条规则：一次只允许一个淘宝发布任务（流水线驱动的是同一个浏览器页面），
        # 检查与插入必须在同一把锁里——分开写就是 TOCTOU 竞态。原因和代价见那边的注释。
        with service.lock:
            in_flight = [t for t in service.tasks.values()
                         if t.get('status') in ('pending', 'running')]
            if in_flight:
                busy = in_flight[0]
                return jsonify(
                    success=False,
                    msg='已有一个淘宝发布任务在进行中（{}，{}），请等它结束后再发起'.format(
                        busy.get('task_id'), busy.get('record_name') or ''),
                ), 409
            service.tasks[task_id] = {
                'task_id': task_id,
                'platform': 'taobao',
                'account_profile': account_profile,
                'record_id': None,
                'record_name': '批量({}个)'.format(len(records)),
                'status': 'pending',
                'progress': 0,
                'message': '批量上传 {} 个商品'.format(len(records)),
                'current_step': None,
                'steps': [],
                'error': None,
                'blockers': [],
                'result': None,
                'created_at': datetime.now().isoformat(),
                'started_at': None,
                'finished_at': None,
                'dry_run': options['dry_run'],
                'stop_before_submit': options['stop_before_submit'],
                'fill_only': options['fill_only'],
                'publish_confirmed': False,
                'cancelled': False,
            }

        worker = threading.Thread(target=service.run_publish_batch_task, args=(task_id, options), daemon=True)
        worker.start()
        return api_ok(msg='已启动淘宝批量发布（{}个商品）'.format(len(records)), data={
            'task_id': task_id,
            'count': len(records),
            'dry_run': options['dry_run'],
            'stop_before_submit': options['stop_before_submit'],
        })

    @routes.get('/api/taobao/publish/status/<task_id>')
    def taobao_publish_status(task_id):
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return jsonify(success=False, msg='任务不存在，请重新发起'), 404
            data = dict(task)
        return api_ok('已获取淘宝发布进度', data=data)

    @routes.post('/api/taobao/publish/cancel/<task_id>')
    def taobao_publish_cancel(task_id):
        """请求取消。**不中断已经在跑的那一步**——阶段边界才会检查。"""
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return jsonify(success=False, msg='任务不存在'), 404
            if task['status'] in ('succeeded', 'failed', 'cancelled'):
                return api_ok('任务已结束，无需取消', data={'task_id': task_id, 'status': task['status']})
            task['cancelled'] = True
            task['message'] = '已请求取消，将在阶段边界停止'
        return api_ok('已请求取消（阶段边界生效，正在执行的那一步不会被打断）',
                      data={'task_id': task_id, 'status': task['status']})

    @routes.get('/api/taobao/publish/tasks')
    def taobao_publish_tasks():
        with service.lock:
            tasks = [dict(item) for item in service.tasks.values()]
        tasks.sort(key=lambda item: item.get('created_at') or '', reverse=True)
        return api_ok('已获取淘宝发布任务列表', data={'count': len(tasks), 'tasks': tasks})

    return routes
