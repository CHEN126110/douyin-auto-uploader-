# -*- coding: utf-8 -*-
"""淘宝发布服务：任务字典与互斥锁、淘宝模块的延迟加载、当前淘宝账户的浏览器地址、素材中心浏览器的拉起、界面资料 → 流水线请求的翻译、单品发布与批量发布的后台 worker。

任务字典 ``tasks`` 和互斥锁 ``lock`` 原来是 ``app.py`` 的模块全局（``_taobao_tasks`` / ``_taobao_tasks_lock``），现在是 ``TaobaoPublishService`` 实例的属性，由应用入口创建一次。

这个类不导入 ``src.utils`` / DrissionPage / ``app.py``，也不在导入时加载 ``taobao_publish`` 包（``load_desktop`` / ``load_pipeline`` 在请求里才加载，缺依赖只让淘宝接口不可用，不影响 Sidecar 启动）；账户门禁、店铺会话、路径解析、日志都由应用入口注入。

与 app.py 旧名字的对应：
  _load_taobao_desktop                       -> TaobaoPublishService.load_desktop
  _load_taobao_pipeline                      -> TaobaoPublishService.load_pipeline
  _taobao_cdp_list_url                       -> TaobaoPublishService.cdp_list_url
  _ensure_taobao_fill_browser                -> TaobaoPublishService.ensure_fill_browser
  _taobao_product_request_payload            -> TaobaoPublishService.product_request_payload
  _run_taobao_publish_task                   -> TaobaoPublishService.run_publish_task
  _run_taobao_publish_batch_task             -> TaobaoPublishService.run_publish_batch_task
  _taobao_tasks / _taobao_tasks_lock         -> tasks / lock
  _active_shop_account                       -> accounts.active_account
  _resolve_active_shop_browser               -> shop_service.resolve_active_browser
  _activate_shop_profile                     -> shop_service.activate_profile"""
import json
import os
import sys
import threading
import traceback
from datetime import datetime

from src import product_media
from .taobao_helpers import _taobao_product_from_record


