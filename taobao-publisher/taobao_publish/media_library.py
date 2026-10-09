# -*- coding: utf-8 -*-
"""素材目录导航。只使用当前素材 iframe 的可见目录树，不扫描其它商品。"""
import json
import time
from collections.abc import Mapping

#: 图片空间目录树的根节点名。`picturecenter.ALL_IMAGES_NODE` 有同一常量，
#: 但那个模块是**协议契约层**（只构造/解析 mtop 请求，不碰页面）；
#: 本模块走页面 DOM，不 import 它，避免把两层耦合起来。两处字面量必须一致。
ALL_IMAGES_NODE = "全部图片"

#: 目录诊断契约里的「三值页面」。写不明页面，路径就没法解释——
#: 选图器与素材中心是**两棵树、两套根表示**（见 :func:`root_prefix`）。
#: `protocol_media.ensure_cloud_folders` 的建目录步骤也复用这组取值。
PAGE_PICKER = '选图器'
PAGE_MATERIAL_CENTER = '素材中心'

#: 「没有对象可写」时 `目标=` 的占位。契约要求不得留空。
NO_TARGET = '-'

#: 阶段名：目录解析与归档全部发生在 `upload_images` 阶段内
#: （stages.py 的绑定分支 :2812 与协议分支 :2837 都在那里）。
#: 调用方要能覆盖它——`media_library` 不 import `stages`，拿不到阶段注册表。
STAGE_UPLOAD_IMAGES = 'upload_images'

#: 判据是「页面还没读出东西」时用的原码：判决 = **读不出来**（不是「没有」）。
REASON_MISSING = 'reason_missing'

#: 判据是「这个页面没有目录树」时用的原码：判决 = **页面没有树**（不是「读不出来」）。
#: `folder_expression` 在 `supported=false` 时就是这个意思，由调用方补上原码。
REASON_TREE_NOT_SUPPORTED = 'directory_tree_not_supported'

#: 契约要求：**确实没有用户可做的动作**时用这一句，不许编一个走不通的动作。
NO_USER_ACTION = '本步骤无可用操作，请把该文案连同判据原码反馈——需改代码'

#: `reason` → 一句**用户在当前界面立刻能做**的动作（Q4）。只给一步、动词开头。
#:
#: ⚠️ 这不是「错误处理」，是**措辞映射**：映射不到就落到 :data:`NO_USER_ACTION`，
#: 于是漏登记的判据会在文案里**显形**，不会被一句"请重试"糊过去。
#:
#: 白名单固定（契约原文）：在素材中心建好某目录后重试 / 关掉多余标签只留一个发布页 /
#: 关掉选图器弹层重开后重试 / 等图库卡片渲染完再重试 / 删掉多余同名素材后再试 /
#: 显式开启 TAOBAO_UPLOAD_ALLOW_WRITE 后重试 / 手动重载该标签页。
#: 禁止拿 `PAGE_ERROR` 的通用 hint「确认调试浏览器停留在预期的页面与登录态」充当动作。
REASON_ACTIONS = {
    # 「目录不在树里」——用户要在**另一棵树**（素材中心）里把它建出来。
    'directory_missing': '先在素材中心（图片空间 → 素材中心）建好该目录，再点一次「开始淘宝发布」',
    # 命中太多，无法确定是哪一条：先去重，再让程序重读。
    'directory_ambiguous': '删掉多余的同名目录或素材后再点一次「开始淘宝发布」',
    'directory_disabled': '改用另一个可用的同名目录，或把被禁用的那个恢复后再点一次「开始淘宝发布」',
    'directory_tree_not_unique': '关掉多余的淘宝发布页标签，只留一个再重试',
    'selected_directory_not_unique': '关掉选图器弹层重新打开，让它重读一次当前目录',
    'directory_expander_not_unique': '关掉选图器弹层重新打开后，再点一次「开始淘宝发布」',
    'directory_button_may_submit': '别点那个目录控件，改在素材中心里手工建好该目录后重试',
    REASON_TREE_NOT_SUPPORTED: '在调试浏览器里打开该店铺的淘宝发布页并确认已登录，再点一次「开始淘宝发布」',
    REASON_MISSING: '手动重载该标签页后重试（目录树表达式没有返回有效结果）',
    # ensure_child_directory 六步（**该自动建目录步骤尚未真机验证**）。
    'create_folder_missing': '手工在素材中心建好该目录后重试（该自动建目录步骤尚未真机验证）',
    'create_folder_ambiguous': '关掉素材中心里多余的「新建文件夹」入口（只留一个）后重试（该自动建目录步骤尚未真机验证）',
    'create_folder_button_may_submit': '别点那个「新建文件夹」按钮，改在素材中心里手工建好该目录后重试',
    'create_folder_input_missing': '手工在素材中心建好该目录后重试（该自动建目录步骤尚未真机验证）',
    'create_folder_confirm_missing': '手工在素材中心建好该目录后重试（该自动建目录步骤尚未真机验证）',
    # 建目录的写授权门（`_cloud_folder_creator.create` 在 stages.py 侧先 require）。
    'write_not_authorized': '显式开启 TAOBAO_UPLOAD_ALLOW_WRITE 授权后重试；本次一个目录都没建',
    # 同一路径命中多条 / 商品名重复：页面渲染或素材本身重复。
    'ambiguous': '删掉多余的同名目录或素材后再点一次「开始淘宝发布」',
    'directory_limit_exceeded': '删掉该商品目录下的多余子目录后重试',
}


def _media_failure(stage, branch, page, target, reason, *, action=None):
    """媒体目录诊断契约的**唯一实现处**：把一处判据渲染成一行可定位的失败文案。

    契约（本仓库固定，改动要先改文档）：

    * 形状 = 一行主句 + 一句动作，用「。下一步：」连接，**不换行、不追加第二句建议**；
    * 主句 = ``媒体失败｜阶段={stage}｜分支={branch}｜页面={page}｜目标={target}｜判据={reason}``
      —— 六项**必填非空**；
    * ``branch`` 由产生该判据的代码分支**显式传入**，禁止从文案反推、禁止用中文短语代替：
      同一句 ``无法进入图片目录 …：directory_missing`` 在绑定分支与协议分支都会逐字产出，
      只有 ``分支=`` 能把两者分开；
    * ``reason`` 必须是判据点返回的**英文原码逐字照抄**（封闭词表见
      :data:`REASON_ACTIONS`）；读不出来写 :data:`REASON_MISSING`，
      页面没有树写 :data:`REASON_TREE_NOT_SUPPORTED`，
      **禁止**改写成「无有效结果」「没有受支持的目录树」这类模糊中文；
    * ``target`` 写定位对象且与代码实际尝试到达的对象逐段一致
      （完整目录路径 / ``pictureId=<纯数字串>`` / ``<目录路径>/<文件名>`` / 契约键 /
      ``操作=<operation>``）；确实没有对象时写 :data:`NO_TARGET`，不得留空；
    * ``action`` 只写一步、动词开头、必须是用户**在当前界面立刻能做**的动作；
      确实没有时写 :data:`NO_USER_ACTION`。

    ⚠️ **只拼文案**：这里不做任何页面交互、不等待、不重试、不吞异常。
    本函数是内部约定（下划线开头）。

    ## 本轮（2026-10-07）接线的边界——别把它当已完工

    * ``branch`` 由**每个抛错点自己写死**该点的分支标识（恰好在处，不是从文案反推）；
    * ``stage`` 现在取自 :data:`STAGE_UPLOAD_IMAGES`（模块默认值），
      **调用点接线尚未做**：外层 `stages.stage_upload_images` 与 `form_adapters`
      还没把 ``stage=`` / ``branch=`` 从调用点显式传进来；接线时本函数签名会把这两项收紧成必填；
    * 落点仍是**外层包装层的 detail**（如 ``stages.py`` 的
      ``"上传商品图片失败：{}".format(exc)``）——那层在本轮改动范围之外，一行没动。

    :param reason: 判据点返回的**原码**；传空即视为「读不出来」（``reason_missing``）。
    """

    text = str(reason or '').strip() or REASON_MISSING
    if action is None:
        action = REASON_ACTIONS.get(text, NO_USER_ACTION)
    return '媒体失败｜阶段={}｜分支={}｜页面={}｜目标={}｜判据={}。下一步：{}'.format(
        stage, branch, page, target or NO_TARGET, text, action)


