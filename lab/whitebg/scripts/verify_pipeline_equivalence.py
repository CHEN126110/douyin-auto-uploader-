# -*- coding: utf-8 -*-
"""受控对照：同一份输入、同一套参数，只把 matte 那一层换成 rembg 旧实现再跑一遍，
把两轮产物逐字节比对。

为什么不能直接和商品目录里已有的产物比：那份产物可能是更早的版本或不同参数
（不同 matte 模型 / canvas / 是否转正）生成的，拿它当基准会把「历史差异」误判成
「这次改动导致的差异」。

跑法（仓库根目录）：

    python lab/whitebg/scripts/verify_pipeline_equivalence.py <源商品目录> <工作目录>
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

MODEL = os.environ.get('MATTE_MODEL', 'birefnet-general')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def rembg_infer(rgb: np.ndarray, session, infer_side: int) -> np.ndarray:
    """改动前的 ``matte._infer``：整段照抄旧实现，用作对照。"""

    from rembg import remove
    im = Image.fromarray(rgb)
    work = im
    if infer_side and max(im.size) > infer_side:
        work = im.copy()
        work.thumbnail((infer_side, infer_side), Image.LANCZOS)
    mask = remove(work, session=session, only_mask=True, post_process_mask=False)
    if mask.size != im.size:
        mask = mask.resize(im.size, Image.BICUBIC)
    return np.asarray(mask.convert('L'), dtype=np.uint8)


def run_once(source: Path, target: Path, legacy: bool = False) -> None:
    """跑一遍完整流水线。

    :param legacy: ``True`` 时**连会话创建一起换回 rembg**（只换 ``_infer`` 不够——
        rembg 的 ``remove`` 要求会话带 ``.predict``，用新会话对象会直接 AttributeError，
        那样旧轮根本没跑到 matte，比对就失去意义）。
    """

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    from whitebg import matte
    original_infer, original_make = matte._infer, matte.make_session
    if legacy:
        def legacy_make(model_name=matte.DEFAULT_MODEL, model_home=None):
            if model_home:
                os.environ['REMBG_HOME'] = str(model_home)
            from rembg import new_session
            return new_session(model_name)
        matte._infer = rembg_infer
        matte.make_session = legacy_make
    try:
        from whitebg.pipeline import Config, SockWhiteBg
        from whitebg.product import process_product_dir
        cfg = Config(canvas=1200, matte_model=MODEL)
        outcome = process_product_dir(str(target), cfg, SockWhiteBg(cfg))
        print('    ok={} {}'.format(getattr(outcome, 'ok', '?'),
                                    str(getattr(outcome, 'message', ''))[:80]))
    finally:
        matte._infer, matte.make_session = original_infer, original_make


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    source = Path(sys.argv[1]).resolve()
    work = Path(sys.argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    old_dir, new_dir = work / 'with-rembg', work / 'with-onnx'
    print('旧实现（rembg：会话 + 推理都走 rembg）→', old_dir)
    run_once(source, old_dir, legacy=True)
    print('新实现（出厂代码：onnxruntime 直连）→', new_dir)
    run_once(source, new_dir)

    files = sorted(p for p in new_dir.rglob('*') if p.is_file())
    same = 0
    skipped = 0
    for item in files:
        relative = item.relative_to(new_dir)
        other = old_dir / relative
        if not other.is_file():
            print('  只有新实现产出：{}'.format(relative))
            continue
        if item.name == '_report.json':
            # 报告里含绝对路径与 generated_at，天然逐字节不同；只比**非易变字段**。
            import json
            def stable(path: Path):
                data = json.loads(path.read_text(encoding='utf-8'))
                # 易变字段：生成时间、耗时、以及每次运行都不同的绝对路径。
                data.pop('generated_at', None)
                data.pop('seconds', None)
                outcome = data.get('outcome') or {}
                outcome.pop('seconds', None)
                for key in ('product_dir', 'white_dir', 'square_dir', 'white_root',
                            'white_root_source'):
                    outcome.pop(key, None)
                for entry in outcome.get('items') or []:
                    entry.pop('seconds', None)
                    for key in ('source', 'white_path', 'square_path'):
                        entry.pop(key, None)
                return json.dumps(data, ensure_ascii=False, sort_keys=True)
            ok = stable(item) == stable(other)
            same += 1 if ok else 0
            print('  {:<44} {}'.format(str(relative) + '（忽略路径/时间戳）',
                                       '结构一致' if ok else '**结构不同**'))
            continue
        a, b = digest(item), digest(other)
        ok = a == b
        same += 1 if ok else 0
        print('  {:<44} {}'.format(str(relative), '一致' if ok else '**不同 {} vs {}**'.format(a, b)))
    print('\n一致 {}/{}'.format(same, len(files)))
    return 0 if same == len(files) else 1


if __name__ == '__main__':
    raise SystemExit(main())
