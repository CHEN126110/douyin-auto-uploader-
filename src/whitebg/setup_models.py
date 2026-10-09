# -*- coding: utf-8 -*-
"""把白底图需要的模型拉到 models/whitebg/（一次性安装步骤）。

    python -m whitebg.setup_models              # 拉默认组合（birefnet-general + CLIP）
    python -m whitebg.setup_models --matte isnet-general-use
    python -m whitebg.setup_models --dest D:\\models\\whitebg

下载完会顺手把 CLIP 的文本 embedding 算好存成 .npz —— 之后就不再需要 text 塔，
发版时可以只带 vision 塔（84MB）。

实测下载注意：**不要并行开好几路**。并行 5 路时速度掉到几十 KB/s 还会卡死，
串行反而稳定在 1MB/s 上下，所以这里是一个一个下的。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from whitebg import paths as model_paths      # type: ignore
else:
    from . import paths as model_paths

REMBG_RELEASE = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0'
HF_CLIP = 'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main'

# rembg 自己校验 md5，这里沿用同一组值，下歪了能当场发现
MATTE_MODELS = {
    'bria-rmbg': ('bria-rmbg.onnx', None),
    'isnet-general-use': ('isnet-general-use.onnx', 'fc16ebd8b0c10d971d3513d564d01e29'),
    'birefnet-general-lite': ('BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx',
                              '4fab47adc4ff364be1713e97b7e66334'),
    'birefnet-general': ('BiRefNet-general-epoch_244.onnx', None),
    'u2net': ('u2net.onnx', '60024c5c889badc19c04ad937298a77b'),
}

CLIP_FILES = [
    ('onnx/vision_model_quantized.onnx', 'vision_model_quantized.onnx'),
    ('onnx/text_model_quantized.onnx', 'text_model_quantized.onnx'),
    ('tokenizer.json', 'tokenizer.json'),
    ('preprocessor_config.json', 'preprocessor_config.json'),
    ('config.json', 'config.json'),
]


def download(url: str, dest: Path, md5: str | None = None) -> None:
    if dest.is_file() and dest.stat().st_size > 0:
        print(f'  [跳过] {dest.name} 已存在')
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + '.part')
    print(f'  [下载] {dest.name} ← {url}')
    with urllib.request.urlopen(url) as resp, open(part, 'wb') as f:
        total = int(resp.headers.get('Content-Length') or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f'\r         {done / 1048576:.0f}/{total / 1048576:.0f} MB '
                      f'({pct}%)', end='', flush=True)
    print()
    if md5:
        got = hashlib.md5(part.read_bytes()).hexdigest()
        if got != md5:
            part.unlink(missing_ok=True)
            raise RuntimeError(f'{dest.name} md5 不匹配：期望 {md5}，实际 {got}')
        print(f'         md5 校验通过')
    part.replace(dest)


def build_text_cache(base: Path) -> None:
    """离线算好 CLIP 文本 embedding，之后不再需要 text 塔。"""
    clip = model_paths.clip_dir(base)
    if (clip / 'text_embeds.npz').is_file() and (clip / 'scene_text_embeds.npz').is_file():
        print('  [跳过] 文本 embedding 缓存已存在')
        return
    print('  [生成] CLIP 文本 embedding 缓存')
    if __package__ in (None, ''):
        from whitebg.clip_gate import ClipGate, SceneClassifier   # type: ignore
    else:
        from .clip_gate import ClipGate, SceneClassifier
    gate = ClipGate(str(clip))
    SceneClassifier(gate)
    print('         已写出 text_embeds.npz / scene_text_embeds.npz')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='下载白底图所需模型')
    ap.add_argument('--matte', default='birefnet-general', choices=sorted(MATTE_MODELS),
                    help='要下载的 matte 模型；默认 birefnet-general（MIT 许可，实测最好）')
    ap.add_argument('--dest', default='', help='目标目录，默认按 paths.resolve_model_dir()')
    ap.add_argument('--skip-clip', action='store_true')
    args = ap.parse_args(argv)

    base = Path(args.dest) if args.dest else model_paths.resolve_model_dir(args.matte)
    base.mkdir(parents=True, exist_ok=True)
    print(f'目标目录: {base}')

    print(f'\n[1/3] matte 模型 {args.matte}')
    remote, md5 = MATTE_MODELS[args.matte]
    download(f'{REMBG_RELEASE}/{remote}',
             model_paths.matte_model_path(base, args.matte), md5)

    if not args.skip_clip:
        print('\n[2/3] CLIP ViT-B/32（语义闸门）')
        for remote_rel, local_name in CLIP_FILES:
            download(f'{HF_CLIP}/{remote_rel}',
                     model_paths.clip_dir(base) / local_name)

        print('\n[3/3] 文本 embedding 缓存')
        build_text_cache(base)

    status = model_paths.model_status(args.matte)
    print(f'\n就绪: {status["ready"]}')
    if not status['ready']:
        print('仍缺:', '、'.join(status['missing']))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