def folder_expression(path=(), *, action='read'):
    from .contracts import load_contracts
    from .page import PageError
    if action not in ('read', 'open', 'expand', 'click'):
        raise ValueError('未知目录动作')
    if any(not isinstance(part, str) or not part.strip() for part in path):
        raise ValueError('目录路径必须包含明确名称')
    contracts = load_contracts().selectors
    contract, node_contract = (contracts.get(key) for key in ('media.directory_tree', 'media.directory_node'))
    for spec in (contract, node_contract):
        if spec.evidence_level not in ('candidate', 'verified') or not spec.selector or not spec.evidence_source:
            raise PageError('目录树没有可验证的候选定位方式')
    return r'''(() => {
      const A = INPUT;
      const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
      const trees=Array.from(document.querySelectorAll(A.tree))
        .filter(visible).filter(e=>!e.parentElement.closest(A.tree));
      if (!trees.length) return {ok:true, supported:false, path:[]};
      if (trees.length!==1) return {ok:false,reason:'directory_tree_not_unique'};
      const tree=trees[0], selector=tree.querySelector('[role="treeitem"]')?'[role="treeitem"]':A.node;
      const nodes=Array.from(tree.querySelectorAll(selector)).filter(visible);
      const labels=node=>Array.from(node.querySelectorAll('.next-tree-node-label,[data-folder-name]'))
        .filter(e=>e.closest(selector)===node&&visible(e));
      const name=node=>{
        const own=labels(node);
        if(own.length===1)return (own[0].textContent||'').trim();
        const explicit=node.getAttribute('aria-label');if(explicit)return explicit.trim();
        const copy=node.cloneNode(true);copy.querySelectorAll('[role="group"],ul,[role="treeitem"],.next-tree-node').forEach(e=>e.remove());
        return (copy.textContent||'').trim();
      };
      const stack=[], entries=[];
      for(const node of nodes){
        const parent=node.parentElement.closest(selector);
        const parentEntry=entries.find(e=>e.node===parent);
        const level=Number(node.getAttribute('aria-level'));
        let base=parentEntry?parentEntry.path:[];
        if(!parentEntry&&Number.isInteger(level)&&level>0){stack.length=Math.min(stack.length,level-1);base=stack.slice()}
        const path=base.concat(name(node));entries.push({node,path});
        if(Number.isInteger(level)&&level>0)stack[level-1]=name(node);
      }
      const selected=entries.filter(e=>e.node.getAttribute('aria-selected')==='true'||e.node.classList.contains('next-tree-node-selected')
        ||Array.from(e.node.querySelectorAll('.next-tree-node-inner.next-selected')).some(n=>n.closest(selector)===e.node));
      if(selected.length>1)return {ok:false,reason:'selected_directory_not_unique'};
      const current=selected.length===1?selected[0].path:[];
      if(A.action==='read')return {ok:true,supported:true,path:current,paths:entries.map(e=>e.path),
        directories:entries.map(e=>({path:e.path,expanded:e.node.getAttribute('aria-expanded'),
          folder_id:String(
            e.node.getAttribute('value')
            || (e.node.closest('.next-tree-node,[role="presentation"]')||{getAttribute:()=>null}).getAttribute('value')
            || '')}))};
      const hits=entries.filter(e=>e.path.length>=A.path.length&&JSON.stringify(e.path.slice(-A.path.length))===JSON.stringify(A.path));
      if(hits.length!==1)return {ok:false,reason:hits.length?'directory_ambiguous':'directory_missing',path:A.path};
      const entry=hits[0],node=entry.node;
      if(node.getAttribute('aria-disabled')==='true'||node.classList.contains('next-disabled'))return {ok:false,reason:'directory_disabled'};
      if(node.getAttribute('aria-expanded')==='false'){
        const expanders=Array.from(node.querySelectorAll('.next-tree-switcher,button[aria-expanded]')).filter(e=>e.closest(selector)===node&&visible(e));
        if(expanders.length!==1)return {ok:false,reason:'directory_expander_not_unique'};
        if(expanders[0].tagName==='BUTTON'&&expanders[0].form&&expanders[0].type!=='button')return {ok:false,reason:'directory_button_may_submit'};
        expanders[0].click();
      }
      if(A.action==='expand')return {ok:true,supported:true,path:entry.path};
      // click：已选中也要真点一次（素材中心靠点当前节点重新拉列表）；
      // open：已选中则跳过（选图器点已选中节点平台不重新拉取，点了也白点）。
      if(A.action!=='click'&&selected.length===1&&selected[0].node===node)return {ok:true,supported:true,path:entry.path,already:true};
      const own=labels(node), target=own.length===1?own[0]:node;
      if(target.tagName==='BUTTON'&&target.form&&target.type!=='button')return {ok:false,reason:'directory_button_may_submit'};
      target.click();return {ok:true,supported:true,path:entry.path,already:false};
    })()'''.replace('INPUT', json.dumps({'path':list(path),'action':action,'tree':contract.selector,
                                       'node':node_contract.selector},ensure_ascii=False),1)


def read_directory(client, *, context_id):
    """读当前页面的目录树状态（唯一的「读树」入口）。

    判据（**必须先在前、后分开读**，不能合成一句）：

    * ``supported=False`` → 页面没有目录树，判决是「这个页面没有树」；
    * 表达式没给出 ``reason`` → 判决是「**读不出来**」，写 ``reason_missing``；
    * 表达式给了原码 → 原码**逐字照抄**（``directory_tree_not_unique`` /
      ``selected_directory_not_unique``）。

    契约要求 reason **不得改写**成「无有效结果」这类模糊中文——原来那正是
    `result.get('reason', '无有效结果')` 的兜底词，它把三个不同判决糊成了一个。
    这里**不新增任何重试或兜底**：判据点说什么就报什么。
    """
    from .page import PageError
    result = client.evaluate(folder_expression(), context_id=context_id)
    if not isinstance(result, dict) or result.get('ok') is not True:
        # 原码缺失 → 「读不出来」；有原码 → 逐字照抄。判据只有一处，不合并。
        reason = result.get('reason') if isinstance(result, dict) else None
        # ⚠️ 动作句**只**在「原码缺失」这一种情况自己给：这里是**读树**，不可能出现
        # 「目录不存在」（judgment point 根本没产过 directory_missing），
        # 走目录缺失那条映射会给出一个走不通的动作。
        # 带原码时留给 :data:`REASON_ACTIONS` 按原码选动作——同一个判据点会返回
        # `directory_tree_not_unique` / `selected_directory_not_unique` 两种原码，
        # 一个统一动作会把它们说成同一件事。
        action = None
        if not reason:
            action = '手动重载该标签页后重试（目录树表达式没有返回有效结果）'
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'read_directory', PAGE_PICKER, NO_TARGET, reason,
            action=action))
    return result


def _all_images_path(state):
    """从目录树状态里取「全部图片」根节点的**完整路径**（取不到返回 ``None``）。"""

    for path in (state.get('paths') or []):
        if path and path[-1] == ALL_IMAGES_NODE:
            return list(path)
    return None


def ensure_product_root(client, product_name, *, context_id, creator=None, role_names=(),
                        wait_seconds=5.0, page=PAGE_PICKER):
    """返回商品目录在树里的路径；不在树里就用 ``creator`` 建。**唯一建目录入口。**

    ## 为什么收敛成一个（2026-10-07 做减法）

    在这之前"确保目录存在"散在**三处**，各自演化：

    * `resolve_role_folder` 里一套（带 `rendered_children` 门 + 轮询等待）；
    * `bind_prepared_media` 里一套——**根本没有建目录能力**，于是新商品第一次上架
      直接报 ``无法进入图片目录 全部图片/ID-…：directory_missing``（真机 2026-10-07）；
    * `stages` 里一段内联的"建目录 + 重开弹层 + 等目录"。

    三套里必然有一套是漏的。现在只留这一处，**准备与绑定两条路径都调它**。

    ## 顺序：先进目录，再读子目录

    目录树是**懒加载**的——商品目录折叠时它的子目录不在 DOM 里（真机实证）。
    所以"读不到子目录"不能推出"目录不存在"；判断依据是**商品目录自己在不在树里**。
    刚在素材中心标签页建好的目录，选图器这棵树要过一会儿才看得到，所以建完要有界地等。

    :param creator: ``creator(商品名, 角色目录名列表) -> {目录名: folderId}``。
        没有它时**如实抛错**，绝不回退到根目录。
    :param page: 这次解析发生在哪个页面（:data:`PAGE_PICKER` / :data:`PAGE_MATERIAL_CENTER`）。
        失败文案要靠它把路径解释清楚——两个页面的树**根表示不同**（见 :func:`root_prefix`）。

    ## 两条失败文案（语义保留，只补页面与路径）

    两条都是**如实失败**，都不回退到根目录；契约要求的「页面」与「目标」写在主句里：

    1. 没有建目录入口 → 商品目录名就是那个「目标」（树里确实没有这个对象，不硬拼前缀）；
    2. 建完仍读不到 → 说明**哪条路径刚在素材中心被建好**，但选图器这棵树没刷新出来。
    """

    from .page import PageError

    path = product_root_path(client, product_name, context_id=context_id, page=page)
    if path:
        return path
    if creator is None:
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'resolve_role_folder', page, product_name,
            'directory_missing'))
    if not isinstance(creator(product_name, [str(name) for name in (role_names or ())]), dict):
        # 回调没给目录映射 = 建目录这一步没有回执，**不能当成建好了**。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'ensure_product_root', PAGE_MATERIAL_CENTER,
            product_name, REASON_MISSING))
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        # 目录是在**另一个标签页**里建好的，这棵树要重新拉一次才看得到它。
        path = product_root_path(client, product_name, context_id=context_id, page=page)
        if path or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    if path:
        return path
    raise PageError(_media_failure(
        STAGE_UPLOAD_IMAGES, 'ensure_product_root', page, product_name,
        'directory_missing',
        action='关掉选图器弹层重开后重试（选图器这棵目录树没能刷新出来：'
               '该商品目录刚在素材中心建好）'))


def resolve_role_folder(client, product_name, role_folder, *, context_id,
                        creator=None, role_folders=(), page=PAGE_PICKER):
    """确保 ``全部图片/<商品名>/<角色目录>`` 存在，返回角色目录的 **folderId**。

    :param creator: **可选的"跨页建目录"回调**。签名 ``creator(product_name, names)
        -> {目录名: folderId}``。选图器里**没有**建目录入口（E-286），所以当目录
        不存在时由调用方决定怎么建——流水线传进来的是"开一个素材中心标签去建"
        （``protocol_media.ensure_cloud_folders``）。
    :param role_folders: 交给 `creator` 一次性建好的**全部角色目录名**。
        传进来是为了**一次建齐**，避免三个角色各开一次素材中心标签。

    ## 为什么需要（用户诉求："直接上传整个文件夹"）

    协议上传原先一律写进图片空间**根目录**（`folder_id=ROOT_FOLDER_ID`），
    而本地结构只体现在文件名里——于是图库里全是散图、没法按商品/用途管理。

    正确形态是三层：``全部图片`` → ``商品名`` → ``主图`` / ``SKU`` / ``详情页``。
    目录名**就取上传内容本身的文件夹名**（本地 ``ID123456/主图/x.jpg``
    → 云端 ``ID123456/主图/x.jpg``），不需要任何人另行约定。

    ## 为什么不返回 `None` 兜底

    拿不到 folderId 就**抛错**。回退到根目录看似"能跑"，实际是把用户要的
    结构悄悄丢掉——那正是这次要修的问题，不能再用兜底掩盖。

    ## ⚠️ 必须先"进入"商品目录，子目录才渲染出来（真机踩过）

    目录树是**懒加载**的：商品目录折叠时，它的子目录（`主图`/`SKU`/`详情页`）
    **根本不在 DOM 里**。真机实测：

    * 进入**前**读树：只有 ``ID-1074582642352``（folderId=1114918855143810805）；
    * ``open_directory(['ID-1074582642352'])`` 之后再读：
      ``…/SKU``、``…/主图``、``…/详情页`` 全部出现并带 folderId。

    我在这一步上错了两次：先自己拼路径（树里不存在那种路径），
    又没进入父目录就读子目录——两次都把"目录已存在且为空"误判成
    "目录不存在，需要新建"。

    ## 为什么不返回 `None` 兜底

    拿不到 folderId 就**抛错**。回退到根目录看似"能跑"，实际是把用户要的
    结构悄悄丢掉——那正是这次要修的问题，不能再用兜底掩盖。
    """

    from .page import PageError

    root = ensure_product_root(client, product_name, context_id=context_id,
                               creator=creator, role_names=role_folders, page=page)
    wanted = list(root) + [role_folder]
    # 子目录 ID 已在树中时直接复用；只有懒加载尚未露出它时才进入父目录。
    existing_id = directory_folder_id(client, wanted, context_id=context_id, page=page)
    if existing_id:
        return existing_id
    open_directory(client, root, context_id=context_id, page=page)
    folder_id = ""
    for _ in range(3):
        # 刚进目录时子目录可能还没渲染出来（懒加载）：给它两三个短呼吸再下结论。
        folder_id = directory_folder_id(client, wanted, context_id=context_id, page=page)
        if folder_id:
            return folder_id
        time.sleep(0.4)
    if creator is None:
        # 没有跨页建目录能力时**如实失败**，并说清该做什么。
        # 不试图在选图器里硬建：那里根本没有入口（E-286），
        # 做一个走不通的操作只会换来一个看不懂的状态错误。
        # 页面固定写「选图器」：这个分支的**当前位置**就是选图器（角色目录在它这棵树里没读到）。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'resolve_role_folder', PAGE_PICKER,
            '/'.join(wanted), 'directory_missing'))
    # 跨页建目录：一次性把商品目录 + 全部角色目录建齐（只开一个素材中心标签）。
    created = creator(product_name, [str(item) for item in (role_folders or (role_folder,))])
    folder_id = str((created or {}).get(role_folder) or '').strip()
    if not folder_id:
        # 回调没有为**这个角色**给出 folderId：建目录这一步给了空回执，如实失败。
        # 页面固定写「素材中心」：回调是在那个独立标签页里执行的。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'resolve_role_folder', PAGE_MATERIAL_CENTER,
            '/'.join(wanted), REASON_MISSING))
    return folder_id


