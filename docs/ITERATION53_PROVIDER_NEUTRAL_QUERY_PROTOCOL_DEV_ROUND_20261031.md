# 迭代 53：bt_api_base 中立查询合同结构轮

## 基线与范围

- 仓库：D:\bt_api_py\bt_api\bt_api_base
- 分支：dev
- 建档时 HEAD：a61298c35d101b5aca38b0491c41eb5ac62c20c1
- HEAD 父提交：3960ee680183a7882e06da239b8e9366b6a7ea2f
- pyproject.toml 声明 Python >=3.9。
- 本轮新增 src/bt_api_base/query_protocol.py 与本记录；不修改 bt_api_base/__init__.py，不改变包级导出。
- 源码 SHA-256：BC1A00EEDAD3AD5C167497781AF238F13F78E5668335A340E5FA82F20D850896。
- 本轮不提交；由主代理按结构轮精确选择源码与记录文件。

## 中立查询接口

新模块路径为 bt_api_base.query_protocol，只依赖标准库和现有 bt_api_base 契约。

- QueryCompleteness(str, Enum) 定义 COMPLETE、PARTIAL、UNAVAILABLE、UNKNOWN。
- QueryRequest(request_ref, family, filters={}, required=True, require_complete_scope=False) 表示一个 family 请求。request_ref 在批次中唯一；family 使用小写中立标识符；filters 为递归冻结、限深和限大小的 JSON 值。未支持的 family/filter 必须显式失败或报告不可用，不能静默丢弃。
- QuerySnapshot(request, source_ref, generation, snapshot_ref, completeness, started_at, completed_at, observed_at, scope_complete, records=(), blockers=(), continuation_ref=None) 表示一个请求的不可变语义结果。所有时间必须是有时区 UTC 且顺序合理。record_count、records_digest 自动计算。COMPLETE 需要来源、代次、快照标识、时间，且无 blocker/continuation；这只说明请求结果完整，不自动证明资源范围完整。
- QueryBatchReceipt(batch_ref, source_ref, generation, started_at, completed_at, requests, snapshots, blockers=()) 回显请求和结果。它要求 request_ref 唯一、每个 snapshot 精确对应批内请求、已知 source/generation 一致；缺结果使必需项不能完整。complete 由必需项、scope 要求、snapshot 状态和批次 blockers 派生，receipt_digest 自动绑定请求、记录摘要、source/generation 与时间。
- QuerySnapshotLease(lease_ref, receipt_digest, source_ref, generation, snapshot_refs, issued_at, expires_at, purpose) 是 provider 签发的不可变 lease 描述，不包含 native handle 或凭证。构造 DTO 本身不构成可信授权；provider 必须验证它。
- ProviderQueryPort 定义 query_batch(requests, *, deadline) -> QueryBatchReceipt、acquire_snapshot_lease(receipt, *, purpose, expires_at) -> QuerySnapshotLease、validate_lease(lease, receipt, *, now) -> bool。deadline/lease 时间均为 UTC。lease 只能绑定完整 receipt 的 source/generation 与 complete snapshot refs；无法确认当前性、已过期或来源/代次/快照变化时，复验返回 False。

## Family schema 与兼容约束

标准 family 限于已有中立记录模型：

| Family | 每条记录的规范模型 |
| --- | --- |
| account | AccountBalance |
| positions | AccountPosition |
| open_orders | AccountOpenOrder |
| instruments | MarketInstrumentKey |

构造 QuerySnapshot 时，标准 family 的 records 会经对应模型的 from_dict 校验，并要求模型 to_dict() 与输入记录一致。open_orders 只接受模型现有的 open / partially_filled 状态；不能把终态订单过滤掉后报告完整订单快照。trades、费率及其他扩展 family 当前没有共享记录 schema：请求可表达，但在 schema 进入 base 契约前不得携带记录或声明 COMPLETE。标准 filter key 常量只列当前互操作子集；有限的未来 key 可表达，但 provider 不支持时必须 fail closed。

CTP native query rows 必须在 SDK/provider service 内投影为这些既有中立 DTO 的 JSON 形态；详细 native 诊断由 SDK 自己保管，可由 snapshot_ref 关联。bt_api_py facade 负责校验并传递中立 DTO，Backtrader 不接收 CTP 行投影器，也不创建逐交易所 BT adapter。未能无损映射的结果不能伪造为 COMPLETE。

## 审查与验收边界

- direct_review 对最终模块做了只读静态审查，结论为 GO；审查未运行测试或账户操作。
- 本轮没有运行测试、导入运行、provider、账户或 BT/CTP 集成；没有证明 CTP 下游实现、实际 query、scope 覆盖、lease 签发/复验或真实账户行为。
- 本轮是结构合同源码轮，不增加任何正式案例通过数，不是 package/runtime/account acceptance。
- 本记录使用 UTF-8 BOM；已通过 BOM 检查、严格 UTF-8 解码、中文无替换字符检查，以及 Windows PowerShell 5.1 默认 Get-Content 读取检查（显示版本 5.1）。

## 工作区状态

记录创建时子仓处于 dev，HEAD 为 a61298c35d101b5aca38b0491c41eb5ac62c20c1，相对 origin/dev ahead 2；既有订单状态 UNKNOWN 修复已在 HEAD 历史中。此前唯一新增未跟踪源码是 src/bt_api_base/query_protocol.py。本记录随后作为另一个未跟踪路径新增。本轮未改其他文件、未暂存、未提交；主代理负责精确 stage/commit。