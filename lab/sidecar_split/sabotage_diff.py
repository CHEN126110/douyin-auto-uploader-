# -*- coding: utf-8 -*-
"""验证「新旧对打」本身会变红：把新代码故意改坏，跑对打场景，旧 / 新的 JSON 必须不再相同。

对打脚本如果对什么改动都“相同”，那它的“相同”就不值钱。这里从 sabotage.py 的 MUTATIONS 里挑出
会影响场景行为的改动，逐个写进新代码、跑 ``slice_diff.py <场景> new``，和事先记录好的旧输出比对。

用法（仓库根执行；同样会原地改动源码，运行期间别的测试和会话都不要碰这些文件）::

    # 先用搬迁前的 app.py 把旧输出记下来（每个场景只需一次）
    python lab/sidecar_split/slice_diff.py capture old <备份 app.py> <tmp>/capture_old.json <tmp>/data_capture_old
    # 再验证对打脚本会变红：<场景>=<旧输出 json>，可以给多个；末尾的 -k 只跑名字里含这些关键词的改动
    python lab/sidecar_split/sabotage_diff.py <tmp>/work capture=<tmp>/capture_old.json [shop=... debug=...] [-k 关键词,关键词]

PLANS 里登记了每个场景「会影响场景行为」的改动（名字前缀，对应 sabotage.py 里的 MUTATIONS）。
2026-10-20 起支持 capture（链接采集）和 taobao（淘宝发布）；shop / debug 是上一轮的。
"""
import filecmp
import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sabotage  # noqa: E402

REPO = sabotage.REPO
APP = sabotage.APP
SLICE_DIFF = os.path.join(REPO, 'lab', 'sidecar_split', 'slice_diff.py')

PLANS = {
    'shop': [
        'service: 切换账户不丢弃旧浏览器句柄',
        'service: 浏览器属于别的账户时不报冲突',
        'service: 实测身份记到当前账户而不是浏览器所属账户',
        'accounts: 平台门禁判反',
        'accounts: 有发布任务也允许切换账户',
        'accounts: 当前账户不存在也不报错',
        'routes: forget 默认连目录一起删',
        'routes: switch 不再要求账户已存在',
        'app: 账户切换只看上传任务',
    ],
    'debug': [
        'debug: 会话上限 8 改 9',
        'debug: 事件不再截断',
        'debug: attach 不再强制 existing_only',
        'debug: 启动超时不杀进程',
        'debug: 打包态产物目录判反',
        'routes: query 默认包含不可见元素',
        'routes: launch 默认不复用已运行的浏览器',
        'routes: action 失败不留证据',
    ],
    # 链接采集：只挑会改变场景输出的改动（改日志、改只在 app.py 装配里被场景覆盖掉的接线之类的不算）
    'capture': [
        'capture-routes: 互斥锁不再拒绝第二个任务',
        'capture-routes: 启动时不记录占用互斥锁的任务 id',
        'capture-routes: 线程结束不释放互斥锁',
        'capture-routes: 启动失败不释放互斥锁',
        'capture-routes: 取消不释放互斥锁',
        'capture-routes: 取消时连别人的互斥锁一起释放',
        'capture-routes: 历史不按时间倒序',
        'capture-routes: 已结束的任务也能被取消',
        'capture-routes: 取消不打 cancelled 标志',
        'capture-routes: 下载开关失效',
        'capture-routes: 完成后不写协议采集结果',
        'capture-service: cookie 缓存永不过期',
        'capture-service: cookie 缓存不记录时间',
        'capture-service: mtop 缓存不写入',
        'capture-service: token 被拒绝后不刷新',
        'capture-service: 连续验证后不暂停',
        'capture-service: 店铺采集被取消后还接着采',
        'capture-service: punish 类错误不计入验证次数',
        'capture-service: 没有商品链接也不报错',
        'capture-service: 店铺商品全部失败也算完成',
        'capture-service: 同一目录多条历史记录时也覆盖',
        'capture-service: 端口选择不比对资料目录',
        'capture-service: 读取 mtop 的 cookie 不过滤域名',
        'capture-helpers: 淘宝登录页漏掉天猫',
        'capture-helpers: 资源耗尽只认 10048',
        'capture-helpers: 价格递归不限深度',
        'capture-helpers: 店铺判断把商品页也算进去',
        'capture-helpers: 失败的任务不能重试',
        'capture-helpers: ICE 商品 id 不一致也放行',
        'capture-helpers: 短链落到别的域名也放行',
        'app: 采集服务接错端口段',
    ],
    # 淘宝发布：只挑会改变场景输出的改动。纯日志类、只在测试里被替换掉的接线（如 bootstrap_log 换成 print：场景里换成了记录器）不算。
    'taobao': [
        'taobao-helpers: 默认就往平台写',
        'taobao-helpers: 默认不停在提交前',
        'taobao-helpers: 默认就保存草稿',
        'taobao-helpers: 开关不再要求是布尔',
        'taobao-helpers: 上架方式不再校验',
        'taobao-helpers: 请求白名单漏掉 product',
        'taobao-helpers: 整数类目不再映射成名称',
        'taobao-helpers: 价格为 0 的规格也放行',
        'taobao-helpers: 没有名字的规格也放行',
        'taobao-helpers: 库存不取记录里的库存',
        'taobao-helpers: 标题不回退到商品名',
        'taobao-service: 标题超长不再拦',
        'taobao-service: 标题为空不再拦',
        'taobao-service: 类目编号不再校验',
        'taobao-service: 价格为 0 也放行',
        'taobao-service: 库存允许小数',
        'taobao-service: SKU 图片不再核对是不是登记过的',
        'taobao-service: 类目路径分隔符错',
        'taobao-service: sku_mode 不再校验',
        'taobao-service: 取浏览器地址时平台写成抖音',
        'taobao-service: 非淘宝账户也去开浏览器',
        'taobao-service: 不核对打开的是不是当前账户',
        'taobao-service: 打包运行也改 sys.path',
        'taobao-service: 任务结束不还原环境变量',
        'taobao-service: 流水线报已取消时记成失败',
        'taobao-service: 流水线跑完就当商品已上架',
        'taobao-service: 整页必填没确认也说完整填写',
        'taobao-service: 回执自称 dry-run 也算完整填写',
        'taobao-service: 做了保存草稿不说',
        'taobao-service: 图片目录记录失败不报给界面',
        'taobao-service: 图片目录记录失败不写启动日志',
        'taobao-service: 填写任务拿到了提交授权',
        'taobao-service: 取消钩子不读任务里的标志',
        'taobao-service: 上架方式不转发给流水线',
        'taobao-service: 保存草稿开关不转发给流水线',
        'taobao-service: 素材准备没绑定任务的账户',
        'taobao-service: 批量发布不再检查取消',
        'taobao-service: 批量全失败也算完成',
        'taobao-service: 批量里抛异常的记录不计入失败',
        'taobao-service: 批量没有记录也不报错',
        'taobao-routes: 填写任务可以不在提交前停止',
        'taobao-routes: 已有任务在进行中也放行',
        'taobao-routes: 409 不说是哪个任务占着',
        'taobao-routes: 商品资料版本不再核对',
        'taobao-routes: 填写前不再检查账户切换互斥',
        'taobao-routes: 填写任务不拉起素材中心浏览器',
        'taobao-routes: 任务不记录商品编号',
        'taobao-routes: 任务一开始就当作已上架',
        'taobao-routes: 翻译结果不带商品编号',
        'taobao-routes: 翻译时不传商品记录',
        'taobao-routes: 批量发布不校验平台门禁',
        'taobao-routes: 批量任务一开始就是已取消',
        'taobao-routes: 批量账户标识取成空',
        'taobao-routes: 查不到任务也返回 200',
        'taobao-routes: 已结束的任务也能被取消',
        'taobao-routes: 取消不打标志',
        'taobao-routes: 任务列表不按时间倒序',
        'taobao-routes: 就绪度检查把缺依赖当成未预期错误',
        'taobao-routes: 资料检查的资料问题报成 503',
        'app: 保存商品的编辑保护看不到淘宝任务',
        'app: 账户切换只看上传任务',
        'app: 更新器不数淘宝任务',
        'app: 保存时不校验淘宝标题',
        'app: 淘宝服务接错仓库根目录',
    ],
}