def directory_folder_id(client, path, *, context_id, page=PAGE_PICKER):
    """读某个目录的 **folderId**（协议上传要用它）。

    为什么需要：`upload.api` 的目标目录是 **`folderId`（数字）**，不是目录名
    （E-223 已实证：把路径写进文件名会被平台拒，
    ``FILE_NAME_CONTAIN_SPECIAL_CHARACTER``）。而目录树节点上就带着它——
    2026-10-06 实测（E-282）：

    .. code-block:: html

        <li role="presentation" class="next-tree-node"
            value="1114918855143810805" name="ID-1074582642352" level="1">

    **`value` 就是 folderId**。目录名可能重复（图省里真有两个同名文件夹），
    所以这里按**完整路径**定位，取不到就如实返回 ``None``——**不猜**。

    ⚠️ **"不存在"与"有歧义"必须分开**：同一个完整路径在树里命中 **多于一条**
    说明页面渲染出现了重复节点。这种情况静默返回 ``None`` 会让调用方误以为
    "目录不存在"、进而去**重复建一个同名目录**。所以这里显式抛错。

    :return: folderId 字符串；目录不在树里、被折叠未渲染、或节点没有 `value` → ``None``。
    :raises PageError: 同一完整路径命中多条（页面渲染歧义）。

    ⚠️ **读不出来与「目录不存在」不是一回事**：``supported=False``（页面没有树）
    时这里仍然返回 ``None``（调用方按既有语义处理），但真到"命中多条"这种
    **必须由人消歧**的状态，抛出的文案带 ``页面=``、完整路径与 ``判据=ambiguous``。
    """

    from .page import PageError
    wanted = list(path)
    if not wanted:
        return None
    state = read_directory(client, context_id=context_id)
    if not state.get('supported'):
        return None
    hits = [entry for entry in (state.get('directories') or [])
            if list(entry.get('path') or []) == wanted]
    if len(hits) > 1:
        # 同一完整路径命中多条 = 页面渲染出现重复节点。这里**不猜**：
        # 猜错会让调用方去重复建一个同名目录，比报错更难发现。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'directory_folder_id', page, '/'.join(wanted), 'ambiguous'))
    if not hits:
        return None
    folder_id = str(hits[0].get('folder_id') or '').strip()
    return folder_id or None


#: 存在性判定前的懒加载助推窗口（秒）。测试可把它 patch 成 0 跳过助推——
#: 助推本身有专门的合成用例覆盖，不让每个建目录用例都真等 5 秒。
_EXISTENCE_RENDER_TIMEOUT = 5.0


def ensure_child_directory(client, parent_path, name, *, context_id, timeout=15.0):
    """在 `parent_path` 下确保存在名为 `name` 的子目录，返回它的 **folderId**。

    ## 为什么要走页面 UI，而不是协议

    实测（E-278）：`mtop.taobao.picturecenter.console.dir.add` 与 `dir.query`
    **都返回 `FAIL_SYS_ILLEGAL_ACCESS::非法请求`**（HTTP 200、签名链路正常，
    是**网关侧**拒绝）。所以"建目录"只能走**平台自己的页面 UI**。

    ⚠️ 而且**只有素材中心页有那个 UI**（E-286）：选图器弹层里平铺按钮只有
    「本地上传」、右键也不弹菜单。所以本函数**必须在素材中心页的客户端上调用**
    （`protocol_media.ensure_cloud_folders` 就是那么用的）。

    ## 行为

    1. 目录已存在 → 直接返回它的 folderId（**幂等，不重复建**）；
    2. 不存在 → 先进入 `parent_path`，点「新建文件夹」并提交 `name`，
       然后回读新目录的 folderId；
    3. 任何一步拿不到确定的 folderId → 抛错，**不返回猜测值**。

    :raises PageError: 页面没有建目录入口、建目录失败、或建完仍读不到 folderId。
    """

    from .page import PageError

    wanted = list(parent_path) + [name]
    existing = directory_folder_id(client, wanted, context_id=context_id,
                                   page=PAGE_MATERIAL_CENTER)
    if existing:
        return existing

    # ⚠️ **存在性判定不能被懒加载骗**（2026-10-07 真机实证，
    # `tmp/probe-duplicate-name-rejection.py`）：父节点的子目录没渲染时
    # `directory_folder_id` 返回 None，直接判定"不存在"会去建一个**重名**目录——
    # 平台拒绝（toast「新建文件夹失败。」）且**弹层不关闭**，残留的弹层会把
    # 同一个标签里后续的建目录步骤全部污染。所以判定前先把父节点的子目录
    # 助推渲染出来，有界重读确认"真的不存在"才往下走创建。
    if parent_path:
        render_deadline = time.monotonic() + _EXISTENCE_RENDER_TIMEOUT
        while time.monotonic() < render_deadline:
            _nudge_children_render(client, parent_path, context_id=context_id)
            time.sleep(0.4)
            existing = directory_folder_id(client, wanted, context_id=context_id,
                                           page=PAGE_MATERIAL_CENTER)
            if existing:
                return existing

    # 唯一性守卫：**命中不是恰好 1 个就一次都不点**（与 `folder_expression` 同一风格）。
    # 页面顶部还有搜索框等控件，放宽条件会点到错的按钮。
    guard = client.evaluate(_FIND_CREATE_FOLDER_EXPRESSION, context_id=context_id)
    if not isinstance(guard, dict) or guard.get('ok') is not True:
        # 原码逐字照抄（create_folder_missing / create_folder_ambiguous /
        # create_folder_button_may_submit）；没给原码 = 读不出来，写 reason_missing。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'ensure_child_directory', PAGE_MATERIAL_CENTER,
            '/'.join(wanted), (guard or {}).get('reason') if isinstance(guard, dict) else None))

    # ⚠️ **必须先站到父目录上**：「新建文件夹」是建在**当前选中目录**下的。
    # `parent_path` 为空表示父目录就是「全部图片」那一层——而素材中心页的树里
    # **没有**这个节点（见 `open_root_directory`），所以不能走 `open_directory`。
    if parent_path:
        open_directory(client, parent_path, context_id=context_id, page=PAGE_MATERIAL_CENTER)
    else:
        open_root_directory(client, context_id=context_id, page=PAGE_MATERIAL_CENTER)
    expression = _CREATE_FOLDER_EXPRESSION.replace(
        'FOLDER_NAME', json.dumps(str(name), ensure_ascii=False), 1)
    created = client.evaluate(expression, context_id=context_id, timeout=30.0)
    if not isinstance(created, dict) or created.get('ok') is not True:
        # 同上：原码照抄（create_folder_missing / create_folder_input_missing /
        # create_folder_confirm_missing），不合并成一个模糊中文。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'ensure_child_directory', PAGE_MATERIAL_CENTER,
            '/'.join(wanted), (created or {}).get('reason') if isinstance(created, dict) else None))

    # 回读：等目录出现在树里并带上 folderId。**等不到就失败**——不回退到按名字猜。
    deadline = time.monotonic() + max(1.0, timeout)
    last_nudge = 0.0
    while True:
        folder_id = directory_folder_id(client, wanted, context_id=context_id,
                                        page=PAGE_MATERIAL_CENTER)
        if folder_id:
            return folder_id
        if time.monotonic() >= deadline:
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'ensure_child_directory', PAGE_MATERIAL_CENTER,
                '/'.join(wanted), REASON_MISSING,
                action='手动重载素材中心该标签页后重试（该自动建目录步骤尚未真机验证）'))
        # 真机实证（2026-10-07，`tmp/probe-expand-node.py`）：素材中心的树节点会停在
        # 「aria-expanded=true 但子节点根本没渲染」的状态——刚建好的子目录不在 DOM 里，
        # 回读永远落空；点一下父节点的开关才会把子节点拉进 DOM。
        # 只在「子节点一个都没渲染」时点（渲染了就等数据出现，再点会把节点折回去），
        # 且两次点击至少隔 2 秒，避免把正在加载的节点又折回去。
        if parent_path and time.monotonic() - last_nudge >= 2.0:
            last_nudge = time.monotonic()
            _nudge_children_render(client, parent_path, context_id=context_id)
        time.sleep(0.25)


def _nudge_children_render(client, parent_path, *, context_id):
    """点一下父节点的开关，把**没渲染出来的子节点**拉进 DOM（真机懒加载实证）。

    这是**助推**，不是判决：任何一步读不准（父节点缺失/不唯一/开关不唯一/形状不符）
    都不动页面、不抛错，交给 `ensure_child_directory` 的回读轮询如实超时。
    """
    expression = _CHILDREN_NUDGE_EXPRESSION.replace(
        'PARENT_PATH', json.dumps([str(p) for p in parent_path], ensure_ascii=False), 1)
    try:
        client.evaluate(expression, context_id=context_id)
    except Exception:  # noqa: BLE001 - 助推失败不该掩盖回读本身的判决
        pass


#: 等「下一层子目录渲染出来」的总时长（秒）。
#: 真机实证（2026-10-10）：素材中心页点开父节点后会停在
#: ``aria-expanded=true`` 而子节点一个都没挂载的状态，助推一次约 1 秒内出现。
_CHILD_RENDER_TIMEOUT = 5.0

