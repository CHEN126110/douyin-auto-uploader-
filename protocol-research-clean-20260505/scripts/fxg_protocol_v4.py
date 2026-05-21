# -*- coding: utf-8 -*-
"""FXG 协议上传流水线 v4 — CDP页面驱动 + React状态注入 + webpack提交。

与 v2/v3 的核心区别：
  1. 单一持久 CDP 连接，不复开
  2. 必须先打开发布页面，等待 schemaForm 就绪
  3. 通过 React 状态注入 (DouXiaoerStore.schemaForm.setState) 而非离线 body 构造
  4. 注入后从页面读回 model 验证一致性
  5. 通过页面自身的 webpack __fxgPost 提交

前提条件:
  - Chrome 以 --remote-debugging-port=9222 启动
  - 已登录 fxg.jinritemai.com
"""

import json, os, sys, time, re, uuid, datetime, random, tempfile, traceback
from urllib.request import urlopen, Request

try:
    import websocket
except ImportError:
    websocket = None
    print('[v4] WARNING: websocket-client not installed')

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"

PUBLISH_URL = "https://fxg.jinritemai.com/ffa/g/create"

# ---- 错误体系（自包含，不依赖 fxg_errors） ----

ERR = {
    "NO_BROWSER":       ("连接", "无法连接Chrome调试端口", "请以 --remote-debugging-port=9222 启动Chrome"),
    "NO_PAGE":          ("连接", "未找到抖店后台页面", "请在Chrome中打开 https://fxg.jinritemai.com 并登录"),
    "WS_FAIL":          ("连接", "CDP通信失败", "Chrome连接中断，请检查Chrome是否在运行"),
    "CDP_TIMEOUT":      ("连接", "CDP命令超时", "页面响应过慢，请刷新页面后重试"),
    "NO_COOKIE":        ("登录", "未获取到登录信息", "请先在Chrome中登录抖店后台"),
    "WEBPACK_CHUNK":    ("连接", "页面未完全加载", "请刷新发品页面后重试"),
    "NO_PUBLISH_ID":    ("连接", "无法获取发布凭证", "请刷新发品页面后重试"),
    "SCHEMAFORM_GONE":  ("连接", "发品表单未就绪", "请先在页面中选择商品类目"),
    "SCHEMA_FAILED":    ("配置", "获取类目属性失败", "类目ID可能无效，请检查商品类目设置"),
    "UPLOAD_FAILED":    ("图片", "图片上传失败", "检查网络连接和登录状态"),
    "NO_TITLE":         ("信息", "标题不符合要求", ""),
    "NO_SKU":           ("信息", "SKU列表为空", "请确保商品包含至少一个规格"),
    "NO_IMAGES":        ("图片", "缺少商品图片", "请确保主图目录下有图片文件"),
    "INJECT_FAILED":    ("连接", "页面状态注入失败", "请刷新发品页面后重试"),
    "SUBMIT_FAILED":    ("提交", "平台提交失败", ""),
}

# ---- 平台错误消息 → 用户友好描述 ----
PLATFORM_MSG_MAP = {
    # 标题相关
    "标题最长":      ("标题过长", "标题最长30个汉字（60个字符），请在商品编辑中缩短标题"),
    "标题长度不能低于": ("标题过短", "标题至少8个汉字（15个字符），请在商品编辑中补充标题"),
    # 品牌相关
    "品牌为空":      ("品牌未选择", "请在商品编辑中选择品牌（可选'无品牌'）"),
    "品牌不存在":     ("品牌无效", "所选品牌未通过平台审核，请重新选择品牌"),
    # 类目属性
    "类目属性填写不完整": ("类目属性不完整", "请在商品编辑中补充必填的类目属性（如材质成分、适用季节等）"),
    "材质成分":      ("材质成分未填写", "请在商品编辑中填写材质成分（如'棉75%;氨纶25%'）"),
    # 图片相关
    "主图.*3:4":     ("3:4主图比例不符", "请确保3:4主图比例为3:4（如1440x1920像素）"),
    "主图.*1:1":     ("1:1主图比例不符", "请确保1:1主图比例为正方形（如800x800像素）"),
    "上传1~5张":     ("主图数量不符", "请上传1~5张商品主图"),
    "非白底":        ("白底图不合规", "请使用白色背景的商品图片作为白底图；可在浏览器中点击'一键抠图→白底图'用AI处理"),
    # 价格/库存
    "价格.*最小":    ("价格过低", "商品价格不能低于0.01元"),
    "库存":          ("库存设置错误", "请检查SKU库存数量是否正确"),
    # SKU/规格
    "SKU.*重复":     ("SKU名称重复", "存在重复的SKU规格名称，请在商品编辑中去重"),
    "规格":          ("规格设置错误", "SKU规格与商品规格不一致，请检查规格配置"),
    # 风控
    "非官方途径":     ("平台安全检测", "提交过于频繁触发了平台安全检测，请等待2-5分钟后重试；或先在浏览器中手动发布一次"),
    "非正规技术":     ("平台安全检测", "提交方式触发了平台安全检测，请在浏览器中手动发布一次后再试"),
    "发品方式可能存在异常": ("平台安全检测", "平台检测到异常发布方式，请等待冷却后重试或先在浏览器中手动发布一次"),
    # 运费
    "运费模板":      ("运费模板未设置", "请在商品编辑中选择运费模板"),
    # 限时/活动
    "限时":          ("限时活动冲突", "当前商品参与限时活动，请在活动结束后再发布"),
}

def parse_platform_error(platform_msg, platform_code=""):
    """解析平台返回的错误消息，输出用户友好描述 + 修复建议。

    Returns:
        {friendly_msg: str, fix_hint: str, is_anti_abuse: bool}
    """
    msg = str(platform_msg or "")
    code = str(platform_code or "")

    # 1. 精确匹配已知模式
    import re as _re
    for pattern, (friendly, fix) in PLATFORM_MSG_MAP.items():
        if _re.search(pattern, msg):
            return {"friendly_msg": friendly, "fix_hint": fix,
                    "is_anti_abuse": "安全检测" in friendly}

    # 2. 反滥用拦截 (最高优先级)
    if "非官方途径" in msg or "非正规技术" in msg or "发品方式可能存在异常" in msg:
        return {"friendly_msg": "平台安全检测",
                "fix_hint": "提交过于频繁或方式异常。等待2-5分钟冷却后重试，或在浏览器中手动发布一次",
                "is_anti_abuse": True}

    # 3. code=10013 通用验证错误
    if code == "10013":
        if "token" in msg.lower() or "参数异常" in msg:
            return {"friendly_msg": "认证凭证过期",
                    "fix_hint": "请刷新Chrome页面重新登录，然后重试",
                    "is_anti_abuse": False}
        return {"friendly_msg": "平台验证未通过",
                "fix_hint": f"平台返回验证错误(code=10013): {msg[:150]}。请检查商品信息是否完整",
                "is_anti_abuse": False}

    # 4. code=10001010A 反滥用
    if code == "10001010A":
        return {"friendly_msg": "发布方式异常",
                "fix_hint": "平台检测到非正常发布方式。请在浏览器中手动发布一次商品后，再使用协议模式",
                "is_anti_abuse": True}

    # 5. 未匹配 → 展示原始消息 + 通用建议
    return {"friendly_msg": f"平台校验不通过",
            "fix_hint": f"平台返回: {msg[:200]}。请检查商品信息是否完整、图片是否符合规范",
            "is_anti_abuse": False}


