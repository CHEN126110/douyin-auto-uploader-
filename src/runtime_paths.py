from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional, Union

RESOURCE_DIR_ENV = "DOUYIN_RESOURCE_DIR"
DATA_DIR_ENV = "DOUYIN_DATA_DIR"
RUNTIME_ROOT_ENV = "DOUYIN_RUNTIME_ROOT"

PathLike = Union[str, os.PathLike[str]]


def _path_from_env(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).resolve()


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    path = _path_from_env(RESOURCE_DIR_ENV)
    if path is not None:
        return path
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _default_repo_root()


def get_runtime_root() -> Path:
    path = _path_from_env(RUNTIME_ROOT_ENV)
    if path is not None:
        return path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _default_repo_root()


def get_data_dir(create: bool = False) -> Optional[Path]:
    path = _path_from_env(DATA_DIR_ENV)
    if path is None:
        if getattr(sys, "frozen", False):
            path = get_runtime_root() / "data"
        else:
            return None
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_data_file(relative_path: PathLike, legacy_fallback: Optional[PathLike] = None) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        return path

    data_dir = get_data_dir(create=False)
    if data_dir is not None:
        return data_dir / path

    if legacy_fallback is not None:
        return Path(legacy_fallback)

    return path


def _iter_source_paths(sources: Iterable[PathLike]) -> Iterable[Path]:
    for source in sources:
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = get_resource_dir() / source_path
        yield source_path


def seed_data_file(relative_path: PathLike, sources: Iterable[PathLike], overwrite: bool = False) -> Optional[Path]:
    data_dir = get_data_dir(create=True)
    if data_dir is None:
        return None

    target_path = data_dir / Path(relative_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not overwrite:
        return target_path

    for source_path in _iter_source_paths(sources):
        if source_path.exists():
            shutil.copy2(source_path, target_path)
            return target_path

    return target_path if target_path.exists() else None


def bootstrap_runtime_environment(seed_files: Optional[dict[str, Iterable[PathLike]]] = None) -> None:
    resource_dir = get_resource_dir()
    os.environ.setdefault(RESOURCE_DIR_ENV, str(resource_dir))

    runtime_root = get_runtime_root()
    os.environ.setdefault(RUNTIME_ROOT_ENV, str(runtime_root))

    if DATA_DIR_ENV not in os.environ and getattr(sys, "frozen", False):
        os.environ[DATA_DIR_ENV] = str(runtime_root / "data")

    data_dir = get_data_dir(create=bool(seed_files))
    if data_dir is None or not seed_files:
        return

    for relative_path, sources in seed_files.items():
        seed_data_file(relative_path, sources)