#: 两次助推之间的最小间隔（秒）。助推只在「子节点一个都没渲染」时才真点开关。
_CHILD_RENDER_NUDGE_INTERVAL = 0.8


def _wait_for_child_render(client, path, *, context_id, timeout=None):
    """确保 `path` 这一层已经渲染出来；渲染不出来就**如实返回** ``False``。

    ## 为什么必须等（2026-10-10 真机实证）

    素材中心页的树是虚拟列表：点开父节点后，DOM 会停在
    ``aria-expanded="true"`` 而**子节点一个都没挂载**的状态（真机实测持续 3 秒以上）。
    这时 :func:`folder_expression` 按路径找不到节点、原码是 ``directory_missing``，
    于是 :func:`open_directory` 把「没渲染」判成「不存在」，报「请去素材中心建好该目录」——
    而那个目录其实**一直在**：平台自己的 ``dir.query`` 对该商品目录返回
    ``childrenSize=3``，三个子目录 id 与上传账本里的 ``folder_id`` 逐字相同。
    照那句提示去手工建，只会建出**重复目录**（E-293 早警告过「读不到 ≠ 不存在」）。

    助推（:func:`_nudge_children_render`）点一下父节点的开关即可让子节点挂载回来。

    这里是**助推 + 有界等待**，不是兜底：

    * 已经渲染 → 立刻返回 ``True``（一次都不点）；
    * 等不到 → 返回 ``False``，调用方照原样如实报 ``directory_missing``（不猜、不建目录）。
    """

    wanted = [str(part) for part in path]
    if not wanted:
        return True
    if timeout is None:
        timeout = _CHILD_RENDER_TIMEOUT
    deadline = time.monotonic() + max(0.0, timeout)
    last_nudge = None
    while True:
        state = read_directory(client, context_id=context_id)
        if any(list(known)[-len(wanted):] == wanted for known in (state.get('paths') or [])):
            return True
        now = time.monotonic()
        if now >= deadline:
            return False
        if last_nudge is None or now - last_nudge >= _CHILD_RENDER_NUDGE_INTERVAL:
            last_nudge = now
            _nudge_children_render(client, wanted[:-1], context_id=context_id)
        time.sleep(0.25)


#: 助推表达式：父节点的子目录**一个都没渲染**时点一下它的开关。
#: 路径比对用 `li.next-tree-node` 的 name 祖先链（与真机/合成页同形）。
_CHILDREN_NUDGE_EXPRESSION = r"""
(() => {
  const PARENT = PARENT_PATH;
  const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
  const lis=Array.from(document.querySelectorAll('li.next-tree-node')).filter(visible);
  if(!lis.length)return {ok:false,reason:'tree_missing'};
  const chain=el=>{
    const names=[];let n=el;
    while(n){names.unshift(n.getAttribute('name'));
      n=n.parentElement?n.parentElement.closest('li.next-tree-node'):null;}
    return names;
  };
  const hits=lis.filter(e=>JSON.stringify(chain(e))===JSON.stringify(PARENT));
  if(hits.length!==1)return {ok:false,reason:hits.length?'parent_ambiguous':'parent_missing'};
  const node=hits[0];
  // 已渲染的子节点：只要有一个就说明懒加载完成，**不能再点**（再点会折回去）。
  const rendered=Array.from(node.querySelectorAll('li.next-tree-node')).filter(visible);
  if(rendered.length)return {ok:true,nudged:false,rendered:rendered.length};
  const switchers=Array.from(node.querySelectorAll('.next-tree-switcher'))
    .filter(e=>e.closest('li.next-tree-node')===node&&visible(e));
  if(switchers.length!==1)return {ok:false,reason:'switcher_not_unique'};
  switchers[0].click();
  return {ok:true,nudged:true};
})()
"""


#: 定位「新建文件夹」控件。**要求唯一 + 可见 + 未禁用**——
#: 命中不唯一就一次都不点（与 `folder_expression` 同一风格）。
_FIND_CREATE_FOLDER_EXPRESSION = r"""
(() => {
  const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
  const buttons=Array.from(document.querySelectorAll('button')).filter(visible)
    .filter(e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true')
    .filter(e=>(e.textContent||'').replace(/\s+/g,'')==='新建文件夹');
  if(buttons.length!==1)return {ok:false,reason:buttons.length?'create_folder_ambiguous':'create_folder_missing'};
  const form=buttons[0].form;
  if(form&&buttons[0].type!=='button')return {ok:false,reason:'create_folder_button_may_submit'};
  return {ok:true};
})()
"""


#: 点「新建文件夹」→ 在出现的输入框里填 `FOLDER_NAME` → 点确认。
#:
#: ⚠️ 输入框与确认按钮是**点完之后才渲染**的，所以必须分步、并在每步之后
#: 重新查询 DOM（一次表达式里拿旧引用会落空）。这里用 `await` + 轮询等它们出现。
#:
#: 真机实测（2026-10-07，`tmp/probe-create-folder-dialog.py`）与合成夹具有三点不同，
#: 每条都对应下面的一处逻辑，改之前先看这段：
#: ① 弹层（.next-dialog）里有**两个**可写文本框——「所属上级文件夹」的 select
#:    触发框（在 .next-select 里）和「新文件夹名称」输入框；必须排除前者；
#: ② 弹层外还常驻 3 个可写文本框（帮助搜索、图片搜索、分页跳页），所以
#:    「全页恰好一个」的兜底在真机上永远不会命中，也不该命中；
#: ③ 「确定」在 next-dialog-footer 里，是 next-dialog-body 的**兄弟**——
#:    用最近的弹层祖先当作用域会找不到它，必须取**最外层**弹层容器。
_CREATE_FOLDER_EXPRESSION = r"""
(async () => {
  const NAME = FOLDER_NAME;
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
  const text=e=>(e.textContent||'').replace(/\s+/g,'').trim();
  const DIALOG_SEL='[class*="dialog"],[class*="modal"],[class*="Dialog"]';

  const pick=(sel)=>Array.from(document.querySelectorAll(sel)).filter(visible);
  const button=()=>{
    const hits=pick('button').filter(e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true')
      .filter(e=>text(e)==='新建文件夹');
    return hits.length===1?hits[0]:null;
  };
  const opener=button();
  if(!opener)return {ok:false,reason:'create_folder_missing'};
  opener.click();

  // 等名称输入框出现：弹层内 ∧ 不在 .next-select 里（排除「所属上级文件夹」
  // 的触发搜索框）∧ 唯一。多于一个就继续等/放弃——绝不猜是哪一个。
  //
  // ⚠️ **没有"全页唯一"兜底**（2026-10-07 真机教训）：真机页面常驻多个可写文本框
  // （帮助搜索/图片搜索/分页跳页），弹层没及时打开时"恰好一个"可能命中其中的
  // 搜索框——把目录名输进搜索框比报错难发现得多。弹层没开就如实报
  // `create_folder_input_missing`。合成夹具的输入框也在 .next-dialog 里，
  // 走的就是弹层路径，不依赖任何全页兜底。
  let input=null;
  for(let i=0;i<40&&!input;i++){
    await sleep(150);
    const boxes=pick('input[type="text"],input:not([type])')
      .filter(e=>!e.disabled&&e.getAttribute('readonly')===null&&e.getAttribute('aria-disabled')!=='true');
    const scoped=boxes.filter(e=>e.closest(DIALOG_SEL)&&!e.closest('.next-select'));
    if(scoped.length===1)input=scoped[0];
  }
  if(!input)return {ok:false,reason:'create_folder_input_missing'};
  input.focus();
  // 平台的 next-* 组件是 React 受控输入框：直接赋 value 框架 state 拿不到，
  // 「确定」会按"名称为空"静默不建。必须用原型上的 value setter 再派事件。
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(input,NAME);
  input.dispatchEvent(new Event('input',{bubbles:true}));
  input.dispatchEvent(new Event('change',{bubbles:true}));

  // 点确认：只在弹层里找「确定」，避免点到页面上别的确认按钮。
  // 弹层容器取**最外层**匹配——「确定」在 footer，是输入框所在 body 的兄弟。
  // 轮询时长与输入框一致：真机弹层的 footer 可能比输入框渲染得晚。
  let host=null;
  for(let n=input.parentElement;n;n=n.parentElement){
    if(n.matches&&n.matches(DIALOG_SEL))host=n;
  }
  host=host||document;
  let confirm=null;
  for(let i=0;i<40&&!confirm;i++){
    await sleep(150);
    const hits=pick('button').filter(e=>host.contains(e))
      .filter(e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true')
      .filter(e=>['确定','确认','保存','新建'].indexOf(text(e))>=0);
    if(hits.length===1)confirm=hits[0];
  }
  if(!confirm)return {ok:false,reason:'create_folder_confirm_missing'};
  confirm.click();
  await sleep(400);
  return {ok:true};
})()
"""


#: 选图器当前目录列表的瞬态：可见卡片数、空占位数、骨架占位数、卡片签名。
#: 空占位判据（2026-10-07/08 两次真机探针）：空目录渲染完成后列表区出现可见的
#: ``PicList_..._main-emptyarea`` 占位元素——**它没有任何文本**（图标型占位），
#: 所以不能按「暂无」文案认它；而发布表单自己的空态控件（主图槽位「+」按钮，
#: class 含 image-empty）也匹配 class 选择器，在表单与图库同文档的页面里会把
#: 「列表正在清空重载」误判成「空目录终态」。计数规则：class 含 PicList 的
#: empty 元素（真机选图器），或带「暂无」文案的 empty 元素（夹具/文案型占位）。
#:
#: 骨架占位判据（2026-10-08 run20 真机探针）：目录内容**已存在但尚未渲染**时，
#: 列表区为每个待渲染项摆一个可见的 ``<i class="PicList_i_dom__…">`` 占位图标
#: （卡片水合后它仍留在卡片底下，所以**不能拿它当骨架**；判据是
#: 「骨架 > 0 且卡片 == 0」）。真机三种状态对照::
#:
#:     加载中/拉取悬挂：cards=0  empty=1  skel=10   ← **不是终态**
#:     水合完成：       cards=10 empty=0  skel=10
#:     真空目录：       cards=0  empty=1  skel=0
_LISTING_STATE_EXPRESSION = r"""
(() => {
  const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
  const cards=Array.from(document.querySelectorAll('[class*="PicList_pic_background"]')).filter(visible);
  const sig=cards.map(c=>{const i=c.querySelector('img');return (i&&i.getAttribute('src')||'').slice(-48);}).join('|');
  const empty=Array.from(document.querySelectorAll('[class*="empty"],[class*="Empty"],.next-empty'))
    .filter(e=>visible(e)&&(String(e.className).indexOf('PicList')>=0
      ||(e.textContent||'').indexOf('暂无')>=0)).length;
  const skel=cards.length?0:Array.from(document.querySelectorAll('[class*="PicList_i_dom"]')).filter(visible).length;
  return {cards:cards.length,empty:empty,skel:skel,sig:sig};
})()
"""


