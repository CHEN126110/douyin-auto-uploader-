# -*- coding: utf-8 -*-
"""图片空间**目录与文件查询**的 mtop 接口层（候选契约，按需实测）。

## 这些 api 是哪来的

图片空间生产 bundle 原文（``sucai-tu-selector`` chunk）里的 api 名与入参：

* ``mtop.taobao.picturecenter.console.dir.query`` —— 目录树（``dirs``）
* ``mtop.taobao.picturecenter.console.dir.add`` —— 建目录，返回
  ``jsPictureCategoryDO.pictureCategoryId``，**这个 ID 就是上传用的 folderId**
* ``mtop.taobao.picturecenter.console.file.query`` —— 按目录查文件
  （``fileModule[]``：``pictureId`` / ``name`` / ``fullUrl`` / ``pixel`` / ``status``）

**证据等级**：api 名与入参是 ``verified``（bundle 原文）；
``version`` / 网关 / ``appKey`` 是从仓库已跑通的 mtop 读路径外推的，整体记
``candidate``——也就是说，**这个模块的接口形态必须实测才算成立**。
未实测前，它只能用来「试探并如实报告失败原因」，不能当成已经能用的能力。

## 为什么不用 DOM 拿目录

DOM 路线要展开懒加载树、逐层点、等异步渲染（``media_library.py`` 里那一大套），
而且目录树选择器目前还只是 ``candidate``。接口路线一次请求拿到完整树，
失败也失败得干净（一个 ret 码，而不是「点了没反应」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .mtop import (
    H5_APP_KEY_DEFAULT,
    MtopRequest,
    MtopResponse,
    build_browser_request,
    classify_response,
)
from .upload_api import (
    EVIDENCE_CANDIDATE,
    EVIDENCE_VERIFIED,
    MTOP_API_DIR_ADD,
    MTOP_API_DIR_QUERY,
    MTOP_API_FILE_QUERY,
)

#: 目录/文件接口的 api 级证据等级（api 名 verified，网关与 version 未实测）。
PICTURECENTER_EVIDENCE: str = EVIDENCE_CANDIDATE

#: 目录树根节点名。图片空间的「全部图片」是树的根，上传不指定目录时落到它下面。
ALL_IMAGES_NODE: str = "全部图片"


@dataclass(frozen=True, slots=True)
class PictureFolder:
    """图片空间里的一个目录。"""

    folder_id: str
    name: str
    parent_id: str = ""
    children: Tuple["PictureFolder", ...] = ()
    raw_keys: Tuple[str, ...] = ()

    def walk(self) -> Iterable["PictureFolder"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "folder_id": self.folder_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(frozen=True, slots=True)
class PictureFile:
    """图片空间里的一个文件。``full_url`` 是可直接用于发布选图的地址。"""

    picture_id: str
    name: str
    full_url: str = ""
    folder_id: str = ""
    pixel: str = ""
    status: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "picture_id": self.picture_id,
            "name": self.name,
            "full_url": self.full_url,
            "folder_id": self.folder_id,
            "pixel": self.pixel,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# 响应解析（对字段名保守，缺字段就如实报缺）
# ---------------------------------------------------------------------------
_DIR_LIST_KEYS: Tuple[str, ...] = ("dirs", "data", "dirList", "list")
_ID_KEYS: Tuple[str, ...] = ("pictureCategoryId", "id", "catId", "dirId")
_NAME_KEYS: Tuple[str, ...] = ("name", "dirName", "title")
_CHILD_KEYS: Tuple[str, ...] = ("children", "subDirs", "childDirs", "subCategories")


def _pick(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _node_from(raw: Any, *, parent_id: str = "") -> Optional[PictureFolder]:
    if not isinstance(raw, Mapping):
        return None
    folder_id = _pick(raw, _ID_KEYS)
    name = _pick(raw, _NAME_KEYS)
    if folder_id is None or name is None:
        return None
    children_raw = _pick(raw, _CHILD_KEYS)
    children: List[PictureFolder] = []
    if isinstance(children_raw, (list, tuple)):
        for child in children_raw:
            node = _node_from(child, parent_id=str(folder_id))
            if node is not None:
                children.append(node)
    return PictureFolder(
        folder_id=str(folder_id),
        name=str(name).strip(),
        parent_id=parent_id,
        children=tuple(children),
        raw_keys=tuple(sorted(str(key) for key in raw.keys())),
    )


def parse_directory_tree(payload: Optional[Any]) -> Tuple[Optional[PictureFolder], str]:
    """从 ``dir.query`` 的响应里取目录树。

    :return: ``(根节点, 说明)``；解析不出来时根节点为 ``None``，说明写清原因。
        字段名一旦与实测不符，这里会明确报「字段名不认识」并附上实际键名，
        **不会**退化成空树——空树会让人以为「图片空间里没有目录」。
    """

    if payload is None:
        return None, "响应为空"
    if not isinstance(payload, Mapping):
        return None, "响应不是 JSON 对象"
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    container = None
    for key in _DIR_LIST_KEYS:
        value = data.get(key) if isinstance(data, Mapping) else None
        if isinstance(value, (list, tuple)) and value:
            container = value
            break
        if isinstance(value, Mapping) and value:
            node = _node_from(value)
            if node is not None:
                return node, "ok"
    if container is None:
        return None, "响应里没有目录数组，实际键名：" + "、".join(
            sorted(str(key) for key in (data.keys() if isinstance(data, Mapping) else ()))
        )
    roots: List[PictureFolder] = []
    for item in container:
        node = _node_from(item)
        if node is not None:
            roots.append(node)
    if not roots:
        return None, "目录数组里没有可识别的目录节点（id 或 name 缺失）"
    if len(roots) == 1:
        return roots[0], "ok"
    # 多个根：合成一个匿名根，避免调用方以为只有一个根。
    return PictureFolder(folder_id="", name="", children=tuple(roots)), "ok"


def parse_files(payload: Optional[Any]) -> Tuple[Tuple[PictureFile, ...], str]:
    """从 ``file.query`` 的响应里取文件清单。

    实测键路径是 ``data.catModule``（**不是** ``data.fileModule``）——
    ``tmp/live-directory-api.json`` 里真实响应的原文是
    ``{"data":{"catModule":[{"deleted":0,"featuresMap":{},...``。
    两者都试，谁有内容用谁。
    """

    if payload is None:
        return (), "响应为空"
    if not isinstance(payload, Mapping):
        return (), "响应不是 JSON 对象"
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    container = None
    for key in ("catModule", "fileModule", "files", "list", "items"):
        value = data.get(key) if isinstance(data, Mapping) else None
        if isinstance(value, (list, tuple)):
            container = value
            break
    if container is None:
        return (), "响应里没有文件数组，实际键名：" + "、".join(
            sorted(str(key) for key in (data.keys() if isinstance(data, Mapping) else ()))
        )
    files: List[PictureFile] = []
    for item in container:
        if not isinstance(item, Mapping):
            continue
        picture_id = _pick(item, ("pictureId", "id", "fileId"))
        name = _pick(item, ("name", "fileName"))
        if picture_id is None or name is None:
            continue
        files.append(
            PictureFile(
                picture_id=str(picture_id),
                name=str(name).strip(),
                full_url=str(_pick(item, ("fullUrl", "url", "picUrl")) or ""),
                folder_id=str(_pick(item, ("catId", "pictureCategoryId", "folderId")) or ""),
                pixel=str(_pick(item, ("pixel", "pix", "size")) or ""),
                status=str(_pick(item, ("status", "state")) or ""),
            )
        )
    return tuple(files), "ok"


# ---------------------------------------------------------------------------
# 请求构造（不发送）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PictureCenterRequest:
    """一次 picturecenter mtop 调用的描述。``request`` 已含签名。"""

    api: str
    request: MtopRequest
    body_params: Mapping[str, Any] = field(default_factory=dict)
    evidence_level: str = PICTURECENTER_EVIDENCE

    def describe(self) -> Dict[str, Any]:
        return {
            "api": self.api,
            "evidence_level": self.evidence_level,
            "data_keys": sorted(str(key) for key in self.body_params.keys()),
            "version": self.request.version,
            "url_host": self.request.describe()["url_host"],
        }


def build_directory_query(
    token: str,
    *,
    version: str = "1.0",
    app_key: str = H5_APP_KEY_DEFAULT,
    ttid: str = "",
    extra_data: Optional[Mapping[str, Any]] = None,
    timestamp_ms: Optional[str] = None,
) -> PictureCenterRequest:
    """构造「读目录树」请求。**纯构造，不发送。**

    入参按**实测**对齐：真实页面调这个 api 时 ``data`` 就是 **空对象 ``{}``**
    （实测 ``data_keys=[]``，见 ``tmp/live-directory-api.json``），并且带 ``ttid``。
    早先按 bundle 猜的 ``{"clientType": 0}`` 是错的——猜出来的入参换来的是
    ``FAIL_SYS_ILLEGAL_ACCESS::非法请求``。
    """

    data: Dict[str, Any] = dict(extra_data or {})
    request = build_browser_request(
        MTOP_API_DIR_QUERY, data, token, version=version, app_key=app_key,
        ttid=ttid, timestamp_ms=timestamp_ms,
    )
    return PictureCenterRequest(api=MTOP_API_DIR_QUERY, request=request, body_params=data)


def build_directory_add(
    token: str,
    *,
    parent_id: str,
    name: str,
    version: str = "1.0",
    app_key: str = H5_APP_KEY_DEFAULT,
    ttid: str = "",
    timestamp_ms: Optional[str] = None,
) -> PictureCenterRequest:
    """构造「建目录」请求（入参来自 bundle 原文：``{dirId, name}``）。

    ⚠️ 证据等级仍是 ``candidate``：``dir.add`` 的入参只在 bundle 里出现过，
    没有实测过（本轮只读到 ``dir.query`` / ``file.query`` 的真实请求）。
    """

    if not isinstance(parent_id, str) or not parent_id.strip():
        raise ValueError("建目录必须给出父目录 ID")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("建目录必须给出目录名")
    data = {"dirId": parent_id.strip(), "name": name.strip()}
    request = build_browser_request(
        MTOP_API_DIR_ADD, data, token, version=version, app_key=app_key,
        ttid=ttid, timestamp_ms=timestamp_ms,
    )
    return PictureCenterRequest(api=MTOP_API_DIR_ADD, request=request, body_params=data)


def build_file_query(
    token: str,
    *,
    folder_id: str,
    page: int = 1,
    keyword: str = "",
    version: str = "1.0",
    app_key: str = H5_APP_KEY_DEFAULT,
    ttid: str = "",
    timestamp_ms: Optional[str] = None,
) -> PictureCenterRequest:
    """构造「按目录查文件」请求。

    入参按**实测**对齐：真实页面的 ``data`` 键是
    ``catId / clientType / deleted / ignoreCat / orderBy / page / status / type``
    （实测 ``data_keys``，见 ``tmp/live-directory-api.json``）。
    **没有** ``pageSize``——早先按 bundle 加上它反而偏离实测，已去掉；
    ``key`` 只在有关键词时才带。
    """

    if not isinstance(folder_id, str) or not folder_id.strip():
        raise ValueError("查文件必须给出目录 ID")
    if type(page) is not int or page < 1:
        raise ValueError("页码必须是从 1 开始的整数")
    data: Dict[str, Any] = {
        "catId": folder_id.strip(),
        "page": page,
        "orderBy": "",
        "deleted": 0,
        "status": 0,
        "ignoreCat": 0,
        "clientType": 0,
        "type": 1,
    }
    if keyword:
        data["key"] = str(keyword)
    request = build_browser_request(
        MTOP_API_FILE_QUERY, data, token, version=version, app_key=app_key,
        ttid=ttid, timestamp_ms=timestamp_ms,
    )
    return PictureCenterRequest(api=MTOP_API_FILE_QUERY, request=request, body_params=data)


def folder_id_from_add_response(raw_text: Optional[str]) -> Tuple[str, MtopResponse]:
    """从 ``dir.add`` 的响应里取新目录 ID（**上传用的 folderId**）。

    取不到时返回空串并保留分类结果——调用方必须据此停下来，
    不允许「拿不到 ID 就传到默认目录」。
    """

    response = classify_response(raw_text)
    if not response.ok or not isinstance(response.payload, Mapping):
        return "", response
    payload = response.payload
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    for key in ("jsPictureCategoryDO", "pictureCategoryDO", "dir"):
        node = data.get(key) if isinstance(data, Mapping) else None
        if isinstance(node, Mapping):
            value = _pick(node, _ID_KEYS)
            if value is not None:
                return str(value), response
    value = _pick(data, ("pictureCategoryId", "catId", "dirId", "id")) if isinstance(data, Mapping) else None
    if value is not None:
        return str(value), response
    return "", response


def find_folder_by_path(root: Optional[PictureFolder], path: Sequence[str]) -> Optional[PictureFolder]:
    """按**完整路径**在树里找目录；每一段都必须与前一段有真实的父子关系。

    两条必须在实现里守住的规则（都栽过）：

    1. **按名字取第一个匹配是不行的**：图片空间允许不同父目录下存在同名子目录
       （每个商品都有自己的「主图」），取第一个就会把 A 商品的图传进 B 商品的目录，
       或者把图选成别的商品的图。
    2. **路径必须是连续的父子链，不是「顺序出现的子序列」**：
       ``全部图片 → 主图`` 在树里可能是 ``全部图片 → 商品A → 主图``——
       共享的只有末端名字。如果按「依次出现」来匹配，这条路径会被判成存在，
       而我们其实表达的是「根下面直接有一个主图目录」。所以这里只在
       **当前节点自己**满足这一段、或**它的直接子节点**满足这一段时前进，
       不允许跨层跳跃。

    多根树（:func:`parse_directory_tree` 合成的匿名根，``name`` 为空）会先在
    直接子节点里找路径首段。
    """

    names = [str(part).strip() for part in path if str(part).strip()]
    if not names or root is None:
        return None

    def advance(node: PictureFolder, index: int) -> Optional[PictureFolder]:
        """已经站在 ``node`` 上（``names[:index]`` 已消费完），继续往下走。"""

        if index == len(names):
            return node
        expected = names[index]
        # 当前节点自己就满足这一段：只允许在根节点这一层发生（即路径首段就是根名）。
        if index == 0 and node.name == expected and node.name:
            return advance(node, index + 1)
        for child in node.children:
            if child.name == expected:
                found = advance(child, index + 1)
                if found is not None:
                    return found
        return None

    return advance(root, 0)


def all_images_folder(root: Optional[PictureFolder]) -> Optional[PictureFolder]:
    """定位「全部图片」根目录。找不到返回 ``None``（**不猜**）。"""

    if root is None:
        return None
    if root.name == ALL_IMAGES_NODE:
        return root
    for node in root.walk():
        if node.name == ALL_IMAGES_NODE:
            return node
    return None


def contract_summary() -> Dict[str, Any]:
    return {
        "apis": [
            {"api": MTOP_API_DIR_QUERY, "purpose": "读目录树",
             "api_name_evidence": EVIDENCE_VERIFIED, "overall_evidence": PICTURECENTER_EVIDENCE},
            {"api": MTOP_API_DIR_ADD, "purpose": "建目录（返回 folderId）",
             "api_name_evidence": EVIDENCE_VERIFIED, "overall_evidence": PICTURECENTER_EVIDENCE},
            {"api": MTOP_API_FILE_QUERY, "purpose": "按目录查文件",
             "api_name_evidence": EVIDENCE_VERIFIED, "overall_evidence": PICTURECENTER_EVIDENCE},
        ],
        "unknown": [
            "真实 version 取值（当前按 mtop 读路径的 1.0 外推）",
            "网关域名与 appKey 是否与 H5 读路径一致",
            "响应字段名是否与 bundle 一致（解析器遇到不认识的结构会报出实际键名）",
        ],
    }
