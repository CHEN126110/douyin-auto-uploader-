# Sidecar 拆分工具（lab/sidecar_split）

把 `tauri-app/python-sidecar/app.py` 里的一个业务域**机械搬迁**成 `src/sidecar/` 下的 Blueprint 模块，并证明
「搬迁前后行为一致」。2026-10-18 用它拆出了 `ai_routes` / `title_routes` / `settings_routes` / `pricing_routes`
（运营闭环 `src/sidecar/ops/` 用的是这套工具的早期版本）。2026-10-19 又拆出店铺会话（`shop_accounts` /
`shop_service` / `shop_routes`）和调试浏览器（`debug_browser_service` / `debug_browser_routes`），这一轮给工具加了
「搬成服务类的方法」「链式运行多个切片」「行覆盖」等能力，见下文。2026-10-20 又拆出素材导入（`import_routes`）和小红书批量填表（`xhs_batch_service` / `xhs_batch_routes`），这一轮只补了「带类型注解的状态变量」。同一天又拆出链接采集（`capture_helpers` / `capture_service` / `capture_routes`），这一轮补了 `global` 声明的处理（见下文）。
再拆出淘宝发布（`taobao_helpers` / `taobao_service` / `taobao_routes`），这一轮没有加新能力，用到的是已有的 `decorator_name_map`（`@_with_shop_account_lock` → `@accounts.with_lock`）和 `app_edits`（改 app.py 里读被搬走状态的几处），
并第一次把「只给这个域用的别名」随域一起删掉（见下文「直接依赖服务」）。方案和进度见
[`docs/架构重构方案_2026-10-18.md`](../../docs/架构重构方案_2026-10-18.md)。

## 它做什么、不做什么

- **做**：按 AST 抽出指定的顶层函数 / 常量，函数体、字符串、注释、空行逐字保留；只做规格里声明的改写
  （`app` → `routes` / `current_app`、全局依赖 → 工厂参数、给某些调用插入首参）；自动推导模块需要的 import；
  从 `app.py` 删掉搬走的内容，并清理**因搬迁而不再被使用**的导入（原本就没用的不动）。
- **做**：独立校验——用 `ast.NodeTransformer` 在原 AST 上重放同样的改写，与新模块逐节点比较，
  再检查 `app.py` 其余顶层节点一个都没变。
- **做**：搬成服务类。``class_name`` 非空时 ``funcs`` 变成类的方法（自动补 ``self``），``state_assigns`` 把 app.py 里的状态变量
  （锁、字典）的右值逐字搬进 ``__init__``（带类型注解的 ``x: dict = {}`` 也认，注解原样保留）；紧挨着函数 / 常量上方的注释跟着一起走；函数自己的文档字符串随缩进
  （``verify`` 按 ``inspect.cleandoc`` 归一后比较，只忽略统一缩进的差异）。
- **做**：必须手写的少数几处（端口 dataclass、``__init__``、被拆成两半的函数）用 ``prelude`` / ``init_lines`` /
  ``manual_methods`` / ``app_replacements`` 声明。它们**不参与 AST 重放**，要靠测试和新旧对打守住——越少越好，并在文档里逐个列出。
- **做**：搬迁后原文已经失真的说明文字（例如提到「被某某测试抽取」）用 ``doc_edits``（函数文档字符串，``verify`` 同样重放）、
  ``comment_edits``（模块注释）、``app_edits``（app.py 的收尾，如删掉变成孤立的区块注释）修正，每处断言恰好匹配一次。
- **不做**：不改行为、不重构函数体、不删除代码。逻辑修改请搬完后另做，别和搬迁混在一起。

## 使用流程

需要 Python 3.10+（用了 `sys.stdlib_module_names`、`ast.unparse`），依赖见 `tauri-app/python-sidecar/requirements.txt`。
命令都在仓库根执行；`<tmp>` 换成任意临时目录（**不要放进仓库**）。