def _listing_signature(state):
    """目录列表签名的**唯一**构造处：``(卡片数, 空占位数, 骨架数, 卡片签名)``。

    ``wait_listing_settled`` 的「内容变过一次」判据拿它跟点击前签名逐字比较，
    两处构造一旦 drift（一处加字段另一处没加），逐字比较就**永不相等**——
    「变过」会在第一帧旧内容上直接成立，把上一目录的卡片当成新目录的
    （2026-10-08 run21：加 skel 字段时只改了采样处，点击前签名还是旧三元组，
    变化判据失效，按 ID 选主图报 missing）。所以签名只许从这里出。
    """
    return (state['cards'], state.get('empty') or 0, state.get('skel') or 0,
            state.get('sig') or '')


def _receipt_targets_ready(client, receipts, *, context_id):
    """只读当前卡片身份；目标已到位，无需再观察一次清空/重载过程。"""
    from .page import MEDIA_IMAGE_CARD, PageError, _images_match
    expression = r'''(() => {
      const selector = SELECTOR;
      const visible = el => {
        if (el.closest('[hidden],[aria-hidden="true"],[class*="UploadPanel"]')) return false;
        const r=el.getBoundingClientRect(), s=getComputedStyle(el);
        return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';
      };
      return Array.from(document.querySelectorAll(selector)).filter(visible).map(card=>{
        const checkbox=card.querySelector('input[type="checkbox"]'), img=card.querySelector('img[src]');
        let id=checkbox ? String(checkbox.value||'') : '';
        if(!/^\d{10,}$/.test(id)) {
          id=''; let node=checkbox && checkbox.parentElement;
          while(node && node!==document.body) {
            if(/^\d{10,}$/.test(node.id||'')){id=node.id;break;} node=node.parentElement;
          }
        }
        return {picture_id:id,url:img ? img.src : ''};
      });
    })()'''.replace('SELECTOR',json.dumps(MEDIA_IMAGE_CARD),1)
    cards=client.evaluate(expression,context_id=context_id)
    if not isinstance(cards,list):
        raise PageError('目标图片就绪检查没有返回当前卡片清单')
    for receipt in receipts:
        url=str(receipt.get('url') or '')
        picture_id=str(receipt.get('picture_id') or '')
        if not url:
            return False
        matches=[card for card in cards if
            (str(card.get('picture_id') or '')==picture_id if picture_id else _images_match(str(card.get('url') or ''),url))]
        if len(matches)!=1 or not _images_match(str(matches[0].get('url') or ''),url):
            return False
    return bool(receipts)


def wait_listing_settled(client, *, context_id, timeout=6.0, change_from=None, expected_images=()):
    """等选图器目录列表渲染到**终态**：有卡片或空占位出现，且签名稳定。

    ## 为什么 busy 等待不够（2026-10-07 真机实证，探针 12/13）

    选图器切目录**没有 aria-busy**：点完目录节点的瞬间旧卡片先被清空，
    新数据异步回来再渲染，全程 ``busy=False``。只等 busy 就会读到
    「清空后、渲染前」的瞬时空白，把有图目录误判成空目录——真机症状：
    25 张已归档素材平台侧全在（console.file.query 证实），验证却连报
    ``MEDIA_IMAGE_MISSING``（run7~run10 四次）。

    终态判据（探针 13 实测，两个方向都 ≤221ms 到位）：

    * 可见卡片数 > 0；
    * 或空占位（``[class*="empty"]`` 可见）出现——只有查询返回空它才渲染。

    两者都要求签名两次采样一致（间隔 300ms），防止读到半渲染帧。
    超时不返回「空目录」——那是**读不出来**，如实抛 ``reason_missing``。

    ## 「空占位」不等于终态：骨架占位卡住的第三种状态（2026-10-08 run20 真机）

    选图器为每个待渲染项摆一个可见的 ``<i class="PicList_i_dom__…">`` 占位图标；
    拉取悬挂时它**和空占位一起出现**（cards=0 empty=1 skel=N），按旧判据会被
    当成「空目录终态」——run17/run20 两次按 ID 选图 missing 都是这么来的：
    目录里明明有 N 张（点别的目录再点回来立刻水合），流水线却按"空目录"
    放行、随后选图报 missing。所以空占位终态要求 **skel == 0**；
    skel > 0 只是「内容在、渲染没完」——瞬态会继续等，悬挂会等到超时抛错，
    由调用方（``open_directory``/``refresh_gallery``）做「点走再点回」重拉。

    :param change_from: **点击前的列表签名**（``_listing_signature`` 的四元组）。
        给了它就要求「签名先变过一次」才算终态——树选中是点击即变的，
        列表渲染却滞后（后台标签页更明显）：没有这个判据，两次采样可能
        都落在「旧目录卡片还没清」的窗口里，把上一目录的内容当成新目录的
        （run12 按 ID 选主图 4 报 missing 就是这么来的）。
        同目录重刷（内容合法地不变）传 ``None``。

    ## 两个目录装着**完全相同**的图片时怎么办

    签名逐字相同，「变过一次」永远等不到。两条出路：

    * 清空窗口：真机点目录后列表**先清空再渲染**（≤221ms），所以变化判据
      阶段用 80ms 密采样，抓得到这帧空白；
    * busy 作证：若等待期间观察到过 ``busy=True``（``reloaded``），说明
      确实重载过一轮，内容相同也接受——busy 只在真加载时出现，不会被
      「旧卡片赖着不走」误触发（run12 全程无 busy）。
    """
    from .page import PageError, read_media_gallery_state
    deadline = time.monotonic() + max(0.5, timeout)
    last = None
    changed = change_from is None
    reloaded = False
    while True:
        state = client.evaluate(_LISTING_STATE_EXPRESSION, context_id=context_id)
        if not isinstance(state, dict) or type(state.get('cards')) is not int:
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'wait_listing_settled', PAGE_PICKER,
                '当前目录列表', REASON_MISSING,
                action='关掉选图器弹层重新打开，让它重读一次当前目录'))
        busy = read_media_gallery_state(client, context_id=context_id,
                                        stage=STAGE_UPLOAD_IMAGES)['busy']
        if busy:
            reloaded = True
        # 图片 ID/URL 是实际目标，比“列表相对旧签名变过”更直接；没有目标时保留完整目录扫描判据。
        if expected_images and not busy and _receipt_targets_ready(client, expected_images, context_id=context_id):
            return state
        sig = _listing_signature(state)
        if not changed and sig != change_from:
            changed = True
        terminal = (changed or reloaded) and not busy \
            and (state['cards'] > 0 or ((state.get('empty') or 0) > 0 and not (state.get('skel') or 0)))
        if terminal and sig == last:
            return state
        last = sig
        if time.monotonic() >= deadline:
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'wait_listing_settled', PAGE_PICKER,
                '当前目录列表', REASON_MISSING,
                action='手动重载该标签页后重试（目录内容在 {} 秒内没有完成加载）'.format(timeout)))
        time.sleep(0.3 if (changed or reloaded) else 0.08)


def retrigger_listing(client, path, *, context_id):
    """目录列表悬挂时的强制重拉：点一个**别的**目录，再点回目标目录。

    选图器对「点已选中的当前节点」不重新拉取（2026-10-08 run17/run20 真机），
    骨架占位、假空目录的重拉都只有「点走再点回」有效（探针实测 0.5 秒水合）。
    点击走 ``folder_expression``（``open_directory`` 同款定位：只用
    ``[role=treeitem]``、路径后缀匹配、点 own-label——选图器的树每行是
    ``li[role=treeitem] > div.next-tree-node`` 双层节点，按尾段点名会命中两个
    而恒判歧义，run23 的恢复就是这么静默失效的）。

    只重拉一次，不循环重试；任何一步不成（读不出树、没有别的目录可点、
    点击未生效、重拉后仍不到终态）都返回 ``False``，由调用方如实抛原错误。
    """
    try:
        state = read_directory(client, context_id=context_id)
    except Exception:  # noqa: BLE001 - 读不出树按恢复失败处理
        return False
    # 候选排除目标目录和**当前选中**目录：away 若就是已选中节点，
    # folder_expression 会按 already 跳过不点，发不出重新拉取。
    current = list(state.get('path') or [])
    candidates = [list(p) for p in (state.get('paths') or [])
                  if p and list(p) not in (list(path), current)]
    if not candidates:
        return False
    # 优先同级兄弟目录（叶子，点击必触发重新拉取）；没有就拿任意别的目录。
    parent = list(path)[:-1]
    away = next((p for p in candidates if p[:-1] == parent), candidates[0])
    for target in (away, list(path)):
        # 点击前签名：等待终态时用它判定「内容真的换过」，防止把上一目录的
        # 卡片当成新目录的（与 open_directory 慢路同一判据）。
        before = None
        try:
            pre = client.evaluate(_LISTING_STATE_EXPRESSION, context_id=context_id)
            if isinstance(pre, dict) and type(pre.get('cards')) is int:
                before = _listing_signature(pre)
        except Exception:  # noqa: BLE001 - 读不出签名就退回不带变化判据的终态等待
            before = None
        result = client.evaluate(folder_expression(target, action='open'),
                                 context_id=context_id)
        if not isinstance(result, dict) or result.get('ok') is not True \
                or not result.get('supported'):
            return False
        try:
            wait_listing_settled(client, context_id=context_id, change_from=before)
        except Exception:  # noqa: BLE001 - 重拉没到位按恢复失败处理，原错误由调用方如实抛
            return False
    return True


