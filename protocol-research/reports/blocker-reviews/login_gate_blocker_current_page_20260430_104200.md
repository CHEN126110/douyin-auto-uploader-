# 登录态阻塞报告

## 阻塞名称

`FXG live probe login gate`

## 阻塞级别

高

## 当前状态

已解除

## 当前事实

- 本地后端已健康。
- CDP 调试浏览器已实际启动，调试地址为 `127.0.0.1:9333`。
- 当前浏览器打开的是抖店登录页：
  - 标题：`抖店登录-抖店后台-抖音电商后台`
  - URL：`https://fxg.jinritemai.com/login/common?...`
- `cdp_environment_check` 复查结果显示：
  - `ok=true`
  - `matchingTargetCount=0`
  - `readyForFxgProtocolProbe=false`

## 阻塞影响

当前阻塞会直接影响下面任务：

- `cdp_fxg_schema_probe`
- `cdp_fxg_runtime_options_probe`
- `cdp_fxg_freight_probe`
- `cdp_fxg_submit_probe`
- `cdp_fxg_qualification_probe`
- `cdp_fxg_material_probe`
- `cdp_fxg_category_matrix_probe`

## 为什么它是 blocker

- 上述工具都要求：当前必须存在已登录的 FXG 发布页运行时。
- 当前页面只有登录页，没有发布页目标。
- 在这种情况下继续调用 probe，只会得到无效结果或直接失败，不能作为研究证据。

## 当前不能声称的内容

- 不能声称第一轮只读探针已经完成。
- 不能声称当前页面 schema 已重新取证。
- 不能声称新的 live submit、qualification、material、runtime 证据已经拿到。
- 不能声称已经具备进入第二轮本地截停研究的条件。

## 阻塞解除条件

满足下面任一条件，才可以认为该 blocker 解除：

1. 当前调试 Chrome 登录成功，并打开 `fxg.jinritemai.com/ffa/g/create`。
2. 存在另一个已登录且带远程调试端口的 Chrome，可被 `cdp_environment_check` 命中。

## 阻塞解除后的立即动作

1. 重新执行 `cdp_environment_check`
2. 执行 schema probe
3. 执行 runtime options probe
4. 执行 freight probe
5. 执行 submit probe
6. 执行 qualification probe
7. 执行 material probe
8. 执行 category matrix probe

## 当前结论

当前阶段最前置的任务不是继续猜接口，而是先拿到“已登录发布页 + CDP 可访问”这个 live probe 入口。

## 后续进展

- 该阻塞已在同一轮会话后续阶段解除。
- 解除依据：
  - `matchingTargetCount=1`
  - `readyForFxgProtocolProbe=true`
  - 当前页面命中 `https://fxg.jinritemai.com/ffa/g/create`
- 阻塞解除后，第一轮只读 probe 已实际开始执行并生成产物。