```powershell
# 0. （可选）先侦察：各业务域的函数闭包、与别的域共享的函数、引用的顶层状态、哪些测试在读这些函数名。只读，不写任何文件。
python lab/sidecar_split/recon.py tauri-app/python-sidecar/app.py tests

# 1. 备份当前 app.py，作为「搬迁前」基准
Copy-Item tauri-app/python-sidecar/app.py <tmp>/before.py

# 2. 在 lab/sidecar_split/slice_defs.py 里加一个 Slice（可参考已有的 4 个）
#    funcs: 搬进工厂闭包的函数（路由和要用到注入依赖的辅助函数）
#    module_funcs / consts: 搬成模块级的纯函数 / 常量
#    params / aliases: 工厂的关键字参数，以及 `Record = record_model` 这类别名
#    name_map / import_overrides: 额外改写和不能照搬的 import（来自 src.utils 的名字会被拒绝，因为会拖进浏览器库）

# 3. 生成并校验（校验问题必须是 0）
python lab/sidecar_split/run_slice.py <key> <tmp>/before.py <tmp>/stage
python -m pyflakes <tmp>/stage/src/sidecar/<模块>.py        # 不应有未定义名

# 4. 把模块拷进 src/sidecar/，写一个新旧对打场景（scenarios.py），两边各跑一遍后 diff 必须为空
python lab/sidecar_split/slice_diff.py <场景> old <tmp>/before.py       <tmp>/old.json <tmp>/data_old
python lab/sidecar_split/slice_diff.py <场景> new <tmp>/stage/app_<key>.py <tmp>/new.json <tmp>/data_new
diff <tmp>/old.json <tmp>/new.json

# 5. 用 <tmp>/stage/app_<key>.py 覆盖 tauri-app/python-sidecar/app.py，跑全量测试
python -m pytest tests
```

## 服务类形态与链式运行（2026-10-19）

状态（锁、字典）和浏览器能力耦合较深的域，不能只拆成 Blueprint 工厂闭包——``app.py`` 里别的代码还要用它。
这时把状态和逻辑搬成**服务类**，路由留在 Blueprint：

- ``Slice(class_name=..., class_params=[...], init_lines=[...], state_assigns=[('_lock', 'self._lock')], funcs=[...],
  name_map={...}, per_func={...: {'new_name': ...}})``：``funcs`` 变成类的方法；``name_map`` 把旧的全局名改成
  ``self.xxx``（状态、同类方法、注入的端口），``per_func[...]['new_name']`` 给对外有调用方的方法起公开的名字。
- ``insert_after=[(锚点, 文本)]`` 在 app.py 里插入服务的创建代码和旧函数名的别名；``app_replacements`` 把一个函数原位换成别的文本
  （这一轮只用了一次：把 ``_account_change_blocked`` 里「查任务字典」那一半留在 app.py，因为任务字典属于还没拆的上传 / 淘宝域）。
- 多个切片按顺序**链式**运行：``run_slice.py a,b,c <before.py> <stage>``，后一个切片的输入是前一个生成的 app.py，
  每一步校验都必须是 0 个问题，最终结果在 ``<stage>/app_final.py``。店铺会话 + 调试浏览器的 5 个切片见 ``slice_defs_shop_debug.py``。
- 生成的模块里每个替换文本的根名字（``self`` / ``accounts`` / ``service``）都会和原函数里的局部变量比对，重名直接报错，
  不会静默改变含义。

## `global` 声明与模块全局状态（2026-10-20）

采集域里有三个函数靠 `global` 读写模块变量（`_capture_running_task_id`、`_browser_cookie_str` / `_browser_cookie_ts`）。工具现在这样处理：

- `name_map` 里的名字如果在函数里用 `global` 声明并赋值，mover 把读写都改成属性读写（`service.running_task_id = ...` / `self._browser_cookie_ts = ...`），**并把 `global` 语句整句删掉**。
  要求：声明里的名字全部在 `name_map` 里（否则会留下半截 `global`）、语句独占一行。`verify` 同样重放（`_Rewrite.visit_Global`；改名后的目标只有最外层节点继承原来的读写上下文，``service`` 本身仍是读取）。
- **作用域感知**：外层函数声明了 `global`、内层函数没声明就赋值时，Python 里内层赋的是局部变量，改成属性赋值会悄悄改变语义，所以直接报错；内层要有自己的 `global` 声明才放行（`start_capture` 里的嵌套函数就是这样）。
  嵌套函数的形参和改名映射同名也会报错。
- `state_assigns` 的校验只在 `__init__` 顶层语句里找初始化（方法体里对同一属性的后续赋值——原来的 `global X; X = ...`——不算），所以带 `global` 回写的状态也能搬。
- 后台线程里没有 Flask 应用上下文，日志不能走 `current_app`：把 `app` 映射成 `self`（服务类里，服务暴露 `.logger`）或 `service`（路由闭包里），由应用入口把 `app.logger` 注入服务。
- 三个切片的链式顺序是 `capture_helpers`（只有 `module_funcs`，没有工厂也没有类）→ `capture_service`（类）→ `capture_routes`（工厂）；后两个模块里用到的 helpers 函数名经 `import_overrides` 从 `.capture_helpers` 导入。
  `wrap_init=True` 把 `__init__` 的签名一行一个形参（形参多的类用）。
