# -*- coding: utf-8 -*-
"""淘宝**图片空间协议上传**契约层（纯计算，不发起任何请求）。

## 为什么需要这个模块

`page.py` 的 DOM 路线（点主图空位 → 素材中心 iframe → 塞 ``input[type=file]``
→ 点「完成」落库）已经实机跑通，但它有三个绕不过去的代价：

1. **必须停在填写页**：上传只存在于发布表单的弹层里，与商品填写强耦合；
2. **上传完才知道落地结果**：地址要等图片空间把卡片渲染出来再去 DOM 里捞；
3. **慢**：一道文件名一次点击，几十张图要几十个来回。

协议层直接对 ``stream-upload.taobao.com`` 发 multipart，能一次把整批送进去，
并且**当场拿到图片地址与 pictureId**（后面发布选图用得上）。

## 端点是怎么来的（证据等级）

``POST https://stream-upload.taobao.com/api/upload.api?appkey=tu&folderId=<目录ID>&watermark=false&picCompress=false&_input_charset=utf-8``

* ``verified`` —— 图片空间微模块的常量表原文（``upload:`` 唯一指向它）：
  ``g.alicdn.com/merchant-micro-mods/sucai-center-components/0.0.50/js/976.c39500ed.chunk.js``；
  同一份 bundle 里 ``PicUpload`` 把 query 与 ``multipart_params`` 一次性配给 Plupload：
  ``appkey: "tu"`` / ``folderId: parentId || "0"`` / ``watermark`` / ``picCompress`` /
  ``multipart_params = { ua }``。``sucai-batch-upload@0.0.17`` 里同一组参数再次出现，
  说明这是图片空间**统一的上传网关**。
* ``verified`` —— 旧版 selector chunk 里裁剪上传的 ``FormData`` 构造原文
  （``append("water","false")`` / ``append("name",新名)`` /
  ``append("_tb_token_",cookie值)`` / ``append("file",blob,新名)``）。
* ``verified`` —— 官方 plupload 封装自己拼同一 URL
  （host ``//stream.taobao.com`` + ``/api/upload.api``，``file_data_name="file"``）。
* ``verified`` —— 开源实现（只需 Cookie + folderId，读 ``response.object.url``）
  与第三方抓包原文的 multipart body 与上面逐字吻合。

详细取证与复跑命令见 ``docs/31-图片空间协议上传端点取证.md``。

**未取证的部分（不要当已知）**：普通上传分支的文件字段名与 ``ua`` 是否必需、
普通分支是否也要 ``_tb_token_``、真实 header 细节、并发与频率阈值、
超过 3MB 的图片走哪条路。这些在 :data:`CONTRACT_NOTES` 里逐条列出。

## 红线（本模块遵守）

* 本模块**只做纯计算与分类**，不读 cookie、不发请求、不写文件。
* 请求的发送由调用方（CDP 页面内 fetch 或注入的 HTTP 传输层）负责，
  凭据不进本模块的日志与产物。
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 证据等级
# ---------------------------------------------------------------------------
EVIDENCE_VERIFIED: str = "verified"
EVIDENCE_CANDIDATE: str = "candidate"
EVIDENCE_UNKNOWN: str = "unknown"
EVIDENCE_REJECTED: str = "rejected"
EVIDENCE_LEVELS: Tuple[str, ...] = (
    EVIDENCE_VERIFIED,
    EVIDENCE_CANDIDATE,
    EVIDENCE_UNKNOWN,
    EVIDENCE_REJECTED,
)


# ---------------------------------------------------------------------------
# 端点常量
# ---------------------------------------------------------------------------
#: 图片空间上传网关。**上传不是 mtop 调用**——bundle 里
#: ``mtop.taobao.picture.upload`` / ``mtop.taobao.pic.*`` / ``mtop.taobao.sucai.*``
#: 零命中（已证伪，见 :data:`CONTRACT_NOTES`）。
UPLOAD_HOST: str = "https://stream-upload.taobao.com"
#: 上传路径。
UPLOAD_PATH: str = "/api/upload.api"
#: 图片空间使用的 appkey。
UPLOAD_APP_KEY: str = "tu"
#: 表单编码。
UPLOAD_CHARSET: str = "utf-8"

#: multipart 里放文件的字段名（官方 SDK 的 ``file_data_name``）。
FIELD_FILE: str = "file"
#: multipart 里放文件名的字段名（与 ``file`` 同为文件名的字符串字段）。
FIELD_NAME: str = "name"
#: multipart 里放 CSRF token 的字段名（值取 cookie ``_tb_token_``）。
#: 只在裁剪上传分支的原文里出现；普通上传分支是否要求它**未取证**，
#: 因此不默认发送（见 :data:`CONTRACT_NOTES`）。
FIELD_TOKEN: str = "_tb_token_"
#: 水印开关字段（旧版 bundle 的裁剪分支里出现过）。
FIELD_WATER: str = "water"
FIELD_WATER_OFF_VALUE: str = "false"
#: UA 令牌字段。图片空间把 ``window.uabModule.getUA()`` 的结果放进
#: ``multipart_params.ua``；缺失是否被拒**未取证**。
FIELD_UA: str = "ua"

#: ``folderId`` 用哪个 query 参数传。
QUERY_FOLDER_ID: str = "folderId"
QUERY_APP_KEY: str = "appkey"
QUERY_CHARSET: str = "_input_charset"
QUERY_WATERMARK: str = "watermark"
QUERY_PIC_COMPRESS: str = "picCompress"

#: 图片空间**根目录**的 ID。bundle 原文：``folderId: i.getNative().parentId || "0"``，
#: 即没有父目录时用 ``"0"`` 表示「全部图片」这一层。
DEFAULT_FOLDER_ID: str = "0"

#: 图片空间目录/文件查询的 mtop api（证据等级 candidate，见文档）。
MTOP_API_DIR_QUERY: str = "mtop.taobao.picturecenter.console.dir.query"
MTOP_API_DIR_ADD: str = "mtop.taobao.picturecenter.console.dir.add"
MTOP_API_FILE_QUERY: str = "mtop.taobao.picturecenter.console.file.query"

#: 图片落地地址允许的 host 后缀。响应里的 ``object.url`` 必须命中其一，
#: 否则视为平台给了意料之外的地址，不能拿去做发布选图。
ALICDN_HOST_SUFFIXES: Tuple[str, ...] = (
    ".alicdn.com",
    ".taobaocdn.com",
    ".tbcdn.cn",
)

# ---------------------------------------------------------------------------
# 平台约束（bundle 原文，verified）
# ---------------------------------------------------------------------------
#: 一次请求最多几张。
MAX_FILES_PER_REQUEST: int = 200
#: 单张体积上限（字节）。3MB——bundle 原文的 ``-600`` 分支。
MAX_FILE_BYTES: int = 3 * 1024 * 1024
#: 允许的扩展名。
ALLOWED_SUFFIXES: Tuple[str, ...] = (".jpg", ".jpeg", ".gif", ".png", ".bmp")

# ---------------------------------------------------------------------------
# 平台返回码 → 本子项目错误码
# ---------------------------------------------------------------------------
ERROR_RATE_LIMITED: str = "VERIFICATION_REQUIRED"
ERROR_UPLOAD_FAILED: str = "IMAGE_UPLOAD_FAILED"
ERROR_NOT_AUTHORIZED: str = "WRITE_NOT_AUTHORIZED"
ERROR_PLATFORM: str = "PLATFORM_ERROR"

#: 命中即表示「平台限流，必须人工过验证码」。处理方式固定为**停手，不重试**：
#: 生产 bundle 里拿到这个码就是 ``stop()``，重试只会把风控窗口拖长。
RATE_LIMIT_CODES: Tuple[str, ...] = ("BAXIA_BLOCKED",)
#: 风控文案/标记。**每一条都是实测撞到的**：
#:
#: * ``BAXIA_BLOCKED`` / ``滑动验证`` —— 上传面板里看到的文案（DOM 路线实测）；
#: * ``FAIL_SYS_USER_VALIDATE`` + ``RGV587_ERROR`` —— **协议上传**被拦时平台回的
#:   ``ret``（实测原文：``FAIL_SYS_USER_VALIDATE`` + ``RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试``）。
#:   这个形态最初没被识别，于是「需要人工验证」被误报成「平台未给原因」，
#:   流水线还会继续把剩下的几十张挨个撞一遍——**这是必须修的分类缺陷**；
#: * ``x5secdata`` / ``_____tmd_____`` / ``punish`` / ``action=captcha`` ——
#:   同一次响应里给出的验证页地址与参数（``data.url``）。
RATE_LIMIT_MARKERS: Tuple[str, ...] = (
    "BAXIA_BLOCKED",
    "FAIL_SYS_USER_VALIDATE",
    "RGV587_ERROR",
    "滑动验证",
    "操作过于频繁",
    "验证码",
    "x5secdata",
    "_____tmd_____",
    "action=captcha",
    "pureCaptcha",
)

#: 平台业务码 → 中文原因。只列出 bundle 原文里出现过的。
#:
#: 说明：``-9001`` 的原文语义是「一次最多 200 张」，不是「文件太大」；
#: 这里如实照抄，不做「更合理的推测」。
PLATFORM_CODE_REASONS: Dict[str, str] = {
    "-600": "单张图片超过大小上限（3MB）",
    "-601": "图片格式不被接受（允许 jpg/jpeg/gif/png/bmp）",
    "-9001": "单次上传数量超过上限（最多 200 张）",
}

#: 容量不足分支的文案标记。
QUOTA_MARKERS: Tuple[str, ...] = ("容量不足", "空间不足", "容量已满")

#: 图片空间的尺寸/比例约束接口（candidate，用于上传前预检）。
PAGE_CONFIG_URL: str = "https://sucai.wangpu.taobao.com/getPageConfig.do"

#: 契约里仍然没有证据的部分。必须如实列出，**不允许用默认值掩盖**。
CONTRACT_NOTES: Tuple[Dict[str, str], ...] = (
    {
        "item": "上传请求必须从**与端点同源**的页面发出",
        "evidence_level": EVIDENCE_VERIFIED,
        "detail": "实测：在 `item.upload.taobao.com` / `qn.taobao.com` 页面里向上传端点发 "
                  "fetch，被浏览器判 `TypeError: Failed to fetch`（跨源 CORS）；"
                  "把工作页开在 `stream-upload.taobao.com` 上即成功。见 upload_page.open_session",
    },
    {
        "item": "`_tb_token_` 必须是真实值",
        "evidence_level": EVIDENCE_VERIFIED,
        "detail": "实测：假值（`x`）得到 **404**（Tomcat 错误页）；真实值（12 字符）进业务并成功。"
                  "token 从 CDP `Storage.getCookies` 读——页面脚本读 document.cookie 在素材中心页会抛 "
                  "`SecurityError: Access is denied for this document`",
    },
    {
        "item": "平台按图片规则校验内容，且失败也是 HTTP 200",
        "evidence_level": EVIDENCE_VERIFIED,
        "detail": "实测：1×1 图被判 `NOT_ALLOW_UPLOAD_1x1_IMAGE`，3 字节假 blob 被判 "
                  "`TYPE_NOT_CONFIRMED`——两者都是 **HTTP 200 + success:false**。"
                  "所以成功判据必须同时看状态码与 `success`",
    },
    {
        "item": "上传接口有两条 body 构造，本模块按哪条发",
        "evidence_level": EVIDENCE_VERIFIED,
        "detail": "bundle 原文里有两条：(A) 显式 FormData——body 有 water/name/_tb_token_/file；"
                  "(B) Plupload 普通本地上传——body 里只显式放 ua。**本模块按 (A) 发，且已真机跑通**："
                  "只带 `water` 就能进业务，加 `name` 无影响，"
                  "`_tb_token_` 必须真实（假值 404）",
    },
    {
        "item": "(B) Plupload 路径是否携带 cookie 与 ua 是否必需",
        "evidence_level": EVIDENCE_UNKNOWN,
        "detail": "本仓库走 (A) 且已成功，因此 (B) 的这两个问题不再影响可用性；"
                  "只有当平台改回 Plupload 主路径时才需要重新取证",
    },
    {
        "item": "上传频率与并发阈值",
        "evidence_level": EVIDENCE_UNKNOWN,
        "detail": "只有前端口径（超频文案 BAXIA_BLOCKED），没有可复现的阈值数据；"
                  "因此本模块不自动重试",
    },
    {
        "item": "超过 3MB 的图片走哪条路",
        "evidence_level": EVIDENCE_UNKNOWN,
        "detail": "bundle 里大文件走 mtop.taobao.mediacenter.pc.image.upload.init → "
                  "服务端下发 uploadUrlList 逐片 PUT(application/octet-stream) → "
                  "mtop...upload.complete；uploadUrlList 的 host 与签名形态必须真机才拿得到，"
                  "本模块暂不实现该分支（商品图实际都小于 3MB）",
    },
    {
        "item": "图片空间产品服务协议是否阻断上传",
        "evidence_level": EVIDENCE_VERIFIED,
        "detail": "实测：本次上传**没有被协议拦下**（该账号已签）。"
                  "未签账号是否被拦仍未知——相关 api："
                  "mtop.taobao.seller.content.pic.protocol.query / protocol.sign",
    },
    {
        "item": "mtop.taobao.picturecenter.console.* 自己调用不可用",
        "evidence_level": EVIDENCE_REJECTED,
        "detail": "四种形态（POST+body / GET+query / JSONP / 带真实 ttid）全部实测返回 "
                  "`FAIL_SYS_ILLEGAL_ACCESS::非法请求`，而同一 api 在浏览器里每次都成功 → "
                  "自己拼调用这条路**已证伪**。目录与文件清单改用已跑通的 DOM 路线；"
                  "协议上传本身不依赖它（`folderId=0` 即根目录）",
    },
)

#: 已证伪的路线。**不要重试**。
REJECTED_ROUTES: Tuple[Dict[str, str], ...] = (
    {
        "route": "图片上传走 mtop（mtop.taobao.picture.upload 等）",
        "rejected_by": "生产 bundle 与 selector chunk 里 mtop.*upload* 零命中",
    },
    {
        "route": "sucai.taobao.com 是图片空间",
        "rejected_by": "实测 title 为「TOP素材网」店铺首页",
    },
    {
        "route": "sc.taobao.com 是图片空间",
        "rejected_by": "实测 404",
    },
    {
        "route": "imgbank.taobao.com 是图片空间",
        "rejected_by": "实测 302 到「无此店铺」",
    },
    {
        "route": "taobao.picture.upload（picture_category_id/base64_image）可用于网页链路",
        "rejected_by": "那是开放平台服务端接口（eco.taobao.com/router/rest + 授权），"
                       "集市卖家自研走不通，只能当响应语义参考",
    },
)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class UploadEndpoint:
    """一次上传的目标 URL 与查询参数。

    ``folder_id`` 为空时退回 :data:`DEFAULT_FOLDER_ID`（``"0"`` = 图片空间根目录）。
    这个默认值**不是猜的**：bundle 原文就是 ``parentId || "0"``，
    即「没有父目录时用 0」。但「传 0 会不会落到某个奇怪的位置」仍未实测，
    所以调用方应当显式给出商品目录 ID；只有在确实要传到根目录时才省略。

    :param allow_insecure_host: 只在**离线演练**时打开（本地 mock 服务端是
        ``http://127.0.0.1``）。真实上传必须保持 ``False``：契约 host 是
        ``https``，把 http 放进来等于把「用明文发图」变成可能。
    """

    host: str = UPLOAD_HOST
    path: str = UPLOAD_PATH
    folder_id: str = ""
    app_key: str = UPLOAD_APP_KEY
    charset: str = UPLOAD_CHARSET
    watermark: bool = False
    compress: bool = False
    extra_query: Tuple[Tuple[str, str], ...] = ()
    allow_insecure_host: bool = False

    def _assert_host_allowed(self) -> None:
        if self.allow_insecure_host:
            return
        if not str(self.host).startswith("https://"):
            raise ValueError(
                f"上传端点必须是 https（当前 {self.host!r}）："
                "离线演练请显式传 allow_insecure_host=True，真实上传不允许明文"
            )

    def build_url(self) -> str:
        """拼出带 query 的完整 URL。

        参数顺序与 bundle 原文一致（``appkey`` → ``folderId`` → ``watermark``
        → ``picCompress`` → ``_input_charset``）。顺序没有契约意义，
        但对齐原文能让抓包对照更容易。
        """

        from urllib.parse import urlencode

        self._assert_host_allowed()
        folder = (self.folder_id or "").strip() or DEFAULT_FOLDER_ID
        query: List[Tuple[str, str]] = [
            (QUERY_APP_KEY, self.app_key),
            (QUERY_FOLDER_ID, folder),
            (QUERY_WATERMARK, "true" if self.watermark else "false"),
            (QUERY_PIC_COMPRESS, "true" if self.compress else "false"),
            (QUERY_CHARSET, self.charset),
        ]
        query.extend((str(key), str(value)) for key, value in self.extra_query)
        return f"{self.host}{self.path}?{urlencode(query)}"

    def describe(self) -> Dict[str, Any]:
        """脱敏描述：只回 host/path 与参数名，不回 query 原文。"""

        return {
            "host": self.host,
            "path": self.path,
            "app_key": self.app_key,
            "query_keys": [
                QUERY_APP_KEY, QUERY_FOLDER_ID, QUERY_WATERMARK, QUERY_PIC_COMPRESS, QUERY_CHARSET,
            ],
            "folder_id": (self.folder_id or "").strip() or DEFAULT_FOLDER_ID,
            "watermark": self.watermark,
            "compress": self.compress,
            "evidence_level": EVIDENCE_VERIFIED,
        }


# ---------------------------------------------------------------------------
# 上传前的本地护栏
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class UploadCandidate:
    """一张准备上传的本地图片。``name`` 是**上传到图片空间后的文件名**。"""

    path: str
    name: str
    size: int
    sha256: str = ""

    def validate(self) -> None:
        """体积 / 格式 / 文件名三道护栏，全部在**发出请求之前**。

        早检查的理由：平台对这三项各有自己的拒绝码（``-600`` / ``-601`` /
        ``-9001``），但等到平台拒绝时整批已经发出去一半，回执会变成
        「一部分成功、一部分失败」的混合态。本地能判的就在本地判。
        """

        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("上传候选缺少本地路径")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("上传候选缺少上传文件名")
        if self.name != self.name.strip():
            raise ValueError(f"上传文件名首尾不能有空白：{self.name!r}")
        if type(self.size) is not int or self.size <= 0:
            raise ValueError(f"上传文件大小非法：{self.size!r}")
        if self.size > MAX_FILE_BYTES:
            raise ValueError(
                f"单张图片超过平台上限 3MB：{self.name}（{self.size} 字节）"
            )
        suffix = _suffix_of(self.name)
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"图片格式不在平台允许范围内：{self.name}"
                f"（允许 {'/'.join(item.lstrip('.') for item in ALLOWED_SUFFIXES)}）"
            )

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


def _suffix_of(name: str) -> str:
    index = name.rfind(".")
    return name[index:].lower() if index >= 0 else ""


#: Windows 保留名。上传文件名与本地文件名一致时会被平台记成这个名字，
#: 不是必须拒绝，但值得在预检里报出来。
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

#: 文件名里不允许出现的字符（路径分隔符 + Windows 非法字符 + 控制字符）。
_ILLEGAL_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def validate_upload_name(name: str) -> str:
    """校验**上传到图片空间的文件名**。

    与 ``page.upload_files_to_media`` 的同名守卫保持一致（不允许路径分隔符），
    但额外拒绝 ``..`` 与 Windows 保留名——这两个在图片空间侧的表现未知，
    与其让平台静默改名，不如本地就报出来。
    """

    if not isinstance(name, str) or not name.strip():
        raise ValueError("上传文件名不能为空")
    if name != name.strip():
        raise ValueError(f"上传文件名首尾不能有空白：{name!r}")
    if _ILLEGAL_NAME_CHARS.search(name):
        raise ValueError(f"上传文件名含非法字符：{name!r}")
    if name in (".", ".."):
        raise ValueError("上传文件名不能是 . 或 ..")
    stem = name[: name.rfind(".")] if "." in name else name
    if stem.strip().lower() in _RESERVED_NAMES:
        raise ValueError(f"上传文件名是系统保留名：{name!r}")
    if len(name.encode("utf-8")) > 200:
        raise ValueError(f"上传文件名过长：{name!r}")
    return name


def check_batch(files: Sequence[UploadCandidate]) -> None:
    """整批护栏：非空、数量上限、文件名唯一。"""

    if not files:
        raise ValueError("上传批为空")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise ValueError(
            f"单次上传 {len(files)} 张，超过平台上限 {MAX_FILES_PER_REQUEST} 张；请分批"
        )
    seen: Dict[str, int] = {}
    for candidate in files:
        candidate.validate()
        validate_upload_name(candidate.name)
        seen[candidate.name] = seen.get(candidate.name, 0) + 1
    duplicated = sorted(name for name, count in seen.items() if count > 1)
    if duplicated:
        # 同名同目录在图片空间里怎么表现没有取证。**不自动改名**——
        # 改名会让「上传回执」与「本地文件」的对应关系断掉，后续选图就选错。
        raise ValueError(
            "同一批里出现重复的上传文件名，无法保证回执与本地文件一一对应："
            + "、".join(duplicated[:5])
        )


# ---------------------------------------------------------------------------
# multipart 编码
# ---------------------------------------------------------------------------
def new_boundary() -> str:
    """生成 multipart 分隔串。用 ``secrets`` 而不是固定串：同一批里两次
    请求的分隔串不应该相同（服务端把分隔串当数据边界的唯一依据）。"""

    return "----WebKitFormBoundary" + secrets.token_hex(12)


def _quote_field_name(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def encode_multipart(
    fields: Sequence[Tuple[str, str]],
    files: Sequence[Tuple[str, str, str]],
    *,
    boundary: str,
) -> bytes:
    """编码 ``multipart/form-data`` 请求体。

    :param fields: ``(字段名, 值)`` 的普通文本字段。
    :param files: ``(字段名, 上传文件名, 文件路径)`` 的文件字段。
    :param boundary: 分隔串；必须与 ``Content-Type`` 里的一致。

    与 ``requests`` / ``urllib3`` 的实现对齐的三点细节（都踩过）：

    1. 每个 part 之间是 ``\\r\\n--boundary``，**最后**一个 part 后面是
       ``--boundary--``；
    2. 文件 part 的 ``Content-Type`` 缺失时严格的服务端会当成文本处理，
       所以这里按扩展名补一个 image/*；
    3. 文件名只做 ``"`` 与 ``\\`` 的转义，不做 RFC 5987 编码——
       淘系的 SDK 也是这么发的，改了反而对不上。
    """

    if not isinstance(boundary, str) or not boundary or "\r" in boundary or "\n" in boundary:
        raise ValueError("multipart 分隔串非法")
    delimiter = boundary.encode("utf-8")
    body = bytearray()
    for name, value in fields:
        body += b"--" + delimiter + b"\r\n"
        body += b'Content-Disposition: form-data; name="' + _quote_field_name(name).encode("utf-8") + b'"\r\n\r\n'
        body += str(value).encode("utf-8") + b"\r\n"
    for name, filename, path in files:
        content_type = _content_type_for(filename)
        with open(path, "rb") as stream:
            payload = stream.read()
        body += b"--" + delimiter + b"\r\n"
        body += (
            b'Content-Disposition: form-data; name="' + _quote_field_name(name).encode("utf-8")
            + b'"; filename="' + _quote_field_name(filename).encode("utf-8") + b'"\r\n'
        )
        body += b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n"
        body += payload + b"\r\n"
    body += b"--" + delimiter + b"--\r\n"
    return bytes(body)


def _content_type_for(filename: str) -> str:
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    return mapping.get(_suffix_of(filename), "application/octet-stream")


def build_request_body(
    candidate: UploadCandidate,
    *,
    token: str,
    boundary: str,
) -> Tuple[bytes, str]:
    """为**单张**图片构造请求体，返回 ``(body, content_type)``。

    这里发的是 bundle 里那条**显式 FormData** 的形态（裁剪/替换/AI 上传三处都有
    同一组字段的原文）::

        form.append("water", "false")
        form.append("name",  "<文件名>.<ext>")
        form.append("_tb_token_", <cookie 里的 _tb_token_>)
        form.append("file", blob, "<文件名>.<ext>")

    另一条路（Plupload 普通本地上传）的 body 由 Plupload 自己组，原文里只显式放了
    ``ua``（``window.uabModule.getUA({Token})`` 的返回值）——那个令牌无法离线复现，
    而且它的文件字段名在原文里查不到。两条路都写不通的地方在
    :data:`CONTRACT_NOTES` 里列着，**不用默认值糊过去**。

    :param boundary: 分隔串。真实上传用 :func:`new_boundary`；浏览器路线由
        ``FormData`` 自己生成（见 ``upload_page``）。
    """

    if not isinstance(token, str) or not token.strip():
        raise ValueError("缺少 _tb_token_：图片空间上传要求该字段参与表单")
    candidate.validate()
    fields = [
        (FIELD_WATER, FIELD_WATER_OFF_VALUE),
        (FIELD_NAME, candidate.name),
        (FIELD_TOKEN, token),
    ]
    body = encode_multipart(fields, [(FIELD_FILE, candidate.name, candidate.path)], boundary=boundary)
    return body, f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# 响应解析与分类
# ---------------------------------------------------------------------------
#: 成功响应里图片地址的候选键路径（按优先级）。
_URL_KEY_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("object", "url"),
    ("object", "fullUrl"),
    ("url",),
    ("picUrl",),
)
#: pictureId / fileId 的候选键路径。
_ID_KEY_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("object", "fileId"),
    ("object", "pictureId"),
    ("object", "id"),
    ("pictureId",),
)


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    """一张图片的**上传回执**——协议路线的核心产出。"""

    name: str
    url: str
    picture_id: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    folder_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "picture_id": self.picture_id,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "folder_id": self.folder_id,
        }


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    """一次上传的分类结果。失败时**必须**带平台原文，不允许只说「失败」。"""

    ok: bool
    receipt: Optional[UploadReceipt] = None
    error_code: str = ""
    message: str = ""
    platform_code: str = ""
    platform_message: str = ""
    stopped: bool = False
    """是否属于「必须停手」的失败（限流 / 风控）。为 ``True`` 时调用方
    不得继续上传后续文件，也不得重试。"""

    challenge_url: str = ""
    """平台给出的人工验证入口（风控响应 ``data.url``）。

    **它是平台自己给的、你本人去完成验证的地址**，不是绕过路径：
    打开它、按提示验证，然后从断点继续。已完成的 ``_tb_token_`` 会让后续请求恢复正常。
    """

    challenge_step: int = 0
    """验证步骤（``x5step``）；平台没给时为 0。"""

    retry_allowed: bool = False
    """本模块**从不**建议自动重试；这个字段恒为 ``False``，保留它只是为了让
    调用方显式看到「平台限流不能靠重试解决」这个结论。"""

    def describe(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error_code": self.error_code,
            "message": self.message,
            "platform_code": self.platform_code,
            "platform_message": self.platform_message,
            "stopped": self.stopped,
            "retry_allowed": self.retry_allowed,
            "challenge_url": self.challenge_url,
            "challenge_step": self.challenge_step,
            "receipt": self.receipt.to_dict() if self.receipt else None,
        }


def image_identity(url: str) -> str:
    """取图片地址里**稳定的资源标识**。

    ## 为什么不能逐字比 URL（实机踩过）

    同一个图片资源在不同场景是**不同 URL 形态**：

    * 上传回执给的是原图地址：``…/O1CN012vpW9ytISlG1chua_!!2214966481149.jpg``
    * 图库卡片渲染的是带处理参数的：
      ``…/O1CN012vpW9ytISlG1chua_!!2214966481149.jpg_320x320?t=…``
      甚至 ``…_320x320q80_.webp``（转码成 webp）

    按"逐字相等"判定身份，就会把**同一张图**判成不一致——协议路线因此
    报 `MEDIA_IMAGE_MISSING` / `ambiguous`，整条流水线停在选图前。

    稳定的是 ``O1CN…`` 那一段（含它所属的 ``iN`` 分区前缀），它在缩略、转码、
    加参数之后都不变。所以身份取它。

    :return: 资源标识；取不到时返回空串（调用方必须把空串当**无法确认身份**）。
    """

    if not isinstance(url, str):
        return ""
    text = url.strip()
    if not text:
        return ""
    import re

    match = re.search(r"(/imgextra/[^/]+/)(O1CN[\w-]+)", text)
    if match:
        return match.group(1) + match.group(2)
    # 退一步：任何 O1CN 开头的段
    match = re.search(r"(O1CN[\w-]+)", text)
    if match:
        return match.group(1)
    return ""


#: 可按「同一资源」忽略的查询参数名。
#:
#: 只放**时间戳 / 缓存击穿**这类平台自己加的噪声参数。**不能全部忽略**：
#: 像 ``version`` 这种参数变了通常意味着**指向另一个资源**——
#: 实测有一处既有测试正是靠 ``version=`` → ``changed=`` 来断言"内容变了必须报错"，
#: 把查询串整个丢掉会放过真实差异（判据过宽）。
_VOLATILE_QUERY_KEYS = frozenset({
    "t", "ts", "_", "time", "timestamp", "v", "_t", "cache", "_v",
})


def _url_without_volatile_query(url: str) -> str:
    """去掉只影响缓存的查询参数，保留其余（含路径与文件名）。"""

    text = str(url or "").strip()
    if "?" not in text:
        return text
    base, _, query = text.partition("?")
    kept = [
        part for part in query.split("&")
        if part and part.split("=", 1)[0].strip().lower() not in _VOLATILE_QUERY_KEYS
    ]
    return base if not kept else base + "?" + "&".join(kept)


def same_image(left: str, right: str) -> bool:
    """两个地址是否指向**同一张图**。

    判据分两层（实机踩出来的边界）：

    1. **两边都能取到资源标识**（``O1CN…``）→ 按标识比。
       这是主路径：缩略、webp 转码、带时间戳都能判成同一张。
    2. **取不到标识时退回逐字比较**（只忽略时间戳/缓存类查询参数）。

       为什么不是"取不到就判否"：**不是所有图片地址都长成 imgextra 形态**
       ——仓库里既有测试、离线演练里用的都是普通 https 地址。把它们一律判成
       "不同"会让既有用例失败，也会让真实场景里形态不同的地址互相误杀。
       退回逐字比较是**保守且可解释**的：只有"路径 + 非缓存参数"完全一样才算同一张，
       ``version=`` 这类**语义参数不同仍然判不一致**。

    两边都为空时返回 ``False``。
    """

    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if not left.strip() or not right.strip():
        return False
    identity_left, identity_right = image_identity(left), image_identity(right)
    if identity_left and identity_right:
        return identity_left == identity_right
    # 百分号编码是**传输编码**，不是资源差异：浏览器在 DOM 里会把中文文件名编码成
    # ``%E6%B5%8B…``，而上传回执/账本里存的是原始字符——逐字比会把同一个地址
    # 判成两张图（2026-10-08 离线夹具实测踩过）。先解码再比。
    from urllib.parse import unquote
    return (_url_without_volatile_query(unquote(left))
            == _url_without_volatile_query(unquote(right)))


def _challenge_of(payload: Any) -> Tuple[str, int]:
    """从风控响应里取人工验证入口：``data.url`` 与 ``x5step``。

    实测原文形如::

        {"ret":["FAIL_SYS_USER_VALIDATE","RGV587_ERROR::SM::…"],
         "data":{"url":"…/_____tmd_____/punish?x5secdata=…&x5step=2&action=captcha&pureCaptcha="}}

    这里**只把平台给的地址原样交出去**，由本人去打开完成验证；
    不做任何探测、改写或绕过。取不到时返回空串。
    """

    if not isinstance(payload, Mapping):
        return "", 0
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return "", 0
    url = data.get("url")
    if not isinstance(url, str) or not url.strip():
        return "", 0
    step = 0
    match = re.search(r"[?&]x5step=(\d+)", url)
    if match:
        try:
            step = int(match.group(1))
        except ValueError:
            step = 0
    return url.strip(), step


def extract_json_payload(text: Optional[str]) -> Tuple[Optional[Any], str]:
    """从响应文本里取出 JSON 对象。

    为什么要这么麻烦：风控/异常时淘系返回的是**HTML**（``<pre>`` 里裹着 JSON），
    而 HTTP 状态码仍然是 200。SDK 自己就写了从 ``pre-wrap;">…</pre>`` 抠 JSON
    的兜底逻辑——这是平台的既有行为，不是我们多此一举。

    :return: ``(payload, note)``；解析不出来时 ``payload`` 为 ``None``。
    """

    if text is None:
        return None, "响应为空"
    raw = str(text).strip()
    if not raw:
        return None, "响应为空"
    import json

    try:
        return json.loads(raw), "json"
    except (ValueError, TypeError):
        pass
    match = re.search(r"<pre[^>]*>(.*?)</pre>", raw, re.DOTALL | re.IGNORECASE)
    if match:
        import html
        import json as _json

        candidate = html.unescape(match.group(1)).strip()
        try:
            return _json.loads(candidate), "pre_block"
        except (ValueError, TypeError):
            return None, "pre 块不是 JSON"
    return None, "响应不是 JSON"


def _dig(payload: Any, key_path: Sequence[str]) -> Any:
    node = payload
    for key in key_path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _first_url(payload: Any) -> str:
    for key_path in _URL_KEY_PATHS:
        value = _dig(payload, key_path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_id(payload: Any) -> str:
    for key_path in _ID_KEY_PATHS:
        value = _dig(payload, key_path)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def _first_int(payload: Any, key_path: Sequence[str]) -> int:
    value = _dig(payload, key_path)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _parse_pixel(payload: Any, *, index: int) -> int:
    """解析 ``object.pix`` 的 ``"800x800"`` 形态。

    平台把宽高塞在一个字符串里（bundle 里字段名是 ``pix``），不是两个数字字段。
    解析不出来时返回 0——**不猜**，调用方看到 0 就知道没读到。
    """

    value = _dig(payload, ("object", "pix"))
    if not isinstance(value, str):
        return 0
    parts = [part.strip() for part in value.lower().split("x")]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return 0
    return int(parts[index])


def validate_image_url(url: str) -> str:
    """校验上传回执里的图片地址。

    只接受 ``https`` 且 host 命中 :data:`ALICDN_HOST_SUFFIXES`、无凭据的地址。
    这不是「多疑」：图片地址会被写进商品的素材引用，一个带来路不明的地址
    会变成外链盗图（历史上被平台判过盗链）。
    """

    if not isinstance(url, str) or not url.strip():
        raise ValueError("图片地址为空")
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise ValueError(f"图片地址必须是 https：{parsed.scheme or '(无 scheme)'}")
    if parsed.username or parsed.password:
        raise ValueError("图片地址不允许携带凭据")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("图片地址缺少 host")
    if not any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in ALICDN_HOST_SUFFIXES):
        raise ValueError(f"图片地址不在淘宝 CDN 白名单内：{host}")
    return url.strip()


def classify_upload_response(
    *,
    http_status: int,
    text: Optional[str],
    name: str,
    folder_id: str = "",
) -> UploadOutcome:
    """把一次上传响应分类成 :class:`UploadOutcome`。

    判定顺序（**缺一不可**，只看 HTTP 200 会把风控页当成功）：

    1. HTTP 不是 200 → 失败（平台错误，保留状态码）；
    2. 文本里命中限流/验证码标记 → ``VERIFICATION_REQUIRED`` +
       ``stopped=True``（**停手，不重试**）；
    3. 不是 JSON（含 ``pre`` 块兜底）→ 失败；
    4. ``success`` 不是真值 → 按 ``errorCode`` 分类；
    5. 有 URL → 校验地址形态后产出回执；没有 URL → 失败（不拿假的地址凑).
    """

    payload, note = extract_json_payload(text)
    raw_text = "" if text is None else str(text)

    if http_status != 200:
        return UploadOutcome(
            ok=False,
            error_code=ERROR_PLATFORM,
            message=f"上传接口返回 HTTP {http_status}",
            platform_message=raw_text[:300],
        )

    lowered = raw_text.lower()
    hit_marker = next((marker for marker in RATE_LIMIT_MARKERS if marker.lower() in lowered), "")
    if payload is None and hit_marker:
        return UploadOutcome(
            ok=False,
            error_code=ERROR_RATE_LIMITED,
            message="平台返回风控页（HTTP 200 但内容不是 JSON）：" + hit_marker,
            platform_message=raw_text[:300],
            stopped=True,
        )

    if payload is None:
        return UploadOutcome(
            ok=False,
            error_code=ERROR_UPLOAD_FAILED,
            message=f"上传响应无法解析为 JSON（{note}）",
            platform_message=raw_text[:300],
        )

    if not isinstance(payload, Mapping):
        return UploadOutcome(
            ok=False,
            error_code=ERROR_UPLOAD_FAILED,
            message="上传响应不是 JSON 对象",
            platform_message=raw_text[:300],
        )

    success = payload.get("success")
    error_code_raw = str(payload.get("errorCode") or payload.get("code") or "").strip()
    platform_message = str(
        payload.get("errorMsg") or payload.get("message") or payload.get("msg") or ""
    ).strip()
    # ⚠️ 风控**不一定**走 ``success`` 字段：协议上传被拦时平台回的是
    # ``{"ret":["FAIL_SYS_USER_VALIDATE","RGV587_ERROR::SM::…"],"data":{"url":"…/punish?…"}}``
    # ——既没有 ``success`` 也没有 ``errorCode``。所以这里要**先**把 ``ret`` 与
    # 整段原文一起查一遍，否则会把「需要人工验证」误报成「平台未给原因」，
    # 还会继续把剩下的图挨个撞上去。
    ret_text = ""
    raw_ret = payload.get("ret")
    if isinstance(raw_ret, str):
        ret_text = raw_ret
    elif isinstance(raw_ret, (list, tuple)):
        ret_text = " ".join(str(item) for item in raw_ret)
    risk_haystack = " ".join((ret_text, platform_message, raw_text))
    if error_code_raw in RATE_LIMIT_CODES or any(
        marker in risk_haystack for marker in RATE_LIMIT_MARKERS
    ):
        detail = platform_message or ret_text or error_code_raw or "平台未给原因"
        challenge_url, challenge_step = _challenge_of(payload)
        return UploadOutcome(
            ok=False,
            error_code=ERROR_RATE_LIMITED,
            message="平台风控拦截，需要人工完成验证后才能继续："
                    + detail
                    + "（已停止本批剩余上传，且不会自动重试）",
            platform_code=error_code_raw or ret_text.split("::", 1)[0],
            platform_message=platform_message or ret_text,
            stopped=True,
            challenge_url=challenge_url,
            challenge_step=challenge_step,
        )

    if success is not True:
        reason = PLATFORM_CODE_REASONS.get(error_code_raw, "")
        if not reason:
            reason = next((text for text in QUOTA_MARKERS if text in platform_message), "")
        detail = platform_message or error_code_raw or "平台未给原因"
        if reason:
            detail = f"{reason}（平台原文：{detail}）"
        return UploadOutcome(
            ok=False,
            error_code=ERROR_UPLOAD_FAILED,
            message=detail,
            platform_code=error_code_raw,
            platform_message=platform_message,
        )

    url = _first_url(payload)
    if not url:
        return UploadOutcome(
            ok=False,
            error_code=ERROR_UPLOAD_FAILED,
            message="平台返回成功但响应里没有图片地址，不能拿它去选图",
            platform_code=error_code_raw,
            platform_message=platform_message,
        )
    try:
        url = validate_image_url(url)
    except ValueError as exc:
        return UploadOutcome(
            ok=False,
            error_code=ERROR_UPLOAD_FAILED,
            message=f"平台返回的图片地址不可用：{exc}",
            platform_code=error_code_raw,
            platform_message=platform_message,
        )

    receipt = UploadReceipt(
        name=name,
        url=url,
        picture_id=_first_id(payload),
        size=_first_int(payload, ("object", "size")),
        width=_parse_pixel(payload, index=0) or _first_int(payload, ("object", "width")),
        height=_parse_pixel(payload, index=1) or _first_int(payload, ("object", "height")),
        folder_id=folder_id,
    )
    return UploadOutcome(ok=True, receipt=receipt)


def contract_summary() -> Dict[str, Any]:
    """把契约摊开给调用方/CLI/文档用，避免各处硬编码一份。"""

    return {
        "endpoint": {
            "method": "POST",
            "host": UPLOAD_HOST,
            "path": UPLOAD_PATH,
            "query": {
                QUERY_APP_KEY: UPLOAD_APP_KEY,
                QUERY_FOLDER_ID: f"<图片空间目录 ID；缺省 {DEFAULT_FOLDER_ID}（根目录）>",
                QUERY_WATERMARK: "false",
                QUERY_PIC_COMPRESS: "false",
                QUERY_CHARSET: UPLOAD_CHARSET,
            },
            "content_type": "multipart/form-data",
            "evidence_level": EVIDENCE_VERIFIED,
        },
        "fields": [
            {"name": FIELD_FILE, "kind": "file", "evidence_level": EVIDENCE_VERIFIED},
            {"name": FIELD_NAME, "kind": "text", "note": "与 file 同名；裁剪分支原文有，普通分支未取证",
             "evidence_level": EVIDENCE_CANDIDATE},
            {"name": FIELD_UA, "kind": "text", "note": "runtime UA 令牌；本实现不发送，是否必需未取证",
             "evidence_level": EVIDENCE_UNKNOWN},
            {"name": FIELD_TOKEN, "kind": "text", "note": "cookie _tb_token_；只在裁剪分支原文出现",
             "evidence_level": EVIDENCE_CANDIDATE},
            {"name": FIELD_WATER, "kind": "text", "note": FIELD_WATER_OFF_VALUE,
             "evidence_level": EVIDENCE_CANDIDATE},
        ],
        "limits": {
            "max_files_per_request": MAX_FILES_PER_REQUEST,
            "max_file_bytes": MAX_FILE_BYTES,
            "allowed_suffixes": list(ALLOWED_SUFFIXES),
            "evidence_level": EVIDENCE_VERIFIED,
        },
        "large_file_route": {
            "apis": [
                "mtop.taobao.mediacenter.pc.image.upload.config",
                "mtop.taobao.mediacenter.pc.image.upload.init",
                "mtop.taobao.mediacenter.pc.image.upload.complete",
            ],
            # ⚠️ 这里**故意不写** `"implemented": False` 这类硬编码布尔：
            # 自检第 5 道门（陈旧说法）就是拦这种「今天写的布尔，明天变假话」的字段，
            # 一写它 `python -m taobao_publish check` 就会红。
            # 用一句带 blocker 的说明代替，读的人照样知道现在不能用。
            "blocker": "本模块没有实现分片直传：uploadUrlList 的真实 host 与签名形态"
                       "必须登录态下真传一次才拿得到，未取证前不写这条路径",
            "evidence_level": EVIDENCE_UNKNOWN,
        },
        "success_criteria": [
            "HTTP 200",
            "且响应 JSON 的 success 为 true",
            "且能取到 object.url 并通过 CDN 白名单校验",
        ],
        "stop_conditions": {
            "codes": list(RATE_LIMIT_CODES),
            "behavior": "停手，不重试，交人工处理验证码",
        },
        "mtop_apis": [
            {"api": MTOP_API_DIR_QUERY, "purpose": "读目录树", "evidence_level": EVIDENCE_CANDIDATE},
            {"api": MTOP_API_DIR_ADD, "purpose": "建目录，返回 pictureCategoryId 作为 folderId",
             "evidence_level": EVIDENCE_CANDIDATE},
            {"api": MTOP_API_FILE_QUERY, "purpose": "按目录查文件（拿到 fullUrl/pictureId）",
             "evidence_level": EVIDENCE_CANDIDATE},
        ],
        "notes": [dict(item) for item in CONTRACT_NOTES],
        "rejected": [dict(item) for item in REJECTED_ROUTES],
    }


def iter_unique_names(names: Iterable[str]) -> List[str]:
    """保持顺序去重。给调用方拼批次用，不做任何改名。"""

    seen: Dict[str, None] = {}
    for name in names:
        seen.setdefault(str(name), None)
    return list(seen)
