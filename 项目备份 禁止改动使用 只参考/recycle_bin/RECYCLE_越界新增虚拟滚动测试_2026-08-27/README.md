# RECYCLE_越界新增虚拟滚动测试_2026-08-27

## 回收原因

本目录内的 `test_price_stock_virtual_scroll.py` 是 2026-08-27 代码质量治理任务期间，
由自动化 agent **越界产生**的文件，不属于该任务授权范围。

该任务的授权范围是「在不影响功能的前提下清理死代码与重复代码」，
但这个测试文件配套的是一组**发布核心链路的功能改动**：

- `tauri-app/python-sidecar/app.py` 的 `_fill_price_stock_and_delivery`：272 行 → 395 行
- `tauri-app/python-sidecar/protocol_publish/stages/price_stock_runtime.py`：+216 行

改动内容是重写抖店发布页价格库存表（rc-virtual-list 虚拟滚动表格）的行等待逻辑：
把「滚动后只等 scrollTop 到位就读行」改成「等待渲染出来的行集合确实发生变化」，
并按 `data-row-key` 重新解析行元素以避免重渲染后使用失效句柄。

## 为什么回滚而不是保留

1. 超出任务授权范围（清理 ≠ 改业务逻辑）。
2. 改的是价格库存填写这条**最危险的发布链路**。
3. 只有假 DOM 桩测试，**没有经过真实抖店页面验证**。

经用户确认后回滚，改动完整另存备查。

## 完整改动备份位置

四份对照文件（旧/新各一份）保存在本次会话的 scratchpad：

```
<session-scratchpad>/unauthorized-virtualscroll-change/
  app.py._fill_price_stock_and_delivery.OLD.py    # 回滚后生效的版本
  app.py._fill_price_stock_and_delivery.NEW.py    # 越界改动的版本
  price_stock_runtime.py.OLD                      # 回滚后生效的版本
  price_stock_runtime.py.NEW                      # 越界改动的版本
  test_price_stock_virtual_scroll.py              # 本目录这份的副本
```

scratchpad 是会话级目录，如需长期保留请尽快转存。

## 恢复方式

若后续确认要采纳这个虚拟滚动修复：

1. 把本目录的 `test_price_stock_virtual_scroll.py` 移回仓库根的 `tests/`。
2. 用备份里的 `.NEW` 版本替换 `app.py` 的 `_fill_price_stock_and_delivery` 函数体
   与 `protocol_publish/stages/price_stock_runtime.py`。
3. **必须**在真实抖店发布页跑一次多 SKU（超过一屏）的完整发布流程验证，
   假 DOM 桩测试不能替代这一步。

## 相关既有问题

回滚后 `tests/test_upload_price_stock_locators.py::test_price_stock_fill_uses_shared_root_finder`
会恢复为失败状态。该失败是**既有的**（治理任务开始前就存在）：
测试断言 `app.py` 里要出现「跳过价格库存空白行」这句文案，而当前实现里没有这句日志，
但跳过空白行的功能是在的（`if not row_name and not row_size: continue`）。
属于测试锁死日志文案导致的脆弱断言，未纳入本次治理范围。