- 搬迁后 `app.py` 里「因搬迁而不再使用」的导入由工具自动清掉；清理依据是整个文件里 `ast.Name` 的使用情况，所以只给搬走的代码用的名字（包括被函数内局部导入遮住的）会一起走。

## 直接依赖服务，随域删别名（2026-10-20）

早先拆出的服务（`ShopAccountGuard` / `ShopSessionService`）在 `app.py` 里留了一批旧函数名的别名，给还没拆的域继续用。后面的域拆出去时：

- 新模块的 `name_map` 把别名直接映射到服务对象的方法（`'_active_shop_account': 'accounts.active_account'`，服务类里是 `self._accounts.active_account`），装饰器用 `decorator_name_map`（`'_with_shop_account_lock': 'accounts.with_lock'`），不再经别名；
- 先 `grep` 每个别名在 `app.py` 里还有谁用；**没人用了的别名**用 `app_edits` 删掉（淘宝发布删了 `_account_change_blocked` / `_resolve_active_shop_browser` / `_activate_shop_profile`），注释里「这些域拆出去时再删」的说明同步改；
- 之前轮次留下的改坏项 / 场景如果引用了被删的别名或被搬走的状态（`sabotage.py` 里的 `_account_change_blocked 恒为 None`、`scen_shop.py` 的 `_taobao_tasks`），要一起改：这一轮前者删掉（等价的守护在 `taobao-routes: 填写前不再检查账户切换互斥`），后者改成 `_taobao_task_dict(ctx)` 两种布局都认；
  `python -c "import sabotage; ..."` 对每条改坏项做一次 `apply_mutation`，能立刻发现「旧文本找不到」。

## 纯页面操作模块：搬类、直接导入 `src.utils`、常量夹在函数之间（2026-10-21）

抖店上传的第一步（`upload_steps`，见 `slice_defs_upload.py`）搬的是 62 个**不碰任何服务状态**的页面操作函数 + 1 个异常类 + 13 个常量。
它没有工厂、没有服务类、**没有任何改写规则**——函数体逐字不动，`verify` 重放的规则是空的，所以这一步只加了三个小开关：

- **类也能搬**：`module_funcs` 里可以放模块级的类（比如自定义异常 `PublishUnconfirmedError`）；`mover.extract` 认 `class` 行，`verify` / `patch_app` 把 `ClassDef` 和函数同样重放 / 清理。类不支持首形参。
- **`allow_src_utils=True`**：允许模块直接 `from src.utils import ...`。默认仍然拒绝（`src.utils` 会拖进浏览器库）——页面操作本来就靠那二十六个浏览器工具函数，注入它们没有意义；其余业务域继续经端口注入。
- **`interleave=True`**：常量按它在 `app.py` 里的原位置夹在函数之间（紧挨着用它的函数），不再全部堆在模块开头；相邻的常量，单行的紧挨着、多行的空一行隔开。

**怎么算出「哪些函数能原样搬」**：`closure_levels.py` 从路由出发求函数闭包，把「直接引用服务状态名的函数」标出来（任务字典 / 锁 / `gui` / 账户别名 / 路径与端口常量 / `__file__` / `Record` / `request` …），
**调用了它们的函数也一并标成服务侧**（传递闭包）；剩下的就是纯的一侧。纯的一侧不会调用服务侧（按定义），所以可以先搬纯的，服务侧留在原地调用它们。
`--state` 要自己列全：漏列一个状态名，依赖它的函数会被误判成纯的。**Git Bash 里要加 `MSYS_NO_PATHCONV=1`**，否则 `--routes /api/upload,...` 会被当成路径悄悄改写，少算几条路由（会得到一个看似正常的更小的闭包）。

```powershell
python lab/sidecar_split/closure_levels.py tauri-app/python-sidecar/app.py --routes /api/upload,/api/protocol,/start --state gui,_upload_tasks,... --json out.json
```

**纯搬迁没有改写规则，AST 重放就只能证明「函数体没变」，够不着的地方靠这三个静态检查补足**（都是只读脚本，参数 `<搬迁前 app.py> <新模块>`）：

