# -*- coding: utf-8 -*-
"""淘宝发布流程 —— 视觉观察器（无 CDP 时的兜底方案）。

## 什么时候用它

主路径是 CDP（`watch-publish-flow.mjs` + `capture-publish-requests.mjs`），能拿到
DOM 结构与网络请求。但有些场景用不了 CDP：

* 用户的日常 Chrome 已经登录好了淘宝，而不想再在一个独立 profile 里扫码；
* Chrome 无法给**已在运行**的实例补开 `--remote-debugging-port`，只能关掉重启；
* 而 Chrome 136+ 又拒绝在默认 data dir 上开调试端口。

这时唯一的「看页面」的办法就是**把窗口画下来**。本脚本定时截取指定窗口，
画面有明显变化就存一帧，从而把一次手动走查变成可回看的流程图。

## 它能看到 / 看不到什么

**能看到**：页面长什么样、有哪几步、每步有哪些字段与按钮、校验提示原文、
类目树结构、选项文案。足够回答「这个流程是什么」。

**看不到**：CSS 选择器、DOM 层级、接口名与请求字段。这些只能靠 CDP。
所以本脚本的产物用来**理解流程**，不能用来**填 `contracts/selectors.json`**。

## 只读保证

只调用 `GetWindowRect` / `PrintWindow` / `GetDIBits` 三个只读 API。
不点击、不输入、不导航、不注入。

唯一的可见副作用：目标窗口若已最小化，会先 `ShowWindow(SW_RESTORE)` 把它恢复
显示（否则 `PrintWindow` 只能拿到黑图）。这是可逆的。

## 用法

```powershell
python taobao-publisher/scripts/watch-publish-flow-visual.py --pid 29424 --seconds 1800
python taobao-publisher/scripts/watch-publish-flow-visual.py --title 商品发布 --interval 2
```

产物：`taobao-publisher/tmp/visual-flow-<时间戳>/frame-NN.png` + `manifest.json`

.. warning::
    截图里会出现**已登录的页面内容**（店铺名、商品资料等）。产物落在已 gitignore 的
    ``tmp/`` 下，**不要**把它们提交进仓库。需要留证据时请人工确认画面里没有敏感信息。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 本机已装
    print("需要 Pillow：pip install pillow", file=sys.stderr)
    raise SystemExit(2)

if sys.platform != "win32":  # pragma: no cover - 本工具是 Windows 专用
    print("本脚本使用 Win32 窗口 API，仅支持 Windows。", file=sys.stderr)
    raise SystemExit(2)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_RENDERFULLCONTENT = 0x00000002
SW_RESTORE = 9
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def find_window_by_pid(pid: int) -> int:
    """找该进程面积最大的可见顶层窗口。"""

    best = {"hwnd": 0, "area": 0}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > best["area"]:
            best["hwnd"] = hwnd
            best["area"] = area
        return True

    user32.EnumWindows(callback, 0)
    return best["hwnd"]


def find_window_by_title(fragment: str) -> int:
    """按标题片段找窗口（找不到 PID 时的备用入口）。"""

    found = {"hwnd": 0}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if fragment in buffer.value:
            found["hwnd"] = hwnd
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found["hwnd"]


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def ensure_visible(hwnd: int) -> bool:
    """最小化的窗口 PrintWindow 只能拿到黑图，先恢复显示。**只在启动时调用一次。**

    运行中不再自动恢复：用户主动最小化窗口是他自己的操作，脚本反复把它弹回来
    是在跟用户抢桌面。
    """

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(1.0)
    return not user32.IsIconic(hwnd)


def capture(hwnd: int) -> Image.Image | None:
    """把窗口画面渲染到内存 DC 再拷成 PIL 图像。不解屏幕、不受遮挡影响。"""

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    if not hdc_mem or not hbmp:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)
        return None

    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        # Chrome 是 GPU 合成的，必须传 PW_RENDERFULLCONTENT，否则得到黑图。
        if not user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT):
            return None

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # 负数 = 自上而下
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS)
        if copied == 0:
            return None
        # 用 frombytes 而不是 frombuffer：frombuffer 会**共享** buffer 的内存，
        # buffer 出作用域后图像数据可能已失效（实测出现过保存出 0 字节 PNG 的情况）。
        # frombytes 会复制一份，代价可接受（这是每 1.5 秒一次的操作）。
        return Image.frombytes("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def frame_signature(image: Image.Image, size: int = 16) -> list:
    """降采样灰度均值哈希，用来判断「画面变了没有」。

    不用文件哈希：鼠标移动、光标闪烁、抗锯齿抖动都会让字节不同，
    但画面其实是同一屏。均值哈希对这类噪声不敏感。
    """

    small = image.convert("L").resize((size, size), Image.Resampling.BILINEAR)
    # 用 tobytes() 而不是 getdata()：后者在 Pillow 14 起被弃用，且逐像素取数慢得多。
    # 灰度图（mode "L"）每字节就是一个像素，直接当字节序列用。
    pixels = small.tobytes()
    if not pixels:
        return []
    average = sum(pixels) / len(pixels)
    # 用平均值量化成 0/1，得到对亮度整体漂移不敏感的签名
    return [1 if value > average else 0 for value in pixels]


def signature_distance(a: list, b: list) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="淘宝发布流程视觉观察器（无 CDP 兜底，只读）"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pid", type=int, help="目标 Chrome 进程 PID")
    group.add_argument("--title", help="目标窗口标题片段，例如 商品发布")
    parser.add_argument("--seconds", type=int, default=1800, help="观察时长（默认 1800）")
    parser.add_argument("--interval", type=float, default=2.0, help="截屏间隔秒数（默认 2.0）")
    parser.add_argument("--threshold", type=int, default=12, help="判定为「换屏」的哈希距离阈值（默认 12/256）")
    parser.add_argument("--out", default="", help="输出目录")
    parser.add_argument("--max-frames", type=int, default=60, help="最多保存多少帧（默认 60）")
    parser.add_argument(
        "--title-filter",
        default="",
        help=(
            "只在这个子串出现在窗口标题里时才截图。强烈建议设置："
            "用户在同一个窗口里切到别的标签页时，标题会变，不加过滤会把无关浏览也拍下来。"
        ),
    )
    parser.add_argument(
        "--idle-warn-seconds",
        type=int,
        default=300,
        help="标题不匹配持续多久后提示一次（默认 300 秒），避免用户以为脚本挂了",
    )
    args = parser.parse_args()

    hwnd = find_window_by_pid(args.pid) if args.pid else find_window_by_title(args.title)
    if not hwnd:
        print("没有找到目标窗口。用 --pid 或 --title 指定。", file=sys.stderr)
        return 1

    title = window_title(hwnd)
    print("=" * 72)
    print("淘宝发布流程 · 视觉观察（只读，无 CDP）")
    print("=" * 72)
    print(f"目标窗口：{title}  (HWND={hwnd})")
    print(f"观察时长：{args.seconds} 秒    截屏间隔：{args.interval} 秒")
    if args.title_filter:
        print(f"标题过滤：仅当标题含 {args.title_filter!r} 时才截图")
    else:
        print("标题过滤：**未启用** —— 同一窗口切到别的标签页也会被拍下来，建议加 --title-filter")
    if not ensure_visible(hwnd):
        print("窗口无法恢复显示，退出。", file=sys.stderr)
        return 2

    subproject_root = Path(__file__).resolve().parent.parent
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    out_dir = Path(args.out) if args.out else (subproject_root / "tmp" / f"visual-flow-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"产出目录：{out_dir}")
    print("")
    print("请在浏览器里**正常手动走一遍**发布流程。画面有变化就会自动存一帧。")
    print("---- 实时日志 ----")

    frames = []
    last_signature = None
    deadline = time.time() + args.seconds
    index = 0
    skipped_minimized = 0
    off_target_since = None
    last_off_target_notice = 0.0

    while time.time() < deadline and len(frames) < args.max_frames:
        # 最小化时 GetWindowRect 会返回 (-32000,-32000) 一类的坐标和 158x26 的假尺寸，
        # 截出来是个无意义的小图，还会被当成「画面变了」。直接跳过、不落盘。
        if user32.IsIconic(hwnd):
            skipped_minimized += 1
            if skipped_minimized == 1 or skipped_minimized % 40 == 0:
                print(f"[跳过] 窗口已最小化（第 {skipped_minimized} 次）——恢复显示后会自动继续")
            time.sleep(args.interval)
            continue

        # 标题过滤：同一个 Chrome 窗口里切标签页时标题会变。
        # 不加这道过滤，用户中途去干别的事也会被拍进来（实测踩过）。
        if args.title_filter:
            current_title = window_title(hwnd)
            if args.title_filter not in current_title:
                now = time.time()
                if off_target_since is None:
                    off_target_since = now
                    last_off_target_notice = 0.0
                elif now - off_target_since >= args.idle_warn_seconds and now - last_off_target_notice >= args.idle_warn_seconds:
                    last_off_target_notice = now
                    print(
                        f"[等待] 当前标签页标题 {current_title[:60]!r} 不含 "
                        f"{args.title_filter!r}，已跳过 {int(now - off_target_since)} 秒"
                    )
                time.sleep(args.interval)
                continue
            off_target_since = None

        image = capture(hwnd)
        if image is None:
            print("[跳过] 截屏失败")
            time.sleep(args.interval)
            continue

        signature = frame_signature(image)
        distance = 256 if last_signature is None else signature_distance(signature, last_signature)
        if distance >= args.threshold:
            index += 1
            path = out_dir / f"frame-{index:02d}.png"
            image.save(path)
            # 落盘后自检：实测出现过 0 字节 PNG（frombuffer 的内存共享问题）。
            # 空产物比没有产物更糟——它会让人以为「这一帧就是空的」。
            if not path.exists() or path.stat().st_size == 0:
                print(f"[警告] 第 {index} 帧写出 0 字节，已删除：{path.name}")
                path.unlink(missing_ok=True)
                index -= 1
                last_signature = signature
                time.sleep(args.interval)
                continue
            last_signature = signature
            frames.append(
                {
                    "index": index,
                    "file": path.name,
                    "captured_at": datetime.now().isoformat(timespec="seconds"),
                    "size": list(image.size),
                    "signature_distance": distance,
                }
            )
            print(f"[帧 {index:02d}] 画面变化（距离 {distance}） → {path.name}")
        time.sleep(args.interval)

    manifest = {
        "probe_kind": "taobao_publish_visual_flow_readonly",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_title": title,
        "hwnd": hwnd,
        "title_filter": args.title_filter,
        "note": (
            "只读视觉观察：只调用 GetWindowRect / PrintWindow / GetDIBits，"
            "不点击、不输入、不导航、不注入。截图含登录后的页面内容，属敏感产物，"
            "必须留在 tmp/ 下，不要提交进仓库。"
        ),
        "frame_count": len(frames),
        "frames": frames,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("")
    print(f"共保存 {len(frames)} 帧。")
    print(f"清单：{out_dir / 'manifest.json'}")
    if not frames:
        print("没有捕捉到画面变化——可能全程停在同一个页面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