def open_directory(client, path, *, context_id, timeout=5.0, expand=False, page=PAGE_PICKER, expected_images=()):
    """按完整路径逐层进入；不能用全树同名的第一个子目录替代。"""
    from .page import PageError, wait_for_media_gallery_ready
    target_options = {'expected_images': expected_images} if expected_images else {}
    state = read_directory(client, context_id=context_id)
    # 「全部图片」根节点是**虚拟化渲染**的：树滚动/折叠后它可能不在 DOM 里
    # （2026-10-08 真机：选图器停在商品子目录时 paths 直接从商品目录开始，
    # root_prefix==[]）。调用方传来的路径带这一段而当前树没有它时，去掉再进；
    # 树一个节点都没渲染时不猜，保持原路径，让后面如实报 directory_missing。
    if page == PAGE_PICKER and path and list(path)[0] == ALL_IMAGES_NODE:
        if root_prefix(state) == []:
            path = list(path)[1:]
    # 表达式允许路径后缀，但 Python 侧也必须用同一个完整路径比较。
    # 否则 ['商品','主图'] 已经选中时仍会按 ['商品']→['商品','主图'] 重走。
    if path:
        matches = [list(known) for known in state.get('paths', [])
                   if len(known) >= len(path) and list(known[-len(path):]) == list(path)]
        if len(matches) > 1:
            raise PageError(_media_failure(STAGE_UPLOAD_IMAGES, 'open_directory', page,
                                          '/'.join(path), 'directory_ambiguous'))
        if len(matches) == 1:
            path = matches[0]
    if state.get('path') == list(path) and not expand:
        wait_for_media_gallery_ready(client, context_id=context_id, timeout=timeout)
        if read_directory(client, context_id=context_id).get('path') != list(path):
            # 「等图加载期间目录变了」：判据是**两次读树的结果不一致**，不是某个原码，
            # 所以写 reason_missing（判决「读不出来」），并把目标写成该完整路径。
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'open_directory', page, '/'.join(path),
                REASON_MISSING,
                action='关掉选图器弹层重新打开，让它重读一次当前目录'))
        if page == PAGE_PICKER:
            # 快速路也可能赶上上一次点击的清空-重载间隙，同样等终态。
            try:
                wait_listing_settled(client, context_id=context_id, **target_options)
            except PageError:
                # 等不到终态：点走再点回强制重拉一次（与慢路同一恢复）。
                if not retrigger_listing(client, list(path), context_id=context_id):
                    raise
        return list(path)
    # 目标已渲染时一次直达；只有懒加载子项才逐层展开。
    sizes = [len(path)] if list(path) in state.get('paths', []) else range(1, len(path) + 1)
    # 点击前的列表签名：树选中是点击即变的，列表渲染却滞后——等终态时用它
    # 判定「内容真的换过」，防止把上一目录的卡片当成新目录的（run12 踩过）。
    # 只在**确实要切目录**时才带这个判据：expand 展开一个已选中的折叠父级时，
    # 当前目录没变、列表合法地保持不变，带 change_from 会永远等不到变化。
    listing_before = None
    if path and page == PAGE_PICKER and state.get('path') != list(path):
        try:
            pre = client.evaluate(_LISTING_STATE_EXPRESSION, context_id=context_id)
            if isinstance(pre, dict) and type(pre.get('cards')) is int:
                listing_before = _listing_signature(pre)
        except Exception:  # noqa: BLE001 - 读不出签名就退回不带变化判据的终态等待
            listing_before = None
    for size in sizes:
        prefix = list(path[:size])
        # 素材中心页把「已展开」父节点的子项从 DOM 上卸载（真机实证 2026-10-10）：
        # 子目录**存在**却读不到。进下一层之前先助推并有界等待，等不到再照原样如实报
        # directory_missing——否则会把「没渲染」判成「不存在」，把人引去手建重复目录。
        # 选图器不点：那棵树的子目录会正常渲染（E-291/E-293），多点一下只会把节点折回去。
        if page == PAGE_MATERIAL_CENTER and len(prefix) > 1:
            _wait_for_child_render(client, prefix, context_id=context_id)
        result = client.evaluate(folder_expression(prefix, action='open'), context_id=context_id)
        if not isinstance(result, dict) or result.get('ok') is not True or not result.get('supported'):
            if not isinstance(result, dict) or result.get('reason'):
                # 判据点给了原码 → 逐字照抄（directory_missing / directory_ambiguous /
                # directory_disabled / directory_expander_not_unique / …）。
                reason = (result or {}).get('reason')
            else:
                # 判据点明确说了 supported=false → 判决是「页面没有树」，
                # 不是「读不出来」：这两个判决**不许合并成一句**。
                reason = REASON_TREE_NOT_SUPPORTED
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'open_directory', page, '/'.join(prefix), reason))
        deadline = time.monotonic() + timeout
        while True:
            state = read_directory(client, context_id=context_id)
            if state.get('path') == result['path']:
                if page != PAGE_PICKER:
                    wait_for_media_gallery_ready(client, context_id=context_id,
                        timeout=max(0.0, deadline - time.monotonic()))
                    state = read_directory(client, context_id=context_id)
                if state.get('path') == result['path']:
                    break
            if time.monotonic() >= deadline:
                # 同上：判据是回读对不上，不是某个原码。
                raise PageError(_media_failure(
                    STAGE_UPLOAD_IMAGES, 'open_directory', page, '/'.join(prefix),
                    REASON_MISSING,
                    action='关掉选图器弹层重新打开，让它重读一次当前目录'))
            time.sleep(0.1)
    if path and page == PAGE_PICKER:
        # ⚠️ 切目录没有 aria-busy（2026-10-07 真机实证）：点击后旧卡片先清空、
        # 新数据异步渲染，busy 等待会立即放行，读到「清空后、渲染前」的瞬时空白，
        # 把有图目录误判成空目录（run7~run10 的 MEDIA_IMAGE_MISSING 就是这么来的）。
        # 所以逐级到位之后，必须再等列表到终态（有卡片或空占位且签名稳定），
        # 且签名要相对点击前变过一次（树选中即时变、列表滞后变）。
        try:
            wait_listing_settled(client, context_id=context_id, change_from=listing_before, **target_options)
        except PageError:
            # 等不到终态（骨架/拉取悬挂，run17/run20 真机）：点走再点回强制
            # 重拉一次；恢复不了就把原错误如实抛出。
            if not retrigger_listing(client, list(path), context_id=context_id):
                raise
    return state['path'] if path else []


def root_prefix(state):
    """「全部图片」这一层在**当前页面**的树里对应的路径前缀。

    ## 两个页面不一样（2026-10-07 真机实证）

    * **选图器**（发布页弹层）：树里有显式节点 ``全部图片``（folderId=0）→ 前缀
      ``['全部图片']``。
    * **素材中心页**（``qn.taobao.com/.../sucai-tu``）：树里**没有**这个节点——
      顶层节点的 path 只有一段（``['ID-1074582642352']``），**树根就是那一层** →
      前缀 ``[]``。同一个容器，两种呈现。

    实测对照（同一台机器、同一个商品）::

        directory_folder_id(['ID-1074582642352'])              -> 1114918855143810805  ✅
        directory_folder_id(['全部图片', 'ID-1074582642352'])   -> None                  ❌

    所以 `ensure_cloud_folders` 原来写死 ``全部图片 + [商品名]`` 的写法在素材中心页
    **必然失败**（它会报"找不到「全部图片」根目录"）——那条路此前零调用方，
    所以一直没暴露。

    :return: 路径前缀；``state`` 里一个节点都没有（页面还没渲染好）时返回 ``None``
        —— 读不到就**不猜**，由调用方如实失败。
    """

    explicit = _all_images_path(state)
    if explicit is not None:
        return explicit
    if state.get('paths'):
        return []
    return None


#: 点「全部图片」面包屑回到树的根那一层。**唯一性 = 恰好 1 项 + 可见 +
#: 文本等于根节点名**；已经激活就一次都不点（与其它点击同一风格）。
_CLICK_ROOT_CRUMB_EXPRESSION = r"""
(() => {
  const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
  const text=e=>(e.textContent||'').replace(/\s+/g,'');
  const items=Array.from(document.querySelectorAll('ul.next-breadcrumb li.next-breadcrumb-item'))
    .filter(visible).filter(li=>text(li).replace(/\/$/,'')===NODE);
  if(items.length!==1)return {ok:false,reason:items.length?'root_crumb_ambiguous':'root_crumb_missing'};
  const target=items[0].querySelector('span.next-breadcrumb-text');
  if(!target||!visible(target))return {ok:false,reason:'root_crumb_text_missing'};
  if(/(^|\s)activated(\s|$)/.test(target.className||''))return {ok:true,already:true};
  target.click();
  return {ok:true,already:false};
})()""".replace('NODE', json.dumps(ALL_IMAGES_NODE, ensure_ascii=False), 1)


def open_root_directory(client, *, context_id, timeout=5.0, page=PAGE_MATERIAL_CENTER):
    """回到「全部图片」这一层，并**确认**已经到位。

    ## 为什么不能只调 `open_directory(client, [])`
    素材中心页的树里没有根节点（见 :func:`root_prefix`），所以"回到根"没有树节点
    可点——`open_directory(client, [])` 在这种页面上是个**空操作**，当前目录仍停在
    原来的子目录上。而「新建文件夹」是建在**当前选中目录**下的，
    于是会静默建到错误的位置。

    实测（2026-10-07 真机）：页面上有面包屑 ``ul.next-breadcrumb``，
    第一项文本就是「全部图片」，点它之后 ``read_directory().path`` 变成 ``[]``。

    **确认不了就抛错**：宁可失败，也不要把目录建到别处。

    :param page: 默认「素材中心」——本函数今天**只被那边的建目录链调用**
        （``protocol_media.ensure_cloud_folders``）；失败文案里的页面要如实。

    :raises PageError: 面包屑不可点、或点完当前目录没有回到根。
    """

    from .page import PageError

    if read_directory(client, context_id=context_id).get('path') == []:
        return []

    result = client.evaluate(_CLICK_ROOT_CRUMB_EXPRESSION, context_id=context_id)
    if not isinstance(result, dict) or result.get('ok') is not True:
        # 原码逐字照抄：root_crumb_missing / root_crumb_ambiguous / root_crumb_text_missing。
        # 动作句显式给：这条链在**另一个标签页**里跑，用户在那边能立刻做的就是重载它
        # ——不走 REASON_ACTIONS 的默认兜底句（那会变成"本步骤无可用操作"）。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'open_root_directory', page, ALL_IMAGES_NODE,
            (result or {}).get('reason') if isinstance(result, dict) else None,
            action='手动重载素材中心该标签页后重试（该自动建目录步骤尚未真机验证）'))

    deadline = time.monotonic() + max(1.0, timeout)
    while True:
        if read_directory(client, context_id=context_id).get('path') == []:
            return []
        if time.monotonic() >= deadline:
            # 点过面包屑但回读没到位：判据是回读对不上，不是某个原码。
            raise PageError(_media_failure(
                STAGE_UPLOAD_IMAGES, 'open_root_directory', page, ALL_IMAGES_NODE,
                REASON_MISSING,
                action='手动重载素材中心该标签页后重试（该自动建目录步骤尚未真机验证）'))
        time.sleep(0.25)


