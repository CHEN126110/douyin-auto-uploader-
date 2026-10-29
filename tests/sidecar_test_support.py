# -*- coding: utf-8 -*-
"""Sidecar 接口测试共用的小工具：隔离数据库里的最小 Record 模型。

只含接口代码实际读写的字段，不导入 src.orm（它在导入时就会连上用户的真实数据库）。
"""

from __future__ import annotations

from datetime import datetime

from peewee import BooleanField, CharField, DateTimeField, IntegerField, Model, SqliteDatabase, TextField


def make_record_model(db_path):
    """在临时库里建一个 Record 表，返回 (模型类, 数据库)；用完请 ``database.close()``。"""
    database = SqliteDatabase(str(db_path))

    class Record(Model):
        name = CharField()
        path = CharField(default="")
        title = CharField(null=True)
        clazz = CharField(null=True)
        remark = CharField(null=True)
        status = IntegerField(default=0)
        repo = IntegerField(null=True)
        content = TextField(default="[]")
        source_url = CharField(null=True)
        type = IntegerField(default=1)
        import_source = CharField(null=True, default="manual")
        managed_files = BooleanField(default=False)
        update_time = DateTimeField(default=datetime.now)

        class Meta:
            pass

    Record._meta.database = database
    database.connect()
    database.create_tables([Record])
    return Record, database
