# -*- coding: utf-8 -*-
"""本地文件夹导入（src/sidecar/import_routes.py）回归：真实临时目录 + 隔离数据库，直接注册 Blueprint。

这个接口在拆分之前没有任何测试。重点守住：
1. 参数校验和「找不到 SKU」的逐个文件夹报错；
2. SKU 命名规则（括号优先 / 去序号前缀 / C- 开头的自选备注目录）和按名称去重；
3. 同一路径换个写法只导入一次，重复导入会替换旧记录；
4. 单个文件夹出错不影响别的文件夹；入库出错时不破坏已有记录（删除旧记录和插入新记录在同一个事务里）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sidecar_test_support import make_record_model  # noqa: E402
from src.sidecar import import_routes  # noqa: E402

URL = "/api/import/folders"


def _split_number_prefix(text):
    """与 src.utils.split_number_prefix 同语义的替身：接口模块只认注入的函数。"""
    from src.utils import split_number_prefix
    return split_number_prefix(text)


@pytest.fixture()
def env(tmp_path):
    Record, database = make_record_model(tmp_path / "records.db")
    app = Flask(__name__)
    app.register_blueprint(import_routes.create_import_blueprint(
        record_model=Record, split_number_prefix=_split_number_prefix))
    root = tmp_path / "src_folders"
    root.mkdir()

    class Env:
        pass

    e = Env()
    e.client, e.Record, e.root = app.test_client(), Record, root
    e.app = app
    yield e
    database.close()


def _make_product(root, name, *files, sku_dir="SKU"):
    for relative in files:
        target = root / name / sku_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    return str(root / name)


def _post(env, *paths):
    return env.client.post(URL, json={"paths": list(paths)}).get_json()


def _sku_names(env, folder):
    row = env.Record.get(env.Record.path == os.path.abspath(folder))
    return [sku["name"] for sku in json.loads(row.content)]


# ---------------------------------------------------------------- 参数校验

@pytest.mark.parametrize("payload,message", [
    ({}, "没有选择文件夹"),
    ({"paths": []}, "没有选择文件夹"),
    ({"paths": "not-a-list"}, "没有选择文件夹"),
    ({"paths": ["", "   ", 5, None]}, "没有有效的文件夹路径"),
])
def test_rejects_missing_or_invalid_paths(env, payload, message):
    body = env.client.post(URL, json=payload).get_json()
    assert body["success"] is False and body["msg"] == message
    assert env.Record.select().count() == 0


def test_body_that_is_not_json_is_treated_as_empty(env):
    body = env.client.post(URL, data="not json", content_type="application/json").get_json()
    assert body["success"] is False and body["msg"] == "没有选择文件夹"


def test_each_folder_without_usable_skus_is_reported_separately(env):
    (env.root / "无SKU目录").mkdir()
    (env.root / "无SKU目录" / "readme.txt").write_text("x")
    empty = _make_product(env.root, "空SKU", "x.txt")
    file_not_dir = env.root / "SKU是个文件"
    file_not_dir.mkdir()
    (file_not_dir / "SKU.txt").write_text("x")

    body = _post(env, str(env.root / "不存在"), str(env.root / "无SKU目录"), empty, str(file_not_dir))
    assert body["success"] is True and body["data"]["imported_count"] == 0
    errors = "\n".join(body["data"]["errors"])
    assert "不是有效的文件夹" in errors and "未找到SKU文件夹" in errors and "未找到有效的SKU图片" in errors
    assert len(body["data"]["errors"]) == 4
    assert "失败 4 个" in body["msg"]


# ---------------------------------------------------------------- 命名与去重

def test_sku_names_come_from_file_names_and_duplicates_are_dropped(env):
    folder = _make_product(env.root, "货号A", "1(红色).jpg", "2 蓝色-加厚.png", "3(红色).jpeg", "4(RED).webp",
                           "5(red).gif", "note.txt")
    body = _post(env, folder)
    assert body["success"] is True and body["data"]["imported_count"] == 1
    # 括号里的名字优先；"2 蓝色-加厚" 去掉序号前缀并把 - 换成 +；忽略大小写同名只留第一个；非图片被忽略
    assert _sku_names(env, folder) == ["红色", "蓝色+加厚", "RED"]
    row = env.Record.get(env.Record.path == os.path.abspath(folder))
    assert (row.name, row.type, row.status, row.repo, row.clazz, row.import_source, row.managed_files) == \
        ("货号A", 1, 0, 100, "2", "manual", False)
    assert all(os.path.isfile(sku["path"]) for sku in json.loads(row.content))


def test_folder_name_with_id_is_marked_as_type_2(env):
    folder = _make_product(env.root, "ID-9001", "5-白.webp", sku_dir="sku图片")
    assert _post(env, folder)["data"]["imported_count"] == 1
    assert env.Record.get(env.Record.path == os.path.abspath(folder)).type == 2


def test_custom_note_directory_names_the_sku_after_the_directory(env):
    folder = _make_product(env.root, "C-自选", "自选备注/7 黑.png", "自选备注/8 灰.png")
    _post(env, folder)
    assert _sku_names(env, folder) == ["自选备注"]                    # 两张图同名，只留一张
    plain = _make_product(env.root, "C-普通", "1 米白.jpg")
    _post(env, plain)
    assert _sku_names(env, plain) == ["米白"]                         # 不在自选备注目录里，按文件名取


def test_empty_sku_names_are_kept_and_never_reported_as_duplicates(env):
    folder = _make_product(env.root, "空名", "1().png", "2().jpg")
    body = _post(env, folder)
    assert _sku_names(env, folder) == ["", ""]
    assert body["data"]["duplicate_sku_products"] == []


def test_images_in_nested_directories_are_collected_and_only_the_first_sku_dir_is_used(env):
    nested = _make_product(env.root, "嵌套款", "深色/9 藏青.bmp")
    two = env.root / "双SKU"
    (two / "SKU1").mkdir(parents=True)
    (two / "sku2").mkdir()
    (two / "SKU1" / "1 一.jpg").write_bytes(b"x")
    (two / "sku2" / "2 二.jpg").write_bytes(b"x")
    _post(env, nested, str(two))
    assert _sku_names(env, nested) == ["藏青"]
    assert _sku_names(env, str(two)) == ["一"]


# ---------------------------------------------------------------- 路径去重与重复导入

def test_same_path_in_different_spellings_is_imported_once(env):
    folder = _make_product(env.root, "货号A", "1(红).jpg")
    body = _post(env, folder, folder + os.sep, os.path.join(folder, "..", "货号A"), folder.upper())
    assert body["data"]["imported_count"] == 1
    assert env.Record.select().count() == 1


def test_reimporting_a_path_replaces_the_old_record(env):
    folder = _make_product(env.root, "货号A", "1(红).jpg")
    _post(env, folder)
    (Path(folder) / "SKU" / "2(蓝).png").write_bytes(b"x")
    _post(env, folder)
    assert env.Record.select().count() == 1
    assert _sku_names(env, folder) == ["红", "蓝"]


# ---------------------------------------------------------------- 出错时的行为

def test_a_failure_in_one_folder_does_not_stop_the_others(env, monkeypatch):
    good = _make_product(env.root, "好的", "1(红).jpg")
    bad = _make_product(env.root, "坏的", "1(蓝).jpg")
    original = import_routes._collect_image_files

    def flaky(start_dir):
        if "坏的" in start_dir:
            raise OSError("模拟磁盘故障")
        return original(start_dir)

    monkeypatch.setattr(import_routes, "_collect_image_files", flaky)
    body = _post(env, bad, good)
    assert body["success"] is True and body["data"]["imported_count"] == 1
    assert body["data"]["errors"] == ["坏的: 模拟磁盘故障"]
    assert [row.name for row in env.Record.select()] == ["好的"]


def test_database_failure_is_reported_and_leaves_existing_records_untouched(env, monkeypatch):
    folder = _make_product(env.root, "货号A", "1(红).jpg")
    _post(env, folder)
    (Path(folder) / "SKU" / "2(蓝).png").write_bytes(b"x")

    def boom(*args, **kwargs):
        raise RuntimeError("模拟入库失败")

    monkeypatch.setattr(env.Record, "insert_many", staticmethod(boom))
    body = _post(env, folder)
    assert body["success"] is False and "导入失败: 模拟入库失败" in body["msg"]
    # 删除旧记录和插入新记录在同一个事务里：插入失败时旧记录还在，内容没变
    assert env.Record.select().count() == 1
    assert _sku_names(env, folder) == ["红"]


# ---------------------------------------------------------------- 依赖注入

def test_sku_naming_uses_the_injected_split_function(tmp_path):
    Record, database = make_record_model(tmp_path / "records.db")
    seen = []

    def fake_split(text):
        seen.append(text)
        return None, "固定名"

    app = Flask(__name__)
    app.register_blueprint(import_routes.create_import_blueprint(record_model=Record, split_number_prefix=fake_split))
    folder = _make_product(tmp_path, "货号A", "任意文件名.jpg")
    body = app.test_client().post(URL, json={"paths": [folder]}).get_json()
    assert body["success"] is True and seen == ["任意文件名"]
    assert [sku["name"] for sku in json.loads(Record.get().content)] == ["固定名"]
    database.close()
