# stage31 独立代码审查（第 1 轮）：AIW-12 额度预留与结算

- 审查角色：独立 Review Agent（只读，不修改业务代码）
- 审查范围（仅 AIW-12）：`backend/app/services/ai_service.py` 的额度预留/结算改造；`tests/backend/test_aiw12_quota_concurrency.py`；被授权更新的 `tests/backend/test_aiw05_proactive_quota.py` 对应用例
- 契约依据：`.codeartsdoer/plans/aiw12-assets-quota/design.md` §2、§4 `C-AI-RESERVATION@2`
- 日期：2026-11-14
- 工作区状态：未提交改动。`ai_service.py` 的同一 diff 里还混入了 AIW-09/14 的 `list_conversations(offset, total)`；`schemas.py` / `models.py` / `main.py` / `routers/agent.py` 含 AIW-14 的 Library/搜索改动。本报告结论只针对上述 AIW-12 段落，混杂改动另见 I-4。

## 复核的本地验证（本轮实际执行，不采信历史结论）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw12_quota_concurrency.py -q` | 0 | `6 passed in 3.01s` |
| `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw12_quota_concurrency.py tests/backend/test_aiw05_proactive_quota.py -q` | 1 | `1 failed, 17 passed in 3.80s`；失败用例 `test_aiw05_proactive_quota.py::test_second_quota_check_after_committed_overrun`：期望 `code=4290`，实际 `code=0` |

未执行/未覆盖：`bash tests/backend/run_all.sh` 全量回归、CI、真实模型（`MAAS_MOCK=0`）、多进程（uvicorn workers>1）并发、浏览器/前端行为、`frontend/src/**` 对 `AiUsageOut` 新语义的展示验证。

## Critical Issues

### C-1 `tests/backend/test_aiw05_proactive_quota.py:543-572` 未随契约更新，回归红

- 文件在 `git status` 中**无改动**（仍是 HEAD 版本），与「被授权更新对应用例」的范围声明不符。
- 该用例仍断言旧实现的「模型调用后二次额度检查」：`_used_today` 第 2 次调用返回 50 时期望 4290（`ai_service.py` HEAD 版本在写账本前会二次校验，本改动已删除该逻辑，改由预留 `pending` 行占用）。
- 影响：`pytest tests/backend/test_aiw12_quota_concurrency.py tests/backend/test_aiw05_proactive_quota.py` 退出码 1，交付/CI 无法变绿；且该断言与被冻结的 `C-AI-RESERVATION@2` 语义直接冲突。
- 建议：把用例改写为预留语义下的等价回归，二选一：
  1. 预置一条当天 `pending` 行占满额度 → `POST /api/agent/chat` 期望 4290，且不新增第二条账本行；或
  2. 保留 `_used_today` 的 monkeypatch，但断言点改为「预留事务内统计到超限 → 4290 且本次 `request_id` 无账本行」（第一次调用返回 50），删除「第 2 次调用」的期待。
  同时更新文件头 docstring 第 9 条「二次额度检查」描述。若选择删除该用例，需在阶段文档中注明契约变更依据，不静默移除。

## Important Issues

### I-1 `ai_service.py:179-221`、`512-515`：同 `request_id` 重放不校验消息与作用域，异内容静默复用旧答案

`_replay` 只按 `(user_id, request_id)` 命中账本即重放，未比对本次请求的 `message` / `scope_type` / `scope_id` / `conversation_id`。

- 影响：违反 §2「同一用户/request_id 只有一个有效生成与预留；同键异内容拒绝或走明确冲突，不复用错误结果」。实际后果是：前端复用了同一 `request_id` 但修改了提问内容或切换了会话作用域时，接口返回 `replayed=True` 的旧回答，而 `conversation_id` 可能是另一个作用域的会话；UI 会把不匹配的答案当成本次提问结果。
- 建议（最小改动）：`_replay` 拿到 `user_message` 后增加 `user_message.content != text` → `ApiError(ERR_CONFLICT, "该请求已处理，请重新提问")`；并对 `conversation.scope_type/scope_id` 与本次归一化作用域做比较，不一致同样 4090。需要把 `text` 与归一化作用域作为参数传入 `_replay`（入口处 512 与冲突分支 537 两处调用同步改）。

