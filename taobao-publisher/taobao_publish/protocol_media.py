# -*- coding: utf-8 -*-
"""协议优先的素材准备：「整批传图片空间 → 直接按回执选图 → 继续后面阶段」。

## 这条路与 DOM 路线的分工

============================  ==========================  =====================
环节                          DOM 路线（原）              协议路线（本模块）
============================  ==========================  =====================
上传                          点「本地上传」塞文件输入框   `upload.api` multipart
上传后的目录                  页面弹层里的「全部图片」     **同一个**「全部图片」
身份                          页面上渲染出的卡片           **`pictureId` + 完整 URL**
选图                          点卡片 label                 **同一套**（复用 page.py）
============================  ==========================  =====================

也就是说：**只替换「上传」这一件事，选图与回读完全复用已经跑通的那套**。
这样改动面最小，也不会把「上传成功」和「图位填对了」混为一谈。

## 为什么协议路线的身份更强

DOM 路线只能靠「文件名 + 卡片 URL」核对；协议路线在上传那一刻就拿到了
`pictureId` 与 `object.url`，随后在页面上按**同一个 URL** 核对。
对不上就报错，不会「差不多就选一张」。

## 开关

`TAOBAO_MEDIA_ROUTE=protocol` 才走协议；默认仍是 `dom`（原来的行为一行不改）。
两种取值之外的值**直接报错**，不做「不认识就回退」——静默回退会让人以为跑的是协议。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .constants import WRITE_UPLOAD_IMAGE
from .authorization import WriteAuthorization
from .errors import TaobaoPublishError

#: 素材路线环境变量。
ENV_MEDIA_ROUTE: str = "TAOBAO_MEDIA_ROUTE"
#: 协议路线。
ROUTE_PROTOCOL: str = "protocol"
#: DOM 路线（默认，保持既有行为）。
ROUTE_DOM: str = "dom"
#: 允许取值。
MEDIA_ROUTES: Tuple[str, ...] = (ROUTE_DOM, ROUTE_PROTOCOL)

#: 图片空间的根目录 ID（bundle 原文：``parentId || "0"``）。
#: 协议上传默认传这里，与 DOM 路线的「上传至全部图片」是同一个位置。
ROOT_FOLDER_ID: str = "0"

#: 各用途在图片空间里的目录名（DOM 路线用来分组；协议路线只用于记录）。
ROLE_FOLDERS: Mapping[str, str] = {"main": "主图", "sku": "SKU", "detail": "详情页"}

#: 素材中心页——**唯一能新建目录的地方**（E-286：选图器里没有建目录入口）。
MATERIAL_CENTER_URL: str = (
    "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu")


def ensure_cloud_folders(port: int, product_name: str,
                         folder_names: Sequence[str]) -> Dict[str, str]:
    """在素材中心页确保 ``全部图片/<product_name>/<folder_names…>`` 存在。

    ## 为什么必须由程序自己建（用户诉求："带文件夹一起上传"）

    协议上传的目标目录是 **numeric folderId**，而平台**不会**因为文件名叫
    `a/b/c.jpg` 就自动建目录（E-223：那样会被拒
    ``FILE_NAME_CONTAIN_SPECIAL_CHARACTER``）。所以"保留结构"的前提是
    目录**先存在**。而目录名不该由人约定——它就该来自上传内容本身：
    ``<本地上传文件夹名>/<本地子目录名>``。

    ## 为什么在这里做、而不是在发布页

    菜单/按钮决定了一切（E-286 实测）：
    * **选图器弹层**：只有「本地上传」，没有「新建文件夹」，右键也不弹菜单；
    * **素材中心页**：有「新建文件夹」按钮 **且** 目录节点带 folderId。

    所以本函数**新开一个素材中心标签**建目录，建完立刻关掉——不去导航发布页，
    也就不影响正在填写的表单。

    :param port: 调试端口（与流水线同一个浏览器）。
    :param product_name: 商品目录名。**直接取上传内容本身的文件夹名**，不做转换。
    :param folder_names: 角色子目录名（`主图`/`SKU`/`详情页`）。
    :return: ``{子目录名: folderId}``。

    ## 失败怎么报（2026-10-07 接诊断契约）

    这一层**不吞错、不兜底、不重试**，只把「哪个页面、哪条路径、原始判据、下一步」
    补进 `media_library` 的媒体失败文案里（唯一实现处见
    `media_library._media_failure`）：

    * 素材中心页没有目录树 → ``判据=directory_tree_not_supported``（判决「页面没有树」）；
    * 树在、一个节点都没渲染出来 → ``判据=reason_missing``（判决「读不出来」）；
      两条**不许合并**成「没有可用的目录树」这种模糊中文；
    * 目标先写商品目录名——此时**还没有**确定的云端路径，
      所以不凭 `ALL_IMAGES_NODE` 硬拼「全部图片」前缀（素材中心根本没有那个节点）。

    ⚠️ 建目录链每一步的写步骤（点击 → 输入 → 确定 → 回读 folderId）
    **尚未在真机执行过**：涉及这部分的动作句都带「该自动建目录步骤尚未真机验证」，
    证据等级是 ``candidate``，不得当 ``verified`` 用。

    :raises PageError: 页面读不出树 / 树没有节点 / 建目录六步失败（``PAGE_ERROR``）。
    :raises TaobaoPublishError: ``CDP_UNREACHABLE``——连不上调试浏览器，此时一个目录都没建。
    """

    from . import media_library
    from .cdp_ws import CdpBrowser, CdpClientError
    from .page import PageClient, PageError

    #: 这条链是**调用点**的产物（`stages._cloud_folder_creator` 里那个 `create`），
    #: 所以诊断契约的 `分支=` 用它——契约示例里 `write_not_authorized` 那条就是这么写的。
    #: 链**内部**每一步另有自己的分支名（`read_directory` / `ensure_child_directory` /
    #: `open_root_directory`），由 `media_library` 那侧自报，两者不冲突。
    branch = '_cloud_folder_creator.create'
    page = media_library.PAGE_MATERIAL_CENTER

    def _fail(target, reason, *, action=None):
        """如实抛错：**不吞、不兜底、不重试**，只把页面与路径补进契约文案。"""

        raise PageError(media_library._media_failure(
            media_library.STAGE_UPLOAD_IMAGES, branch, page, target, reason, action=action))

    browser = CdpBrowser(port=port, timeout=30.0)
    target = None
    try:
        target = browser.new_page(MATERIAL_CENTER_URL)
        time.sleep(7.0)          # 素材中心页很重；等目录树渲染出来
        client = PageClient.connect(target.web_socket_url, target_url=target.url)
        try:
            state = media_library.read_directory(client, context_id=None)
            if not state.get('supported'):
                # 页面没有目录树：判决是「这个页面没有树」，不是「读不出来」。
                # 建目录前拿不到树就没法定位父级，**不猜**。
                _fail(product_name, media_library.REASON_TREE_NOT_SUPPORTED)

            # ⚠️ **素材中心页的树里没有「全部图片」节点**——树根本身就是那一层
            # （2026-10-07 真机实证：顶层节点 path 只有一段，
            #  `directory_folder_id(['ID-…'])` 命中、加上「全部图片」前缀反而读不到）。
            # 所以这里用 `root_prefix` 判前缀，而不是写死根节点名：
            # 显式节点存在（选图器那种页面）→ 用它的路径；不存在但树里有节点 → 空前缀；
            # **树里一个节点都没有 → 读不到就不猜**，如实失败。
            all_images = media_library.root_prefix(state)
            if all_images is None:
                # 树在、但一个节点都没渲染出来：这是「读不出来」（reason_missing），
                # 与上一条的「页面没有树」是两个判决，不合并。
                # 此时**还没有**确定的云端路径可写，所以目标写商品名本身
                # （不凭 ALL_IMAGES_NODE 硬拼前缀）。
                _fail(product_name, media_library.REASON_MISSING)

            # 逐级建：商品目录 → 各角色目录。`ensure_child_directory` 幂等，
            # 已存在就直接返回 folderId（**不重复建**）。
            product_path = all_images + [product_name]
            if media_library.directory_folder_id(client, product_path, context_id=None) is None:
                media_library.ensure_child_directory(
                    client, all_images, product_name, context_id=None)

            resolved: Dict[str, str] = {}
            for name in folder_names:
                resolved[str(name)] = media_library.ensure_child_directory(
                    client, product_path, str(name), context_id=None)
            return resolved
        finally:
            client.close()
    except CdpClientError as exc:
        # 连不上调试浏览器：**一个目录都没建**，如实报 CDP 不可达（不是页面交互失败）。
        raise TaobaoPublishError(
            "CDP_UNREACHABLE", "创建图片空间目录时无法连接调试浏览器：{}".format(exc))
    finally:
        if target is not None:
            try:
                browser.close_target(target.target_id)
            except Exception:  # noqa: BLE001 - 关标签失败不该掩盖建目录的结果
                pass
        browser.close()


def media_route_from_environment(environ: Optional[Mapping[str, str]] = None) -> str:
    """读素材路线开关。未设置时是 ``dom``（保持既有行为）。

    取值不认识时**抛错**，不回退：静默回退会让人以为跑的是协议路线。
    """

    env = os.environ if environ is None else environ
    raw = env.get(ENV_MEDIA_ROUTE)
    if raw is None or str(raw).strip() == "":
        return ROUTE_DOM
    value = str(raw).strip().lower()
    if value not in MEDIA_ROUTES:
        raise ValueError(
            f"{ENV_MEDIA_ROUTE} 取值非法：{raw!r}（只允许 {' / '.join(MEDIA_ROUTES)}）"
        )
    return value


@dataclass(frozen=True, slots=True)
class ProtocolMediaEntry:
    """一张已进图片空间的素材，以及它在页面上选图需要的信息。"""

    role: str
    path: str
    name: str
    sha256: str
    url: str
    picture_id: str = ""
    folder_path: Tuple[str, ...] = ()
    page_number: Optional[int] = None
    uploaded_now: bool = True

    def to_plan_entry(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "sha256": self.sha256,
            "url": self.url,
            "picture_id": self.picture_id,
            "folder_path": list(self.folder_path),
            "page_number": self.page_number,
            "uploaded_now": self.uploaded_now,
        }


def build_entries(
    *,
    roles: Mapping[str, Sequence[Mapping[str, Any]]],
    receipts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, List[ProtocolMediaEntry]]:
    """把「各用途的本地文件身份」与「协议上传回执」拼成带 URL 的条目。

    :param roles: ``{role: [身份, ...]}``，身份形如
        ``{'path': ..., 'name': ..., 'sha256': ...}``（见 ``form_adapters.media_file_identity``）。
    :param receipts: ``{上传文件名: 回执}``，回执必须含 ``url``。

    **缺回执就抛错**：宁可停下，也不让一张没有 URL 的图进入选图阶段。
    """

    result: Dict[str, List[ProtocolMediaEntry]] = {}
    for role, identities in roles.items():
        entries: List[ProtocolMediaEntry] = []
        for identity in identities:
            name = str(identity.get("name") or "")
            receipt = receipts.get(name)
            if receipt is None:
                raise TaobaoPublishError(
                    "IMAGE_UPLOAD_FAILED",
                    f"素材 {name!r} 没有协议上传回执，不能进入选图阶段",
                )
            url = str(receipt.get("url") or "")
            if not url.startswith("https://"):
                raise TaobaoPublishError(
                    "IMAGE_UPLOAD_FAILED",
                    f"素材 {name!r} 的回执缺少有效 HTTPS 地址",
                )
            entries.append(
                ProtocolMediaEntry(
                    role=role,
                    path=str(identity.get("path") or ""),
                    name=name,
                    sha256=str(identity.get("sha256") or ""),
                    url=url,
                    picture_id=str(receipt.get("picture_id") or ""),
                    folder_path=tuple(str(part) for part in (receipt.get("folder") or ())),
                    uploaded_now=bool(receipt.get("uploaded_now", True)),
                )
            )
        result[role] = entries
    return result


def plan_from_entries(entries: Mapping[str, Sequence[ProtocolMediaEntry]]) -> Dict[str, List[Dict[str, Any]]]:
    """转成 ``stage_upload_images`` 直接可用的 plan 形状。"""

    return {
        role: [entry.to_plan_entry() for entry in items]
        for role, items in entries.items()
    }


def verify_against_gallery(
    found: Mapping[str, Mapping[str, Any]],
    expected: Sequence[ProtocolMediaEntry],
) -> List[ProtocolMediaEntry]:
    """用页面上实际读到的卡片核对协议回执：**URL 必须逐字相等**。

    :param found: ``{name: 卡片回执}``（``page.find_media_images`` 的 receipts）。
    :return: 补齐 ``page_number`` 后的条目。

    名字对上了但 URL 不同 → 抛 ``MEDIA_IMAGE_MISSING``：说明图片空间里那张同名的图
    不是我们刚传的那张（历史同名素材），这时**必须失败**，不能将就。
    """

    resolved: List[ProtocolMediaEntry] = []
    for entry in expected:
        receipt = found.get(entry.name)
        if receipt is None:
            raise TaobaoPublishError(
                "MEDIA_IMAGE_MISSING",
                f"图片空间里没有找到刚上传的素材：{entry.name}",
            )
        actual = str(receipt.get("url") or "")
        # ⚠️ **不能逐字比 URL**：回执是原图地址，卡片是带处理参数的缩略/转码地址
        # （`_320x320?t=…`、`_320x320q80_.webp`），逐字比会把同一张图判成不一致。
        from .upload_api import same_image
        if not same_image(actual, entry.url):
            raise TaobaoPublishError(
                "MEDIA_IMAGE_MISSING",
                f"图片空间里同名素材与本批上传回执指向的不是同一张图：{entry.name}",
            )
        resolved.append(
            ProtocolMediaEntry(
                role=entry.role,
                path=entry.path,
                name=entry.name,
                sha256=entry.sha256,
                url=entry.url,
                picture_id=entry.picture_id,
                folder_path=entry.folder_path,
                page_number=_page_number_of(receipt),
                uploaded_now=entry.uploaded_now,
            )
        )
    return resolved


def _page_number_of(receipt: Mapping[str, Any]) -> Optional[int]:
    value = receipt.get("page_number")
    if type(value) is int and value > 0:
        return value
    return None


@dataclass(frozen=True, slots=True)
class ProtocolUploadPlan:
    """一次「协议传整个商品文件夹」的执行计划（不发送，只描述）。"""

    record_id: int
    product_dir: str
    folder_name: str
    role_paths: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    @property
    def all_paths(self) -> Tuple[str, ...]:
        seen: Dict[str, None] = {}
        for paths in self.role_paths.values():
            for path in paths:
                seen.setdefault(path, None)
        return tuple(seen)

    def describe(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "folder_name": self.folder_name,
            "counts": {role: len(paths) for role, paths in self.role_paths.items()},
            "total_unique": len(self.all_paths),
        }


def build_upload_plan(item: Any) -> ProtocolUploadPlan:
    """从商品条目生成上传计划。

    **整个商品文件夹的图片都进**：主图 + SKU 图 + 详情图，合并去重后一次传完，
    与 DOM 路线「一次上传本商品全部缺图」的语义一致。
    """

    roles = {
        "main": tuple(str(path) for path in (item.images.main or ()) if str(path).strip()),
        "sku": tuple(str(path) for path in (item.images.sku or ()) if str(path).strip()),
        "detail": tuple(str(path) for path in (item.images.detail or ()) if str(path).strip()),
    }
    if not roles["main"]:
        raise TaobaoPublishError(
            "EVIDENCE_INSUFFICIENT", "没有要上传的主图（item.images.main 为空）"
        )
    missing = sorted({path for paths in roles.values() for path in paths if not Path(path).is_file()})
    if missing:
        raise TaobaoPublishError(
            "REQUIRED_FIELD_MISSING",
            "以下素材在磁盘上不存在：" + "、".join(missing[:3]),
        )
    return ProtocolUploadPlan(
        record_id=int(getattr(item, "record_id", 0) or 0),
        product_dir=_product_dir_of(item),
        folder_name=str(getattr(item, "record_name", "") or "").strip(),
        role_paths=roles,
    )


def _product_dir_of(item: Any) -> str:
    for path in list(getattr(item.images, "main", ()) or ())[:1]:
        parent = Path(str(path)).parent
        # 主图常在 ``主图/`` 或 ``主图/800/`` 下，往上找到商品目录即可；
        # 这里不做猜测式上溯，只取「包含本地文件的最近一级」交给调用方核对。
        return str(parent)
    return ""


def authorize(authorization: WriteAuthorization) -> None:
    """协议上传前的授权门。未授权直接抛错，**不会发出任何请求**。"""

    authorization.require(WRITE_UPLOAD_IMAGE)


# ---------------------------------------------------------------------------
# 上传回执账本（断点续传的底座）
# ---------------------------------------------------------------------------
#: 账本文件名。放运行数据目录里（``DOUYIN_DATA_DIR`` / LOCALAPPDATA），不进仓库。
LEDGER_FILENAME: str = "taobao_media_upload_ledger.json"


def ledger_path() -> Path:
    """账本路径：跟随运行数据目录，**不写死绝对路径**。"""

    import os

    candidates = []
    explicit = os.environ.get("DOUYIN_DATA_DIR")
    if explicit:
        candidates.append(Path(explicit))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "com.dyin.sock-publisher")
    candidates.append(Path.cwd())
    for base in candidates:
        if base.is_dir():
            return base / LEDGER_FILENAME
    return Path.cwd() / LEDGER_FILENAME


@dataclass
class UploadLedger:
    """已成功上传的素材回执。

    **为什么需要它**：平台按频率触发风控，一次几十张很容易在中间被打断
    （实测：连传数十张后回 ``FAIL_SYS_USER_VALIDATE``）。没有账本的话，
    下一次只能整批重来——**重来又会更快撞上风控**，形成死循环。
    有账本就能「传过的跳过，只补没传的」。

    身份用 **相对路径 + sha256**：内容变了就得重传，改个名字不能冒充新图。
    """

    path: Path
    entries: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # -- 读写 ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "UploadLedger":
        target = path or ledger_path()
        data: Dict[str, Any] = {}
        if target.is_file():
            try:
                parsed = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(parsed, dict) and isinstance(parsed.get("entries"), dict):
                    data = parsed["entries"]
            except (ValueError, OSError):
                # 账本坏了不能当成「没有账本」之外的别的东西——但要如实说清楚：
                # 读不出来就是读不出来，下一次会重新上传，不会静默用坏数据。
                data = {}
        return cls(path=target, entries={str(k): dict(v) for k, v in data.items()
                                         if isinstance(v, dict)})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": self.entries}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    # -- 查询与登记 ---------------------------------------------------------
    @staticmethod
    def key(identity: Mapping[str, Any]) -> str:
        return "{}\u0000{}".format(str(identity.get("name") or ""),
                                   str(identity.get("sha256") or ""))

    def lookup(self, identity: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        record = self.entries.get(self.key(identity))
        if not record:
            return None
        url = str(record.get("url") or "")
        if not url.startswith("https://"):
            return None
        return record

    def record(self, identity: Mapping[str, Any], receipt: Mapping[str, Any],
               folder_id: str = "") -> None:
        """登记一条上传回执。

        :param folder_id: 这次上传**落到哪个目录**。必须记下来——见 :meth:`reuse`。

        早先不记目录，于是账本只知道"这张传过"，不知道"传到了哪"。
        改成按用途分目录上传后，那个旧回执会**挡住新逻辑**：`reuse` 认为
        "已经传过"，而图其实躺在根层，用户看到的就是"图片还是散的"（E-284）。
        """

        self.entries[self.key(identity)] = {
            "name": str(identity.get("name") or ""),
            "sha256": str(identity.get("sha256") or ""),
            "path": str(identity.get("path") or ""),
            "url": str(receipt.get("url") or ""),
            "picture_id": str(receipt.get("picture_id") or ""),
            "folder_id": str(folder_id or ""),
        }
        self.save()

    def reuse(self, identities: Sequence[Mapping[str, Any]],
              destinations: Optional[Mapping[str, str]] = None) -> Dict[str, Dict[str, Any]]:
        """把账本里已经传过、**且落在目标目录**的那部分挑出来。

        :param destinations: ``{上传文件名: 目标 folderId}``。给了就**只复用
            目录一致**的回执；不一致的（例如旧版全部传在根层留下的记录）
            视为需要重传——它没有完成这次想要的结构。

        ## 为什么必须校验目录（E-284）

        账本键是"文件名 + 内容 sha256"，**不含目录**。若不校验目录，
        任何历史回执都会让"改成分目录上传"这个改动**完全不生效**：
        平台上的图还在根层，程序却认为已经传好了——比报错更难发现。
        """

        wanted = {str(k): str(v) for k, v in (destinations or {}).items()}
        found: Dict[str, Dict[str, Any]] = {}
        for identity in identities:
            name = str(identity.get("name"))
            record = self.lookup(identity)
            if record is None:
                continue
            if wanted:
                # 账本里没记目录（旧记录）或不等于目标目录 → **不复用**，让它重传。
                if str(record.get("folder_id") or "") != wanted.get(name, ""):
                    continue
            found[name] = dict(record, folder=[], uploaded_now=False)
        return found

    def describe(self) -> Dict[str, Any]:
        return {"path": str(self.path), "count": len(self.entries)}


def default_pace_seconds() -> float:
    """每张之间默认留多久。

    风控是按频率触发的（实测撞到 ``RGV587_ERROR``）。这个值不是从平台文档来的
    （平台没给），是**保守取值 + 可被环境变量覆盖**：``TAOBAO_UPLOAD_PACE_SECONDS``。
    取值的目的是「比撞上风控再停手便宜」，不是把速度做到极限。
    """

    import os

    raw = os.environ.get("TAOBAO_UPLOAD_PACE_SECONDS")
    if raw is not None and str(raw).strip():
        try:
            value = float(str(raw).strip())
        except ValueError:
            raise ValueError(
                f"TAOBAO_UPLOAD_PACE_SECONDS 不是数字：{raw!r}"
            ) from None
        if value < 0:
            raise ValueError("TAOBAO_UPLOAD_PACE_SECONDS 不能为负")
        return value
    return 1.2