def run_new(scenario, out_json, data_dir):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    done = subprocess.run([sys.executable, SLICE_DIFF, scenario, 'new', APP, out_json, data_dir],
                          cwd=REPO, env=env, capture_output=True, text=True, encoding='utf-8')
    return done.returncode


def parse_args(argv):
    keywords = None
    if '-k' in argv:
        index = argv.index('-k')
        keywords = argv[index + 1].split(',')
        argv = argv[:index] + argv[index + 2:]
    work, *pairs = argv
    old = {}
    for pair in pairs:
        scenario, _, path = pair.partition('=')
        assert scenario in PLANS and path, '用法见文件头：%r' % pair
        old[scenario] = path
    return work, old, keywords


def main():
    work, old_outputs, keywords = parse_args(sys.argv[1:])
    os.makedirs(work, exist_ok=True)
    originals = {}
    results = []
    try:
        for scenario, old_json in old_outputs.items():
            for prefix in PLANS[scenario]:
                if keywords and not any(k in prefix for k in keywords):
                    continue
                matches = [m for m in sabotage.MUTATIONS if m['name'].startswith(prefix)]
                assert len(matches) == 1, (prefix, len(matches))
                m = matches[0]
                originals.setdefault(m['path'], sabotage.md5(m['path']))
                with io.open(m['path'], encoding='utf-8', newline='') as fp:
                    text = fp.read()
                mutated = sabotage.apply_mutation(text, m)
                assert mutated is not None, m['name']
                out_json = os.path.join(work, 'mut_%s.json' % len(results))
                try:
                    with io.open(m['path'], 'w', encoding='utf-8', newline='') as fp:
                        fp.write(mutated)
                    code = run_new(scenario, out_json, os.path.join(work, 'data_mut'))
                finally:
                    with io.open(m['path'], 'w', encoding='utf-8', newline='') as fp:
                        fp.write(text)
                same = code == 0 and os.path.exists(out_json) and filecmp.cmp(old_json, out_json, shallow=False)
                results.append((scenario, m['name'], 'crash' if code != 0 else ('相同✗' if same else '不同✓')))
                print('%-8s %-6s %s' % (scenario, results[-1][2], m['name']), flush=True)
    finally:
        for path, digest in originals.items():
            assert sabotage.md5(path) == digest, '文件没有恢复: ' + path
    missed = [r for r in results if r[2] == '相同✗']
    print('\n对打脚本验证：%d 个改动，%d 个让新旧输出变得不同，%d 个没被对打抓住' % (
        len(results), len([r for r in results if r[2] != '相同✗']), len(missed)))
    for r in missed:
        print('  未抓住:', r[0], r[1])
    return 1 if missed else 0


if __name__ == '__main__':
    sys.exit(main())
