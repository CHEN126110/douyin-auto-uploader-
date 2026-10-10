# -*- coding: utf-8 -*-
"""绑定平台的浏览器账户，以及抖店店铺会话身份。

**核心原则：Chrome profile 的名字不代表它登录了哪个店铺。**

profile 只是一个装 cookie 的目录，用户随时可能在里面重新登录到另一家店。
唯一可信的店铺身份是实测值：

  1. cookie ``ecom_gray_shop_id``（``.jinritemai.com`` 域）
  2. ``GET https://fxg.jinritemai.com/common/index/index`` 返回的店铺名与店铺 id

两者必须一致；不一致说明会话正在切换或串了，属于必须让用户看见的事实。

``protocol-research-clean-20260505/scripts/fxg_protocol_v4.py`` 里记着一次事故：
shop_id 读不到时兜底成测试店铺，结果把商品提交到了别人店铺。所以本模块
**任何情况下都不猜、不兜底、不给默认店铺 id**，读不到就如实返回未知状态。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote, unquote

from .runtime_paths import get_data_dir, get_runtime_root

# 抖店后台的店铺信息接口：同一个响应里同时给店铺名和店铺 id，
# 可以和 cookie 交叉校验，避免「cookie 是 A 店、页面其实是 B 店」。
SHOP_INFO_URL = "https://fxg.jinritemai.com/common/index/index"
SHOP_ID_COOKIE = "ecom_gray_shop_id"
FXG_DOMAIN = "jinritemai.com"

# 发布浏览器的默认 profile。历史上只有这一个，保持它作为默认值，
# 老用户升级后原来的登录态继续可用。
DEFAULT_PROFILE_NAME = "upload-browser-profile"
ACCOUNT_PLATFORMS = ("douyin", "taobao", "xiaohongshu")

#: 平台的中文名（前端与提示文案共用；加平台时**必须**同时补这里 ✓）
PLATFORM_LABELS = {
    "douyin": "抖音 / 抖店",
    "taobao": "淘宝",
    "xiaohongshu": "小红书千帆",
}

# ---- 小红书千帆（ark.xiaohongshu.com）----------------------------------------
# 全部来自真机实测，见 ``xiaohongshu-publisher/docs/05-证据日志.md``：
#   E-XHS-ENV-20261010（独立 profile，端口 9336，与抖店 9333 / 淘宝 9334 不复用）
#   E-XHS-LOGIN-20261010（未登录会跳 customer.xiaohongshu.com/login）
#   E-XHS-CREATE-STEP1-20261010（创建页路由）
XHS_DOMAINS = ("ark.xiaohongshu.com", "customer.xiaohongshu.com", "school.xiaohongshu.com")
XHS_CREATE_URL = "https://ark.xiaohongshu.com/app-item/good/create"
XHS_HOME_URL = "https://ark.xiaohongshu.com/app-system/home"
XHS_LOGIN_PAGE_HINTS = ("customer.xiaohongshu.com/login",)
XHS_PROFILE_DIR = ".runtime/chrome-xhs-cdp"
XHS_CDP_PORT = 9336

#: **店铺身份读取尚未取证**：实测只能从界面文字看到店铺名（如「涩计似空的店」），
#: 域名/接口级的稳定读法**没有验证过** ✗。因此这里显式声明不支持，
#: 上层应当如实显示「未登录／未读到」，**不得拿本地账户备注冒充店铺身份** ✓。
XHS_IDENTITY_SUPPORTED = False

_REGISTRY_FILENAME = "shop_profiles.json"


# 本模块生成的 slug 形如 "<安全字符>-<8位十六进制>"。用它识别「已经 slug 过」的值，
# 保证 slugify 幂等。
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+-[0-9a-f]{8}$")

# sidecar 跑在 threaded=True 的 Flask 上，状态轮询和切换店铺可能并发。
# 注册表是「读-改-写」，不串行化会丢记录。
_registry_lock = threading.RLock()


def normalize_platform(value: str) -> str:
    """规范账户平台；非法显式值不能被当作旧账户回落到抖店。"""
    if not isinstance(value, str) or value.strip().lower() not in ACCOUNT_PLATFORMS:
        raise ValueError("账户平台必须是 " + "、".join(ACCOUNT_PLATFORMS))
    return value.strip().lower()


def _profile_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("账户备注必须是字符串")
    return value.strip() or None


def slugify_profile_name(name: Optional[str]) -> str:
    """把用户输入的店铺备注名转成可以当目录名的 slug。

    店名基本都是中文，直接过滤非 ASCII 会把「甲店」「乙店」一起变成空串、
    再退回默认 profile——两家店会共用同一份登录态，等于发错店。
    所以纯非 ASCII 的名字改用名字本身的哈希，保证不同名字必得不同目录。

    同名即同一个 profile，这是有意的：用户输入同一个名字就应该复用同一份登录态。
    """
    raw = str(name or "").strip()
    if not raw:
        return DEFAULT_PROFILE_NAME
    if raw == DEFAULT_PROFILE_NAME:
        return raw
    # 必须幂等：这个函数在路由、注册表、目录解析三层都会被调用，
    # 如果 slug(slug(x)) != slug(x)，注册表的键和 active_profile 就会对不上，
    # 表现为「切换成功但列表里找不到这家店」。
    if _SLUG_PATTERN.match(raw):
        return raw
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    if not slug:
        return "shop-{}".format(digest)
    # ASCII 部分可能在不同名字之间撞车（例如「A店」和「A铺」都只剩 "A"），
    # 统一带上哈希后缀，让目录名与原始名字一一对应。
    return "{}-{}".format(slug[:32], digest)


def display_label(
    profile_name: str,
    label: Optional[str] = None,
    shop_name: Optional[str] = None,
    shop_id: Optional[str] = None,
) -> str:
    """店铺在界面上显示的名字。

    只有实测到的店铺名、用户自己写的备注，以及店铺编号这三种是真的。
    不存在「默认店铺」「待登录」这类名字——那是程序内部的容器状态，
    给它安一个店名等于凭空造出一家并不存在的店。
    没登录过就返回空串，由调用方决定不展示它。
    """
    name = str(shop_name or "").strip()
    if name:
        return name
    text = str(label or "").strip()
    if text and text != profile_name:
        return text
    if shop_id:
        return "店铺 {}".format(shop_id)
    return ""


# ---------------------------------------------------------------- 注册表


def profiles_base_dir() -> str:
    """浏览器 profile 目录的父目录。

    必须与 ``src/utils.py:_get_persistent_browser_user_data_path`` 的算法一致，
    否则注册表记的 profile 和发布真正打开的目录会对不上。
    """
    data_dir = get_data_dir(create=True)
    base = data_dir if data_dir is not None else (get_runtime_root() / "runtime")
    os.makedirs(str(base), exist_ok=True)
    return str(base)


def profile_dir(profile_name: str) -> str:
    return os.path.join(profiles_base_dir(), slugify_profile_name(profile_name))


def registry_path() -> str:
    # 注册表和 profile 目录放在一起：它记的就是这些目录的实测身份，
    # 分开放会在换运行目录时产生「记录还在、目录没了」的错配。
    return os.path.join(profiles_base_dir(), _REGISTRY_FILENAME)


def _empty_registry() -> Dict[str, Any]:
    return {
        "active_profile": DEFAULT_PROFILE_NAME,
        "profiles": {},
        "note": "由 src/shop_session.py 维护。profiles 里的 shop_id/shop_name 是实测记录，不要手工编辑。",
    }


def load_registry() -> Dict[str, Any]:
    path = registry_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _empty_registry()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("账户注册表内容损坏，请先修复注册表") from exc
    return _normalize_registry(data)


def _normalize_registry(data: Any) -> Dict[str, Any]:
    """旧账户仅在 platform 缺键时迁移；错形或非法绑定直接失败。"""
    if not isinstance(data, dict):
        raise ValueError("账户注册表顶层必须是对象")
    registry = dict(data)
    registry.setdefault("active_profile", DEFAULT_PROFILE_NAME)
    if not isinstance(registry["active_profile"], str) or not registry["active_profile"].strip():
        raise ValueError("账户注册表 active_profile 必须是非空字符串")
    profiles = registry.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("账户注册表 profiles 必须是对象")
    normalized = {}
    for slug, entry in profiles.items():
        if not isinstance(slug, str) or not isinstance(entry, dict):
            raise ValueError("账户注册表条目必须以字符串命名并包含对象")
        if not slug or slugify_profile_name(slug) != slug:
            raise ValueError("账户注册表包含不规范的账户目录标识")
        item = dict(entry)
        platform = normalize_platform(item["platform"] if "platform" in item else "douyin")
        if slug == DEFAULT_PROFILE_NAME and platform != "douyin":
            raise ValueError("历史默认账户只能绑定抖店平台")
        item["platform"] = platform
        normalized[slug] = item
    registry["profiles"] = normalized
    return registry


def save_registry(registry: Dict[str, Any]) -> bool:
    """同目录原子替换；写入失败直接抛错，调用方不能误报账户保存成功。"""
    normalized = _normalize_registry(registry)
    path = registry_path()
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent,
            prefix="shop_profiles-", suffix=".tmp", delete=False,
        ) as f:
            temporary_path = f.name
            json.dump(normalized, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        return True
    finally:
        if temporary_path is not None:
            os.unlink(temporary_path)


def _new_profile(slug: str, platform: str, label: Optional[str]) -> Dict[str, Any]:
    return {
        "profile_name": slug,
        "platform": platform,
        "label": label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "shop_id": None,
        "shop_name": None,
        "last_seen_at": None,
        "seen_count": 0,
    }


def _ensure_profile_entry(
    registry: Dict[str, Any], slug: str, label: Optional[str], platform: Optional[str]
) -> None:
    entry = registry["profiles"].get(slug)
    bound = entry["platform"] if entry is not None else "douyin"
    requested = normalize_platform(platform) if platform is not None else bound
    if slug == DEFAULT_PROFILE_NAME and requested != "douyin":
        raise ValueError("历史默认账户只能绑定抖店平台")
    if entry is not None and requested != bound:
        raise ValueError("已绑定账户的平台不可更改，请新建对应平台的账户")
    text = _profile_label(label)
    if entry is None:
        registry["profiles"][slug] = _new_profile(slug, requested, text)
    elif text is not None:
        entry["label"] = text


def ensure_profile(
    profile_name: str, label: Optional[str] = None, platform: Optional[str] = None
) -> Dict[str, Any]:
    """把一个 profile 登记进注册表（幂等），返回更新后的注册表。"""
    slug = slugify_profile_name(profile_name)
    with _registry_lock:
        registry = load_registry()
        _ensure_profile_entry(registry, slug, label, platform)
        save_registry(registry)
        return registry


def has_login_data(profile_name: str) -> bool:
    """这份账号信息的目录里是否已经存着登录数据。

    只看注册表是不够的：注册表可能被清过、换过运行目录，而 Chrome 目录还在。
    一旦拿一个还留着旧 cookie 的目录去「添加店铺」，打开就是已登录状态，
    用户会以为添加失败——2026-09-06 实测就是这么发生的。
    """
    directory = profile_dir(profile_name)
    candidates = [
        os.path.join(directory, "Default", "Network", "Cookies"),
        os.path.join(directory, "Default", "Cookies"),
    ]
    for path in candidates:
        try:
            metadata = os.stat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0:
            return True
    return False


def create_profile(platform: str = "douyin", label: Optional[str] = None) -> str:
    """准备一个用来登录新店铺的空目录，返回它的目录名。

    备注是用户定义的账户名，不代表平台实测身份。平台绑定在创建时确定，
    不复用其它平台账户；显式备注不覆盖另一份账户的自定义备注。

    已经存在但没登录过的容器会被复用（包括历史遗留的那个），
    否则用户每点一次「添加店铺」就在磁盘上多一个空目录。
    """
    platform = normalize_platform(platform)
    label = _profile_label(label)
    with _registry_lock:
        registry = load_registry()
        existing = registry.get("profiles") or {}

        # 复用要同时满足两条：注册表里没登录记录，磁盘上也确实没有登录数据。
        # 少查磁盘那一条，就会把一个还留着旧 cookie 的目录当成空容器交出去。
        for slug, entry in existing.items():
            if entry["platform"] != platform:
                continue
            old_label = _profile_label(entry.get("label"))
            if label is not None and old_label is not None and label != old_label:
                continue
            has_identity_history = any(
                entry.get(field) for field in ("shop_id", "shop_name", "last_seen_at", "seen_count", "history")
            )
            if not has_identity_history and not has_login_data(slug):
                if label is not None:
                    entry["label"] = label
                save_registry(registry)
                return slug
        for _ in range(20):
            # 目录前缀按平台区分（抖店沿用历史默认 "shop" ✓；小红书用 "xhs"）。
            # 与 PLATFORM_LABELS / ACCOUNT_PLATFORMS 对应，加平台时三处一起补 ✓。
            prefix = {"douyin": "shop", "taobao": "taobao", "xiaohongshu": "xhs"}.get(platform, "shop")
            slug = "{}-{}".format(prefix, uuid.uuid4().hex[:8])
            if slug not in existing and not has_login_data(slug):
                break
        else:
            raise RuntimeError("无法生成未占用的账户目录，请重试添加账户")
        registry["profiles"][slug] = _new_profile(slug, platform, label)
        save_registry(registry)
    return slug


def is_empty_default_profile(profile_name: str, entry: Any) -> bool:
    """识别固定默认空占位，不把有身份、备注或观测历史的账户当成占位。"""
    if profile_name != DEFAULT_PROFILE_NAME or not isinstance(entry, Mapping):
        return False
    if any(entry.get(field) for field in ("shop_id", "shop_name", "last_seen_at", "seen_count", "history")):
        return False
    return _profile_label(entry.get("label")) is None


def get_active_profile() -> str:
    return slugify_profile_name(load_registry().get("active_profile"))


def set_active_profile(
    profile_name: str, label: Optional[str] = None, platform: Optional[str] = None
) -> str:
    slug = slugify_profile_name(profile_name)
    with _registry_lock:
        registry = load_registry()
        _ensure_profile_entry(registry, slug, label, platform)
        registry["active_profile"] = slug
        save_registry(registry)
    return slug


def _purge_profile_directory(slug: str) -> bool:
    """彻底删除一个 profile 的浏览器数据目录。

    目录里是登录态。**先改名再删**，理由是失败时的状态：

    * 直接 ``rmtree`` 遇到占用（浏览器还开着）会在**删掉一半之后**报错，
      留下一个残缺的 Chrome profile——Chrome 下次启动可能直接报「配置文件损坏」；
    * 先 ``os.replace`` 改名：改名失败说明目录被占用，此时**一个字节都没动**，
      原路径完好，可以安全地提示用户「先关闭该账户的浏览器」；
      改名成功后，即使 ``rmtree`` 中途失败，损坏的也只是一个已经准备删除的临时目录。

    路径安全：只允许删除 ``profiles_base_dir()`` **正下方**的那个同名目录，
    且必须是普通目录（重解析点一律拒绝）。任何不满足的情况都抛错而不是勉强删。
    """

    import shutil

    base = os.path.abspath(profiles_base_dir())
    target = os.path.abspath(os.path.join(base, slug))
    # 必须严格位于 base 之内，且不是 base 本身。
    if os.path.dirname(target) != base or os.path.basename(target) != slug:
        raise ValueError("拒绝删除：目标不在账户目录根下")
    if not os.path.isdir(target):
        return False
    if os.path.islink(target):
        raise ValueError("拒绝删除：目标是符号链接")

    staging = os.path.join(base, ".purge-{}-{}".format(slug, uuid.uuid4().hex[:8]))
    try:
        os.replace(target, staging)
    except OSError as exc:
        raise ValueError("该账户的浏览器可能还在运行，请先关闭它再删除（{}）".format(exc)) from exc

    shutil.rmtree(staging, ignore_errors=True)
    if os.path.isdir(staging):
        # 改名成功但没删干净：此时原路径已经是干净的，残留的只是一个待删目录。
        raise ValueError("已从列表移除，但磁盘上的登录资料未能完全删除：{}".format(staging))
    return True


def remove_profile(profile_name: str, purge_directory: bool = False) -> bool:
    """移除一个 profile 记录；``purge_directory`` 为真时**同时删除浏览器数据目录**。

    :param purge_directory: 删除的语义分两档，调用方必须明确选一个：

        * ``False``（默认）—— 只摘掉列表里的记录，磁盘上的登录态保留。
          适合「先让它从列表消失，回头再说」。
        * ``True`` —— 记录与登录资料一起删。**这才是用户说的「删除」。**
          下次重新添加同一个账户时是全新的、未登录的状态。

    允许移除**当前账户**：删掉之后会把 active 交给另一个仍然存在的账户
    （按 ``last_seen_at`` 取最近见过的那个），一个都不剩时退回默认占位。
    这一点与早先的实现不同——早先要求「先切走再删」，但用户遇到「登录错了账户」
    时，那个错账户恰恰就是当前账户，要求先切走等于把人卡住。

    .. warning::
        删掉当前账户的记录之后，如果它的浏览器仍然开着并处于登录态，
        下一次实测会把这条记录**重新登记回来**（这是自动发现账户的设计使然）。
        所以「删当前账户」通常要配合关闭该浏览器，或者用 ``purge_directory=True``。
    """

    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("账户标识必须是非空字符串")
    slug = slugify_profile_name(profile_name)
    with _registry_lock:
        registry = load_registry()
        profiles = registry.get("profiles", {})
        if slug not in profiles:
            return False
        if slug == DEFAULT_PROFILE_NAME and not is_empty_default_profile(slug, profiles[slug]):
            raise ValueError("默认浏览器账户已有店铺身份、备注或观测历史，不能作为空占位移除")

        was_active = slugify_profile_name(registry.get("active_profile")) == slug
        # 先删目录再删记录：目录删不掉时（浏览器占用）就应该整体失败，
        # 不能出现「记录没了但登录资料还在」这种既没删干净又查不到的状态。
        if purge_directory:
            _purge_profile_directory(slug)

        del profiles[slug]
        if was_active:
            # 交回给一个**确实还存在**的账户，而不是一个可能不存在的默认占位——
            # 后者会让下一个 /api/shop/current 直接报「当前账户不存在」。
            remaining = sorted(
                profiles.values(),
                key=lambda item: str(item.get("last_seen_at") or item.get("created_at") or ""),
                reverse=True,
            )
            registry["active_profile"] = remaining[0]["profile_name"] if remaining else DEFAULT_PROFILE_NAME
        save_registry(registry)
    return True


def observe_identity(
    profile_name: str,
    shop_id: Optional[str],
    shop_name: Optional[str],
    platform: str = "douyin",
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """记录一次实测观测。

    返回 ``{'status': 'new'|'confirmed'|'changed', 'previous_shop_id': ...}``。
    ``changed`` 表示同一个 profile 这次登录到了**另一家店**——通常是用户
    自己重新登录换了店，是合法操作，但必须留痕，否则「以为在发 A 店」这类
    错误没有任何线索可查。

    :param platform: 本次实测走的是哪条平台链路。**必须与注册表里该 profile
        的平台一致**——把淘宝读出来的身份写进抖店 profile，正是本模块开头
        那条「profile 名字不代表登录了哪个店铺」要防的漂移。
    :param account_id: **账户** ID（淘宝的 ``unb``）。与 ``shop_id``（**店铺** ID）
        是两件事，实测比例是 13 位 : 9 位。分开存是为了不把「谁登录的」和
        「哪家店」混成一个字段——抖店那边这两者是同一个东西，淘宝不是。
    """

    normalized = normalize_platform(platform)
    slug = slugify_profile_name(profile_name)
    with _registry_lock:
        registry = load_registry()
        entry = registry["profiles"].get(slug)
        if entry is not None and entry["platform"] != normalized:
            raise ValueError(
                "账户平台不匹配：profile {} 登记为 {}，本次实测走的是 {}".format(
                    slug, entry["platform"], normalized
                )
            )
        # 一个身份都没有才叫「不知道」。只有账户 ID（淘宝能读 unb 但读不到店铺）时
        # 仍然要记下来——「确认了登录的账户」本身是有价值的事实，只是没有店铺 ID。
        if not shop_id and not account_id:
            return {"status": "unknown", "previous_shop_id": None}
        now = datetime.now().isoformat(timespec="seconds")
        shop_id = str(shop_id) if shop_id else None
        account_id = str(account_id) if account_id else None

        if entry is None:
            registry["profiles"][slug] = {
                "profile_name": slug,
                "platform": normalized,
                "label": None,
                "created_at": now,
                "shop_id": shop_id,
                "shop_name": shop_name or None,
                "account_id": account_id,
                "last_seen_at": now,
                "seen_count": 1,
            }
            save_registry(registry)
            return {"status": "new", "previous_shop_id": None}

        previous = entry.get("shop_id")
        if previous == shop_id:
            status = "confirmed"
        elif previous:
            status = "changed"
        else:
            status = "new"

        entry["shop_id"] = shop_id
        if account_id:
            entry["account_id"] = account_id
        if shop_name:
            entry["shop_name"] = shop_name
        entry["last_seen_at"] = now
        entry["seen_count"] = int(entry.get("seen_count") or 0) + 1
        if status == "changed":
            history = entry.setdefault("history", [])
            history.append(
                {"shop_id": previous, "shop_name": entry.get("shop_name"), "replaced_at": now}
            )
            del history[:-9]
        save_registry(registry)
        return {"status": status, "previous_shop_id": previous}


def list_profiles() -> List[Dict[str, Any]]:
    """列出可选择的绑定平台账户，包括尚未实测登录身份的账户。

    未实测到身份的账户以用户备注或本地账户标识展示，不把它冒充成店铺身份。

    **两个平台现在走同一套规则**：``shop_id`` 是实测值，有就是已验证，没有就是
    未验证。早先这里写死 ``platform == "douyin"``，导致淘宝**永远不可能**
    变成已验证——那是当时「淘宝只做本地资料准备」的产品决策留下的。
    现在淘宝也走真实登录链路了，所以规则统一。
    """
    registry = load_registry()
    active = slugify_profile_name(registry.get("active_profile"))
    result = []
    for slug, entry in (registry.get("profiles") or {}).items():
        item = dict(entry)
        item["profile_name"] = slug
        # 「已验证」= 实测到过任何一个真实的平台身份。
        #
        # 淘宝上「账户 ID」与「店铺 ID」是两个不同的东西，可能只拿到前者
        # （登录确认了，但店铺信息接口没读到）。那种情况仍算「已验证登录」，
        # 只是没有店铺身份——展示时据实说明，不拿账户 ID 冒充店铺 ID。
        has_verified_identity = bool(item.get("shop_id") or item.get("account_id"))
        if not has_verified_identity:
            default_label = (
                "默认抖音账户" if slug == DEFAULT_PROFILE_NAME
                else "{}账户 {}".format("淘宝" if item["platform"] == "taobao" else "抖音", slug[-8:])
            )
            item["label"] = _profile_label(item.get("label")) or default_label
            item["shop_id"] = None
            item["shop_name"] = None
            item["account_id"] = None
        else:
            item["label"] = display_label(
                slug, item.get("label"), item.get("shop_name"), item.get("shop_id")
            )
        item["is_active"] = slug == active
        # 允许移除**当前账户**：后端会把它交接给另一个仍然存在的账户。
        #
        # 早先这里还有一条 ``slug != active``，要求「先切走再删」。理由是
        # 「当前这家移除了也会被实测记回来」——那个顾虑本身没错（浏览器还开着并
        # 登录着时，下一次实测确实会把记录重新登记回来），但拿它来禁用按钮是错的：
        # 用户遇到「登录错了账户」时，那个错账户恰恰就是当前账户，要求先切走等于
        # 把人卡死在原地。真正的解法是让删除**连浏览器数据目录一起删**。
        item["removable"] = slug != DEFAULT_PROFILE_NAME or is_empty_default_profile(slug, entry)
        # 这里的店铺名是「上次登录时看到的」，不是当前事实；
        # 当前登录着哪家以 /api/shop/current 的实测结果为准。
        item["identity_source"] = "registry_last_seen" if has_verified_identity else "local_account"
        result.append(item)
    result.sort(key=lambda x: (not x["is_active"], x["label"]))
    return result


def owning_profile_of(user_data_dir: Optional[str]) -> Optional[str]:
    """这个浏览器的用户数据目录属于哪个店铺 profile。

    实测结果必须记到「它真正来自的那个 profile」，而不是「当前选中的那个」。
    记错了就会出现：注册表声称 A 目录是甲店，其实甲店在 B 目录里——
    这正是本模块开头那条原则要防的漂移，只不过换了个方向。

    目录不在我们的 profile 根目录下（例如协议探针自己的目录）时返回 None，
    这种浏览器不归属任何店铺，不该往注册表里写东西。
    """
    if not user_data_dir:
        return None
    try:
        base = os.path.normcase(os.path.abspath(profiles_base_dir()))
        target = os.path.normcase(os.path.abspath(str(user_data_dir)))
    except Exception:
        return None
    parent, name = os.path.split(target.rstrip(r"\/"))
    if parent != base or not name:
        return None
    return os.path.basename(str(user_data_dir).rstrip(r"\/"))


def browser_profile_text(browser: Optional[Dict[str, Any]]) -> str:
    return "{} {}".format(
        (browser or {}).get("user_data_dir") or "",
        (browser or {}).get("profile_directory") or "",
    ).strip().lower()


def filter_browsers_for_profile(
    browsers: List[Dict[str, Any]],
    active_profile: str,
    known_profiles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """从候选浏览器里剔除「属于别的店铺」的那些。

    多店铺同时开着时，如果不过滤，就会出现「切到 B 店 → B 的浏览器没开 →
    复用还开着的 A 店浏览器」：每一步都成功，商品却发到了另一家店，事后无迹可查。

    过滤是双向的，默认店铺同样不能反过来抢别人的浏览器。
    不属于任何已登记店铺的浏览器（比如协议探针那个独立目录）仍然放行——
    它不归属任何一家店，谈不上串店。
    """
    needle = str(active_profile or "").strip().lower()
    if known_profiles is None:
        known_profiles = list((load_registry().get("profiles") or {}).keys())
    others = [str(name).lower() for name in known_profiles if str(name).lower() != needle]

    kept: List[Dict[str, Any]] = []
    for browser in browsers or []:
        text = browser_profile_text(browser)
        if needle and needle in text:
            kept.append(browser)
        elif any(other and other in text for other in others):
            continue
        else:
            kept.append(browser)
    return kept


# ---------------------------------------------------------------- 实测身份


def _cdp_page_targets(debug_address: str, timeout: float = 2.0) -> List[Dict[str, Any]]:
    from urllib.request import urlopen

    url = "http://{}/json/list".format(debug_address)
    with urlopen(url, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return data if isinstance(data, list) else []


def _pick_fxg_target(targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for target in targets:
        url = target.get("url") or ""
        if (
            target.get("type") == "page"
            and FXG_DOMAIN in url
            and not url.startswith("devtools://")
        ):
            return target
    return None


def _shop_info_expression() -> str:
    """在页面上下文里请求店铺信息接口的 JS。

    必须在页面里发（而不是 sidecar 直接 HTTP），因为登录态是 cookie，
    只有同源页面上下文才带得上。

    这段代码可能在「发布流程正在自动填表」的同一个页面上执行，
    所以绝不能留下任何 DOM 痕迹：默认直接用页面原生 fetch，
    只有确认 fetch 被 SPA 包过时才临时建一个 iframe 取干净引用，用完立刻删掉。
    """
    return (
        "(async () => {"
        "  let frame = null;"
        "  let send = window.fetch;"
        "  try {"
        "    if (!/native code/.test(String(window.fetch)) && document.body) {"
        "      frame = document.createElement('iframe');"
        "      frame.style.display = 'none';"
        "      frame.src = 'about:blank';"
        "      document.body.appendChild(frame);"
        "      send = frame.contentWindow.fetch.bind(frame.contentWindow);"
        "    } else {"
        "      send = window.fetch.bind(window);"
        "    }"
        "  } catch (e) { send = window.fetch.bind(window); }"
        "  try {"
        "    const r = await send(" + json.dumps(SHOP_INFO_URL) + ", "
        "      {credentials: 'include', headers: {accept: 'application/json, text/plain, */*'}});"
        "    const text = await r.text();"
        "    return JSON.stringify({status: r.status, body: text.slice(0, 20000)});"
        "  } catch (e) {"
        "    return JSON.stringify({status: 0, error: String(e)});"
        "  } finally {"
        "    if (frame && frame.parentNode) { frame.parentNode.removeChild(frame); }"
        "  }"
        "})()"
    )


def _extract_shop_fields(payload: Any) -> Dict[str, Optional[str]]:
    """从店铺信息接口响应里取店铺 id 与店铺名。

    实测响应形如
    ``{"st":10008,"msg":"账号未登录","code":10008,"data":{},"page":0,"size":0,"total":0}``，
    店铺信息在 ``data`` 里。**只在 data / data.shop 里找，不碰信封外层**——
    外层的 id / name 之类字段和店铺无关，认错了就是发错店。
    """
    candidates: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        inner = payload.get("data")
        if isinstance(inner, dict):
            candidates.append(inner)
            deeper = inner.get("shop")
            if isinstance(deeper, dict):
                candidates.append(deeper)

    shop_id: Optional[str] = None
    shop_name: Optional[str] = None
    for item in candidates:
        if shop_id is None:
            for key in ("shop_id", "shopId", "id"):
                value = item.get(key)
                if value not in (None, "", 0, "0"):
                    shop_id = str(value)
                    break
        if shop_name is None:
            for key in ("shop_name", "shopName", "name"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    shop_name = value.strip()
                    break
    return {"shop_id": shop_id, "shop_name": shop_name}


# 抖店后台用这个业务码表示「账号未登录」（实测 2026-09-06）。
LOGGED_OUT_BUSINESS_CODES = frozenset({10008})


def _server_says_logged_out(raw: Optional[str]) -> bool:
    """服务端是否明确回了「未登录」。

    这比 cookie 更可信：cookie 可能是过期会话留下的。
    只认明确的业务码，解析不出来时返回 False——不确定就别推翻 cookie 的结论。
    """
    if not raw:
        return False
    try:
        envelope = json.loads(raw)
        body = envelope.get("body") if isinstance(envelope, dict) else None
        parsed = json.loads(body) if isinstance(body, str) and body.strip() else None
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    for key in ("code", "st"):
        value = parsed.get(key)
        if isinstance(value, int) and value in LOGGED_OUT_BUSINESS_CODES:
            return True
    return False


def _describe_shop_info_failure(raw: Optional[str]) -> str:
    """店铺名取不到时，说清楚是卡在哪一步。

    之前这里把异常全吞了，线上只看到「没有店铺名」，无从判断是接口没通、
    没登录，还是字段名变了。这条信息只写进 detail，不展示给用户。
    """
    if not raw:
        return "店铺信息接口没有返回内容"
    try:
        envelope = json.loads(raw)
    except Exception:
        return "店铺信息接口返回的不是 JSON：{}".format(str(raw)[:200])

    if not isinstance(envelope, dict):
        return "店铺信息接口返回结构异常：{}".format(str(raw)[:200])
    if envelope.get("error"):
        return "请求店铺信息接口失败：{}".format(envelope["error"])

    body = envelope.get("body")
    status = envelope.get("status")
    if not isinstance(body, str) or not body.strip():
        return "店铺信息接口 HTTP {} 无响应体".format(status)
    try:
        parsed = json.loads(body)
    except Exception:
        return "店铺信息接口 HTTP {} 返回的不是 JSON：{}".format(status, body[:200])

    if not isinstance(parsed, dict):
        return "店铺信息接口 HTTP {} 返回结构异常".format(status)

    code = parsed.get("code", parsed.get("st"))
    msg = parsed.get("msg") or parsed.get("message")
    data = parsed.get("data")
    # 把 data 的字段名列出来（只列名字不列值）：字段名变了的话，一次失败就能看出来。
    keys = sorted(data.keys())[:30] if isinstance(data, dict) else type(data).__name__
    return "店铺信息接口 HTTP {} code={} msg={} data字段={}".format(status, code, msg, keys)


def read_shop_identity(debug_address: str, timeout: float = 10.0) -> Dict[str, Any]:
    """从一个已开远程调试端口的浏览器上实测当前店铺身份。

    ``status`` 取值：

      - ``logged_in``   读到店铺 id（``shop_name`` 可能为 None）
      - ``logged_out``  有抖店页面但没有店铺登录态
      - ``no_fxg_tab``  浏览器里没有抖店页面
      - ``unreachable`` 连不上这个调试端口
      - ``conflict``    cookie 与服务端返回的店铺 id 不一致

    **任何分支都不会返回猜测出来的 shop_id。**
    """
    result: Dict[str, Any] = {
        "status": "unreachable",
        "debug_address": debug_address,
        "shop_id": None,
        "shop_name": None,
        "cookie_shop_id": None,
        "server_shop_id": None,
        "page_url": None,
        "error": None,
        # 技术细节只用于日志排查，不展示给用户
        "detail": None,
    }

    try:
        targets = _cdp_page_targets(debug_address, timeout=min(3.0, timeout))
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "无法访问调试端口 {}：{}".format(debug_address, exc)
        return result

    target = _pick_fxg_target(targets)
    if not target or not target.get("webSocketDebuggerUrl"):
        result["status"] = "no_fxg_tab"
        result["error"] = "尚未登录"
        return result

    result["page_url"] = target.get("url")

    try:
        import websocket as _ws
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "websocket 模块不可用：{}".format(exc)
        return result

    ws = None
    cookies_raw: Optional[List[Dict[str, Any]]] = None
    shop_info_raw: Optional[str] = None
    try:
        ws = _ws.create_connection(
            target["webSocketDebuggerUrl"], timeout=min(5.0, timeout), suppress_origin=True
        )
        ws.settimeout(2)
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        ws.send(
            json.dumps(
                {
                    "id": 3,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": _shop_info_expression(),
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )

        deadline = time.time() + timeout
        while time.time() < deadline and (cookies_raw is None or shop_info_raw is None):
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("id") == 2:
                cookies_raw = message.get("result", {}).get("cookies", []) or []
            elif message.get("id") == 3:
                value = ((message.get("result") or {}).get("result") or {}).get("value")
                shop_info_raw = value if isinstance(value, str) else ""
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "读取店铺身份失败：{}".format(exc)
        return result
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    cookie_shop_id = None
    for cookie in cookies_raw or []:
        if cookie.get("name") == SHOP_ID_COOKIE and FXG_DOMAIN in (cookie.get("domain") or ""):
            raw_value = str(cookie.get("value") or "").strip()
            if raw_value:
                cookie_shop_id = raw_value
            break
    result["cookie_shop_id"] = cookie_shop_id

    server_shop_id = None
    shop_name = None
    if shop_info_raw:
        try:
            envelope = json.loads(shop_info_raw)
            body = envelope.get("body") if isinstance(envelope, dict) else None
            parsed = json.loads(body) if isinstance(body, str) and body.strip() else None
            fields = _extract_shop_fields(parsed)
            server_shop_id = fields["shop_id"]
            shop_name = fields["shop_name"]
        except Exception:
            # 接口结构变了或返回了 HTML 登录页：店铺名拿不到就不显示，
            # 但不能因此影响 cookie 这一路实测结果。
            server_shop_id = None
            shop_name = None
    if not shop_name:
        # 名字取不到时把原因记下来。只进 detail，不展示给用户。
        result["detail"] = _describe_shop_info_failure(shop_info_raw)
    result["server_shop_id"] = server_shop_id
    result["shop_name"] = shop_name

    # 服务端说没登录，就是没登录。cookie 可能是上次留下的旧值，
    # 只信 cookie 会把一个早就失效的店铺显示成「当前店铺」，
    # 用户以为在发 A 店，实际根本发不出去或发到别处。
    if _server_says_logged_out(shop_info_raw):
        # 服务端只说「没登录」，分不出是从没登录过还是登录过期，
        # 所以这里也不要替它下结论。
        result["status"] = "logged_out"
        result["error"] = "尚未登录"
        result["shop_id"] = None
        result["shop_name"] = None
        return result

    if cookie_shop_id and server_shop_id and cookie_shop_id != server_shop_id:
        result["status"] = "conflict"
        result["error"] = "登录状态异常，请重新登录后再发布"
        result["detail"] = "cookie 店铺 id={} 与店铺信息接口返回的 {} 不一致".format(
            cookie_shop_id, server_shop_id
        )
        return result

    resolved = cookie_shop_id or server_shop_id
    if resolved:
        result["status"] = "logged_in"
        result["shop_id"] = resolved
        return result

    result["status"] = "logged_out"
    result["error"] = "尚未登录"
    return result


# ---------------------------------------------------------------- 淘宝身份

# 淘宝/天猫域名。抖店与淘宝是**两套互不相通的账号体系**，身份来源也完全不同，
# 不能把抖店那套 cookie / 接口结论搬过来用。
TAOBAO_DOMAINS = ("taobao.com", "tmall.com")

# 哪些页面算「卖家身份页」。有这些页面才谈得上验证卖家身份；
# 停在登录页或普通商品页说明不了「登录了哪个卖家账号」。
TAOBAO_SELLER_PAGE_HINTS = (
    "item.upload.taobao.com",   # 商品发布工作台
    "item.upload.tmall.com",    # 天猫发布页
    "myseller.taobao.com",      # 卖家中心
    "seller.taobao.com",
    "qn.taobao.com",            # 千牛工作台
)
TAOBAO_LOGIN_PAGE_HINTS = ("login.taobao.com", "login.tmall.com")

# 淘宝登录态里的账户身份 cookie。
#
# **已实证（2026-10-03，真实登录态）**：在专用 profile 里扫码登录一个淘宝账户后，
# ``read_taobao_identity`` 读出了 ``shop_id=1806098450`` 与 ``shop_name=qhdsow``，
# 并被 ``observe_identity`` 记进注册表（``seen_count=15``）。据此确认：
#
#   * ``unb`` 可用——``shop_id`` 只可能来自它，且形态确实是数字用户 ID；
#   * ``tracknick`` / ``_nk_`` 中**至少一个**可用（``shop_name`` 有值）。
#     两者是「按顺序取第一个非空」，具体哪一个生效没有单独区分——不影响结果，
#     但也不要把「两个都一定存在」当成事实。
#
# ⚠️ **语义差异（必须记住）**：这里读到的 ``shop_name`` 是**淘宝会员名（nick）**，
# 不是**店铺名**。淘宝的店铺名只能在卖家中心页面看到，目前没有已实证的读取方式。
# 调用方不得把会员名冒充成店铺名展示——前端在 ``taobaoIdentityNote`` 里如实说明了。
TAOBAO_USER_ID_COOKIES = ("unb",)
TAOBAO_NICK_COOKIES = ("tracknick", "_nk_")
#: 出现其中之一即可判定「这个浏览器确实有淘宝登录态」。
TAOBAO_AUTH_COOKIES = ("unb", "_nk_", "tracknick", "cookie2", "_tb_token_", "sgcookie", "cna")


def _pick_taobao_target(targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """挑一个能说明卖家身份的淘宝页面。

    优先级：卖家页 > 任意淘宝/天猫页 > 登录页。
    登录页也要能选中，否则「停在登录页」和「浏览器里根本没淘宝页」
    会被混成同一个状态，用户不知道下一步该干什么。
    """

    pages = [
        t for t in targets
        if t.get("type") == "page"
        and not str(t.get("url") or "").startswith("devtools://")
    ]

    def _is_taobao(url: str) -> bool:
        return any(domain in url for domain in TAOBAO_DOMAINS)

    for hint in TAOBAO_SELLER_PAGE_HINTS:
        for page in pages:
            if hint in str(page.get("url") or ""):
                return page
    for hint in TAOBAO_LOGIN_PAGE_HINTS:
        for page in pages:
            if hint in str(page.get("url") or ""):
                return page
    for page in pages:
        if _is_taobao(str(page.get("url") or "")):
            return page
    return None


def _collect_taobao_cookies(ws: Any, timeout: float) -> List[Dict[str, Any]]:
    """通过 CDP 取全部 cookie 里属于淘宝/天猫域的那些。"""

    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("id") == 2:
            cookies = message.get("result", {}).get("cookies", []) or []
            return [
                c for c in cookies
                if any(domain in str(c.get("domain") or "") for domain in TAOBAO_DOMAINS)
            ]
    return []


def _taobao_cookie_value(cookies: List[Dict[str, Any]], names: tuple) -> Optional[str]:
    """按优先级取第一个非空 cookie 值。取不到返回 None，**不返回空串**。"""

    for name in names:
        for cookie in cookies:
            if cookie.get("name") != name:
                continue
            raw = str(cookie.get("value") or "").strip()
            if raw:
                return raw
    return None


def read_taobao_identity(debug_address: str, timeout: float = 10.0) -> Dict[str, Any]:
    """从一个已开远程调试端口的浏览器上实测当前**淘宝账户**身份。

    与抖店那条路的关键区别（必须理解，否则会误读结果）：

    * 抖店有 ``/common/index/index`` 接口，同一个响应里给店铺 id 与店铺名，
      可以和 cookie 交叉校验；
    * 淘宝这边**没有已实证的等价接口**——官方发品 API 对集市卖家已关闭
      （见 ``taobao-publisher/docs/01-平台入口与路线判断.md``）。
      所以本函数**只读 cookie，不调用任何猜测出来的接口**。

    因此返回的 ``shop_name`` 实际是**淘宝会员名（nick）**，不是店铺名。
    淘宝的店铺名只能在卖家中心页面看到，目前没有已实证的读取方式。
    调用方**不得**把会员名冒充成店铺名展示。

    ``status`` 取值：

      - ``logged_in``        读到淘宝账户 ID
      - ``logged_out``       有淘宝页面但没有登录态（含停在登录页）
      - ``no_taobao_tab``    浏览器里没有淘宝/天猫页面
      - ``unreachable``      连不上这个调试端口

    **任何分支都不会返回猜测出来的账户 ID。**
    """

    result: Dict[str, Any] = {
        "status": "unreachable",
        "debug_address": debug_address,
        "platform": "taobao",
        "shop_id": None,
        "shop_name": None,
        "nick": None,
        "page_url": None,
        "error": None,
        # 技术细节只用于日志排查，不展示给用户
        "detail": None,
        # 诊断用：本次到底看到了哪些 cookie 名字（只列名字，不含值）
        "cookie_names_seen": [],
    }

    try:
        targets = _cdp_page_targets(debug_address, timeout=min(3.0, timeout))
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "无法访问调试端口 {}：{}".format(debug_address, exc)
        return result

    target = _pick_taobao_target(targets)
    if not target or not target.get("webSocketDebuggerUrl"):
        result["status"] = "no_taobao_tab"
        result["error"] = "尚未登录"
        return result

    page_url = str(target.get("url") or "")
    result["page_url"] = page_url

    try:
        import websocket as _ws
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "websocket 模块不可用：{}".format(exc)
        return result

    ws = None
    cookies: List[Dict[str, Any]] = []
    try:
        ws = _ws.create_connection(
            target["webSocketDebuggerUrl"], timeout=min(5.0, timeout), suppress_origin=True
        )
        ws.settimeout(2)
        cookies = _collect_taobao_cookies(ws, timeout)
    except Exception as exc:
        result["error"] = "读不到登录状态，请重新登录"
        result["detail"] = "读取淘宝 cookie 失败：{}".format(exc)
        return result
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    result["cookie_names_seen"] = sorted({str(c.get("name") or "") for c in cookies if c.get("name")})

    user_id = _taobao_cookie_value(cookies, TAOBAO_USER_ID_COOKIES)
    nick_raw = _taobao_cookie_value(cookies, TAOBAO_NICK_COOKIES)
    cookie_nick = unquote(nick_raw).strip() if nick_raw else None
    result["nick"] = cookie_nick or None

    # 停在登录页且没有任何登录态 cookie → 明确是「没登录」，
    # 不是「读不到」。这两种对用户的意义完全不同。
    has_auth_cookie = any(c.get("name") in TAOBAO_AUTH_COOKIES for c in cookies)
    on_login_page = any(hint in page_url for hint in TAOBAO_LOGIN_PAGE_HINTS)

    # unb 形态校验：淘宝的 unb 是数字用户 ID。形态不对说明 cookie 结构变了，
    # 这时**不能**把它当身份用——宁可报未登录，也不要写一个错的 ID 进注册表。
    account_id = None
    if user_id:
        if str(user_id).strip().isdigit():
            account_id = str(user_id).strip()
        else:
            result["status"] = "logged_out"
            result["error"] = "尚未登录"
            result["detail"] = "unb cookie 形态异常（非数字），未采信为账户 ID"
            return result

    # 账户 ID 只说明「登录了哪个账户」，**不等于**「哪个店铺」。
    # 店铺身份必须走接口读 mtop.taobao.jdy.resource.shop.info.get（实证见该函数）。
    shop = read_taobao_shop_info(debug_address, timeout=timeout)
    result["shop_info_status"] = shop.get("status")
    result["account_id"] = account_id

    if shop.get("status") == "ok":
        result["status"] = "logged_in"
        result["shop_id"] = shop.get("shop_id")
        # shop_name **只**来自接口的 shopName。绝不拿 cookie 里的会员名顶替：
        # 会员名是「谁登录的」，店铺名是「哪家店」，两者是不同的事实。
        result["shop_name"] = shop.get("shop_name")
        result["nick"] = shop.get("nick") or cookie_nick or None
        if not result["shop_name"]:
            result["detail"] = "接口返回了店铺 ID，但没有店铺名"
        return result

    # 接口读不到时，退回到「只确认了账户」——status 仍是 logged_in，
    # 但 shop_id/shop_name 留空，由调用方决定要不要把它算作已验证。
    if account_id:
        result["status"] = "logged_in"
        result["shop_name"] = None
        result["detail"] = "已确认登录的账户，但没读到店铺信息（{}）".format(
            shop.get("detail") or shop.get("error") or shop.get("status")
        )
        return result

    result["status"] = "logged_out"
    result["error"] = "尚未登录"
    if on_login_page:
        result["detail"] = "当前停在淘宝登录页"
    elif not has_auth_cookie:
        result["detail"] = "淘宝 cookie 里没有任何登录态标记（{}）".format(
            "/".join(TAOBAO_AUTH_COOKIES)
        )
    else:
        result["detail"] = "有登录态 cookie 但读不到账户 ID（{}）".format(
            "/".join(TAOBAO_USER_ID_COOKIES)
        )
    return result


def read_account_identity(
    debug_address: str, platform: str = "douyin", timeout: float = 10.0
) -> Dict[str, Any]:
    """按平台分派身份读取。

    抖店与淘宝的身份来源完全不同（cookie 名、接口、判定顺序都不一样），
    所以这里是**分派**而不是共用一套逻辑。共用会诱使人把一方的结论套到另一方，
    那正是本模块开头警告的事。
    """

    if normalize_platform(platform) == "taobao":
        return read_taobao_identity(debug_address, timeout=timeout)
    return read_shop_identity(debug_address, timeout=timeout)


# ---------------------------------------------------------------- 淘宝店铺信息

#: 淘宝卖家工作台自己调用的店铺信息接口。
#:
#: **来源是观察，不是猜**：用 ``taobao-publisher/tmp/review/observe_workbench_requests.py``
#: 通过 CDP 观察 ``item.upload.taobao.com/sell/ai/category.htm`` 自身发出的请求时发现，
#: 并由 ``capture_shop_info_api.py`` 抓到完整的 query 参数与响应结构（2026-10-03）。
#:
#: 实测请求形态（GET，JSONP）::
#:
#:     https://h5api.m.taobao.com/h5/mtop.taobao.jdy.resource.shop.info.get/1.0/
#:         ?jsv=2.6.1 &appKey=12574478 &v=1.0 &data={}
#:         &type=originaljsonp &dataType=originaljsonp
#:         &ttid=11320@taobao_WEB_9.9.99
#:         &t=<毫秒时间戳> &sign=md5(token&t&appKey&data)
#:
#: ``appKey`` / ``jsv`` 与 ``taobao-publish/taobao_publish/mtop.py`` 里的常量逐字相同；
#: ``sign`` 算法与该模块的 :func:`taobao_publish.mtop.sign` 一致。**没有搬用抖店的任何结论。**
TAOBAO_SHOP_INFO_API = "mtop.taobao.jdy.resource.shop.info.get"
TAOBAO_SHOP_INFO_VERSION = "1.0"
TAOBAO_SHOP_INFO_TTID = "11320@taobao_WEB_9.9.99"
TAOBAO_MTOP_APP_KEY = "12574478"
TAOBAO_MTOP_JSV = "2.6.1"
TAOBAO_MTOP_HOST = "https://h5api.m.taobao.com"
TAOBAO_SHOP_INFO_REFERER = "https://item.upload.taobao.com/sell/ai/category.htm"

#: mtop 的登录态失效返回码。遇到时重取一次 ``_m_h5_tk`` 再试一次。
TAOBAO_TOKEN_ERROR_CODES = ("FAIL_SYS_TOKEN_EXOIRED", "FAIL_SYS_TOKEN_EMPTY", "FAIL_SYS_SESSION_EXPIRED")


def _mtop_sign(token: str, timestamp_ms: str, app_key: str, data_str: str) -> str:
    """``md5(token&t&appKey&data)``。

    与 ``taobao-publish/taobao_publish/mtop.py`` 的 ``sign`` 是同一个算法。
    这里没有 import 它，是因为本模块属于共享库 ``src/``，而那个包在
    开发模式下不在 ``sys.path`` 上（只有打包后的 sidecar 通过 ``--paths`` 带上）。
    为了不让「读一次店铺名」这种小事把两边的导入路径绑死，就地实现；
    改动其一时**必须同步另一边**。
    """

    material = "{token}&{ts}&{key}&{data}".format(token=token, ts=timestamp_ms, key=app_key, data=data_str)
    return hashlib.md5(material.encode("utf-8")).hexdigest()


def read_taobao_shop_info(debug_address: str, timeout: float = 10.0) -> Dict[str, Any]:
    """读淘宝**店铺**信息：店铺名、店铺 ID、会员名。

    与 :func:`read_taobao_identity` 的关系（重要，别混）：

    * :func:`read_taobao_identity` 从 **cookie** 读 ``unb``——那是淘宝的**账户** ID；
    * 本函数从**接口**读 ``shopId``——那才是**店铺** ID。

    两者不是一回事（实测：账户 ID 13 位、店铺 ID 9 位）。把账户 ID 当店铺 ID 存进
    ``shop_id`` 是语义错误，所以这里单独读、单独返回字段。

    请求从 Python 侧发出（带上 CDP 读到的 cookie），**不在页面里注入 script**：
    mtop 的 H5 网关对这个接口只提供 JSONP，在页面里发就必须插 ``<script>``，
    会在用户页面上留下 DOM 痕迹。Python 侧直接发就没这个问题。

    :return: ``status`` 为 ``ok`` / ``token_missing`` / ``auth_failed`` / ``failed`` /
        ``unreachable`` / ``no_taobao_tab``。
    """

    result: Dict[str, Any] = {
        "status": "unreachable",
        "platform": "taobao",
        "shop_id": None,
        "shop_name": None,
        "nick": None,
        "error": None,
        "detail": None,
    }

    try:
        targets = _cdp_page_targets(debug_address, timeout=min(3.0, timeout))
    except Exception as exc:
        result["error"] = "读不到店铺信息，请重新登录"
        result["detail"] = "无法访问调试端口 {}：{}".format(debug_address, exc)
        return result

    target = _pick_taobao_target(targets)
    if not target or not target.get("webSocketDebuggerUrl"):
        result["status"] = "no_taobao_tab"
        result["error"] = "尚未登录"
        return result

    try:
        import websocket as _ws
    except Exception as exc:
        result["error"] = "读不到店铺信息，请重新登录"
        result["detail"] = "websocket 模块不可用：{}".format(exc)
        return result

    ws = None
    try:
        ws = _ws.create_connection(
            target["webSocketDebuggerUrl"], timeout=min(5.0, timeout), suppress_origin=True
        )
        ws.settimeout(2)
        cookies = _collect_taobao_cookies(ws, timeout)
    except Exception as exc:
        result["error"] = "读不到店铺信息，请重新登录"
        result["detail"] = "读取淘宝 cookie 失败：{}".format(exc)
        return result
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    token_cookie = _taobao_cookie_value(cookies, ("_m_h5_tk",))
    token = None
    if token_cookie:
        # 格式 "<token>_<过期毫秒>"；token 本身不含下划线，按第一个下划线切。
        token = token_cookie.partition("_")[0] or None
    if not token:
        result["status"] = "token_missing"
        result["error"] = "读不到店铺信息，请在该浏览器里重新登录淘宝"
        result["detail"] = "cookie 里没有可用的 _m_h5_tk（mtop 签名 token）"
        return result

    payload = _call_taobao_shop_info(cookies, token, timeout)
    if payload.get("error"):
        result.update({"status": payload.get("status") or "failed",
                       "error": payload["error"], "detail": payload.get("detail")})
        return result

    body = payload.get("body")
    if not isinstance(body, dict):
        result["status"] = "failed"
        result["error"] = "店铺信息响应无法解析"
        result["detail"] = payload.get("detail")
        return result

    ret = body.get("ret") or []
    ret_text = " ".join(str(item) for item in ret) if isinstance(ret, list) else str(ret)
    if "SUCCESS" not in ret_text:
        result["status"] = "auth_failed"
        result["error"] = "读不到店铺信息，请重新登录"
        # 只留返回码的**前缀**，避免把整串（可能含会话信息）写进日志
        result["detail"] = "mtop 返回码：{}".format(ret_text.split("::")[0][:60])
        return result

    data = body.get("data")
    entry = data.get("result") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        result["status"] = "failed"
        result["error"] = "店铺信息响应里没有 data.result"
        result["detail"] = "顶层字段：{}".format(sorted(body.keys())[:12])
        return result

    shop_id = entry.get("shopId")
    result["status"] = "ok"
    result["shop_id"] = str(shop_id) if shop_id not in (None, "", 0, "0") else None
    result["shop_name"] = _clean_text(entry.get("shopName"))
    result["nick"] = _clean_text(entry.get("displayNick")) or _clean_text(entry.get("nick"))
    if not result["shop_id"]:
        result["status"] = "failed"
        result["error"] = "店铺信息里没有 shopId"
        result["detail"] = "data.result 字段：{}".format(sorted(entry.keys())[:20])
    return result


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _call_taobao_shop_info(
    cookies: List[Dict[str, Any]], token: str, timeout: float
) -> Dict[str, Any]:
    """发一次已签名的 mtop 请求。返回 ``{'body': ...}`` 或 ``{'error': ...}``。

    .. warning::
        这里会临时拼出带登录态的 ``Cookie`` 头。**只存在于内存**，
        任何分支都不得把它写进日志、异常信息或产物。
    """

    try:
        import requests
    except Exception as exc:
        return {"error": "读不到店铺信息，请重新登录", "detail": "requests 不可用：{}".format(exc)}

    data_str = "{}"
    timestamp = str(int(time.time() * 1000))
    signature = _mtop_sign(token, timestamp, TAOBAO_MTOP_APP_KEY, data_str)

    query = {
        "jsv": TAOBAO_MTOP_JSV,
        "appKey": TAOBAO_MTOP_APP_KEY,
        "t": timestamp,
        "sign": signature,
        "api": TAOBAO_SHOP_INFO_API,
        "v": TAOBAO_SHOP_INFO_VERSION,
        "type": "originaljson",
        "dataType": "json",
        "ttid": TAOBAO_SHOP_INFO_TTID,
        "data": data_str,
    }
    url = "{host}/h5/{api}/{version}/?{query}".format(
        host=TAOBAO_MTOP_HOST,
        api=TAOBAO_SHOP_INFO_API,
        version=TAOBAO_SHOP_INFO_VERSION,
        query="&".join("{}={}".format(k, quote(str(v), safe="")) for k, v in query.items()),
    )

    cookie_header = "; ".join(
        "{}={}".format(c.get("name"), c.get("value"))
        for c in cookies
        if c.get("name") and c.get("value") is not None
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": TAOBAO_SHOP_INFO_REFERER,
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_header,
    }

    try:
        response = requests.get(url, headers=headers, timeout=max(3.0, min(timeout, 15.0)))
    except Exception as exc:
        # 异常文本可能带上完整 URL（含 sign），所以只报类型，不回显。
        return {
            "error": "读不到店铺信息，请重新登录",
            "detail": "请求失败：{}".format(type(exc).__name__),
        }

    text = response.text or ""
    for code in TAOBAO_TOKEN_ERROR_CODES:
        if code in text:
            return {
                "status": "auth_failed",
                "error": "读不到店铺信息，请在该浏览器里重新登录淘宝",
                "detail": "mtop 报 {}（签名 token 已失效）".format(code),
            }

    try:
        body = json.loads(text)
    except Exception:
        return {
            "error": "店铺信息响应不是 JSON",
            "detail": "HTTP {}，响应长度 {}".format(response.status_code, len(text)),
        }
    return {"body": body}


# ---------------------------------------------------------------- 运费模板

# 店铺运费模板列表。实测（2026-09-06）响应：
#   {"code":0,"st":0,"msg":"","data":{"count":7,"list":[{...}]},...}
# 每条模板带 id / template_name / shop_id 等字段。
FREIGHT_TEMPLATE_URL = "https://fxg.jinritemai.com/freight/template/getFreightTemplateList"


def _freight_expression() -> str:
    """在页面上下文里请求运费模板列表的 JS。

    和店铺信息一样必须在同源页面里发（登录态是 cookie），
    也同样不能在页面上留下任何 DOM 痕迹——这个页面可能正被发布流程操作。
    """
    return (
        "(async () => {"
        "  let frame = null;"
        "  let send = window.fetch;"
        "  try {"
        "    if (!/native code/.test(String(window.fetch)) && document.body) {"
        "      frame = document.createElement('iframe');"
        "      frame.style.display = 'none';"
        "      frame.src = 'about:blank';"
        "      document.body.appendChild(frame);"
        "      send = frame.contentWindow.fetch.bind(frame.contentWindow);"
        "    } else {"
        "      send = window.fetch.bind(window);"
        "    }"
        "  } catch (e) { send = window.fetch.bind(window); }"
        "  try {"
        "    const r = await send(" + json.dumps(FREIGHT_TEMPLATE_URL) + ", "
        "      {credentials: 'include', headers: {accept: 'application/json, text/plain, */*'}});"
        "    const text = await r.text();"
        "    return JSON.stringify({status: r.status, body: text.slice(0, 60000)});"
        "  } catch (e) {"
        "    return JSON.stringify({status: 0, error: String(e)});"
        "  } finally {"
        "    if (frame && frame.parentNode) { frame.parentNode.removeChild(frame); }"
        "  }"
        "})()"
    )


def _extract_freight_templates(payload: Any) -> List[Dict[str, Any]]:
    """从运费模板接口响应里取出模板列表。

    实测结构是 ``data.list``。只认已知位置，不做深度递归猜测——
    发布流程按模板名匹配，认错了就是按别的运费规则发货。
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    raw_list = None
    if isinstance(data, dict):
        for key in ("list", "data", "templates"):
            if isinstance(data.get(key), list):
                raw_list = data[key]
                break
    elif isinstance(data, list):
        raw_list = data
    if not raw_list:
        return []

    templates = []
    seen_names = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = item.get("template_name") or item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in seen_names:
            continue
        seen_names.add(name)

        raw_id = item.get("id")
        if raw_id in (None, ""):
            raw_id = item.get("template_id")
        raw_shop_id = item.get("shop_id")

        # 实测里除了店铺自己的模板，还有一条 {id:0, name:"包邮", shop_id:0}，
        # 那是平台通用选项。**不能因为 id 是 0 就把它丢掉**：发布是按名字匹配模板的，
        # 丢了用户就选不到这一项。这里如实带出来，用 shop_scoped 区分归属。
        shop_id = str(raw_shop_id) if raw_shop_id not in (None, "", 0, "0") else None
        templates.append(
            {
                "id": str(raw_id) if raw_id not in (None, "") else "0",
                "name": name,
                "shop_id": shop_id,
                "shop_scoped": shop_id is not None,
            }
        )
    return templates


