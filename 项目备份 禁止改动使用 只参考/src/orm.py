# -*- coding: utf-8 -*-
# mypy: ignore-errors
import logging
from peewee import *  # type: ignore
database = SqliteDatabase('sqlite.db')


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


database.create_tables([Record])    