def _mkerr(errcode, **kw):
    cat, friendly, hint = ERR.get(errcode, ERR["SUBMIT_FAILED"])
    msg = friendly
    for k, v in kw.items():
        msg = msg.replace("{" + k + "}", str(v))
    return {"success": False, "error": {
        "code": errcode, "category": cat,
        "message": msg, "fix_hint": hint.format(**kw) if "{" in hint else hint,
    }}


# ============================================================
# CDP 连接管理
# ============================================================

class CDPSession:
    """持久 CDP 会话。保持单条 WS 连接，所有操作复用。"""

    def __init__(self, host=CDP_HOST, port=CDP_PORT):
        self.host = host
        self.port = port
        self.ws = None
        self._mid = [0]
        self._debug_url = None

    def connect(self, timeout=15):
        """连接到任意 jinritemai.com 标签页，不存在则创建。"""
        try:
            resp = urlopen(f"http://{self.host}:{self.port}/json/list", timeout=3)
            targets = json.loads(resp.read())
        except Exception as e:
            raise RuntimeError(f"[CDP] 无法连接 Chrome @ {self.host}:{self.port}: {e}")

        # 优先找发品页，其次任意 jinritemai 页面
        target = None
        for t in targets:
            t_url = t.get("url", "")
            if "jinritemai.com" not in t_url:
                continue
            if "/ffa/g/create" in t_url:
                target = t
                break
            if not target:
                target = t  # 第一个 jinritemai 页面作为备选
        if not target:
            raise RuntimeError("[CDP] 未找到 jinritemai.com 标签页，请先在Chrome中打开并登录")

        self._debug_url = target["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(self._debug_url, timeout=timeout, suppress_origin=True)
        self.ws.settimeout(3)
        print(f"[CDP] 已连接到: {target['url'][:80]}")

    def call(self, method, params=None, timeout=30):
        """发送 CDP 命令并等待响应。"""
        self._mid[0] += 1
        msg_id = self._mid[0]
        payload = json.dumps({"id": msg_id, "method": method, "params": params or {}})
        self.ws.send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                raise RuntimeError(f"[CDP] WS recv 失败: {e}")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"[CDP] {method} 返回错误: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"[CDP] {method} 超时({timeout}s)")

    def evaluate(self, expression, await_promise=True, timeout=20):
        """执行 JS 表达式并返回 value。"""
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "timeout": min(timeout, 30) * 1000,
        })
        return (result.get("result") or {}).get("value")

    def navigate(self, url):
        """导航标签页到指定 URL。"""
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url})
        time.sleep(2)

    def ensure_create_page(self):
        """确保当前在发品页面，否则导航过去。"""
        url = self.evaluate("window.location.href", await_promise=False) or ""
        if "/ffa/g/create" not in str(url):
            print(f"[CDP] 当前页面非发品页，导航到: {PUBLISH_URL}")
            self.navigate(PUBLISH_URL)
            time.sleep(3)
        else:
            print("[CDP] 已在发品页面")

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except:
                pass


# ============================================================
# Step 1: 会话初始化
# ============================================================

def step_session(cdp):
    """获取 cookies、publishId、shop_id，确保在发品页面。

    返回: {"success": True, "data": {cookie_str, publish_id, shop_id}}
    """
    cdp.ensure_create_page()

    # 获取 cookies
    cdp.call("Network.enable")
    cookies_result = cdp.call("Network.getAllCookies")
    cookies = cookies_result.get("cookies", [])
    cookie_parts = []
    for c in cookies:
        if "jinritemai.com" in (c.get("domain") or ""):
            cookie_parts.append(f"{c['name']}={c['value']}")
    cookie_str = "; ".join(cookie_parts)
    if not cookie_str:
        return _mkerr("NO_COOKIE")
    print(f"[v4:1/5] Cookie 获取成功 ({len(cookie_parts)} 项)")

    # 获取 webpack 运行时 + publishId + shop_id
    cdp.call("Runtime.enable")
    js_result = cdp.evaluate('''
        (function() {
            var chunkName = Object.keys(window).find(function(k) {
                return k.includes("@ecom-mcenter/ffa-goods");
            });
            if (!chunkName) return JSON.stringify({error: "chunk not found"});

            if (!window.__fxgWebpackRequire) {
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;
            var publishId = req(68671).T({
                useUrlParams: true, useWindowCache: true, writeWindowCache: true
            });
            window.__fxgReq = req;
            window.__fxgPost = req(90665).bE;
            window.__fxgGet = req(28974).J;
            window.__fxgPublishId = publishId;

            var shopId = "";
            try {
                document.cookie.split(";").forEach(function(c) {
                    c = c.trim();
                    if (c.startsWith("ecom_gray_shop_id=")) shopId = c.split("=")[1];
                });
            } catch(e) {}

            return JSON.stringify({ok: true, publishId: publishId, shopId: shopId});
        })()
    ''')
    session = json.loads(js_result)
    if session.get("error") == "chunk not found":
        return _mkerr("WEBPACK_CHUNK")
    if not session.get("ok"):
        return _mkerr("NO_PUBLISH_ID", detail=str(js_result)[:200])

    publish_id = session.get("publishId", "")
    shop_id_val = session.get("shopId", "155450371")
    print(f"[v4:1/5] publishId={publish_id[:16]}... shopId={shop_id_val}")
    return {"success": True, "data": {
        "cookie_str": cookie_str,
        "publish_id": publish_id,
        "shop_id": shop_id_val,
    }}


# ============================================================
# Step 2: 图片上传 (复用 HTTP batchupload)
# ============================================================

def _resize_to_ratio(image_path, target_w, target_h):
    if not HAS_PIL:
        return image_path
    try:
        img = Image.open(image_path)
        orig_w, orig_h = img.size
        if abs((orig_w / orig_h) - (target_w / target_h)) < 0.01:
            return image_path
        if (orig_w / orig_h) > (target_w / target_h):
            new_w = int(orig_h * target_w / target_h)
            img = img.crop(((orig_w - new_w) // 2, 0, (orig_w + new_w) // 2, orig_h))
        else:
            new_h = int(orig_w * target_h / target_w)
            img = img.crop((0, (orig_h - new_h) // 2, orig_w, (orig_h + new_h) // 2))
        img = img.resize((target_w, target_h), Image.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(suffix=os.path.splitext(image_path)[1] or ".jpg", delete=False)
        img.save(tmp.name, quality=95)
        return tmp.name
    except Exception:
        return image_path


def _upload_single(image_path, cookie_str):
    if not os.path.exists(image_path):
        return None
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".bmp": "image/bmp"}
    mime_type = mime_map.get(ext, "image/png")
    with open(image_path, "rb") as f:
        image_data = f.read()

    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    filename = os.path.basename(image_path)
    body = b"\r\n".join([
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime_type}'.encode(),
        b"", image_data,
        f"--{boundary}--".encode(),
    ])
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Cookie": cookie_str,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
        "Referer": "https://fxg.jinritemai.com/ffa/g/create",
        "Origin": "https://fxg.jinritemai.com",
    }
    try:
        req = Request("https://fxg.jinritemai.com/product/img/batchupload",
                      data=body, headers=headers, method="POST")
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))
        if result.get("errno") == 0 and result.get("data"):
            return result["data"][0]
    except Exception as e:
        print(f"  [WARN] 图片上传失败: {image_path} -> {e}")
    return None


