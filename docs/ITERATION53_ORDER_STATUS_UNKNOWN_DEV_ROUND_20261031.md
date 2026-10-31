# 迭代 53：中立订单状态 UNKNOWN 解析修复

## 范围

本轮只修改 `bt_api_base` 现有 `dev` 检出中的订单状态源码及本记录。`OrderStatus.UNKNOWN` 已存在，但解析别名表缺少小写 `unknown` 与大写 `UNKNOWN`。本轮在 `OrderStatus.get_static_dict()` 中加入这两个精确别名，均映射到现有枚举成员 `OrderStatus.UNKNOWN`。

兼容边界保持不变：`OrderStatus.from_value(None)` 仍返回 `REJECTED`；其他未映射值仍抛出 `ValueError`。未改 CTP、Backtrader、执行相关测试或其他订单逻辑，未读取私密配置，未调用账户或 provider。

## 验收

临时纯值校验通过：小写和大写 `unknown` 均解析为 `UNKNOWN`，`None` 仍解析为 `REJECTED`，`invalid_status` 与 `non_existent_status` 仍抛出 `ValueError`。该校验没有新增持久测试文件。

现存适用测试 `tests/containers/orders/test_order_status.py`：10 passed，1 条已存在的 pytest 配置警告（未知配置项 `asyncio_default_fixture_loop_scope`）；Python 3.11.5，测试导入优先指向当前 `src`。本轮未运行私密配置、真实账户或 provider 测试。

独立源码审查：GO；确认精确别名映射、None/非法值兼容和改动范围，未发现阻塞。

## 提交

仓库：`D:/bt_api_py/bt_api/bt_api_base`；分支：`dev`。源码提交 `3960ee680183a7882e06da239b8e9366b6a7ea2f`，父提交 `afcaf29edda1f0038ed01285c0682c0129294fa1`。源码提交仅含本轮源码路径；本 round record 作为单独路径随后的提交归档。父仓库和其他 SDK 子包不属于本轮提交范围。
