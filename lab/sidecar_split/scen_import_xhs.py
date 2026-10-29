# -*- coding: utf-8 -*-
"""本地文件夹导入（/api/import/folders）的新旧对打场景（2026-10-20）。

不需要浏览器：全部是本地目录 + 数据库。数据目录里现造一批商品文件夹，覆盖
  - 参数校验的每个分支；
  - SKU 命名规则（括号优先 / 去序号前缀并把 - 换成 + / C- 开头的自选备注目录 / 同名忽略大小写去重）；
  - 每种“找不到 SKU”的失败；路径去重（Windows 下忽略大小写）；重复导入同一路径会替换旧记录；
  - 单个文件夹出错（只记入 errors）与整批入库出错（外层兜底）。
"""
import json
import os

from scenarios import SCENARIOS


def _touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fp:
        fp.write(data)


def import_setup(ctx):
    root = os.path.join(ctx.data_dir, 'imp_src')
    ctx.state['root'] = root
    # 货号A：括号里的名字优先；"2 蓝色-加厚" 去序号前缀、- 换成 +；3(红色) 与 1(红色) 重名被去重；(Red)/(red) 忽略大小写也算重名
    for name in ('1(红色).jpg', '2 蓝色-加厚.png', '3(红色).jpeg', '4(Red).webp', '5(red).gif', 'note.txt'):
        _touch(os.path.join(root, '货号A', 'SKU', name))
    # 名字里带 ID 的文件夹记为 type=2；SKU 目录名只要含 sku（不分大小写）
    _touch(os.path.join(root, 'ID-9001', 'sku图片', '5-白.webp'))
    # C- 开头 + 自选备注子目录：SKU 名取子目录名（两张图同名，只留一张）
    for name in ('7 黑.png', '8 灰.png'):
        _touch(os.path.join(root, 'C-自选', 'SKU', '自选备注', name))
    # C- 开头但不在自选备注目录里：按文件名取
    _touch(os.path.join(root, 'C-普通', 'SKU', '1 米白.jpg'))
    # 子目录里的图也会收集
    _touch(os.path.join(root, '嵌套款', 'SKU', '深色', '9 藏青.bmp'))
    # 没有序号的文件名、纯数字文件名
    _touch(os.path.join(root, '无序号', 'SKU', '纯文字名.png'))
    _touch(os.path.join(root, '无序号', 'SKU', '12.png'))
    # 括号里是空的：SKU 名为空串，去重时原样保留、重名检查时被跳过
    _touch(os.path.join(root, '空名', 'SKU', '1().png'))
    _touch(os.path.join(root, '空名', 'SKU', '2().jpg'))
    # 找不到 SKU 的三种情况
    _touch(os.path.join(root, '无SKU目录', 'readme.txt'))
    _touch(os.path.join(root, '空SKU', 'SKU', 'x.txt'))
    _touch(os.path.join(root, 'SKU文件夹是个文件', 'SKU.txt'))
    # 两个 SKU 目录：只取遍历到的第一个
    _touch(os.path.join(root, '双SKU', 'SKU1', '1 一.jpg'))
    _touch(os.path.join(root, '双SKU', 'sku2', '2 二.jpg'))


def _p(ctx, *parts):
    return os.path.join(ctx.state['root'], *parts)


def _patch_helper(name, func):
    """把被测模块里的某个辅助函数换成会抛错的假件：old 改 app.py 的全局，new 改新模块的全局。"""
    def before(ctx):
        if ctx.mode == 'old':
            target = ctx.mod
        else:
            import importlib
            target = importlib.import_module('src.sidecar.import_routes')
        ctx.state['patched'] = (target, name, getattr(target, name))
        setattr(target, name, func)
    return before


def _unpatch(ctx):
    target, name, original = ctx.state.pop('patched')
    setattr(target, name, original)
    return {'restored': name}


def _boom(*args, **kwargs):
    raise RuntimeError('模拟磁盘故障')


def _break_insert(ctx):
    ctx.state['orig_insert_many'] = ctx.Record.insert_many
    ctx.Record.insert_many = staticmethod(_boom)


def _restore_insert(ctx):
    ctx.Record.insert_many = ctx.state.pop('orig_insert_many')
    return {'restored': 'insert_many'}


def import_build_new(ctx):
    from src.sidecar.import_routes import create_import_blueprint
    return [create_import_blueprint(record_model=ctx.Record, split_number_prefix=ctx.mod.split_number_prefix)]


def import_requests(ctx):
    url = '/api/import/folders'
    A, ID, C1, C2, NEST = _p(ctx, '货号A'), _p(ctx, 'ID-9001'), _p(ctx, 'C-自选'), _p(ctx, 'C-普通'), _p(ctx, '嵌套款')
    return [
        # ---- 参数校验 ----
        ('POST', url, {}),
        ('POST', url, {'paths': []}),
        ('POST', url, {'paths': 'not-a-list'}),
        ('POST', url, {'paths': ['', '   ', 5, None]}),
        ('POST', url, None, {'data': 'not json', 'content_type': 'application/json'}),
        # ---- 找不到 SKU / 路径无效 ----
        ('POST', url, {'paths': [_p(ctx, '不存在的目录')]}),
        ('POST', url, {'paths': [_p(ctx, '无SKU目录')]}),
        ('POST', url, {'paths': [_p(ctx, '空SKU')]}),
        ('POST', url, {'paths': [_p(ctx, 'SKU文件夹是个文件')]}),
        # ---- 正常导入 ----
        ('POST', url, {'paths': [A]}),
        ('POST', url, {'paths': [ID, C1, C2, NEST, _p(ctx, '无序号'), _p(ctx, '双SKU'), _p(ctx, '空名')]}),
        # 同一路径写两遍（大小写不同）：只导入一次；重复导入已有路径会替换旧记录
        ('POST', url, {'paths': [A, A.upper(), A + os.sep, os.path.join(A, '..', '货号A')]}),
        # 成功与失败混在一起：消息里要带失败个数
        ('POST', url, {'paths': [A, _p(ctx, '无SKU目录'), _p(ctx, '不存在的目录')]}),
        # ---- 兜底分支：单个文件夹出错只记入 errors；整批入库出错走外层兜底 ----
        ('POST', url, {'paths': [A, ID]}, {'before': _patch_helper('_collect_image_files', _boom), 'after': _unpatch}),
        ('POST', url, {'paths': [_p(ctx, '无序号')]}, {'before': _break_insert, 'after': _restore_insert}),
        # 出错之后库里的内容没有被破坏
        ('POST', url, {'paths': [_p(ctx, '无序号')]}),
    ]


def import_final(ctx):
    rows = []
    for r in ctx.Record.select().order_by(ctx.Record.id):
        rows.append({
            'id': r.id, 'name': r.name, 'path': r.path, 'type': r.type, 'status': r.status, 'repo': r.repo,
            'title': r.title, 'clazz': r.clazz, 'remark': r.remark, 'content': json.loads(r.content),
            'import_source': r.import_source, 'source_url': r.source_url, 'managed_files': r.managed_files,
        })
    return rows


SCENARIOS['import_folders'] = dict(
    setup=import_setup,
    patch_old=lambda ctx: None,
    build_new=import_build_new,
    requests=import_requests,
    final=import_final,
)