1. `pyflakes`：搬后的 `app.py` 与新模块没有新增告警；`undefined name` 数出来的就是 `app.py` 里还要从新模块导入的名字，抄进 `app_import`；
2. `check_import_equiv.py`：新模块里每个导入的名字，必须和搬迁前 `app.py` 模块级对这个名字的绑定一致。**`app.py` 里的 `time` 是 `src.utils` 里的一个类（带计时的 `sleep`），不是标准库的 `time`**（标准库的叫 `system_time`），按名字猜来源会猜错；
3. `check_builtin_shadow.py`：新模块里按内置名解析的全局名，在 `app.py` 里是否被重新绑定过。上传域只有一个：`print`（`app.py` 自己定义了一个包装）。
   新模块里的 `print` 是内置的。等价：`app.py` 一导入就把 `sys.stdout` / `sys.stderr` 换成 `_SafeConsoleStream`，它的 `write` 自己处理 `UnicodeEncodeError`，内置 `print` 因此不会抛——包装函数想防的那件事已经在流这一层防了。
   这对此前所有搬进 `src/sidecar` 的模块同样成立。

还有 `list_leftovers.py <搬迁前> <搬迁后> <起始行> <结束行>`：列出原 `app.py` 这段行号里的非函数顶层语句，标注搬迁后是否还留在 `app.py`——函数搬走后“留在原地”的常量要逐个判断是否该一起走
（这一轮就靠它发现了 `_SUBMIT_RESULT_BUTTONS`：没有任何函数引用它，只有测试在提取，闭包分析看不到，但它和提交那组常量是一伙的）。

## 新旧对打是怎么保证的

`harness.py` 把任意一份 `app.py` 源码当成真正的 `app` 模块加载：源码来自你给的文件，但 `__file__` 伪装成仓库里真实的
`app.py` 路径，所以 `repo_root`、资源路径的推导和线上一致；数据目录固定指向临时目录，不碰用户数据。
`slice_diff.py` 对 old 用 `app.test_client()` 并 monkeypatch `app.py` 的全局（假浏览器、假 LLM），对 new 把
Blueprint 直接注册到干净的 Flask 里并注入同样的假件，然后用**同一套请求**打两边，响应（含落盘文件）必须逐字相同，
时间戳 / 数据目录路径 / ``%Y%m%d_%H%M%S_%f`` 形式的会话 id 会先被抹平。场景要同时覆盖成功分支和每个错误分支。

场景可以声明 ``new_via_app=True``：新版不再把 Blueprint 注册进干净的 Flask，而是加载搬迁后的 ``app.py``（连同它自己的装配代码），
只把注入端口里「外部能力」的字段换成同一套假件——这样连 ``app.py`` 的接线也一起对打了。账户注册表这类本地逻辑尽量用**真实实现**
（隔离数据目录），只假浏览器 / 进程 / 网络。

**场景是否覆盖到位，用行覆盖说话**：``SLICE_COVER=<名字,...> python slice_diff.py ...`` 会在跑完后列出每个函数里从未执行过的语句
（``linecover.py``，基于 ``sys.settrace``）。old 模式填 app.py 的顶层函数名，new 模式填 ``src/sidecar`` 下的模块文件名。
补请求，直到剩下的都是结构上不可达的分支（并在文档里写明为什么不可达）。

## 搬迁时要同时处理的三件事

1. **读 `app.py` 文本 / 抽函数的旧测试**：搬走函数后这些测试会找不到它，或者让「X 不在源码里」这类反向断言空转。
   先 `grep tests/` 找谁在读被搬的内容，把测试指向新模块（`test_custom_material_options.py` 就是这样改的）。
   **别漏了 `taobao-publisher/tests/`**——它是另一套测试（约 1700 条、约 10 分钟），十几个文件按文本读或 `exec` Sidecar 源码；前几轮只跑了根目录 `tests/`，它悄悄坏了 28 条，直到淘宝这一轮才发现。
   现在它们经 `taobao-publisher/scripts/sidecar_source.py`（按函数名用 AST 从 `app.py` 与 `src/sidecar/**` 取源码、枚举路由、取拆分后的前端文本）读取，位置无关；`grep taobao-publisher/` 里的函数名时也要覆盖 `scripts/`。
   **每拆一个域，两套测试都要跑。**
   对「从 app.py 抽函数再 exec」的夹具（`test_shop_platform_api.py` 等），做法是在夹具里直接构造真实的服务对象、
   把旧函数名绑到它的方法上，只有仍留在 app.py 的函数继续按名字抽取。