### I-2 `ai_service.py:159-172`、`544-553`、`602-619`：失败释放不是显式事务，且 `is_mock_mode()` 在 try 之外

- `_release_reservation` 用 `db.rollback()` + 普通隐式 `DELETE` + `commit`，与 `_reserve_quota` 的 `BEGIN IMMEDIATE` 不对称；SQLite 默认 busy timeout 5s，写竞争时 delete 可能抛 `OperationalError`，被 `except Exception` 吞成一行 `logger.warning`，`pending` 行残留到下一次同用户请求清理（最长 10 分钟）。
- `chat` 第 545 行 `mock = llm_client.is_mock_mode()` 位于 `try` 之前；该调用若抛异常，已提交的预留不会释放。
- 影响：模型失败或结算失败后，用户在额度刚好用满时会看到 4290 而不是立即可重试，属于「额度被短暂多计」；不是永久泄漏。
- 建议：①`_release_reservation` 内改用 `_begin_immediate(db)` 再 delete（与预留/结算一致），并在 engine 上显式设置 `connect_args={"timeout": 10}` 或 `PRAGMA busy_timeout`；②把 `is_mock_mode()` 移入 `try`（`mock` 初值 `False` 或先于预留取值）；③删除失败时至少保证不掩盖原始异常（当前已满足）。

### I-3 `backend/app/schemas.py:886`、`backend/app/models.py:502`：DTO/模型注释仍写「只统计 settled」，与实现不符

- `AiUsageOut` docstring：「只统计本人 `settled` 记录」；`AiUsageLedger` docstring：「每次成功生成回答写一条 `settled` 记录」。
- 实现已改为 `pending + settled` 计入（`ai_service.py:95-104`），且 `GET /api/agent/usage` 的 `items` 会返回 `status='pending'` 的行。
- 影响：后续开发/前端按旧注释实现或展示会出错（例如把 pending 行当历史记录、或前端自行过滤 status 导致 `used` 与 items 不一致）。
- 建议：同步两处注释为 `status IN ('pending','settled')`，并说明 pending 仅表示「生成中占用一次额度」；前端展示如需隐藏，按 `status` 字段处理，不要改后端统计口径。

### I-4 提交归属混杂：同一工作区混有多阶段改动

- `backend/app/services/ai_service.py` 的未提交 diff 同时包含 AIW-12 预留改造与 AIW-09/14 的 `list_conversations(offset, total)`（`ai_service.py:652-711`、`routers/agent.py:203-220`、`schemas.py:911-915`）；`models.py`/`main.py` 含 AIW-14 的 `LibraryLink`、`library`/`search` 路由。
- 影响：按文件提交会把 AIW-12 与其他阶段绑定，回滚与 CI 归因无法定位；违反 AGENTS.md §5「提交前核对文件归属并显式暂存」。
- 建议：提交前对 `ai_service.py` 用 `git add -p` 只暂存 AIW-12 段落（107-172、485-629），分页改动归入 AIW-09/14 的提交；`schemas.py`/`agent.py` 同理按 hunk 拆分，或与团队确认为同一提交。

## Suggested Improvements