def read_taobao_freight_templates(debug_address: str, timeout: float = 10.0) -> Dict[str, Any]:
    """淘宝店铺的运费模板读取。**走 DOM 路线**。

    运费模板要在**发布表单的「物流服务」区域**上读——那个下拉里列着本店全部模板。
    所以这个函数要求浏览器**当前停在发布表单页**；不在就如实报 ``need_publish_page``，
    不替调用方导航（导航是有副作用的动作，不该藏在「读模板」里）。

    .. note::
        **为什么不是协议接口。** 早期版本的这里找的是 mtop 接口名，所以一直返回
        ``not_captured``。但本项目自 2026-10-03 起走 **DOM 路线**（「搜索发品 → 选类目
        → 下一步填写」），DOM 路线上不需要那个接口名：

        * ``page.open_freight_dropdown`` 展开下拉；
        * ``page.read_freight_options`` 读全部模板名；
        * ``page.read_freight_template`` 读当前选中的那个。

        实测 ``stage_fill_freight`` 就是这么读到「该店铺共 2 个模板」的。

    **全程只读**：不选值、不保存、不提交。展开下拉是 UI 开关，不改平台状态。

    .. warning::
        **空列表绝不等于「该店铺没有模板」。** 下拉没展开、结构变了、页面不是发布表单，
        都会读到 0 个。所以这里**只有在确实读到选项时才返回 ``ok``**，
        其余一律带错误码如实返回。
    """

    # 延迟导入：`src/` 不该在模块导入期就依赖子项目（缺它只是这个接口不可用）。
    try:
        from taobao_publish import cdp as taobao_cdp
        from taobao_publish import page as taobao_page
    except Exception as exc:  # pragma: no cover - 只在打包缺模块时触发
        return {
            "status": "unavailable",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "淘宝 DOM 读取模块不可用",
            "detail": "{}: {}".format(type(exc).__name__, exc),
        }

    list_url = "http://{}/json/list".format(debug_address)
    try:
        targets = taobao_cdp.list_targets(list_url, timeout=min(3.0, timeout))
    except Exception as exc:
        return {
            "status": "no_browser",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "连不上调试浏览器",
            "detail": "{}: {}".format(type(exc).__name__, exc),
        }

    target = taobao_cdp.select_publish_target(targets)
    if target is None:
        return {
            "status": "need_publish_page",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "淘宝运费模板要在发布表单上读",
            "detail": (
                "运费模板下拉只在「发布表单」的物流服务区域里。请先在淘宝发布工作台"
                "打开一个商品的发布页（选完类目进入填写页），再刷新这里。"
            ),
        }

    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        return {
            "status": "no_browser",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "发布页没有可用的调试连接",
            "detail": "目标里没有 webSocketDebuggerUrl",
        }

    try:
        with taobao_page.PageClient.connect(
                ws_url, str(target.get("url") or ""), timeout=min(8.0, timeout)) as client:
            # 先读**当前值**（此刻下拉还没动），再展开读全部选项。
            current = taobao_page.read_freight_template(client)
            opened = taobao_page.open_freight_dropdown(client)
            options = taobao_page.read_freight_options(client)
    except Exception as exc:
        return {
            "status": "read_failed",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "读取运费模板失败",
            "detail": "{}: {}".format(type(exc).__name__, exc),
        }

    if not options:
        # ⚠️ **不把空列表当成「没有模板」**——那两种情况前端要分开显示。
        return {
            "status": "read_failed",
            "debug_address": debug_address,
            "platform": "taobao",
            "templates": [],
            "shop_id": None,
            "error": "运费模板下拉里没有读到任何选项",
            "detail": (
                "零个选项说明下拉没展开、页面不是发布表单、或平台结构变了——"
                "**不等于该店铺没有模板**。展开结果：{}".format(
                    json.dumps(opened, ensure_ascii=False)[:160])
            ),
        }

    return {
        "status": "ok",
        "debug_address": debug_address,
        "platform": "taobao",
        "templates": options,
        "shop_id": None,
        "current": current,
        "error": None,
        "detail": "从发布表单的运费模板下拉里读到 {} 个模板（DOM 路线）".format(len(options)),
    }


