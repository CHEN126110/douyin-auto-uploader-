# -*- coding: utf-8 -*-
"""白底图流水线的模型目录解析。

模型是几百 MB 的二进制，不进仓库、不进安装包，放运行数据目录：
`DOUYIN_WHITEBG_MODEL_DIR` 一旦设置就**只认它**（硬覆盖）；没设时按
`runtime_paths.resolve_data_file('models/whitebg')` → 仓库根 `models/whitebg`
的顺序找，和项目里 cfg.yaml / sqlite.db 的做法一致。

目录布局（rembg 自己要求 `<REMBG_HOME>/models/<name>/<name>.onnx`）：

    models/whitebg/
        rembg/models/birefnet-general/birefnet-general.onnx
        rembg/models/bria-rmbg/bria-rmbg.onnx
        clip-vit-base-patch32/vision_model_quantized.onnx
        clip-vit-base-patch32/text_model_quantized.onnx
        clip-vit-base-patch32/tokenizer.json
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL_DIR_ENV = 'DOUYIN_WHITEBG_MODEL_DIR'
RELATIVE_MODEL_DIR = os.path.join('models', 'whitebg')

CLIP_SUBDIR = 'clip-vit-base-patch32'
REMBG_SUBDIR = 'rembg'

# CLIP 侧必需的文件；text 塔只在首次生成 embedding 缓存时需要，
# 缓存（*.npz）建好之后可以不带 text_model 发版。
CLIP_REQUIRED = ('vision_model_quantized.onnx',)
CLIP_TEXT_OR_CACHE = (('text_model_quantized.onnx', 'tokenizer.json'),
                      ('text_embeds.npz', 'scene_text_embeds.npz'))


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get(MODEL_DIR_ENV)
    if env:
        # 硬覆盖：显式指定了目录就只认它。不然「我明明设了环境变量」却在用另一份
        # 模型，排查起来极难，而且 model_status 会谎报 ready。
        return [Path(env).resolve()]
    try:
        from runtime_paths import resolve_data_file  # type: ignore
    except ImportError:
        try:
            from src.runtime_paths import resolve_data_file  # type: ignore
        except ImportError:
            resolve_data_file = None  # type: ignore
    repo_root = Path(__file__).resolve().parents[2]
    if resolve_data_file is not None:
        # 开发模式下 get_data_dir() 返回 None，resolve_data_file 会原样返回相对路径；
        # 相对路径会跟着进程 CWD 变，必须锚到仓库根，否则从别的目录起 sidecar 就找不到模型
        out.append(Path(resolve_data_file(RELATIVE_MODEL_DIR)))
    out.append(repo_root / RELATIVE_MODEL_DIR)
    seen, uniq = set(), []
    for p in out:
        if not p.is_absolute():
            p = repo_root / p
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def resolve_model_dir(matte_model: str = 'birefnet-general') -> Path:
    """返回第一个「这个 matte 模型和 CLIP 都齐了」的目录；都不齐就返回首选目录。

    返回首选目录而不是抛异常，是为了让 model_status() 能给出「缺哪个文件」
    的具体清单 —— 调用方据此提示用户去下载，而不是抛一个看不懂的路径错误。
    """
    cands = _candidates()
    for base in cands:
        if _matte_ok(base, matte_model) and _clip_ok(base):
            return base
    return cands[0]


def rembg_home(base: Path | str) -> Path:
    return Path(base) / REMBG_SUBDIR


def clip_dir(base: Path | str) -> Path:
    return Path(base) / CLIP_SUBDIR


def matte_model_path(base: Path | str, name: str) -> Path:
    return rembg_home(base) / 'models' / name / f'{name}.onnx'


def _matte_ok(base: Path, name: str) -> bool:
    p = matte_model_path(base, name)
    return p.is_file() and p.stat().st_size > 1024 * 1024


def _clip_ok(base: Path) -> bool:
    d = clip_dir(base)
    if not all((d / f).is_file() for f in CLIP_REQUIRED):
        return False
    return any(all((d / f).is_file() for f in group) for group in CLIP_TEXT_OR_CACHE)


def model_status(matte_model: str = 'birefnet-general') -> dict:
    """给接口用的模型就绪状态：齐没齐、在哪、缺什么。"""
    base = resolve_model_dir(matte_model)
    d = clip_dir(base)
    missing: list[str] = []
    if not _matte_ok(base, matte_model):
        missing.append(str(matte_model_path(base, matte_model).relative_to(base)))
    if not all((d / f).is_file() for f in CLIP_REQUIRED):
        missing += [os.path.join(CLIP_SUBDIR, f) for f in CLIP_REQUIRED
                    if not (d / f).is_file()]
    elif not _clip_ok(base):
        missing.append(os.path.join(CLIP_SUBDIR,
                                    'text_model_quantized.onnx + tokenizer.json'
                                    '（或已生成的 text_embeds.npz + scene_text_embeds.npz）'))
    return {
        'ready': not missing,
        'model_dir': str(base),
        'matte_model': matte_model,
        'rembg_home': str(rembg_home(base)),
        'clip_dir': str(d),
        'missing': missing,
        'searched': [str(p) for p in _candidates()],
    }
