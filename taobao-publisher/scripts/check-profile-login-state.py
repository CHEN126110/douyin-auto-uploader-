# -*- coding: utf-8 -*-
"""只读检查淘宝调试 profile 的登录态是否存在（**不读 cookie 值**）。

为什么需要它：图片空间协议上传取证要求 9334 调试实例带着登录态。
如果 profile 里没有可用的淘宝登录 cookie，启动浏览器也无法取证，
必须先让用户扫码登录一次——这一步不能靠猜。

输出只包含 cookie 的 **名字 / 域名 / 是否 httponly / 是否过期**，
不打印任何 cookie 值，符合 taobao-publisher 证据红线第 3 条。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

#: 判定"登录态会话"的关键 cookie 名（淘宝/天猫成员体系）。
SESSION_COOKIE_NAMES = (
    "cookie2",
    "unb",
    "_tb_token_",
    "sgcookie",
    "cna",
    "t",
    "_l_g_",
    "uc1",
    "uc3",
    "uc4",
    "_nk_",
    "tracknick",
    "lgc",
    "l",
    "isg",
    "tfstk",
    "csg",
    "sku",
)


def chrome_time_to_unix(value: int) -> float | None:
    """Chrome 的 expires_utc 是 1601-01-01 起的微秒数；0 表示会话 cookie。"""
    if value == 0:
        return None
    return value / 1_000_000 - 11_644_473_600


def inspect(profile_dir: str) -> dict:
    cookies_path = os.path.join(profile_dir, "Default", "Network", "Cookies")
    if not os.path.isfile(cookies_path):
        return {"ok": False, "error": "profile 里没有 Default/Network/Cookies", "path": cookies_path}
    handle, temporary = tempfile.mkstemp(prefix="tbck-readonly-", suffix=".db")
    os.close(handle)
    shutil.copy2(cookies_path, temporary)
    try:
        connection = sqlite3.connect(temporary)
        try:
            rows = connection.execute(
                "select host_key, name, expires_utc, is_httponly, path from cookies"
            ).fetchall()
        finally:
            connection.close()
    finally:
        os.remove(temporary)

    now = time.time()
    related = [row for row in rows if any(token in row[0] for token in ("taobao", "tmall", "alicdn", "mmstat"))]
    live, expired = [], []
    for host, name, expires_utc, httponly, path in related:
        expires = chrome_time_to_unix(expires_utc)
        record = {
            "host": host,
            "name": name,
            "httponly": bool(httponly),
            "path": path,
            "session_cookie": expires is None,
            "expires_in_hours": None if expires is None else round((expires - now) / 3600.0, 1),
        }
        (live if expires is None or expires > now else expired).append(record)

    names_live = {record["name"] for record in live}
    session_hits = sorted(names_live & set(SESSION_COOKIE_NAMES))
    unb_live = [record for record in live if record["name"] == "unb"]
    return {
        "ok": True,
        "profile_dir": os.path.abspath(profile_dir),
        "cookies_file": cookies_path,
        "cookies_file_mtime": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(cookies_path))
        ),
        "total_cookies": len(rows),
        "platform_cookies": len(related),
        "live_platform_cookies": len(live),
        "expired_platform_cookies": len(expired),
        "session_cookie_names_present": session_hits,
        "has_login_identity": bool(unb_live),
        "login_verdict": (
            "likely_logged_in" if unb_live else
            ("maybe_logged_in" if len(session_hits) >= 2 else "likely_logged_out")
        ),
        "live_cookie_names": sorted(names_live),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="只读检查淘宝调试 profile 的登录态")
    parser.add_argument("--profile", default=".runtime/chrome-taobao-cdp")
    arguments = parser.parse_args(argv)
    result = inspect(arguments.profile)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
