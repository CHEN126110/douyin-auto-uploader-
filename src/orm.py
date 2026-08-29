# -*- coding: utf-8 -*-
# mypy: ignore-errors
import logging
import os
from peewee import *  # type: ignore
from .runtime_paths import resolve_data_file
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_legacy_database_path = os.path.join(_project_root, 'sqlite.db')
_database_path = str(resolve_data_file('sqlite.db', legacy_fallback=_legacy_database_path))
database = SqliteDatabase(_database_path)


class BaseModel(Model):
    '"""BaseModel类.\n"""'

    class Meta():
        '"""Meta类.\n"""'
        database = database


class Record(BaseModel):
    '"""Record类.\n"""'
    id = PrimaryKeyField()
    name = CharField()
    path = CharField()
    type = IntegerField()
    status = IntegerField()
    repo = IntegerField(null=True)
    title = CharField(null=True)
    clazz = CharField(null=True)
    remark = CharField(null=True)
    content = TextField()
    update_time = DateTimeField()
    publish_time = DateTimeField(null=True)
    # --- 新增字段 ---
    shipping_template = CharField(null=True, default='中通包邮') # 增加一个默认值
    import_source = CharField(null=True, default='manual')
    source_url = CharField(null=True)
    managed_files = BooleanField(default=False)


def _ensure_record_columns():
    """补齐旧数据库缺失字段，避免升级后读取 Record 时缺列。"""
    columns = {
        row[1]
        for row in database.execute_sql('PRAGMA table_info("record")').fetchall()
    }
    migrations = [
        ('shipping_template', 'ALTER TABLE "record" ADD COLUMN "shipping_template" VARCHAR(255) DEFAULT \'中通包邮\''),
        ('import_source', 'ALTER TABLE "record" ADD COLUMN "import_source" VARCHAR(32) DEFAULT \'manual\''),
        ('source_url', 'ALTER TABLE "record" ADD COLUMN "source_url" VARCHAR(2048)'),
        ('managed_files', 'ALTER TABLE "record" ADD COLUMN "managed_files" INTEGER DEFAULT 0'),
    ]
    for column_name, sql in migrations:
        if column_name not in columns:
            database.execute_sql(sql)


def initialize_database_schema():
    """初始化数据库表结构，并补齐旧版本缺失字段。"""
    database.create_tables([Record])
    _ensure_record_columns()


initialize_database_schema()