def enter_product_group(client, product_name, group, *, context_id, missing_ok=False):
    """进入商品用途子目录；可选缓存查询用None表示无对应目录，避免重复扫根图库。"""
    from .page import PageError
    state = read_directory(client, context_id=context_id)
    if not state.get('supported'):
        return None if missing_ok else []
    paths = state.get('paths', [])
    # 同一个商品名称只允许一个完整父路径，防止跨商品/同名目录错选。
    parents = [path for path in paths if path and path[-1] == product_name]
    if len(parents) > 1:
        raise PageError('图片空间存在多个同名商品目录：' + product_name)
    if not parents:
        return None if missing_ok else state.get('path', [])
    parent = open_directory(client, parents[0], context_id=context_id, expand=True)
    # 展开后的子项可能异步到达；只等该父级的目标子目录。
    deadline = time.monotonic() + 3
    while True:
        state = read_directory(client, context_id=context_id)
        children = [p for p in state.get('paths', []) if p == parent + [group]]
        if children:
            return open_directory(client, children[0], context_id=context_id)
        if time.monotonic() >= deadline:
            if missing_ok:
                return None
            raise PageError('商品目录中尚未找到子目录：' + '/'.join(parent + [group]))
        time.sleep(0.1)


def product_root_path(client, product_name, *, context_id, page=PAGE_PICKER):
    """取商品目录在树里的**完整路径**；不存在返回 ``None``。

    为什么单独一个函数：既有调用方需要"商品目录路径"时走的是
    `product_directory_tree`（它会**逐个展开所有子目录**）。那对"只想进父目录
    再读子目录 ID"的场景是多余的，而且会在**空子目录**上超时——真机踩过：
    ``图片子目录未完成加载：ID-1074582642352/SKU``（该目录里 0 个文件，
    平台不会给它 `aria-expanded=true`，于是展开等待永远等不到）。

    这里只做"找路径"，不展开、不进入。

    判据分工（与 `directory_folder_id` 同一纪律）：

    * 树里找不到这个商品名 → 返回 ``None``（**不是**失败：调用方据此去建目录）；
    * **同名命中多条** → ``判据=ambiguous``：这是页面渲染/素材本身重复，
      必须由人先消歧，**不猜第一条**；
    * 页面没有树（``supported=False``）→ 也返回 ``None``，
      但调用方（:func:`ensure_product_root`）会把它报成 ``判据=directory_missing``——
      今天的既有语义如此，不在本轮改动。
    """

    from .page import PageError
    state = read_directory(client, context_id=context_id)
    if not state.get('supported'):
        return None
    parents = [path for path in state.get('paths', []) if path and path[-1] == product_name]
    if len(parents) > 1:
        # 同一商品名命中多条：目标写**商品名**（树里确实没有唯一的路径可写），
        # 不写某一条分支的路径——那会让人以为歧义已经解决了。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'product_root_path', page, product_name, 'ambiguous'))
    return list(parents[0]) if parents else None


def open_all_images(client, *, context_id):
    """发布选择器回到全部图片；不把某个用途子目录当作全库。"""

    from .page import PageError
    state = read_directory(client, context_id=context_id)
    if not state.get('supported'):
        return []
    roots = [path for path in state.get('paths', []) if path and path[-1] == ALL_IMAGES_NODE]
    if len(roots) != 1:
        raise PageError('无法唯一定位图片空间的全部图片目录')
    return open_directory(client, roots[0], context_id=context_id)


def refresh_gallery(client, *, context_id, timeout=10.0, settle=1.5):
    """让图库**重新加载当前目录内容**，然后等它稳定。

    ## 为什么必须有这一步（实机踩过）

    协议上传把图直接 POST 进图片空间，**素材中心页面并不知道**。
    实测：上传 33 张全部成功（账本有据、刷新页面后确实在图库里），
    但流水线紧接着按名字查找时，页面上还是**上传前的那份旧列表**，
    于是报「图片空间里没有找到刚协议上传的素材」——**上传成功却被判失败**。

    做法是**在页面里点一次目录节点**（等价于点一下当前文件夹），
    让素材中心自己去重新拉一次文件列表；不刷新整页、不动发布表单。
    点击走 ``folder_expression(action='click')``（``open_directory`` 同款定位：
    只用 ``[role=treeitem]``、按路径后缀匹配、点 own-label）——旧表达式把
    ``li[role=treeitem]`` 和内层 ``div.next-tree-node`` 一起匹配，每个目录名
    都命中两个节点，在选图器里恒判 ``directory_ambiguous`` 直接放弃
    （2026-10-08 run23 真机：恢复一次都没执行过）。

    **失败一律返回 ``False``，不抛异常**：刷新只是「让查找更可能成功」的优化，
    它自己出问题（iframe 上下文换过、树没渲染、CDP 暂时抽风）不该把整条流水线
    拖死——真找不到图，后面的查找会如实报缺失。
    """

    import time as _time

    try:
        state = read_directory(client, context_id=context_id)
        if not state.get('supported'):
            return False
        paths = state.get('paths') or []
        current = state.get('path') or []
        # 点当前目录自身（有选中态时点击一般不会取消选中，只是重新拉取）
        target = current or (paths[0] if paths else [])
        if not target:
            return False
        result = client.evaluate(folder_expression(target, action='click'),
                                 context_id=context_id)
        if not isinstance(result, dict) or result.get('ok') is not True \
                or not result.get('supported'):
            return False
        _time.sleep(max(0.0, settle))
        from .page import wait_for_media_gallery_ready
        wait_for_media_gallery_ready(client, context_id=context_id, timeout=timeout)
        try:
            # 点当前节点会触发「清空 → 重新拉取」，busy 等不到这个间隙
            # （切目录没有 aria-busy，2026-10-07 探针实证）；必须等列表到终态，
            # 否则紧随其后的查找会读到瞬时空白。
            wait_listing_settled(client, context_id=context_id)
        except Exception:  # noqa: BLE001 - 等不到终态就点走再点回重拉一次；不成按刷新失败处理
            return retrigger_listing(client, target, context_id=context_id)
        return True
    except Exception:  # noqa: BLE001 - 刷新只是优化，任何失败都不该拖垮流水线
        return False


def pick_media_by_id_with_requery(client, picture_ids, *, context_id,
                                  select=True, wait=10.0, stage=None, expected_urls=None):
    """按 ID 选图；缺图时**点走再点回重拉一次当前目录**再选，仍缺就如实抛出。

    选图器会把**有图的目录**渲染成空占位或骨架占位并一直卡住（run15 假空、
    run17/run20 骨架，均为真机），而平台对「点已选中的当前节点」**不重新
    拉取**——所以重拉只有「点走再点回」一种有效形态（``retrigger_listing``），
    对假空、骨架、有卡但目标不在三种情况同样适用（run23/run26 实测）。

    重拉只有**一次**，之后仍按 ID 精确选、仍按 URL 核验身份——这是对平台
    瞬态故障的单次更正，不是兜底掩盖；第二次仍 missing 就原样抛出。
    """
    from .page import MediaImageMissing, pick_media_by_id, FieldMismatchError, _images_match
    expected = dict(expected_urls or {})
    def pick():
        if expected:
            # 写入前先核对整批 ID 与回执 URL，不允许“点到错误图后才报错”。
            found = pick_media_by_id(client, picture_ids, context_id=context_id,
                                     select=False, wait=wait, stage=stage)
            actual = {str(entry.get('pictureId') or ''):str(entry.get('url') or '')
                      for entry in found.get('selected', [])}
            for picture_id in picture_ids:
                if str(picture_id) not in expected or not _images_match(actual.get(str(picture_id), ''), expected[str(picture_id)]):
                    raise FieldMismatchError('图片 ID 对应的图片地址与本批上传回执不一致：' + str(picture_id))
            if not select:
                return found
        return pick_media_by_id(client, picture_ids, context_id=context_id,
                                select=select, wait=0 if expected else wait, stage=stage)
    try:
        return pick()
    except MediaImageMissing:
        current = list(read_directory(client, context_id=context_id).get('path') or [])
        if current:
            retrigger_listing(client, current, context_id=context_id)
        return pick()


def product_directory_tree(client, product_name, *, context_id, max_directories=100, timeout=8.0):
    """读取并展开指定商品的真实子树。目录名不限于主图/SKU/详情页，不依赖本地路径。

    ⚠️ **叶子目录没有子树后代可等**（真机踩过两次：ID-1074582642352/SKU、
    ID-1088046694551/SKU）：`主图`/`SKU`/`详情页` 这类用途目录**不会有子文件夹**，
    平台也不会给空目录 `aria-expanded=true`。所以等待循环有两种完成形态：
    有后代 → 照旧等「expanded=true ∧ 后代渲染 ∧ 签名稳定」；
    没后代 → 「节点在树里 ∧ 签名持续稳定 ≥2 秒」判定为叶子（不看 expanded 取值），
    并记入 `settled_leaves` 防止外层循环对它重复展开。
    """
    from .page import PageError
    if not isinstance(product_name, str) or not product_name.strip():
        raise ValueError('必须提供明确的图片空间商品目录名称')
    state = read_directory(client, context_id=context_id)
    parents = [path for path in state.get('paths', []) if path and path[-1] == product_name]
    if len(parents) > 1:
        raise PageError('图片空间存在多个同名商品目录：' + product_name)
    if not parents:
        return {'root': None, 'directories': [], 'complete': False}
    root = parents[0]
    expanded = set()
    settled_leaves = set()
    while True:
        owned = [entry for entry in state.get('directories', []) if entry['path'][:len(root)] == root]
        paths = [entry['path'] for entry in owned]
        if len(paths) != len({tuple(path) for path in paths}):
            raise PageError('商品图片子树包含重复路径，无法确定文件夹身份')
        if len(paths) > max_directories:
            raise PageError('商品图片子树超过目录数量限制，未把截断结果当成完整文件树')
        # 已判定为叶子的目录**不再展开第二次**：平台不会给空目录 aria-expanded=true
        # （真机实证，见下），不跳过它们会被「重复折叠」守卫误杀。
        pending = next((entry for entry in owned
                        if entry['expanded'] == 'false' and tuple(entry['path']) not in settled_leaves), None)
        if pending is None:
            return {'root': root, 'directories': paths, 'complete': True,
                    'scope': 'rendered_product_tree'}
        target = tuple(pending['path'])
        if target in expanded:
            raise PageError('商品图片目录重复折叠，文件树状态不稳定')
        expanded.add(target)
        result = client.evaluate(folder_expression(target, action='expand'), context_id=context_id)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise PageError('图片子目录无法展开：' + '/'.join(target))
        deadline, previous, stable = time.monotonic() + timeout, None, 0
        settled_since = None
        while True:
            state = read_directory(client, context_id=context_id)
            entry = next((entry for entry in state.get('directories', []) if entry['path'] == list(target)), None)
            signature = state.get('paths')
            descendants = [p for p in signature or [] if len(p) > len(target) and p[:len(target)] == list(target)]
            stable = stable + 1 if signature == previous else 0
            previous = signature
            # 懒加载父项先展开、子项后到达；只读到 aria-expanded=true 还不够。
            if entry and entry['expanded'] == 'true' and descendants and stable >= 2:
                break
            # 叶子目录（没有子文件夹）永远等不到后代，而且平台**不会给它
            # aria-expanded=true**（真机踩过两次：ID-1074582642352/SKU、
            # ID-1088046694551/SKU）。判定「确实没有子目录」= 节点在树里 ∧
            # 整树签名持续稳定 ≥2 秒——不管 expanded 属性停在什么值。
            # 稳定窗口防的是把"子项还在路上"误判成叶子；非空目录的
            # aria-expanded 会翻成 true、签名也会随子项到达而变动，
            # 两个条件都站不住，不会被这条出口误收。
            if entry:
                if settled_since is None:
                    settled_since = time.monotonic()
                elif stable >= 2 and time.monotonic() - settled_since >= 2.0:
                    settled_leaves.add(target)
                    break
            else:
                settled_since = None
            if time.monotonic() >= deadline:
                raise PageError('图片子目录未完成加载：' + '/'.join(target))
            time.sleep(0.1)