def step_upload_images(image_paths, cookie_str):
    """上传图片到 batchupload，返回 URL 集合。

    image_paths: {"main_3x4": [...], "main_1x1": [...], "detail": [...]}
    返回: {"success": True, "data": {main_3x4: [...], main_1x1: [...], detail: [...], white: "..."}}
    """
    urls = {"main_3x4": [], "main_1x1": [], "detail": [], "white": ""}
    errors = []

    label_map = {
        "main_3x4": ("3:4主图", 1440, 1920),
        "main_1x1": ("1:1主图", 1440, 1440),
        "detail":   ("详情图",  1440, 1440),
    }

    for key, (label, tw, th) in label_map.items():
        files = image_paths.get(key, [])
        if not files:
            continue
        for f in files:
            if not os.path.exists(f):
                errors.append({"path": f, "label": label, "error": "NOT_FOUND"})
                continue
            processed = _resize_to_ratio(f, tw, th)
            url = _upload_single(processed, cookie_str)
            if processed != f:
                try: os.unlink(processed)
                except: pass
            if url:
                urls[key].append(url)
            else:
                errors.append({"path": f, "label": label, "error": "UPLOAD_FAILED"})

    # 白底图 = 第一张 1:1 主图
    if urls["main_1x1"]:
        urls["white"] = urls["main_1x1"][0]

    total = sum(len(urls[k]) for k in ["main_3x4", "main_1x1", "detail"])
    print(f"[v4:2/5] 图片上传: {total} 张成功, {len(errors)} 失败")

    if total == 0:
        return _mkerr("NO_IMAGES")

    result = {"success": True, "data": urls}
    if errors:
        result["upload_errors"] = errors
    return result


# ============================================================
# Step 3: React 状态注入
# ============================================================

