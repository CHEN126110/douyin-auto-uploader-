# -*- coding: utf-8 -*-
"""实验入口：对一批 SKU 图跑白底图流水线，出成品 + 调试图 + JSON 报告。

用法：
  python lab/whitebg/scripts/run_lab.py                      # 跑默认 SKU 目录全部
  python lab/whitebg/scripts/run_lab.py --limit 3            # 只跑前 3 张
  python lab/whitebg/scripts/run_lab.py --no-clip            # 跳过语义闸门（只验几何）
  python lab/whitebg/scripts/run_lab.py --matte u2netp       # 换 matte 模型
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))

from whitebg import geometry as geo          # noqa: E402
from whitebg import matte as matte_mod       # noqa: E402
from whitebg import paths as model_paths     # noqa: E402

DEFAULT_SRC = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
               r'\uploads\products\ID-1075636304051\SKU')
OUT_ROOT = os.path.join('lab', 'whitebg', 'out')


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', action='append', default=None,
                    help='源目录，可重复传多个；不传则用默认 SKU 目录')
    ap.add_argument('--out', default=os.path.join(OUT_ROOT, '02_pipeline'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--matte', default=matte_mod.DEFAULT_MODEL)
    # 模型目录统一由 whitebg.paths 解析（环境变量 → 运行数据目录 → 仓库 models/）
    _base = model_paths.resolve_model_dir()
    ap.add_argument('--rembg-home', default=str(model_paths.rembg_home(_base)))
    ap.add_argument('--clip-dir', default=str(model_paths.clip_dir(_base)))
    ap.add_argument('--no-clip', action='store_true', help='跳过语义闸门，保留所有连通域')
    ap.add_argument('--no-deskew', action='store_true')
    ap.add_argument('--canvas', type=int, default=1440)
    ap.add_argument('--fill', type=float, default=0.82)
    ap.add_argument('--core-alpha', type=int, default=150)
    ap.add_argument('--sock-prob', type=float, default=0.45)
    return ap.parse_args()


def alpha_preview(alpha: np.ndarray, size=(360, 480)) -> Image.Image:
    im = Image.fromarray(alpha).convert('L').convert('RGB')
    im.thumbnail(size, Image.LANCZOS)
    return im


def label_preview(labels: np.ndarray, verdicts, size=(360, 480)) -> Image.Image:
    """把连通域按判定结果上色：绿=留下的袜子，红=被语义闸门丢掉的。"""
    h, w = labels.shape
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = 245
    for v in verdicts:
        m = labels == v['label']
        canvas[m] = (60, 180, 75) if v['kept'] else (215, 60, 50)
    im = Image.fromarray(canvas)
    im.thumbnail(size, Image.LANCZOS)
    return im


def contact_sheet(tiles, pad=8, bg=(250, 250, 250)) -> Image.Image:
    w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + pad * 2 + 22
    canvas = Image.new('RGB', (w, h), bg)
    d = ImageDraw.Draw(canvas)
    x = pad
    for caption, t in tiles:
        canvas.paste(t, (x, pad + 22))
        d.text((x + 2, pad + 4), caption, fill=(30, 30, 30))
        x += t.width + pad
    return canvas


class PassThroughGate:
    """--no-clip 时用的占位闸门：所有连通域一律保留，场景一律判为单品。"""

    def score(self, crops):
        return [{'groups': {'sock': 1.0, 'shoe': 0.0, 'other': 0.0},
                 'top_prompt': '(未启用语义闸门)', 'top_prob': 1.0} for _ in crops]

    def classify(self, images):
        return [{'groups': {'single_pair': 1.0, 'many': 0.0, 'worn': 0.0, 'packaged': 0.0},
                 'top': 'single_pair'} for _ in images]


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(os.path.join(args.out, 'debug'), exist_ok=True)

    from whitebg.pipeline import Config, SockWhiteBg, UnsuitableSource

    cfg = Config(
        matte_model=args.matte,
        rembg_home=args.rembg_home,
        clip_dir=args.clip_dir,
        core_alpha=args.core_alpha,
        sock_prob=args.sock_prob,
        canvas=args.canvas,
        fill_ratio=args.fill,
        deskew=not args.no_deskew,
        debug=True,
    )

    t0 = time.time()
    if args.no_clip:
        # 绕过 CLIP 加载，只验 matte + 几何
        proc = SockWhiteBg.__new__(SockWhiteBg)
        proc.cfg = cfg
        proc.session = matte_mod.make_session(cfg.matte_model, cfg.rembg_home)
        proc.gate = PassThroughGate()
        proc.scene = proc.gate
    else:
        proc = SockWhiteBg(cfg)
    print(f'[init] 模型就绪 {time.time() - t0:.1f}s  matte={args.matte}  '
          f'语义闸门={"OFF" if args.no_clip else "CLIP"}')

    srcs = args.src or [DEFAULT_SRC]
    files = []
    for sd in srcs:
        files += sorted(glob.glob(os.path.join(sd, '*.jpg')) +
                        glob.glob(os.path.join(sd, '*.png')))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f'源目录没有图片: {srcs}')
        return 1
    print(f'[src] {len(files)} 张，来自 {len(srcs)} 个目录')

    report = []
    for path in files:
        parts = os.path.normpath(path).split(os.sep)
        prefix = '_'.join(parts[-3:-1]) if len(parts) >= 3 else ''
        name = (prefix + '__' if prefix else '') + os.path.splitext(os.path.basename(path))[0]
        t = time.time()
        try:
            res = proc.process(path)
        except UnsuitableSource as exc:
            print(f'[拒绝] {name}: [{exc.code}] {exc.message}')
            report.append({'file': name, 'ok': False, 'code': exc.code,
                           'message': exc.message, 'detail': exc.detail})
            continue
        except Exception as exc:
            print(f'[异常] {name}: {type(exc).__name__}: {exc}')
            report.append({'file': name, 'ok': False, 'code': 'exception',
                           'message': f'{type(exc).__name__}: {exc}'})
            continue
        cost = time.time() - t

        dest = os.path.join(args.out, f'{name}__白底图.jpg')
        res.image.save(dest, quality=95, subsampling=0)

        dbg = res.debug
        tiles = [
            ('原图', _thumb(Image.open(path).convert('RGB'))),
            ('matte原始', alpha_preview(dbg['alpha_raw'])),
            ('引导细化', alpha_preview(dbg['alpha_ref'])),
            ('语义判定(绿留红弃)', label_preview(dbg['labels'], res.verdicts)),
            (f'转正{res.tilt_deg:+.1f}°+1:1居中', _thumb(res.image)),
        ]
        sheet = contact_sheet(tiles)
        sheet.save(os.path.join(args.out, 'debug', f'{name}__debug.jpg'), quality=88)

        # 各连通域送进 CLIP 的实际画面，便于判断误判是闸门问题还是裁剪问题
        if dbg.get('crops'):
            crop_tiles = []
            for v, c in zip(res.verdicts, dbg['crops']):
                cc = c.copy()
                cc.thumbnail((200, 200), Image.LANCZOS)
                tag = 'KEEP' if v['kept'] else 'DROP'
                crop_tiles.append((f"#{v['label']} {tag} sock={v['sock']:.2f} "
                                   f"shoe={v['shoe']:.2f} other={v['other']:.2f}", cc))
            contact_sheet(crop_tiles).save(
                os.path.join(args.out, 'debug', f'{name}__crops.jpg'), quality=88)

        row = {
            'file': name,
            'ok': True,
            'seconds': round(cost, 2),
            'components': dbg.get('n_components'),
            'tilt_deg': res.tilt_deg,
            'tilt_info': res.tilt_info,
            'scene': {k: round(v, 3) for k, v in res.scene.items()},
            'axes(label,angle,elong,area)': dbg.get('axes'),
            'verdicts': res.verdicts,
            'compose': res.compose_meta,
            'warnings': res.warnings,
            'output': dest,
        }
        report.append(row)
        kept = sum(1 for v in res.verdicts if v['kept'])
        conf = '可信' if res.tilt_info.get('confident') else '不转'
        print(f'[ok] {name}  {cost:.1f}s  连通域 {dbg.get("n_components")} → 留 {kept}  '
              f'转正 {res.tilt_deg:+.2f}°({conf})  占比 {res.compose_meta["fill_ratio_actual"]}'
              + (('  ⚠ ' + ' / '.join(res.warnings)) if res.warnings else ''))

    with open(os.path.join(args.out, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('报告写到', os.path.join(args.out, 'report.json'))
    return 0


def _thumb(im: Image.Image, size=(360, 480)) -> Image.Image:
    im = im.copy()
    im.thumbnail(size, Image.LANCZOS)
    return im


if __name__ == '__main__':
    raise SystemExit(main())
