# -*- coding: utf-8 -*-
"""命令行入口：给采集目录补白底图和 1:1 规格图。

    python -m whitebg <采集目录> [<采集目录> ...]
    python -m whitebg --status                     只看模型齐不齐
    python -m whitebg <目录> --matte isnet-general-use --canvas 1200
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in (None, ''):                       # 支持直接 python src/whitebg/cli.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from whitebg.paths import model_status          # type: ignore
    from whitebg.pipeline import Config             # type: ignore
    from whitebg.product import process_product_dir # type: ignore
    from whitebg.pipeline import SockWhiteBg        # type: ignore
else:
    from .paths import model_status
    from .pipeline import Config, SockWhiteBg
    from .product import process_product_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='袜子白底图 + 1:1 规格图生成')
    ap.add_argument('dirs', nargs='*', help='采集目录，如 <uploads>/products/ID-123')
    ap.add_argument('--status', action='store_true', help='只检查模型就绪状态')
    ap.add_argument('--matte', default='birefnet-general')
    ap.add_argument('--canvas', type=int, default=1440)
    ap.add_argument('--fill', type=float, default=0.82)
    ap.add_argument('--square-size', type=int, default=0,
                    help='规格图统一缩放到这个边长；0 = 保持原分辨率裁出的尺寸')
    ap.add_argument('--no-deskew', action='store_true')
    ap.add_argument('--keep-existing', action='store_true', help='已存在的产物不覆盖')
    args = ap.parse_args(argv)

    status = model_status(args.matte)
    if args.status or not status['ready']:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        if not status['ready']:
            print('\n模型未就绪，缺：' + '、'.join(status['missing']))
            print(f'请把模型放到 {status["model_dir"]}'
                  f'（布局见 src/whitebg/paths.py 的说明）')
            return 2
        return 0

    if not args.dirs:
        ap.error('需要至少一个采集目录，或用 --status')

    cfg = Config(matte_model=args.matte, canvas=args.canvas, fill_ratio=args.fill,
                 deskew=not args.no_deskew, debug=False)
    proc = SockWhiteBg(cfg)
    print(f'[模型] {proc.model_dir}  matte={args.matte}')

    failed = 0
    for d in args.dirs:
        def _progress(i, total, name, _d=d):
            print(f'  [{i}/{total}] {name}', flush=True)

        print(f'\n=== {d}')
        out = process_product_dir(
            d, cfg, processor=proc,
            square_size=args.square_size or None,
            overwrite=not args.keep_existing,
            progress=_progress)
        print(f'  {out.message}  ({out.seconds:.1f}s)')
        for it in out.items + out.fallback_items:
            if it['white_ok']:
                flag = '' if it['tilt_confident'] else '  [未转正]'
                warn = ('  ⚠ ' + ' / '.join(it['warnings'])) if it['warnings'] else ''
                print(f"    ✓ {it['name']}  转正 {it['tilt_deg']:+.2f}°{flag}{warn}")
            else:
                print(f"    ✗ {it['name']}  [{it['code']}] {it['message']}")
        if not out.ok:
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
