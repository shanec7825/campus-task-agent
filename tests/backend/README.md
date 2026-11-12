# 后端契约与集成验证（T10）

本目录是 **T10（后端契约与集成验证，跨边界 E2E）** 的交付物：在**临时数据库 + mock 模式 +
独立端口（8021）**下，验证 `T1`~`T4` 已交付代码在运行时的跨任务契约与关键业务规则。
目录内只做验证，**不修改任何实现文件**；发现缺陷时输出「文件:行号 + 期望 + 实际 + 复现命令 +
建议责任任务」。

## 1. 一键运行

```bash
# 在仓库根执行（git-bash / WSL / Linux 均可）
bash campus-task-agent/tests/backend/run_all.sh
```

脚本做的事（`set -euo pipefail`，任一断言失败即非 0 退出）：

1. `mktemp -d` 创建临时目录，库路径 `<tmp>/t10.db`；
2. 后台启动
   `DATABASE_PATH=<tmp>/t10.db MAAS_MOCK=1 RUN_SCHEDULER=0 MAAS_API_KEY="" .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8021`；
3. 轮询 `GET /api/health` 直到 `code=0`（最多 40 秒）；
4. 依次执行 6 个验证脚本；
5. 额外以 `KB_MIN_SIMILARITY=0` 在 **8011** 启动第二个后端，只做「KB 不过滤」观测
   （输出 `INFO` 行，**不计入失败判据**）；
6. `trap` 清理：停止自己启动的进程、删除临时库与日志；临时目录删除结果会打印
   `INFO: 已停止 8021/8011 后端进程；临时数据库与日志已删除：<tmp>`。
   **不会**删除 `.venv` / `node_modules`，也**不会**按端口强杀非本脚本启动的进程。

可选环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `T10_PORT` | `8021` | 被测后端端口（**不得**使用 8000/5173，它们留给人工演示） |
| `T10_KB_PORT` | `8011` | KB 观测后端端口；被占用时该观测自动 `SKIP`（不影响主结论） |

依赖约定：**只用标准库**（`urllib.request` / `json` / `sqlite3` / `subprocess` / `threading`）
＋后端 `.venv` 既有包，`requirements.txt` 不做任何改动。

## 2. 文件与用例矩阵

| 文件 | 对应 plan 用例 | 覆盖要点 |
|---|---|---|
| `verify_tables.py` | ① 建表校验 | 8 张表存在；`checkins` 的 `UNIQUE(task_id,user_id)`（PRAGMA 元数据 + 真实重复插入双证，事务回滚无残留）；`progress_logs` 存在且列齐全；`tasks.extras` / `tasks.reminder_rule` 经 API 与 SQLite 原始列**双证为 dict**；`/api/health` 的 `tables` 与 `mock` |
| `test_api_e2e.py` | ② 全流程 + 错误码矩阵 | 双角色登录 → 发布（extras / reminder_rule / credit_reward）→ 列表过滤（status 单值/逗号多值、scope、include_sub、排序、`is_claimable`）→ 认领 → 进度（状态推进）→ 提交 → 验收通过（余额 +20、流水 1 条、通知 ≥2）→ 重复验收幂等（`credit_delta=0`）→ 签到两次（第二次 4090）/非负责人签到 4030 → `checkin/me` → `credits/me` 余额 == 流水和 → 401/4010 → 非法流转 4090 → 发布者自认领 4030 → 依赖未完成认领 4020 → 指派 / PATCH 语义 / `/decompose` |
| `test_agent_mock.py` | ③ mock 规则逐条 + KB | `/extract` `/review` `/stream/parse` 三接口 `mock=true`；规则表逐条（秋之韵 / 搬桌椅 / 摄影追加 / 教三→教四 / 明天下午两点 / 仅「下午」→unresolved / 5 个人 / 措辞严谨剥离 / 奖励 20 积分→unresolved）；`spans` 字段归属与原文顺序；确定性（同输入两次结果一致）；`/stream/parse` 单行合并与 `parse_sessions` 落库；`/kb/similar` 的 `threshold=0.6`、top≤3、降序、默认 ≥0.6 过滤 |
| `test_sse_and_reminder.py` | ④ 真 SSE + 三级催办 | `threading` + `urllib` 长连接读 `/api/notifications/stream?token=`，另一线程触发 `verify`，5 秒内断言 `event: notify` 且 `data` 含 `level/user_id/task_id/title/is_read`；直接调 `scan_and_remind(now=...)` 断言 warning 1 + urgent 1 + overdue 2（行数 ≠ 事件数）、逾期扣分仅 1 行 `-10`、任务置 `overdue`、二次扫描 0 新增 |

## 3. 断言语义（为什么不是"只看 HTTP 200"）

- 每个脚本自带 `expect(cond, msg)`：通过打印 `PASS: <msg>` 并计数，失败打印
  `FAIL: <msg>` 后 `exit 1`。
- `api_ok()` 同时断言 **HTTP 200 且 `code == 0`**，再断言 `data` 是对象（防止
  "HTTP 200 + code=4010/4030" 被误判通过）；`api_err()` 同时断言 `code` 与 HTTP 状态。