def _wait_schemaform(cdp, timeout=12):
    """等待 DouXiaoerStore.schemaForm 就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = cdp.evaluate('''
            (function() {
                try {
                    var inst = window.DouXiaoerStore &&
                        (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                    if (inst && inst.schemaForm && inst.schemaForm.n)
                        return JSON.stringify({found: true});
                } catch(e) {}
                try {
                    if (window.dxStoreRef && window.dxStoreRef.current &&
                        window.dxStoreRef.current.schemaForm)
                        return JSON.stringify({found: true});
                } catch(e) {}
                return JSON.stringify({found: false});
            })()
        ''', await_promise=False)
        try:
            if json.loads(probe).get("found"):
                print(f"[v4] schemaForm 就绪 ({time.time() - (deadline - timeout):.1f}s)")
                return True
        except:
            pass
        time.sleep(0.8)
    return False


def step_inject_state(cdp, product_data, image_urls, category_config):
    """通过 React state 注入标题、规格、SKU、价格等。

    注入策略：
      1. 等待 schemaForm 就绪
      2. 构建完整的 spec_detail + sku_detail (含价格/库存)
      3. 构建完整的 model 字段 (图片、类目、描述等)
      4. 批量 setState 注入
      5. 验证注入结果

    返回: {"success": True, "data": {specs, skus}}
    """
    if not _wait_schemaform(cdp):
        return _mkerr("SCHEMAFORM_GONE")

    title = product_data.get("title", "")
    if len(title) < 4:
        return _mkerr("NO_TITLE")

    sku_list = product_data.get("sku_info", [])
    if not sku_list:
        return _mkerr("NO_SKU")

    # 构建 spec_detail: 颜色分类 + 码数(均码)
    colors = list(dict.fromkeys(
        str(s.get("name", "默认")).strip() for s in sku_list
    )) or ["默认"]

    spec_detail = [
        {
            "id": "10000", "cp_id": 2752, "name": "颜色分类",
            "spec_values": [
                {"id": str(996874532588296900 + i + 18), "name": c,
                 "cpv_id": 0, "cpv_path": [], "img_url": None}
                for i, c in enumerate(colors)
            ]
        },
        {
            "id": "20000", "cp_id": 3939, "name": "码数",
            "spec_values": [{"id": "990897920130195435", "name": "均码",
                             "cpv_id": 0, "cpv_path": [], "img_url": None}]
        },
        {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
        {"id": "40000", "cp_id": 93,   "name": "规格",   "spec_values": []},
    ]

    color_ids = [sv["id"] for sv in spec_detail[0]["spec_values"]]
    size_id = spec_detail[1]["spec_values"][0]["id"]

    # 构建 sku_detail：每个颜色一个 SKU
    sku_detail = []
    for i, color in enumerate(colors):
        sku_price = 9.9
        if i < len(sku_list):
            try:
                p = float(sku_list[i].get("price", 0))
                if p > 0:
                    sku_price = p
            except (ValueError, TypeError):
                pass

        sku_stock = 100
        if i < len(sku_list):
            try:
                s = int(sku_list[i].get("stock", 100))
                if s > 0:
                    sku_stock = s
            except (ValueError, TypeError):
                pass

        sid = f"{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:8]}"
        sku_detail.append({
            "id": sid,
            "stock_info": {"stock_num": sku_stock},
            "sku_status": True,
            "confirm_no_barcode": False,
            "spec_detail_ids": [color_ids[i], size_id],
            "price": str(sku_price),
        })

    spec_json = json.dumps(spec_detail, ensure_ascii=False)
    sku_json = json.dumps(sku_detail, ensure_ascii=False)

    # 构建 pic (1:1主图)
    main_1x1 = image_urls.get("main_1x1", [])[:5]
    pic_value = [{"url": u} for u in main_1x1] if main_1x1 else []

    # 构建 main_image_three_to_four (3:4主图)
    main_3x4 = image_urls.get("main_3x4", []) or image_urls.get("main_1x1", [])[:5]
    mitf_value = [{"url": u} for u in main_3x4[:5]]

    # 构建 white_background_pic
    white = image_urls.get("white", "")
    wbg_value = [{"url": white}] if white else []

    # 构建描述
    detail_imgs = image_urls.get("detail", [])[:15]
    desc_parts = []
    for u in detail_imgs:
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    description = "<p>" + "".join(desc_parts) + "</p>" if desc_parts else ""

    # 注入到 schemaForm
    inject_expr = f'''
        (function() {{
            try {{
                var sf = null;
                var inst = window.DouXiaoerStore &&
                    (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                if (inst) sf = inst.schemaForm;
                if (!sf && window.dxStoreRef && window.dxStoreRef.current)
                    sf = window.dxStoreRef.current.schemaForm;
                if (!sf) return JSON.stringify({{error: "schemaForm lost"}});

                // 标题
                sf.n("title").setState({{value: {json.dumps(title, ensure_ascii=False)}}}, "inject");

                // 规格 + SKU
                sf.n("spec_detail").setState({{value: {spec_json}}}, "inject");
                sf.n("sku_detail").setState({{value: {sku_json}}}, "inject");

                // 图片
                var picVal = {json.dumps(pic_value, ensure_ascii=False)};
                if (picVal.length) sf.n("pic").setState({{value: picVal}}, "inject");

                var mitfVal = {json.dumps(mitf_value, ensure_ascii=False)};
                if (mitfVal.length) sf.n("main_image_three_to_four").setState({{value: mitfVal}}, "inject");

                var wbgVal = {json.dumps(wbg_value, ensure_ascii=False)};
                if (wbgVal.length) sf.n("white_background_pic").setState({{value: wbgVal}}, "inject");

                var descVal = {json.dumps(description, ensure_ascii=False)};
                if (descVal) sf.n("description").setState({{value: descVal}}, "inject");

                // 返回验证数据
                return JSON.stringify({{
                    ok: true,
                    specs: {len(colors)},
                    skus: {len(colors)},
                    pics: {len(pic_value)},
                    mitf: {len(mitf_value)},
                    wbg: {1 if wbg_value else 0},
                    desc_len: {len(description)}
                }});
            }} catch(e) {{
                return JSON.stringify({{error: e.message || String(e)}});
            }}
        }})()
    '''

    result = cdp.evaluate(inject_expr, await_promise=False, timeout=20)
    try:
        data = json.loads(result) if isinstance(result, str) else (result or {})
        if data.get("ok"):
            summary = f"标题+{data['specs']}规格+{data['skus']}SKU+{data['pics']}pic+{data['mitf']}mitf"
            print(f"[v4:3/5] React状态注入成功: {summary}")
            return {"success": True, "data": data}
        else:
            return _mkerr("INJECT_FAILED", detail=data.get("error", str(data)[:200]))
    except json.JSONDecodeError:
        return _mkerr("INJECT_FAILED", detail=str(result)[:200])


# ============================================================
# Step 4: 读回验证
# ============================================================

def step_read_state(cdp):
    """从 schemaForm 读回当前 model 关键字段，验证注入结果。"""
    probe = cdp.evaluate('''
        (function() {
            try {
                var inst = window.DouXiaoerStore &&
                    (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                var sf = inst ? inst.schemaForm :
                    (window.dxStoreRef && window.dxStoreRef.current ?
                     window.dxStoreRef.current.schemaForm : null);
                if (!sf) return JSON.stringify({error: "schemaForm lost"});

                var fields = ["title", "spec_detail", "sku_detail", "pic",
                    "main_image_three_to_four", "white_background_pic", "description",
                    "goods_category", "category_properties", "freight_id"];
                var snapshot = {};
                for (var i = 0; i < fields.length; i++) {
                    try {
                        var val = sf.n(fields[i]).getState();
                        snapshot[fields[i]] = val ? val.value : undefined;
                    } catch(e) {
                        snapshot[fields[i]] = null;
                    }
                }
                return JSON.stringify(snapshot);
            } catch(e) {
                return JSON.stringify({error: e.message || String(e)});
            }
        })()
    ''', timeout=15)
    try:
        snapshot = json.loads(probe)
        if "error" in snapshot:
            print(f"[v4:4/5] 读回失败: {snapshot['error']}")
            return {"success": True, "data": {"readback_ok": False, "snapshot": snapshot}}
        title = snapshot.get("title", "")
        spec = snapshot.get("spec_detail", [])
        skus = snapshot.get("sku_detail", [])
        pics = snapshot.get("pic", [])
        print(f"[v4:4/5] 读回验证: title={len(str(title))}字 spec={len(spec)}轴 sku={len(skus)}行 pic={len(pics)}张")
        return {"success": True, "data": {
            "readback_ok": True,
            "title": title,
            "spec_count": len(spec) if isinstance(spec, list) else 0,
            "sku_count": len(skus) if isinstance(skus, list) else 0,
            "pic_count": len(pics) if isinstance(pics, list) else 0,
            "snapshot": snapshot,
        }}
    except json.JSONDecodeError:
        return {"success": True, "data": {"readback_ok": False, "raw": str(probe)[:500]}}


# ============================================================
# Step 5: 提交
# ============================================================

def step_submit(cdp, category_leaf_id, publish_id, shop_id, body_override=None):
    """通过 webpack __fxgPost 提交 addWithSchema。

    body_override: 如果提供，直接使用此 body 提交（离线构造模式）
    否则尝试从页面 React state 获取 model 再提交（React注入模式）
    """
    # 确保 webpack 运行时可用
    cdp.evaluate('''
        (function() {
            if (window.__fxgPost && window.__fxgGet) return "ok";
            var chunkName = Object.keys(window).find(function(k) {
                return k.includes("@ecom-mcenter/ffa-goods");
            });
            if (!chunkName) return "chunk not found";
            if (!window.__fxgWebpackRequire) {
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;
            window.__fxgPost = req(90665).bE;
            window.__fxgGet = req(28974).J;
            return "ok";
        })()
    ''', await_promise=False)

    # 构建 submit JS
    if body_override is not None:
        # 离线 body 模式：直接提交构造好的 body
        body_json = json.dumps(body_override, ensure_ascii=False)
        print(f"[v4:5/5] 使用离线Body提交 ({len(body_json)}字节)")
        submit_js = f'''
            (async function() {{
                try {{
                    try {{
                        await window.__fxgGet("/product/tproduct/publishClickStat?check_status=2",
                            {{timeout: 3000}});
                    }} catch(e) {{}}

                    var result = await window.__fxgPost(
                        "/product/tproduct/addWithSchema?check_status=2",
                        {body_json},
                        {{timeout: 30000}}
                    );
                    return JSON.stringify({{ok: true, via: "fxgPost-offline", result: result}});
                }} catch(e) {{
                    return JSON.stringify({{error: true, via: "exception", msg: e.msg || String(e)}});
                }}
            }})()
        '''
    else:
        # React注入模式：从页面 state 获取 model
        print(f"[v4:5/5] 从页面State获取Model提交")
        submit_js = f'''
            (async function() {{
                try {{
                    var inst = window.DouXiaoerStore &&
                        (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                    var sf = inst ? inst.schemaForm : null;
                    if (!sf && window.dxStoreRef && window.dxStoreRef.current)
                        sf = window.dxStoreRef.current.schemaForm;

                    var model = {{}};
                    if (sf) {{ try {{ model = sf.getModel(); }} catch(e) {{}} }}

                    var now = new Date();
                    var n_token = String(now.getFullYear()) +
                        String(now.getMonth()+1).padStart(2,"0") +
                        String(now.getDate()).padStart(2,"0") +
                        String(now.getHours()).padStart(2,"0") +
                        String(now.getMinutes()).padStart(2,"0") +
                        String(now.getSeconds()).padStart(2,"0") +
                        Math.random().toString(16).slice(2,22).toUpperCase();

                    var body = {{
                        schema: {{
                            model: model,
                            context: {{
                                ability: [], biz_identity: "xiaodian", business_code: "xiaodian",
                                capability_codes: ["standard_capability"],
                                category_id: "{category_leaf_id}",
                                feature: {{session_publish_id: "helper_{publish_id}"}},
                                identity_extension: '{{"Data":{{}}}}',
                                model_type: "", n_token: n_token, operation_type: "normal",
                                product_id: "0", shop_id: "{shop_id}", token: n_token,
                                version: "v1_v8_v9_v10_v11_v12"
                            }}
                        }},
                        category_id: "{category_leaf_id}",
                        context: {{category_id: "{category_leaf_id}", shop_id: "{shop_id}", token: n_token}},
                        pass_through_extra: {{}}, request_extra: {{}}, check_status: 2,
                        session: {{}}, appid: 1
                    }};

                    try {{
                        await window.__fxgGet("/product/tproduct/publishClickStat?check_status=2", {{timeout: 3000}});
                    }} catch(e) {{}}

                    var result = await window.__fxgPost(
                        "/product/tproduct/addWithSchema?check_status=2", body, {{timeout: 30000}}
                    );
                    return JSON.stringify({{ok: true, via: "fxgPost-react", result: result}});
                }} catch(e) {{
                    return JSON.stringify({{error: true, via: "exception", msg: e.msg || String(e)}});
                }}
            }})()
        '''

    result = cdp.evaluate(submit_js, timeout=45)
    try:
        submit_result = json.loads(result)
    except:
        return _mkerr("SUBMIT_FAILED", detail=str(result)[:200])

    if submit_result.get("error"):
        return _mkerr("SUBMIT_FAILED", detail=submit_result.get("msg", str(submit_result)[:200]))

    inner = submit_result.get("result", {})
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except:
            pass

    # 检查平台返回
    errno = inner.get("errno", 0) if isinstance(inner, dict) else 0
    code = inner.get("code", 0) if isinstance(inner, dict) else 0

    if errno == 0 and code == 0:
        product_id = ""
        raw_data = inner.get("data", "") if isinstance(inner, dict) else ""
        if raw_data:
            try:
                d = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                product_id = d.get("product_id", "") if isinstance(d, dict) else str(raw_data)
            except:
                product_id = str(raw_data)
        print(f"[v4:5/5] 提交成功! product_id={product_id}")
        return {"success": True, "data": {"product_id": product_id, "via": submit_result.get("via", "?"),
                                           "raw": inner if isinstance(inner, dict) else str(inner)[:500]}}
    else:
        raw_msg = inner.get("msg", "") if isinstance(inner, dict) else str(inner)
        code_str = str(code)
        # 使用平台错误解析 → 用户友好描述 + 修复建议
        parsed = parse_platform_error(raw_msg, code_str)
        print(f"[v4:5/5] 提交失败: code={code_str} | {parsed['friendly_msg']} → {parsed['fix_hint']}")
        # 构造包含完整诊断信息的错误
        err = _mkerr("SUBMIT_FAILED")
        err["error"]["platform_code"] = code_str
        err["error"]["platform_msg"] = str(raw_msg)[:300]
        err["error"]["message"] = parsed["friendly_msg"]
        err["error"]["fix_hint"] = parsed["fix_hint"]
        err["error"]["retryable"] = parsed["is_anti_abuse"]
        return err


# ============================================================
# 图片合规检查与 AI 工具
# ============================================================

def validate_image_compliance(image_paths):
    """上传前检查图片合规性，返回问题列表。

    返回: {ok: bool, issues: [{level, file, detail}], stats: {...}}
    """
    issues = []
    stats = {"total": 0, "too_small": 0, "bad_format": 0, "oversized": 0}

    for key, files in image_paths.items():
        if not files:
            continue
        for fp in files:
            if not fp or not os.path.isfile(fp):
                issues.append({"level": "error", "file": str(fp), "detail": "文件不存在"})
                continue
            stats["total"] += 1

            ext = os.path.splitext(fp)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                issues.append({"level": "warn", "file": str(fp),
                               "detail": f"格式 {ext} 可能不被支持，建议用 JPG/PNG"})
                stats["bad_format"] += 1

            size_kb = os.path.getsize(fp) / 1024
            if size_kb < 5:
                issues.append({"level": "warn", "file": str(fp),
                               "detail": f"文件过小({size_kb:.0f}KB)，可能是占位图"})
                stats["too_small"] += 1
            elif size_kb > 10240:
                issues.append({"level": "warn", "file": str(fp),
                               "detail": f"文件过大({size_kb/1024:.1f}MB)，建议压缩到10MB以内"})
                stats["oversized"] += 1

    return {
        "ok": not any(i["level"] == "error" for i in issues),
        "issues": issues,
        "stats": stats,
    }


def check_white_background_via_platform(cdp, image_url):
    """调用平台 AI 接口检测白底图是否合规。

    参数名必须是 img_url (不是 url! 已验证)
    返回: {ok: bool, passed: bool, high_quality: bool, reject_reasons: list, result: str}
    """
    if not image_url:
        return {"ok": False, "passed": False, "high_quality": False,
                "reject_reasons": None, "result": "无白底图URL"}
    try:
        result = cdp.evaluate(f'''
            (async function() {{
                try {{
                    var resp = await window.__fxgPost("/common/img/IsWhiteBackgroundPic", {{
                        img_url: "{image_url}"
                    }}, {{timeout: 10000}});
                    return JSON.stringify(resp);
                }} catch(e) {{
                    return JSON.stringify({{error: e.msg || String(e)}});
                }}
            }})()
        ''', timeout=15)
        data = json.loads(result) if isinstance(result, str) else result
        if data.get("error"):
            return {"ok": False, "passed": False, "high_quality": False,
                    "reject_reasons": None, "result": f"API调用失败: {data['error']}"}
        inner = data.get("data") or {}
        passed = inner.get("passed", False)
        high_quality = inner.get("high_quality", False)
        reject_reasons = inner.get("reject_reasons")
        if passed:
            return {"ok": True, "passed": True, "high_quality": high_quality,
                    "reject_reasons": reject_reasons,
                    "result": f"白底图合规{' (高质量)' if high_quality else ''}"}
        else:
            reason_text = f"原因: {reject_reasons}" if reject_reasons else "原因: 非白底图片"
            return {"ok": True, "passed": False, "high_quality": False,
                    "reject_reasons": reject_reasons,
                    "result": f"白底图不合规 — {reason_text}"}
    except Exception as e:
        return {"ok": False, "passed": False, "high_quality": False,
                "reject_reasons": None, "result": f"AI检测异常: {e}"}


def validate_title(title):
    """验证标题合规性。

    返回: {ok: bool, detail: str}
    """
    if not title or not title.strip():
        return {"ok": False, "detail": "标题为空，请先填写商品标题"}
    # 计算中文字符数（含中文标点）
    cn_chars = len([c for c in title if '一' <= c <= '鿿' or '　' <= c <= '〿' or '＀' <= c <= '￯'])
    total_len = len(title)
    if cn_chars < 8:
        return {"ok": False, "detail": f"标题仅{cn_chars}个汉字/英文{total_len}字符，平台要求至少8个汉字(15字符)"}
    if cn_chars > 30:
        return {"ok": False, "detail": f"标题{cn_chars}个汉字，超过平台限制30个汉字(60字符)"}
    return {"ok": True, "detail": f"标题合规({cn_chars}字)"}

def step_get_schema_for_body(cdp, category_leaf_id, publish_id):
    """通过 CDP webpack 获取 schema。用于离线 body 构建时获取真实 value_id。

    返回: {"success": True, "data": {"items": [...], "model": {...}}}
    """
    schema_js = cdp.evaluate(f'''
        (async function() {{
            if (!window.__fxgPost) {{
                var chunkName = Object.keys(window).find(function(k) {{
                    return k.includes("@ecom-mcenter/ffa-goods");
                }});
                if (!window.__fxgWebpackRequire) {{
                    window[chunkName].push([[Math.floor(Math.random() * 1e9)], {{}}, function(req) {{
                        window.__fxgWebpackRequire = req;
                    }}]);
                }}
                window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
                window.__fxgGet = window.__fxgWebpackRequire(28974).J;
            }}
            try {{
                var result = await window.__fxgPost("/product/tproduct/getSchema", {{
                    context: {{
                        category_id: "{category_leaf_id}",
                        operation_type: "normal",
                        ability: [],
                        feature: {{session_publish_id: "helper_{publish_id}"}}
                    }},
                    model: void 0
                }}, {{timeout: 15000}});
                return JSON.stringify(result);
            }} catch(e) {{
                return JSON.stringify({{error: true, msg: e.msg || String(e)}});
            }}
        }})()
    ''', timeout=25)
    try:
        schema = json.loads(schema_js)
    except json.JSONDecodeError:
        return _mkerr("SCHEMA_FAILED", detail=str(schema_js)[:200])

    if schema.get("errno") != 0 and schema.get("code") != 0:
        if str(schema.get("code")) == "500":
            return _mkerr("SCHEMA_FAILED", detail=schema.get("msg", ""))
        return _mkerr("SCHEMA_FAILED", detail=schema.get("msg", str(schema)[:200]))

    model = schema.get("data", {}).get("model", {})
    items = model.get("category_properties", {}).get("items", [])
    if not items:
        return _mkerr("SCHEMA_FAILED", detail="无类目属性")

    print(f"[v4:schema] Schema获取: {len(items)} 类目属性, leaf_id={category_leaf_id}")
    return {"success": True, "data": {"items": items, "model": model}}

def step_build_body_offline(product_data, image_urls, category_config, publish_id, shop_id, schema_data=None):
    """离线构造 addWithSchema body（从 v2 移植）。

    当页面 schemaForm 不可用时（类目未选择/标题未填）使用此路径。
    已验证: product_id=3819288252247048401 (2026-05-11)
    """
    title = product_data.get("title", "")
    if len(title) < 4:
        return _mkerr("NO_TITLE")

    sku_list = product_data.get("sku_info", [])
    if not sku_list:
        return _mkerr("NO_SKU")

    category_leaf_id = category_config.get("category_leaf_id", 1000010267)

    def w(v):
        return {"value": v}

    # -- category_properties --
    # 从 schema 获取真实 value_id，覆盖所有必填属性 + 可选有价值属性
    cp = {}
    if schema_data and schema_data.get("items"):
        # 智能默认值映射：property_id → target_value_name
        smart_defaults = {
            "1577": "通用", "1687": "无品牌",
            "241": "薄款", "810": "透气", "1825": "镂空",
            "1869": "纯色", "1343": "夏季", "2592": "韩系",
        }
        items_lookup = {}
        for item in schema_data["items"]:
            items_lookup[str(item["id"])] = item

        for item in schema_data["items"]:
            pid = str(item["id"])
            pname = item.get("label", "")
            opts = item.get("options") or []
            is_required = item.get("required", False)
            has_default = pid in smart_defaults

            if not is_required and not has_default:
                continue
            if not opts:
                continue

            # 找到目标值
            target = smart_defaults.get(pid)
            selected = None
            if target:
                for o in opts:
                    if o.get("value_name") == target:
                        selected = o
                        break
            if not selected and pname and category_config.get("fourth_cname"):
                for o in opts:
                    if category_config["fourth_cname"] in (o.get("value_name") or ""):
                        selected = o
                        break
            if not selected:
                selected = opts[0]

            entry = {
                "diy_type": 0, "measure_info": None, "tags": None,
                "value_id": str(selected.get("value_id", "")),
                "value_name": str(selected.get("value_name", "")),
            }
            if pid == "1687" and selected.get("value_name") == "无品牌":
                entry["tags"] = {"brand_cn_name": ""}
            cp[pid] = [entry]

    # 材质成分 (785) — 单独处理，因为结构特殊
    material = product_data.get("material", "")
    if material:
        cp["785"] = []
        for part in material.split(";"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"(.+?)(\d+)%?", part)
            if m:
                mat_name, mat_pct = m.group(1).strip(), m.group(2)
            else:
                mat_name, mat_pct = part, "100"
            cp["785"].append({
                "value_id": "", "value_name": f"{mat_name}{mat_pct}%",
                "measure_info": {
                    "template_id": 873,
                    "values": [
                        {"module_id": 1854, "prefix": "", "suffix": "", "value": mat_name},
                        {"module_id": 1855, "prefix": "", "suffix": "",
                         "value": mat_pct, "unit_id": 15, "unit_name": "%"},
                    ]
                }
            })

    # -- spec_detail --
    colors = list(dict.fromkeys(str(s.get("name", "默认")).strip() for s in sku_list)) or ["默认"]
    spec_detail = [
        {
            "id": "10000", "cp_id": 2752, "name": "颜色分类",
            "spec_values": [
                {"id": str(996874532588296900 + i + 18), "name": c,
                 "cpv_id": 0, "cpv_path": [], "img_url": None}
                for i, c in enumerate(colors)
            ]
        },
        {
            "id": "20000", "cp_id": 3939, "name": "码数",
            "spec_values": [{"id": "990897920130195435", "name": "均码",
                             "cpv_id": 0, "cpv_path": [], "img_url": None}]
        },
        {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
        {"id": "40000", "cp_id": 93,   "name": "规格",   "spec_values": []},
    ]
    color_ids = [sv["id"] for sv in spec_detail[0]["spec_values"]]
    size_id = spec_detail[1]["spec_values"][0]["id"]

    # -- sku_detail --
    sku_detail = []
    for i in range(len(colors)):
        sku_price = 9.9
        if i < len(sku_list):
            try:
                p = float(sku_list[i].get("price", 0))
                if p > 0: sku_price = p
            except: pass
        sku_stock = 100
        if i < len(sku_list):
            try:
                s = int(sku_list[i].get("stock", 0))
                if s > 0: sku_stock = s
            except: pass
        sid = f"{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:8]}"
        sku_detail.append({
            "id": sid,
            "stock_info": {"stock_num": sku_stock},
            "sku_status": True,
            "confirm_no_barcode": False,
            "spec_detail_ids": [color_ids[i], size_id],
            "price": str(sku_price),
        })

    # -- 描述 --
    desc_parts = []
    for u in image_urls.get("main_3x4", [])[:1]:
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    for u in image_urls.get("main_1x1", [])[:1]:
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    for u in image_urls.get("detail", []):
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    description = "<p>" + "".join(desc_parts) + "</p>" if desc_parts else ""

    # -- 组装 model --
    model = {}
    model["title"] = w(title)
    model["short_product_name"] = w("")
    model["title_prefix"] = w("")
    model["title_suffix"] = w("")
    model["title_use_brand_name"] = w(False)
    model["goods_category"] = w(category_config)
    model["category_properties"] = w(cp)
    model["category_property_pic"] = w({})
    model["pic"] = w([{"url": u} for u in image_urls.get("main_1x1", [])[:5]])
    model["main_image_three_to_four"] = w([{"url": u} for u in image_urls.get("main_3x4", [])[:5]])
    model["white_background_pic"] = w([{"url": image_urls.get("white", "")}] if image_urls.get("white") else [])
    model["description"] = w(description)
    model["spec_detail"] = w(spec_detail)
    model["sku_detail"] = w(sku_detail)
    model["freight_id"] = w("300713474")
    model["pickup_method"] = w("0")
    model["start_sale_type"] = w("0")
    model["product_type"] = w("0")
    model["presell_type"] = w("0")
    model["delivery_delay_day"] = w("2")
    model["reduce_type"] = w("1")
    model["qualification"] = w({})
    model["after_sale"] = w({"quality_problem_return": {"option_id": None, "selected": True},
                             "supply_day_return_selector": {"option_id": "7-1", "selected": True}})
    model["ai_gen_spec"] = w({"ai_gen_spec_type": 0})
    model["alli_promotion_plan_switch"] = w(False)
    model["area_stock_switcher"] = w(False)
    model["goods_category_appeal"] = w(False)
    model["interest_free_activity"] = w([])
    model["interest_free_activity_id"] = w({"activity_template_id": "IFA202508061521201431032346"})
    model["interest_free_open"] = w(True)
    model["reference_price_enable"] = w(False)
    model["detail_prettify_uri"] = w("")

    # -- 组装完整 body --
    now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_hex = "".join(random.choices("0123456789ABCDEF", k=20))
    n_token = now + random_hex

    sku_values = model.get("sku_detail", {}).get("value", [])
    min_price = 990
    for sku in sku_values:
        try:
            p = int(float(sku.get("price", "9.9")) * 100)
            if p < min_price: min_price = p
        except: pass

    feature = {
        "session_publish_id": f"helper_{publish_id}",
        "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
        "not_first_render": "1",
        "product_sale_property_control": "1",
        "sale_property_sequence_variable": "1",
        "min_sku_price": str(min_price),
    }

    context = {
        "ability": [],
        "biz_identity": "xiaodian",
        "business_code": "xiaodian",
        "capability_codes": ["standard_capability"],
        "category_id": str(category_leaf_id),
        "fast_publish_type": "",
        "feature": feature,
        "identity_extension": '{"Data":{}}',
        "model_type": "",
        "n_token": n_token,
        "operation_type": "normal",
        "product_id": "0",
        "shop_id": shop_id,
        "token": n_token,
        "version": "v1_v8_v9_v10_v11_v12",
    }

    body = {
        "schema": {"model": model, "context": context},
        "category_id": str(category_leaf_id),
        "context": context,
        "pass_through_extra": {},
        "request_extra": {},
        "check_status": 2,
        "session": {},
        "appid": 1,
    }

    body_size = len(json.dumps(body, ensure_ascii=False))
    print(f"[v4:body] 离线Body构造完成: {body_size}字节, {len(colors)}规格, {len(colors)}SKU")
    return {"success": True, "data": {"body": body, "body_size": body_size}}


# ============================================================
# 一键流水线
# ============================================================

def run(category_leaf_id, product_data, image_paths, category_config=None, shop_id=None, progress_callback=None):
    """执行完整协议发布流水线。

    Args:
        category_leaf_id: 叶子类目ID (如 1000010267 中筒袜)
        product_data: {title, sku_info: [{name, price, stock}], material}
        image_paths: {main_3x4: [...], main_1x1: [...], detail: [...]}
        category_config: 可选 {first_cid, first_cname, ...}
        shop_id: 可选
        progress_callback: 可选 callable(pct, msg, step_name, steps) 用于实时进度

    Returns:
        {success: bool, data: {product_id, steps: [...]}}
    """
    steps = []
    step_pcts = [10, 30, 50, 70, 90]  # 5个步骤的进度百分比

    def _step(name):
        t0 = time.time()
        entry = {"name": name, "status": "running"}
        steps.append(entry)
        return t0, entry

    def _done(entry, t0, ok, summary="", step_index=None):
        entry["elapsed_ms"] = int((time.time() - t0) * 1000)
        entry["status"] = "ok" if ok else "failed"
        if summary:
            entry["summary"] = summary
        # 调用进度回调 — 使用用户友好的步骤描述
        if progress_callback and step_index is not None and step_index < len(step_pcts):
            pct = step_pcts[step_index]
            status = "完成" if ok else "失败"

            # 步骤名 → 用户友好描述
            step_label_map = {
                "session": "建立会话连接",
                "upload_images": "上传商品图片",
                "inject_state": "写入商品信息",
                "read_state": "校验商品数据",
                "get_schema": "获取类目属性",
                "build_body_offline": "组装发布数据",
                "submit": "提交到平台",
            }
            friendly_name = step_label_map.get(entry["name"], entry["name"])
            step_msg = f"{'✓' if ok else '✗'} {friendly_name} ({entry['elapsed_ms']/1000:.1f}s)"
            # 不显示技术细节到主消息（summary 只在步骤列表里看）
            progress_callback(pct, step_msg, friendly_name, [{
                "name": step_label_map.get(s["name"], s["name"]),
                "status": s["status"], "elapsed_ms": s.get("elapsed_ms", 0),
                "summary": s.get("summary", "")
            } for s in steps])

    print(f"\n{'='*60}")
    print(f"[V4] 协议发布流水线启动")
    print(f"[V4] 标题: {product_data.get('title', '')[:50]}")
    print(f"[V4] 类目: {category_leaf_id}")
    print(f"[V4] SKU数: {len(product_data.get('sku_info', []))}")
    print(f"[V4] 图片: 3:4={len(image_paths.get('main_3x4',[]))} 1:1={len(image_paths.get('main_1x1',[]))} 详情={len(image_paths.get('detail',[]))}")

    # 图片预检
    img_check = validate_image_compliance(image_paths)
    if img_check["issues"]:
        print(f"[V4] 图片预检: {img_check['stats']['total']}张, {len(img_check['issues'])}个问题")
        for iss in img_check["issues"][:5]:
            print(f"  [{iss['level']}] {os.path.basename(iss['file'])}: {iss['detail']}")
        if not img_check["ok"]:
            return {**_mkerr("NO_IMAGES", detail=f"图片预检不通过: {img_check['issues'][0]['detail']}"), "steps": []}

    # 标题预检
    title_check = validate_title(product_data.get("title", ""))
    if not title_check["ok"]:
        print(f"[V4] 标题预检失败: {title_check['detail']}")
        return {**_mkerr("NO_TITLE", detail=title_check["detail"]), "steps": []}
    print(f"[V4] 标题预检: {title_check['detail']}")

    cdp = CDPSession()

    try:
        # [1/5] 会话
        t0, entry = _step("session")
        cdp.connect()
        session_res = step_session(cdp)
        if not session_res["success"]:
            _done(entry, t0, False, session_res["error"]["message"])
            return {**session_res, "steps": steps}
        session = session_res["data"]
        _done(entry, t0, True, f"publishId={session['publish_id'][:16]}...", step_index=0)

        # [2/5] 图片上传
        t0, entry = _step("upload_images")
        upload_res = step_upload_images(image_paths, session["cookie_str"])
        if not upload_res["success"]:
            _done(entry, t0, False, upload_res["error"]["message"], step_index=1)
            return {**upload_res, "steps": steps}
        image_urls = upload_res["data"]
        _done(entry, t0, True,
              f"3:4={len(image_urls['main_3x4'])} 1:1={len(image_urls['main_1x1'])} "
              f"detail={len(image_urls['detail'])}", step_index=1)

        # [可选] 白底图 AI 检测 (仅警告，不阻断)
        white_url = image_urls.get("white", "")
        if white_url:
            white_check = check_white_background_via_platform(cdp, white_url)
            print(f"[V4] {'✓' if white_check['ok'] else '⚠'} 白底图AI检测: {white_check['result']}")

        # [3/5] 状态注入 或 离线Body（双路径）
        schemaform_ok = _wait_schemaform(cdp, timeout=4)
        if schemaform_ok:
            # === React注入路径 ===
            t0, entry = _step("inject_state")
            inject_res = step_inject_state(cdp, product_data, image_urls, category_config)
            if not inject_res["success"]:
                _done(entry, t0, False, inject_res["error"]["message"], step_index=2)
                return {**inject_res, "steps": steps}
            _done(entry, t0, True, inject_res.get("data", {}).get("ok", ""), step_index=2)

            t0, entry = _step("read_state")
            read_res = step_read_state(cdp)
            _done(entry, t0, read_res["data"].get("readback_ok", False),
                  f"spec={read_res.get('data',{}).get('spec_count',0)} sku={read_res.get('data',{}).get('sku_count',0)}",
                  step_index=3)

            submit_body = None
            used_path = "react"
        else:
            # === 离线Body路径 (v2已验证) ===
            # 先获取 schema（获取真实 value_id）
            t0, entry = _step("get_schema")
            schema_res = step_get_schema_for_body(cdp, category_leaf_id, session["publish_id"])
            schema_data = schema_res.get("data") if schema_res["success"] else None
            if schema_data:
                _done(entry, t0, True, f"{len(schema_data.get('items',[]))}属性", step_index=2)
            else:
                _done(entry, t0, False, schema_res.get("error",{}).get("message",""), step_index=2)

            t0, entry = _step("build_body_offline")
            body_res = step_build_body_offline(product_data, image_urls,
                                                category_config or {},
                                                session["publish_id"],
                                                session.get("shop_id", shop_id or "155450371"),
                                                schema_data=schema_data)
            if not body_res["success"]:
                _done(entry, t0, False, body_res["error"]["message"], step_index=3)
                return {**body_res, "steps": steps}
            _done(entry, t0, True, f"{body_res['data']['body_size']}字节", step_index=3)
            submit_body = body_res["data"]["body"]
            used_path = "offline"

        # [5/5] 提交
        t0, entry = _step("submit")
        submit_res = step_submit(cdp, category_leaf_id,
                                 session["publish_id"],
                                 session.get("shop_id", shop_id or "155450371"),
                                 body_override=submit_body)
        if not submit_res["success"]:
            _done(entry, t0, False, submit_res["error"]["message"], step_index=4)
            return {**submit_res, "steps": steps}
        _done(entry, t0, True, f"product_id={submit_res['data']['product_id']} via={used_path}", step_index=4)

        print(f"[V4] 全部完成! product_id={submit_res['data']['product_id']} path={used_path}")
        return {
            "success": True,
            "data": {"product_id": submit_res["data"]["product_id"],
                     "raw": submit_res["data"].get("raw", ""),
                     "via": submit_res["data"].get("via", ""),
                     "path": used_path},
            "steps": steps,
        }

    except Exception as e:
        traceback.print_exc()
        err = _mkerr("SUBMIT_FAILED", detail=str(e)[:200])
        err["error"]["message"] = f"流水线异常: {str(e)[:150]}"
        err["error"]["fix_hint"] = "请检查Chrome是否在运行、网络是否正常，然后重试"
        err["steps"] = steps
        return err
    finally:
        cdp.close()


# ============================================================
# 命令行 / 测试入口
# ============================================================

if __name__ == "__main__":
    # 简单自测：使用默认参数
    test_product = {
        "title": "2026新款新年男士中筒袜礼盒装 刺绣条纹棉袜",
        "sku_info": [
            {"name": "细条纹+大宽条", "price": 19.9, "stock": 100},
            {"name": "大宽条+新年快乐", "price": 19.9, "stock": 100},
            {"name": "二杠+rich", "price": 19.9, "stock": 100},
        ],
        "material": "棉75%;氨纶25%",
    }

    # 查找测试图片目录
    test_image_dir = None
    for candidate in [
        r"E:\Script Project\Dyin\beiufen\2.0\项目备份 禁止改动使用 只参考\C-975",
    ]:
        if os.path.isdir(candidate):
            test_image_dir = candidate
            break

    if test_image_dir:
        image_paths = {"main_3x4": [], "main_1x1": [], "detail": []}
        # 750 → 3:4主图
        d750 = os.path.join(test_image_dir, "主图", "750")
        if os.path.isdir(d750):
            image_paths["main_3x4"] = [os.path.join(d750, f) for f in os.listdir(d750)
                                       if f.lower().endswith((".jpg", ".png", ".jpeg"))][:5]
        # 800 → 1:1主图
        d800 = os.path.join(test_image_dir, "主图", "800")
        if os.path.isdir(d800):
            image_paths["main_1x1"] = [os.path.join(d800, f) for f in os.listdir(d800)
                                       if f.lower().endswith((".jpg", ".png", ".jpeg"))][:5]
        # 详情图
        dimg = os.path.join(test_image_dir, "images")
        if os.path.isdir(dimg):
            image_paths["detail"] = [os.path.join(dimg, f) for f in os.listdir(dimg)
                                     if f.lower().endswith((".jpg", ".png", ".jpeg"))][:15]
        print(f"测试素材: {test_image_dir}")
        print(f"  3:4主图: {len(image_paths['main_3x4'])} 张")
        print(f"  1:1主图: {len(image_paths['main_1x1'])} 张")
        print(f"  详情图:  {len(image_paths['detail'])} 张")
    else:
        image_paths = {"main_3x4": [], "main_1x1": [], "detail": []}
        print("未找到测试素材目录，使用空图片列表")

    result = run(
        category_leaf_id=1000010267,  # 中筒袜
        product_data=test_product,
        image_paths=image_paths,
        category_config={
            "category_leaf_id": 1000010267,
            "first_cid": 1000003282, "first_cname": "服装",
            "second_cid": 1000009114, "second_cname": "内衣裤袜",
            "third_cid": 1000009597, "third_cname": "袜子",
            "fourth_cid": 1000010267, "fourth_cname": "中筒袜",
        },
    )

    print(f"\n{'='*60}")
    print(f"结果: {'成功' if result['success'] else '失败'}")
    if result["success"]:
        print(f"  product_id: {result['data']['product_id']}")
        print(f"  via: {result['data'].get('via', '')}")
    else:
        err = result.get("error", {})
        print(f"  code: {err.get('code', '?')}")
        print(f"  message: {err.get('message', '?')}")
        print(f"  hint: {err.get('hint', '')}")
    print(f"\n步骤耗时:")
    for s in result.get("steps", []):
        icon = "OK" if s["status"] == "ok" else "FAIL"
        print(f"  [{icon}] {s['name']}: {s['elapsed_ms']}ms {s.get('summary', '')}")