- **S-1 `ai_service.py:95-104`**：`func.substr(created_at, 1, 10) == _today_text()` 使 `created_at` 条件无法直接利用 `ix_ai_usage_user_created`（`models.py:510`），且该查询在 `BEGIN IMMEDIATE` 写锁内执行，会延长锁持有时间。建议改为 `AiUsageLedger.created_at >= _today_text()`（格式 `YYYY-MM-DD HH:MM:SS` 字典序安全），并为 `status` 增加可选索引或复合索引 `(user_id, status, created_at)`。
- **S-2 `ai_service.py:131-136`**：purge 与额度判断同事务，超限时 `db.rollback()` 会一并撤销 purge（陈旧 pending 未真正清理）。当前影响很小（下次请求会再清，且超限判断基于清理后的计数），但「清理在最需要时失效」容易误导排障。建议 purge 用独立短事务先提交，或用 savepoint 只回滚插入。
- **S-3 `ai_service.py:555-601`**：结算时 `reservation = db.get(AiUsageLedger, reservation_id)` 依赖 `_begin_immediate` 里 `db.rollback()` 的 expire 语义才会重新查库。若将来去掉该 rollback，`db.get` 会命中 identity map 返回本地 `pending` 对象，`status != pending` 校验形同虚设。建议显式 `db.get(AiUsageLedger, reservation_id, populate_existing=True)`。
- **S-4 `ai_service.py:107-110`**：`db.execute(text("BEGIN IMMEDIATE"))` 绕开 SQLAlchemy 事务状态机，正确性依赖 pysqlite 隐式事务行为（本轮 6 线程用例通过，证明在当前技术栈可用）；换方言或改连接池前需回归。建议在 `_begin_immediate` docstring 注明「仅适用于 SQLite/pysqlite，勿在异步会话复用」。
- **S-5 `ai_service.py:113-122`**：超时清理已正确限定 `user_id`（符合「只清本用户」），但 `test_aiw12_quota_concurrency.py` 没有回归断言。建议补一条：A 用户存在 11 分钟前 pending 行时，B 用户请求成功且 A 的用户行仍在。
- **S-6 `test_aiw12_quota_concurrency.py`**：缺少同 `request_id` 并发用例（契约 §2 要求「同一用户/request_id 只有一个有效生成」）。建议双线程同键并发，断言 1 个成功 + 1 个 4090（或重放），账本仅 1 行、消息仅 2 条。
- **S-7 测试隔离**：`test_aiw12_quota_concurrency.py:31-41` 与 `test_aiw05_proactive_quota.py:39-49` 各自在 import 时设置 `DATABASE_PATH`，但 `app.db` 只在首次 import 固定 engine。两个文件同进程运行时，后 import 的临时库路径不生效，二者实际共享首个临时库（仍不触碰 `backend/campus.db`，符合硬约束，但与文件头「隔离性」声明有偏差）。建议在 `tests/backend/conftest.py` 统一初始化，或接受现状并在 docstring 说明「同进程仅首个文件的临时库生效」。
- **S-8 `ai_service.py:71-72`**：`RESERVATION_TIMEOUT = 10min` 与契约一致，但慢模型（>10 分钟）场景下预留会被清理，原请求结算命中 `reservation is None` → 4090 且不计费（契约已知口径）。建议在 docstring 或日志注明该权衡，便于后续排查「回答被丢弃」类问题。

## Summary

核心机制与契约对齐：`BEGIN IMMEDIATE` 内完成「清理本用户超时 pending → 统计 → 条件插入」，提交即释放锁，模型调用期间不持锁；结算在同一事务内写消息并把 pending 更新为 settled 并回填 `conversation_id/assistant_message_id`；失败/作用域异常走释放。并发争最后一份额度的实测结果为 6 线程中恰好 1 次 0、5 次 4290，账本当天仅 1 行且为 settled，无残留 pending、无重复计量；模型失败释放、顺序重放、超时恢复（11 分钟清理 / 5 分钟仍占用）、跨日边界 4 组用例均通过。未发现绕过 `credit.adjust_credits` / `notify_service.create_notification` 的旁路，也未发现对历史/任务/报名/验收路径的依赖改动。

必须处理：**C-1**（aiw05 旧用例未同步导致回归红），以及 **I-1**（同键异内容静默重放，触及 §2 契约）和 **I-4**（提交归属）。I-2/I-3 建议本轮一并修（改动小、影响额度准确性与文档一致性）。S-1~S-8 可排后续。审查结论：**不通过**（1 个 Critical + 3 个 Important），修复后进入第 2 轮（仅复核新增 diff 与相关回归）。