- 所有业务错误按契约是 **HTTP 200 + `code != 0`**；仅认证失败是 **HTTP 401 + code=4010**。
  因此 `4010` 用例显式传 `expected_status=401`。
- 数据隔离：`test_api_e2e.py` 的积分/通知断言全部用**相对基线**（先读基线再比较），
  避免与其它脚本写入的数据耦合；除催办用例外，所有任务 `deadline` 为空，
  保证 `scan_and_remind` 的计数可精确断言（脚本会先 `INFO` 打印扫描候选任务，便于定位）。
- 时间参数化：催办 deadline 由 `datetime.now()` 加减固定小时数生成，
  **不依赖真实时间等待**（唯一等待是 SSE 的 5 秒超时）。

## 4. 失败定位建议

| 失败脚本 | 先看什么 |
|---|---|
| `verify_tables.py` | `FAIL` 行里的表名 / 索引列组合；若是 `T10_DB_PATH` 不存在，说明没有通过 `run_all.sh` 运行（脚本拒绝回落到默认库 `./campus.db`） |
| `test_api_e2e.py` | 首个 `FAIL` 的 label 已含接口与期望；断言信息里带实际 `code/msg`。错误码类失败优先查 `app/routers/tasks.py` 的 `ALLOWED_TRANSITIONS` 与各路由的权限判断顺序 |
| `test_agent_mock.py` | 规则类失败对比 plan `2.2.7` 规则表与 `app/agents/mock_fixtures.py`；KB 类失败先看 `INFO: unfiltered 模式 similarity 列表` 与 `app/services/kb_service.py` 的 `score_pair` |
| `test_sse_and_reminder.py` | SSE 失败看 `result["error"]`（连接超时 / 首帧缺失）；催办计数失败先看 `INFO: 扫描候选任务` 列表，确认没有额外命中；扣分失败查 `credit_logs` 的「逾期扣分」前缀幂等 |

失败后重跑：`T10_KB_PORT=8011 bash tests/backend/run_all.sh`（端口被占用时换端口）。

## 5. KB 过滤的两种模式（Leader 裁定口径）

- 后端默认 `KB_MIN_SIMILARITY=0.6`（路由层过滤低于 0.6 的候选），`threshold` 字段恒为 `0.6`；
- `run_all.sh` 的第二段观测以 `KB_MIN_SIMILARITY=0` 启动，验证「后端不过滤」时同一查询会
  多出低分候选（实测：`q="秋之韵"` 默认 0 条 vs 不过滤 3 条），该段输出**不参与失败判定**。

## 6. Deferred（本任务不验证 / 无凭证无法验证）

| 项 | 原因 | 责任任务 |
|---|---|---|
| 真实 MaaS 调用（`MAAS_API_KEY` 缺失，plan `2.3 D5`） | 无真实凭证；`MAAS_MOCK=1` 下以确定性 mock 结论替代，真实调用的 5001/5002/5003 分支未实测 | 环境性缺口（非实现缺陷） |
| 前端渲染、语音切片、SSE 红点 1 秒内刷新 | 需浏览器 + 麦克风，属界面行为 | `T11` |
| 安全红线（Key 扫描、`.gitignore`）、交付物一致性、干净环境复现 | 独立终验范围 | `T12` |
| `.env` 文件加载（`python-dotenv` 未被 `app` 引用） | 本任务仅通过环境变量注入，未断言 `.env` 读取行为；如需要应在部署文档确认 | 观察项，见 T10 报告 |

## 7. 产物与清理

- 运行期间唯一产物是 `mktemp` 目录：`t10.db`、`t10-server.log`、`t10-kb-server.log`；
- `run_all.sh` 退出时删除该目录并打印清理结果；
- 不写入 `backend/campus.db`，不触碰 `.venv` / `node_modules` / 前端构建产物。

---

## T8（第二轮迭代）更新

- 端口改为 **8021**（T8 独占；临时库 + `MAAS_MOCK=1` + `RUN_SCHEDULER=0`）。
- 脚本由 4 个扩为 6 个，顺序：`verify_tables.py` → `test_applications.py` → `test_api_e2e.py` → `test_agent_mock.py` → `test_agent_incremental.py` → `test_sse_and_reminder.py`。
- 新增要点：9 张表 + `task_applications` 的 `CONSTRAINT uq_task_applications_task_user UNIQUE`（以 DDL 为准）；报名审批 R16-AC1~AC16（含 quota=8 第 2/3 人可报名、双人各 +20 幂等、双人签到、legacy 回退）；增量解析与纯值红线；claim 全量改写为 `apply → pending → approve → claimed`。
- 最近一次实测：`EXIT=0`；`verify_tables 41` / `test_applications 413` / `test_api_e2e 257` / `test_agent_mock 217` / `test_agent_incremental 243` / `test_sse_and_reminder 106` 项断言全 PASS（另 KB 不过滤观测 25 项）。