def read_freight_templates(debug_address: str, timeout: float = 10.0) -> Dict[str, Any]:
    """从一个已开远程调试端口的浏览器上读当前店铺的运费模板。

    ``status`` 取值与 read_shop_identity 一致：``ok`` / ``logged_out`` /
    ``no_fxg_tab`` / ``unreachable`` / ``failed``。

    读不到就返回空列表，**不编造任何模板名**——发布按名字匹配模板，
    编一个不存在的名字出来，要么发布失败，要么按别的运费规则发货。
    """
    result: Dict[str, Any] = {
        "status": "unreachable",
        "debug_address": debug_address,
        "templates": [],
        "shop_id": None,
        "error": None,
        "detail": None,
    }

    try:
        targets = _cdp_page_targets(debug_address, timeout=min(3.0, timeout))
    except Exception as exc:
        result["error"] = "读不到运费模板，请重新登录"
        result["detail"] = "无法访问调试端口 {}：{}".format(debug_address, exc)
        return result

    target = _pick_fxg_target(targets)
    if not target or not target.get("webSocketDebuggerUrl"):
        result["status"] = "no_fxg_tab"
        result["error"] = "尚未登录"
        return result

    try:
        import websocket as _ws
    except Exception as exc:
        result["error"] = "读不到运费模板，请重新登录"
        result["detail"] = "websocket 模块不可用：{}".format(exc)
        return result

    ws = None
    raw: Optional[str] = None
    try:
        ws = _ws.create_connection(
            target["webSocketDebuggerUrl"], timeout=min(5.0, timeout), suppress_origin=True
        )
        ws.settimeout(2)
        ws.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": _freight_expression(),
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )
        deadline = time.time() + timeout
        while time.time() < deadline and raw is None:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("id") == 1:
                value = ((message.get("result") or {}).get("result") or {}).get("value")
                raw = value if isinstance(value, str) else ""
    except Exception as exc:
        result["error"] = "读不到运费模板，请重新登录"
        result["detail"] = "读取运费模板失败：{}".format(exc)
        return result
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    if _server_says_logged_out(raw):
        result["status"] = "logged_out"
        result["error"] = "尚未登录"
        return result

    parsed = None
    try:
        envelope = json.loads(raw or "")
        body = envelope.get("body") if isinstance(envelope, dict) else None
        parsed = json.loads(body) if isinstance(body, str) and body.strip() else None
    except Exception:
        parsed = None

    templates = _extract_freight_templates(parsed)
    if not templates:
        result["status"] = "failed"
        result["error"] = "没有读到运费模板"
        result["detail"] = _describe_shop_info_failure(raw)
        return result

    # 只拿店铺自己的模板核对归属，平台通用项（shop_id 为 0）不参与判断
    shop_ids = {t["shop_id"] for t in templates if t.get("shop_id")}
    result["status"] = "ok"
    result["templates"] = templates
    result["shop_id"] = next(iter(shop_ids)) if len(shop_ids) == 1 else None
    return result