def read_directory_files(client, directory, *, context_id, page=PAGE_PICKER):
    """列出指定云端目录的实际图片，不使用本地文件夹推断内容。

    ⚠️ 这里是 :func:`open_directory` **唯一没有 `supported` 守卫**的调用点：
    目录非空就直接把整条路径交给 `open_directory`，由它逐层进。
    页面没有目录树时它产出 ``判据=directory_tree_not_supported``、
    ``目标=`` 那条完整路径（不是「没有受支持的目录树」这种模糊中文）。
    """
    from .page import list_media_images, PageError
    actual = open_directory(client, directory, context_id=context_id,
                            page=page) if directory else []
    result = list_media_images(client, context_id=context_id)
    if not result['complete']:
        # 分页没读完 = **读不出来**，不是「目录里没有图」：判据写 reason_missing，
        # 目标写实际列过的那个目录（不截断路径，括号里点明是分页问题）。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'read_directory_files', page,
            '/'.join(actual) if actual else NO_TARGET, REASON_MISSING,
            action='手动重载该标签页后重试（该目录还有未读取的分页）'))
    after = read_directory(client, context_id=context_id)
    if after.get('path', []) != actual:
        # 读文件的过程中目录自己跳走了：文件归属已不可信，**如实失败**（不重试掩盖）。
        raise PageError(_media_failure(
            STAGE_UPLOAD_IMAGES, 'read_directory_files', page,
            '/'.join(actual) if actual else NO_TARGET, REASON_MISSING,
            action='关掉选图器弹层重新打开，让它重读一次当前目录'))
    return {'path': actual, 'files': result['files'], 'complete': result['complete'],
            'scope': result['scope']}


def find_product_images(client, product_name, names, *, context_id, progress=None,
                        on_located=None, exclude_paths=(), expected_urls=None,
                        allow_conflict=False, extra_paths=()):
    """一次展开商品子树并建立名称→实际目录索引，上传前复用和上传后定位共用。

    :param expected_urls: ``{文件名: 期望的完整 URL}``。**同名多张时用它消歧。**
    :param allow_conflict: ``True`` 时，无法确定身份的同名冲突**不抛错**，
        而是收进返回值的 ``conflicts``，由调用方决定下一步。
        **上传前**必须用 ``True``：那时冲突有可能正是「这张还没传」，
        直接抛错会把「需要上传」误判成「环境坏了」。
    :param extra_paths: **额外要扫的目录全路径**（如
        ``['全部图片', 商品名, '主图']``）。默认空 → 行为与原来完全一致。
        协议路线按用途分目录上传后，素材落在**子目录**里，而商品子树
        （`product_directory_tree`）在子目录**未展开**时可能还没渲染出来；
        把已知的目标目录显式给进来，就不依赖"树恰好已经展开"。

    ## 为什么要 ``expected_urls``（实机踩过）

    图片空间允许同名文件共存（不同目录、或同一目录被传过两次）。原来的判据只有
    「同名 + URL 不同 → 报错」，于是**协议上传回执明明握着那张图的准确 URL**，
    却因为图库里还有一张同名的旧图而整条流水线停下。

    协议路线里的 URL 是**上传回执给的**，属于确定性身份，比名字强。
    所以这里加一条：同名多张时，若**恰好一张**的 URL 与期望值逐字相等，
    就用它；否则（0 张或多张相等）仍按歧义处理——``allow_conflict`` 决定是
    抛错（定位阶段）还是收进 ``conflicts``（上传前）。
    """

    from .page import PageError
    expected = dict(expected_urls or {})
    tree = product_directory_tree(client, product_name, context_id=context_id)
    wanted = set(names)
    receipts, directories = {}, []
    duplicates = {}
    excluded = {tuple(path) for path in exclude_paths}
    # 额外目录排在最前：它们更可能命中（调用方按用途给出的确定路径）。
    # ⚠️ `excluded` 装的是 **tuple**，所以查它也必须用 tuple——
    # 用 `list(path) not in excluded` 会直接抛 `unhashable type: 'list'`
    # （真机踩过：`upload_images` 第一步就挂）。
    scan = [list(path) for path in extra_paths if tuple(path) not in excluded]
    seen_scan = {tuple(path) for path in scan}
    for path in tree['directories']:
        if tuple(path) not in seen_scan:
            scan.append(list(path))
    for directory in scan:
        if tuple(directory) in excluded:
            continue
        if progress:
            progress('进入{}目录，读取图片文件清单：{}'.format(directory[-1], '/'.join(directory)))
        contents = read_directory_files(client, directory, context_id=context_id)
        directories.append(directory)
        for entry in contents['files']:
            name = entry['name']
            if name not in wanted:
                continue
            previous = receipts.get(name)
            if previous is not None and previous['url'] != entry['url']:
                # 同名不同地址：收进 duplicates，最后统一判定（可能能用期望 URL 消歧）
                duplicates.setdefault(name, [previous]).append(dict(entry, folder_path=directory))
                continue
            receipt = dict(entry, folder_path=directory)
            receipts[name] = receipt
            if on_located:
                on_located(name, receipt)
    conflicts = []
    for name, entries in duplicates.items():
        want = expected.get(name, '')
        matching = [entry for entry in entries if want and entry['url'] == want]
        if len(matching) == 1:
            receipt = dict(matching[0])
            receipts[name] = receipt
            if on_located:
                on_located(name, receipt)
            continue
        if allow_conflict:
            # 拿掉按名字写进去的那一条：它的身份未定，不能当作「已经有的素材」
            receipts.pop(name, None)
            conflicts.append({'name': name, 'urls': sorted({entry['url'] for entry in entries})})
            continue
        raise PageError('商品图片子树中存在同名但图片地址不同的素材：' + name)
    missing = [name for name in names if name not in receipts and name not in {item['name'] for item in conflicts}]
    return {'receipts': receipts, 'missing': missing, 'conflicts': conflicts,
            'tree': tree, 'visited': directories}


def locate_uploaded_images(client, names, expected_directory, *, context_id,
                           product_name='', group_names=None, progress=None, on_located=None,
                           expected_urls=None):
    """先查上传目标，再进入本商品的用途子目录；只按本批完整名称定位。

    :param expected_urls: ``{文件名: 期望 URL}``，透传给 :func:`find_product_images`
        用于**同名多张时消歧**（协议上传回执给的 URL 就是确定性身份）。
    """
    from .page import find_media_images, PageError
    names = list(names)
    if group_names is not None:
        if (not isinstance(product_name, str) or not product_name.strip()
                or not isinstance(group_names, Mapping)
                or any(group not in ('主图', 'SKU', '详情页') for group in group_names)
                or any(not isinstance(values, list) for values in group_names.values())):
            raise PageError('上传后用途目录计划无效，未开始查图')
        grouped = [name for values in group_names.values() for name in values]
        if len(grouped) != len(set(grouped)) or set(grouped) != set(names):
            raise PageError('上传后用途目录计划与本批文件清单不一致，未开始查图')
    state = read_directory(client, context_id=context_id)
    current = state.get('path', [])
    candidates = [current]
    if expected_directory and list(expected_directory) not in candidates:
        candidates.append(list(expected_directory))
    missing, receipts, visited, unavailable = list(names), {}, [], []
    def scan(directory, wanted):
        visited.append('/'.join(directory) if directory else '当前图片列表（目录树未识别）')
        result = find_media_images(client, wanted, context_id=context_id)
        for name, receipt in result['receipts'].items():
            receipts[name] = dict(receipt, folder_path=directory)
            if on_located:
                on_located(name, receipts[name])
        return [name for name in names if name not in receipts]
    for directory in candidates:
        if directory:
            open_directory(client, directory, context_id=context_id)
        missing = scan(directory, missing)
        if not missing:
            return receipts
    if product_name and missing:
        lookup = find_product_images(client, product_name, missing, context_id=context_id,
            progress=progress, on_located=on_located, exclude_paths=candidates,
            expected_urls={name: url for name, url in (expected_urls or {}).items()
                           if name in set(missing)})
        if lookup['tree']['root'] is None:
            unavailable.append(product_name)
        visited.extend('/'.join(path) for path in lookup['visited'])
        receipts.update(lookup['receipts'])
        missing = [name for name in names if name not in receipts]
        if not missing:
            return receipts
    detail = '本批上传队列已接收，但还有 {} 张素材未找到：{}；实际查询目录：{}'.format(
        len(missing), '、'.join(missing[:3]), '、'.join(dict.fromkeys(visited)))
    if unavailable:
        detail += '；未能识别或进入的用途目录：' + '、'.join(unavailable)
    raise PageError(detail)


def locate_uploaded_image(client, name, expected_directory, *, context_id):
    """单图调用复用整批目录确认规则。"""
    return locate_uploaded_images(client, [name], expected_directory, context_id=context_id)[name]