class TaobaoPublishService:
    """一个应用一个实例，持有淘宝发布任务的全部进程内状态。

    ``record_model`` 是商品表；``repo_root`` 用来在源码运行时把 ``taobao-publisher`` 放进 sys.path；
    ``accounts`` 是 ``ShopAccountGuard``（当前账户），``shop_service`` 是 ``ShopSessionService``（取 / 拉起账户的浏览器）；
    ``normalize_debug_address`` 在 src.utils 里（会连带导入浏览器库），所以注入；
    ``resolve_data_file`` 决定图片目录记录落在哪个数据目录；``bootstrap_log`` 是应用入口的启动日志。"""

    def __init__(
            self, *,
            record_model,
            repo_root,
            accounts,
            shop_service,
            normalize_debug_address,
            resolve_data_file,
            bootstrap_log,
    ):
        self._record_model = record_model
        self._repo_root = repo_root
        self._accounts = accounts
        self._shop_service = shop_service
        self._normalize_debug_address = normalize_debug_address
        self._resolve_data_file = resolve_data_file
        self._bootstrap_log = bootstrap_log
        # 淘宝发布任务表。与抖店分开：两套流水线的阶段、进度锚点、写入锁都不同，
        # 混在一张表里会让前端按抖音的字段去读淘宝的任务。
        self.tasks = {}
        self.lock = threading.Lock()

    def load_desktop(self):
        """淘宝资料准备独立于抖店上传；仅在对应请求中加载。"""
        if not getattr(sys, 'frozen', False):
            package_root = os.path.join(self._repo_root, 'taobao-publisher')
            if package_root not in sys.path:
                sys.path.insert(0, package_root)
        from taobao_publish import desktop
        return desktop

    def load_pipeline(self):
        """淘宝发布流水线；与资料准备同源，仅在对应请求中加载。"""
        if not getattr(sys, 'frozen', False):
            package_root = os.path.join(self._repo_root, 'taobao-publisher')
            if package_root not in sys.path:
                sys.path.insert(0, package_root)
        from taobao_publish import pipeline
        return pipeline

    def cdp_list_url(self):
        """当前**淘宝**账户的调试地址，转成 ``/json/list`` URL。

        必须是应用管理的那个浏览器（9500-9599 端口段），不是研究用的 9334——
        两者登录态不同，流水线跑到错误的浏览器上会什么都找不到。
        """
        address, _browser_info, _source = self._shop_service.resolve_active_browser(platform='taobao')
        if not address:
            return ''
        return 'http://{}/json/list'.format(address)

    def ensure_fill_browser(self):
        """用当前账户启动素材中心；素材完整导入后才进入发布页。

        与添加/切换账户使用同一生命周期，不检查店铺资料，也不另建登录目录。
        调用方必须先持有账户锁并确认没有正在运行的发布任务。
        """
        account = self._accounts.active_account()
        if account['platform'] != 'taobao':
            raise ValueError('当前账户不属于淘宝')
        from taobao_publish.folder_import import MATERIAL_CENTER_URL
        opened = self._shop_service.activate_profile(account['profile_name'], open_browser=True, browser_url=MATERIAL_CENTER_URL)
        if opened.get('active_profile') != account['profile_name']:
            raise RuntimeError('浏览器账户与当前淘宝账户不一致')
        if not opened.get('browser_opened'):
            raise RuntimeError(opened.get('browser_error') or '浏览器未能启动')
        address = self._normalize_debug_address(opened.get('debug_address'))
        if not address:
            raise RuntimeError('浏览器已打开，但没有返回可连接的调试地址')
        return 'http://{}/json/list'.format(address)

    def product_request_payload(self, product, record=None):
        """把界面传来的 ``product`` 翻译成流水线的 ``request``。**不碰任务表和锁，便于单测**（标题 / 导购标题的长度规则要经 ``load_desktop`` 读本地契约）。

        .. warning::
            **这一步以前根本不存在。** 界面收集了标题/价格/库存/类目，却只用在
            「资料检查 / 导出资料包」上；``/api/taobao/publish/start`` 只传
            ``record_id``，流水线因此在静态预检就报「标题为空」。
            也就是说：**UI 收集的数据从来没有到达过发布流水线。**

        翻译规则（**不猜**）：

        * ``title`` → ``title``；
        * ``category_path`` 按 ``>`` 切成 ``category.path``（流水线要求完整路径精确相等）；
        * ``category_id`` 原样传给 ``category.category_id``（可空，流水线会回读权威值）；
        * ``freight_template_name`` 原样；
        * ``props`` / ``skus`` 原样透传——**规格值必须由调用方明确给出**
          （``skus[].spec_values``），这里不从不存在的字段里推断，
          也不把 SKU 名字拆成属性值（那是猜）。
        """

        if not isinstance(product, dict):
            return None
        request = {
            "record_id": None,   # 由调用方填
            "record_name": "",
        }
        # guide_title 是**选填**：给了才带。它以前既不在翻译里、也不在 PublishItem 上，
        # 于是界面填的导购标题被静默丢弃。
        #
        # ⚠️ 「购买须知」（notice）已**整条退役**：界面在 E-318 撤掉入口，这个翻译函数
        # 从未转发过它，模型 / 映射 / 写入 / 回读期望 / 契约条目也已一并删除。要重新接上，
        # 那五处缺一不可——只在这里加一个键是半截通路（跨边界检查器会立刻报
        # "Sidecar 会读这些键，但界面造不出来"）。
        for key in ("title", "guide_title", "freight_template_name", "outer_id"):
            if key in product:
                if not isinstance(product[key], str):
                    raise ValueError("{} 必须是文本".format(key))
                request[key] = product[key].strip()

        # 在打开浏览器前读取同一份本地契约；不请求店铺资料，也不在前端另写上限。
        text_rules = (("title", "title_max_chars", "宝贝标题"),
                      ("guide_title", "guide_title_max_chars", "导购标题"))
        if any(key in request for key, _, _ in text_rules):
            desktop_text = self.load_desktop()
            rules = desktop_text.load_contracts().rules
            for key, rule_name, label in text_rules:
                if key not in request:
                    continue
                value = request[key]
                if key == "title" and not value:
                    raise ValueError("宝贝标题不能为空")
                rule = rules.get(rule_name)
                if value and rule is not None and rule.hard:
                    units = desktop_text._weighted_length(value)
                    maximum = rule.integer()
                    if units > maximum:
                        raise ValueError("{} {} 字符，超过已归档规则上限 {}（汉字计 2；目标类目实时规则仍需核对）".format(
                            label, units, maximum))

        if 'sku_mode' in product:
            sku_mode = product.get("sku_mode")
            if sku_mode not in ('standard', 'custom'):
                raise ValueError('sku_mode 必须是 standard 或 custom')
            request['sku_mode'] = sku_mode

        path_raw = product.get("category_path")
        if isinstance(path_raw, str) and path_raw.strip():
            request["category"] = {
                "category_id": str(product.get("category_id") or "").strip(),
                "path": [seg.strip() for seg in path_raw.split(">") if seg.strip()],
            }

        keyword = product.get("category_keyword")
        if keyword is not None:
            if not isinstance(keyword, str) or not keyword.strip():
                raise ValueError("category_keyword 必须是已选择的类目名称")
            request.setdefault("category", {})["search_keyword"] = keyword.strip()

        explicit_id = product.get("category_id")
        if explicit_id not in (None, ""):
            if isinstance(explicit_id, bool) or not isinstance(explicit_id, (str, int)):
                raise ValueError("category_id 必须是有效的平台类目编号")
            id_text = str(explicit_id).strip()
            if not id_text.isascii() or not id_text.isdigit() or int(id_text) <= 0:
                raise ValueError("category_id 必须是有效的平台类目编号")
            request.setdefault("category", {})["category_id"] = id_text

        props = product.get("props")
        if props is not None:
            if not isinstance(props, list) or any(not isinstance(p, dict) for p in props):
                raise ValueError("props 必须是属性对象列表")
            request["props"] = props

        skus = product.get("skus")
        if skus is not None:
            if not isinstance(skus, list) or any(not isinstance(s, dict) for s in skus):
                raise ValueError("skus 必须是规格对象列表")
            prepared = []
            desktop = None
            root = None
            registered_images = None
            for index, source in enumerate(skus):
                entry = dict(source)
                for number_field in ("price", "stock"):
                    value = entry.get(number_field)
                    if value is None:
                        continue
                    import math
                    try:
                        finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    except OverflowError:
                        finite = False
                    if not finite:
                        raise ValueError("第{}条SKU的{}必须是有效数字".format(index + 1, number_field))
                    if (number_field == "price" and value <= 0) or (
                        number_field == "stock" and (value < 0 or int(value) != value)
                    ):
                        raise ValueError("第{}条SKU的{}超出有效范围".format(index + 1, number_field))
                image = entry.get("image_path")
                if image is not None and (not isinstance(image, str) or not image.strip()):
                    raise ValueError("第{}条SKU的图片来源无效".format(index + 1))
                if image and record is not None:
                    if desktop is None:
                        desktop = self.load_desktop()
                        root = desktop._product_root(record)
                        if root is None:
                            raise ValueError("当前商品目录不存在，无法确认SKU图片来源")
                        content = record.get("content") or []
                        if isinstance(content, str):
                            content = json.loads(content)
                        if not isinstance(content, list) or any(not isinstance(s, dict) for s in content):
                            raise ValueError("当前商品SKU来源记录无效")
                        registered_images = {
                            os.path.normcase(str(desktop._contained_file(root, str(s["path"]))))
                            for s in content if s.get("path")
                        }
                    image_path = desktop._contained_file(root, image)
                    if not image_path.is_file() or os.path.normcase(str(image_path)) not in registered_images:
                        raise ValueError("第{}条SKU图片与当前商品来源不匹配".format(index + 1))
                    entry["image_path"] = str(image_path)
                prepared.append(entry)
            request["skus"] = prepared

        return request

    def run_publish_task(self, task_id, row, request_payload, options):
        """在工作线程里跑淘宝发布流水线，把进度写回任务表。"""

        # 本函数会**临时**把图片路线设成协议（见下面的 `setdefault`）。
        # ⚠️ 它是**进程级**环境变量，而 `taobao-publisher/tests/test_desktop_fill_entry.py`
        # 会构造真实的服务对象并**真的调用本方法**——所以必须在收尾还原，
        # 否则会把 `protocol` 泄漏给同一进程里后面所有用例（2026-10-07 实测让 24 项集体失败）。
        _previous_media_route = os.environ.get('TAOBAO_MEDIA_ROUTE')

        def _report_progress(pct, msg, step_name, steps):
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['progress'] = int(pct)
                task['message'] = msg
                task['current_step'] = step_name
                task['steps'] = list(steps)

        def _should_cancel():
            """取消钩子：读任务表里的 cancelled 标记。

        **阶段边界才生效**——阶段内部（例如一次上传）不会被打断，
        半途中断会留下说不清的状态。这与取消接口的返回文案是一致的。
        """
            with self.lock:
                task = self.tasks.get(task_id)
                return bool(task and task.get('cancelled'))

        try:
            pipeline = self.load_pipeline()
            from taobao_publish.authorization import WriteAuthorization

            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['status'] = 'running'
                task['started_at'] = datetime.now().isoformat()

            # 主页面填写动作只授权本次上传/表单阶段，不读取全局提交开关。
            # 主页面「直接发布」在界面确认后一次性放行到提交，同样不读环境变量。
            # legacy 研究入口继续使用其显式环境授权，三者不会互相扩权。
            if options.get('fill_only') is True:
                authorization = WriteAuthorization.for_form_filling()
            elif options.get('dry_run') is False and options.get('stop_before_submit') is False:
                authorization = WriteAuthorization.for_confirmed_publish()
            else:
                authorization = WriteAuthorization.from_environment()
            # 桌面填写先走整目录素材准备，发布页仅消费完整回执。
            # 未启用该准备阶段的研究入口仍沿用原协议路线；显式环境配置优先。
            os.environ.setdefault('TAOBAO_MEDIA_ROUTE', 'protocol')
            from taobao_publish.folder_import import make_preparer
            with self.lock:
                media_profile = str((self.tasks.get(task_id) or {}).get('account_profile') or '')
            result = pipeline.run_from_record(
                row,
                request_payload,
                dry_run=options['dry_run'],
                stop_before_submit=options['stop_before_submit'],
                authorization=authorization,
                progress_callback=_report_progress,
                cdp_list_url=options['cdp_list_url'],
                account_profile=media_profile,
                # ⚠️ **素材准备对所有真实任务都要跑**（2026-10-15）：淘宝的流程是
                # 「先把商品文件夹拖拽导入图片空间（平台自己会把目录建出来），
                # 再进发布页选图」。此前 `if fill_only` 的门会让「直接发布」绕过准备、
                # 改走协议路线里**由程序自己去素材中心建目录**——而那样建出来的目录
                # 选图器读不到，整条流水线停在 upload_images（真机任务 2026-10-15 20:43）。
                # 用 `.get(...)` 取地址：worker 是内部函数，对只给部分键的调用方宽容。
                media_preparer=make_preparer(media_profile, options.get('cdp_list_url')),
                write_artifact=False,
                should_cancel=_should_cancel,
                # ⚠️ 这两个**必须显式转发**：不转发的话界面上的选择到不了流水线——
                # 「上架方式」会静默用默认值、「保存草稿」永远 skipped（实测踩过：
                # GUI 路径下 save_draft 一直 skipped，而原因只是侧边栏没传）。
                #
                # 用 `.get(...)` 取：路由那边已保证键齐全，但 worker 是内部函数，
                # 对"少给一个可选开关"的调用方（含测试）应当宽容——缺了就取默认值，
                # 而不是 `KeyError` 把整个任务打成失败。
                listing_mode=options.get('listing_mode', ''),
                save_draft=options.get('save_draft', False),
            )
            payload = result.to_dict()
            media_record_error = ''
            observations = (payload.get('data') or {}).get('media_observations')
            if observations:
                with self.lock:
                    media_account_profile = (self.tasks.get(task_id) or {}).get('account_profile')
                try:
                    product_media.save_receipts(self._resolve_data_file('media_catalog'), row,
                                                 media_account_profile, observations)
                except Exception as exc:  # noqa: BLE001
                    # ⚠️ 这里**只该影响本地索引**，绝不能把平台结果一起丢掉。
                    # 2026-10-10 实测：这一行少了一个导入名（NameError），异常穿透出去，
                    # 于是「填写 100% 全 ok」的任务被报成「淘宝发布失败」——用户看到的
                    # 是发布被截停，其实平台侧全做完了。所以这里连未预期的异常也一并
                    # **如实报出来**（带类型名），而不是让它顶掉 payload。
                    # 本次新增导入名本身就是根因修复；这一层是防止**下一次**同类疏漏
                    # 再把成功误报成失败。
                    media_record_error = '图片目录记录保存失败（{}）：{}'.format(
                        type(exc).__name__, exc)
                    payload.setdefault('data', {})['media_record_error'] = media_record_error
                    self._bootstrap_log(media_record_error)
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['progress'] = 100
                task['steps'] = payload.get('steps') or task['steps']
                task['result'] = payload
                # **提交成功与否不由本任务判定**：报告的 success 是「流水线跑完了」，
                # 不是「商品已上架」。前端必须把这两件事分开显示。
                task['publish_confirmed'] = False
                cancelled = (payload.get('error') or {}).get('code') == 'CANCELLED'
                if cancelled:
                    task['status'] = 'cancelled'
                    task['message'] = '已取消，流水线在阶段边界停止'
                elif payload.get('success'):
                    task['status'] = 'succeeded'
                    # ⚠️ **做了保存草稿就必须说出来。** 否则界面只显示"埋在提交前"，
                    # 而平台上其实已经多了一条草稿——操作人会以为没写任何东西。
                    saved_draft_step = next(
                        (s for s in (payload.get('steps') or [])
                         if s.get('name') == 'save_draft' and s.get('status') == 'ok'), None)
                    draft_note = '；已在平台保存草稿' if saved_draft_step else ''
                    if options.get('fill_only') is True:
                        verification = (payload.get('data') or {}).get('form_verification') or {}
                        from taobao_publish.verification import whole_form_coverage_confirmed
                        if (verification.get('complete') is True and verification.get('status') == 'complete'
                                and payload.get('dry_run') is False and payload.get('stopped_before_submit') is True
                                and whole_form_coverage_confirmed(verification.get('required_field_coverage'))):
                            task['message'] = ('完整填写与回读已确认，停在提交前，尚未发布'
                                               + draft_note)
                        else:
                            task['message'] = ('本次填写操作已结束并停在提交前；'
                                           '整页必填尚未确认，不能认定完整填写' + draft_note)
                    elif options.get('dry_run') is True:
                        task['message'] = '资料校对完成，未填写或发布商品'
                    else:
                        task['message'] = '流水线已完成；是否上架请在卖家中心核对' + draft_note
                else:
                    task['status'] = 'failed'
                    error = payload.get('error') or {}
                    task['message'] = error.get('message') or '流水线未通过'
                    task['error'] = error.get('message') or '流水线未通过'
                    task['blockers'] = payload.get('blockers') or []
                if media_record_error:
                    task['message'] += '；' + media_record_error
                task['finished_at'] = datetime.now().isoformat()
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['status'] = 'failed'
                task['progress'] = 100
                task['message'] = '淘宝发布失败'
                task['error'] = str(e)
                task['finished_at'] = datetime.now().isoformat()
        finally:
            # ⚠️ **必须还原 `TAOBAO_MEDIA_ROUTE`**：`setdefault` 改的是**进程级**环境变量，
            # 而测试会真的调用本方法。不还原 = 把 `protocol` 泄漏给同一进程里
            # 后面的用例，它们会从 DOM 路线悄悄切到协议路线，然后集体失败——
            # 表现为一堆与本次改动无关的用例红掉，极难归因（2026-10-07 实测 24 项）。
            if _previous_media_route is None:
                os.environ.pop('TAOBAO_MEDIA_ROUTE', None)
            else:
                os.environ['TAOBAO_MEDIA_ROUTE'] = _previous_media_route

    def run_publish_batch_task(self, task_id, options):
        """批量淘宝发布 worker：依次处理全部 status=0 商品。

        开始时把任务置为 ``running``，结束时一定落在 ``succeeded`` / ``failed`` / ``cancelled`` 之一。
        ``pending`` / ``running`` 都算「在跑」——账户切换、保存该商品、单品发布都会被它们挡住——
        所以 worker 不能半路悄悄退出而任务还停在这两个状态上：单条记录的问题（资料翻译或流水线抛异常）
        只记成那一条的失败；其余的意外（比如读不出待发布列表）让任务以 ``failed`` 结束并带上原因。

        和单品 worker 一样，``_publish_batch`` 会**临时**把图片路线设成协议（进程级环境变量 ``TAOBAO_MEDIA_ROUTE``），
        不管怎么结束都在 ``finally`` 里还原成进来时的样子。
        """
        _previous_media_route = os.environ.get('TAOBAO_MEDIA_ROUTE')
        try:
            with self.lock:
                task = self.tasks.get(task_id)
                if task:
                    task['status'] = 'running'
                    task['started_at'] = datetime.now().isoformat()
            self._publish_batch(task_id, options)
        except Exception as exc:
            # 和单品 worker 同一口径：回溯打到 stderr，原因写在任务上。
            traceback.print_exc()
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['status'] = 'failed'
                task['progress'] = 100
                task['message'] = '淘宝批量发布失败'
                task['error'] = str(exc)
                task['finished_at'] = datetime.now().isoformat()
        finally:
            # ⚠️ **必须还原 `TAOBAO_MEDIA_ROUTE`**（理由同 ``run_publish_task``）：``_publish_batch`` 里的 `setdefault` 改的是**进程级**
            # 环境变量，不还原 = 批量跑完后 `protocol` 一直留在进程里，泄漏给同一进程里后面读它的代码（别的研究入口、测试）。
            # 这里曾经漏了：批量 worker 是照单品 worker 抄的，`finally` 没抄过来（2026-10-21 补上，「未决问题」第 25 条）。
            if _previous_media_route is None:
                os.environ.pop('TAOBAO_MEDIA_ROUTE', None)
            else:
                os.environ['TAOBAO_MEDIA_ROUTE'] = _previous_media_route

    def _publish_batch(self, task_id, options):
        """``run_publish_batch_task`` 的主体：逐条处理记录并写回任务表；这里抛出的异常由它兜底成任务失败。"""
        records = list(self._record_model.select().where(self._record_model.status == 0).order_by(self._record_model.id))
        total = len(records)
        if total == 0:
            with self.lock:
                task = self.tasks.get(task_id)
                if task:
                    task['status'] = 'failed'
                    task['message'] = '没有待上传的商品'
                    task['finished_at'] = datetime.now().isoformat()
            return

        def _report_progress(pct, msg, step_name, steps):
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['progress'] = int(pct)
                task['message'] = msg
                task['current_step'] = step_name
                task['steps'] = list(steps)

        def _should_cancel():
            with self.lock:
                task = self.tasks.get(task_id)
                return bool(task and task.get('cancelled'))

        os.environ.setdefault('TAOBAO_MEDIA_ROUTE', 'protocol')
        from taobao_publish.folder_import import make_preparer
        from taobao_publish.authorization import WriteAuthorization

        if options.get('fill_only') is True:
            auth = WriteAuthorization.for_form_filling()
        elif options.get('dry_run') is False and options.get('stop_before_submit') is False:
            auth = WriteAuthorization.for_confirmed_publish()
        else:
            auth = WriteAuthorization.from_environment()

        cdp_list_url = options.get('cdp_list_url', '')
        account_profile = str(options.get('account_profile') or '')

        results = []
        succeeded = 0
        failed = 0
        for idx, record in enumerate(records):
            if _should_cancel():
                with self.lock:
                    task = self.tasks.get(task_id)
                    if task:
                        task['status'] = 'cancelled'
                        task['message'] = '批量发布已取消（{}/{}）'.format(idx, total)
                        task['finished_at'] = datetime.now().isoformat()
                return
            base_pct = int((idx / total) * 100)
            _report_progress(base_pct,
                             '批量发布 {}/{}：{}'.format(idx + 1, total, record.name or record.id),
                             'batch', [])

            try:
                # 资料翻译也在 try 里：这一条的商品目录不存在 / 不是绝对路径（``ValueError``）只算这一条失败。
                # 它以前在 try 之外，异常会让整个 worker 线程崩溃，任务永远停在「进行中」。
                product = _taobao_product_from_record(record)
                row = dict(record.__data__)
                request_payload = {
                    'record_id': record.id,
                    'record_name': row.get('name') or '商品{}'.format(record.id),
                }
                translated = self.product_request_payload(product, record=row)
                if translated is not None:
                    translated['record_id'] = record.id
                    translated['record_name'] = request_payload['record_name']
                    request_payload = translated

                pipeline = self.load_pipeline()
                result = pipeline.run_from_record(
                    row,
                    request_payload,
                    dry_run=options.get('dry_run', True),
                    stop_before_submit=options.get('stop_before_submit', True),
                    authorization=auth,
                    progress_callback=_report_progress,
                    cdp_list_url=cdp_list_url,
                    account_profile=account_profile,
                    # 与单商品 worker 同一口径：批量任务也先做整目录素材准备
                    # （拖拽导入 → 平台建目录 → 发布页只选图），不再按 fill_only 分流。
                    media_preparer=make_preparer(account_profile, cdp_list_url),
                    write_artifact=False,
                    should_cancel=_should_cancel,
                    listing_mode=options.get('listing_mode', ''),
                    save_draft=options.get('save_draft', False),
                )
                payload = result.to_dict()
                ok = bool(payload.get('success'))
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                results.append({'record_id': record.id, 'name': record.name, 'success': ok,
                                'error': (payload.get('error') or {}).get('message') or ''})
            except Exception as exc:  # noqa: BLE001
                failed += 1
                results.append({'record_id': record.id, 'name': record.name, 'success': False,
                                'error': '{}: {}'.format(type(exc).__name__, exc)})

        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task['progress'] = 100
            task['result'] = {'success': failed == 0, 'results': results,
                              'succeeded': succeeded, 'failed': failed, 'total': total}
            if failed == 0:
                task['status'] = 'succeeded'
                task['message'] = '批量发布完成：{}/{} 成功'.format(succeeded, total)
            else:
                task['status'] = 'succeeded' if succeeded > 0 else 'failed'
                task['message'] = '批量发布结束：{} 成功 / {} 失败 / 共 {}'.format(succeeded, failed, total)
            task['publish_confirmed'] = False
            task['finished_at'] = datetime.now().isoformat()