2. **路由契约**：`tests/test_sidecar_app_smoke.py` 会真实导入 `app.py` 并对比 `tests/fixtures/sidecar_routes.txt`。
   搬迁不应改变这份快照；它改了就说明丢了路由。
3. **新模块的测试**：直接注册 Blueprint，用 `tests/sidecar_test_support.py` 的隔离 Record 模型和临时数据目录，
   参考 `tests/test_sidecar_config_routes.py`、`tests/test_ops_routes.py`。写完用「故意改坏一处看测试会不会红」验证它真的能拦住问题——
   现在有现成的 `sabotage.py`（测试）和 `sabotage_diff.py`（对打脚本本身）。用虚拟时钟的测试要给 `sleep` 次数设上限：
   被测代码把间隔改成 0 时，虚拟时钟不会前进，测试会死循环而不是失败（`tests/debug_browser_fakes.py` 的 `FakeClock` 就是这么做的）。

## 文件说明

| 文件 | 作用 |
|---|---|
| `mover.py` | 基于 AST 位置的文本改写：Name 替换、首参插入、缩进（多行字符串续行不动） |
| `slice_tool.py` | `Slice` 规格、生成模块、改造 `app.py`、独立校验 |
| `slice_defs.py` | 各业务域的规格（已完成的 4 个是范例；对已经拆过的 `app.py` 不能再运行） |
| `run_slice.py` | 命令行入口：生成 + 校验 |
| `recon.py` | 只读侦察：按路由前缀算出各域的函数闭包，区分「独占」和「与其它域共享」，列出引用的顶层状态和在读这些函数的测试文件 |
| `harness.py` | 隔离加载任意一份 `app.py` |
| `slice_diff.py` | 新旧对打运行器（GET / POST / PUT / DELETE） |
| `scenarios.py`、`scen_settings_pricing.py` | 对打场景（AI + 标题、设置 + 定价） |
| `slice_defs_shop_debug.py` | 店铺会话 + 调试浏览器的 5 个切片（服务类形态的范例；必须按 accounts → debug_service → debug_routes → shop_service → shop_routes 链式运行） |
| `scen_shop_debug.py`、`scen_shop.py` | 调试浏览器（140 个请求）与店铺会话（109 个请求）的对打场景，含假标签页 / 假元素 / 假浏览器端口 |
| `slice_defs_import_xhs.py` | 素材导入（`import_folders`，单独运行）与小红书批量填表（`xhs_batch_service` → `xhs_batch_routes`，必须链式运行）的 3 个切片；`xhs_batch_service` 是带类型注解状态变量（`_xhs_tasks: dict = {}`）的范例 |
| `scen_import_xhs.py`、`scen_xhs_batch.py` | 导入（16 个请求）与小红书批量（22 个请求，`new_via_app=True`，后台线程用 after 钩子等到任务结束）的对打场景 |
| `slice_defs_capture.py` | 链接采集的 3 个切片（`capture_helpers` → `capture_service` → `capture_routes` 必须链式运行）；`global` 声明、日志注入、helpers 名字导入的范例 |
| `scen_capture.py`、`scen_capture_flow.py`、`scen_capture_direct.py`、`scen_capture_direct2.py` | 链接采集的对打场景（103 个请求，`new_via_app=True`）：`scen_capture.py` 是假件与虚拟时钟（假 DrissionPage / websocket / requests / urlopen，`time.sleep` 只拨表；旧版 / 新版的函数、注入依赖、路由模块全局的取法在 `fn` / `patch_fn` / `set_dep` 里抹平），`scen_capture_flow.py` 是 HTTP 流程与场景注册，两个 `direct` 文件是不经 HTTP 的直接调用。要点：每个启动请求前把虚拟时钟拨到固定值，任务 id 因此可预测；采集线程用 after 钩子（按线程名）等到结束；线程可以通过 `clock.block_next` 在下一次 sleep 里挂起，用来做确定性的取消 / 互斥测试 |
| `slice_defs_taobao.py` | 淘宝发布的 3 个切片（`taobao_helpers` → `taobao_service` → `taobao_routes` 必须链式运行）：纯函数 + 常量、带 `wrap_init` 的服务类（7 个方法 + 2 个状态变量）、带 `decorator_name_map` 的路由工厂；`app_edits` 同时改 `app.py` 里读淘宝任务字典的 4 处并删掉 3 个别名 |
| `scen_taobao.py` | 淘宝发布的对打场景（209 个请求，`new_via_app=True`）：用**真实**的 `taobao_publish` 包和账户注册表，只换流水线 `run_from_record`、`make_preparer`、`desktop` 的三个入口和账户的浏览器；流水线假件按「行为表」应答并记录收到的全部参数，`hold` 行为让它停在半路以便稳定地测并发 / 取消；`uuid.uuid4` 换成确定性序列，`cfg(uuid_at=N)` 在关键请求前把计数器设到固定值（任务 id 因此可预测，别让两个特意设定的序号撞上已有任务）；`cfg` 每次先 `join_workers()`，上个请求留下的线程不会和下次重置赛跑。要点：旧版 / 新版的函数、状态、注入依赖的取法在 `fn` / `tasks_of` / `lock_of` / `install_mode_fakes` 里抹平。**⚠️ 2026-10-21 起新旧不再逐字相同**：批量发布的三个既有问题作为独立的行为修改修掉了（旧版 = 搬迁前的 `app.py`，保持原样），`cmp` 有 18 个请求不同（规整掉任务 id 整体后移 1 格之后是 16 个实质差异），`final` 里只有 `env` 一项不同，恰好落在方案文档 12.3 列的五类（类目关键词、有任务在跑时 `start-all`、批量里翻译异常、批量运行中的状态、批量跑完后进程里的 `TAOBAO_MEDIA_ROUTE`）里；以后看这份对打，要看的是「差异恰好是这些、没有别的」，不是「diff 为空」 |
| `slice_defs_upload.py` | 抖店上传的搬迁规格（2026-10-21）。第一步 `upload_steps`：62 个页面操作函数 + 1 个异常类 + 13 个常量，纯搬迁，没有改写规则（用到 `allow_src_utils` / `interleave` / 搬类）；第二步（任务服务 + 路由）见后续 |
| `closure_levels.py` | 只读：一个域的函数闭包按「是否碰服务状态」分成纯的一侧和服务侧（传递闭包），列出纯的一侧引用的常量；决定一个域能不能 / 先搬哪些。Git Bash 里加 `MSYS_NO_PATHCONV=1` |
| `check_import_equiv.py`、`check_builtin_shadow.py`、`list_leftovers.py` | 纯搬迁的三个静态检查：新模块的导入来源与 `app.py` 逐名一致、被 `app.py` 重绑的内置名（`print`）、搬走区域里留在原地的非函数语句 |
| `linecover.py` | 对打时记录被搬函数的行覆盖，列出场景没跑到的语句 |
| `sabotage.py` | **故意改坏验证**：把 `MUTATIONS` 里的小改动逐个写进源码，只跑对应测试，确认变红后恢复原文件并校验摘要（带超时，卡死会单独标出）。里面累计 206 条：店铺会话 / 调试浏览器 51 条、素材导入 14 条、小红书批量 22 条、链接采集 37 条、淘宝发布 82 条（`taobao-` 开头 76 条 + `app:` 6 条，其中 16 条是 2026-10-21 修批量发布的既有问题时加的：批量 worker 的状态与兜底、批量接口的准入、类目代码的映射、批量 worker 的 `TAOBAO_MEDIA_ROUTE` 还原；带参数可只跑名字里含关键词的几条，如 `sabotage.py "import:,xhs"`；注意它会**原地改源码**，运行期间不要同时跑别的测试，也不要有别的会话在改这些文件），换域时照着写自己的 |
| `sabotage_diff.py` | 验证对打脚本本身会变红：同样的改坏，跑 `slice_diff.py <场景> new`，新旧输出必须不再相同。用法 `sabotage_diff.py <work> capture=<旧输出.json> [-k 关键词]`；`PLANS` 里登记了每个场景「会影响场景行为」的改动（shop / debug / capture / taobao）。**淘宝场景的参照输出（`taobao=`）2026-10-21 起不能再用旧版的**：新旧本来就不同，拿旧输出当参照会让每个改坏都显得「变红」而失去意义——改用当前新版、未改坏时跑出的输出（先 `slice_diff.py taobao new <app.py> <参照.json> <数据目录>` 记一份）。2026-10-21 加的 16 条改坏没有登记进 `PLANS`，也没有重跑这个脚本 |
