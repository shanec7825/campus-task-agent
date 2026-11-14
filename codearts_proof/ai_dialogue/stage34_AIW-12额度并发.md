# stage34：AIW-12 问答额度原子预留与并发回归

> 日期：2026-11-14（Asia/Shanghai）。本阶段只做「额度并发准确性」增量；成就规则依赖 D-05，挂起未实施。未提交、未推送、无 CI、未部署。

## 1. 需求与范围

- 用户接续指令：AIW-12 个人资产与额度；成就规则表（D-05）未确认时只挂起直接相关子任务。
- 计划：`.codeartsdoer/plans/aiw12-assets-quota/design.md` §2、§4（C-AI-RESERVATION@2）。
- 范围：每日问答额度在短事务内原子预留、模型调用不持锁、失败释放、同 request_id 幂等、超时恢复、跨日口径、零额度只影响被计量生成。
- 不做：成就发奖写路径（D-05 未确认）、扩大计量范围/收费（D-03）、支付。

## 2. 决策与边界

| 决策 | 口径 |
| --- | --- |
| 预留存储 | 复用 `ai_usage_ledger`，新增 `status='pending'`，不新增表（表基线仍 24） |
| 原子性 | `BEGIN IMMEDIATE` 内「清理超时 → 统计 used → 条件插入 pending」，提交后释放锁 |
| 计量 | `used` = 今日 `pending + settled`；`items` 只列 `settled` |
| 失败释放 | 与预留对称的 `BEGIN IMMEDIATE` 条件删除，重试一次，失败抛 4090 而非静默驻留 |
| 同键 | 已结算重放；异内容/异作用域 4090；处理中 4090 |
| 超时 | 仅清理本用户、早于 10 分钟仍 pending 的行 |
| 非问答功能 | 通知/历史/任务/报名/提交/审核/人工验收不受额度影响 |

## 3. 实际工具与派工

- 平台：华为云码道（CodeArts）；显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
- 1 个 coding-engineer 实现 + 1 个独立审查（第 1 轮）；主 Agent 冻结契约、复跑回归与修订冲突用例。
- 命令：
  - `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw12_quota_concurrency.py tests/backend/test_aiw05_proactive_quota.py -q`
  - `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`

## 4. 产出

- `backend/app/services/ai_service.py`：`_begin_immediate`、`_purge_stale_reservations`、`_reserve_quota`、`_release_reservation`、`_used_today` 口径、`chat` 流程重排、`_replay` 内容/作用域校验、`get_usage` 只列 settled。
- `backend/app/models.py`、`backend/app/schemas.py`：注释口径同步（pending 计入 used）。
- `tests/backend/test_aiw12_quota_concurrency.py`（6 用例）；`tests/backend/test_aiw05_proactive_quota.py` 旧「二次额度检查」用例改为「预留争用」。
- 审查：`codearts_proof/reviews/stage31_quota_review.md`。

## 5. 真实问题与处置

1. **旧用例失败**：`test_second_quota_check_after_committed_overrun` 断言被契约取代的机制 → 授权改写为 pending 预留占用场景；修正后 18 passed。
2. **审查 C-1**：实现者首次声称已更新但 `git status` 无改动 → 本会话按授权直接改写用例并实跑。
3. **审查 I-1**：同 request_id 异内容静默复用 → 增加 `expected_message/expected_scope` 校验，冲突 4090。
4. **审查 I-2**：释放未走事务、`is_mock_mode` 在 try 外 → 改为对称短事务 + 重试 + 异常释放。
5. **审查 I-3**：注释与 items 口径 → `get_usage` 只返回 settled；注释同步。
6. 测试用例曾因 SQLite 行 id 复用导致误判，修正断言后通过（非实现缺陷）。

## 6. 验证与未完成项

- `pytest test_aiw12_quota_concurrency.py`：6 passed（首跑 1 failed 为测试断言自身问题，已修正）。
- `pytest test_aiw12_quota_concurrency.py test_aiw05_proactive_quota.py`：18 passed，EXIT=0。
- 后端全量 `run_all.sh`：EXIT=0，1446 PASS（收口后复跑）。
- 未完成/未验证：成就（D-05）、Profile 资产区块视觉回归未重跑、多进程并发（SQLite 单进程串行语义）、真实模型、真机、CI。