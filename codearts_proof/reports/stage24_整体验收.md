# stage24 整体验收（AIW-06）验证报告

> 日期：2026-11-14。基线：`d25c91cc2fd38910fff76d2934465e46558c5fdd`（stage23 文档回填）。本报告只记录本轮实际执行的命令、退出码与结果；历史阶段数字不作为本轮结论。

## 1. 结论

- 新增端到端验收套件 `tests/backend/test_aiw06_acceptance.py`：**1 passed**（3.46s，EXIT=0）。
- 后端完整门禁 `tests/backend/run_all.sh`：**EXIT=0**。
- 前端完整门禁 `tests/frontend/run_all.sh`：**EXIT=0**（构建 4/4、契约 25/25、语音 21/21）。
- 安全红线：**12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**，失败仅因本地忽略目录运行产物残留。
- 独立审查三轮：首轮 0 Critical / 4 Important；第二轮 0 Critical / 2 Important；第三轮 **0 Critical / 0 Important / 3 Suggestion**。
- 浏览器走查：桌面与 390×844 模拟视口共 8 张真实截图；移动端任务详情无横向溢出。
- **未验证**：真实模型输出质量、真机、移动端完整提交/验收操作、深色主题、部署。

## 2. 隔离与安全边界

套件在 `import app` 前设置：

- `DATABASE_PATH=<系统临时目录>/aiw06.db`
- `MAAS_MOCK=1`
- `MAAS_API_KEY=""`
- `RUN_SCHEDULER=0`
- `AI_DAILY_QUOTA=50`

并在 import 后断言 `app.db.engine.url.database` 等于该临时库；不匹配时模块级 `pytest.skip`，避免全量 pytest 复用首个套件的库。模块退出时先 `engine.dispose()` 再删除临时目录。运行前后 `backend/campus.db` 均不存在，未触碰开发库或真实库。

## 3. 自动化验收覆盖

`tests/backend/test_aiw06_acceptance.py` 串联以下用户可见链路：

1. 组织管理员、协作者（活动负责人）、成员 ×2、外组织成员/管理员登录与组织关系准备。
2. 协作者发布活动与活动资料；发布预热推文任务、舞台布置任务（依赖预热推文）。
3. 依赖未完成时报名舞台布置返回 `4020`。
4. 两名成员报名预热推文 → 发布者审批 → 成员更新进度 → 提交成果 v1。
5. v1 时间与活动不一致，规则预审 `fail` 且 `time_consistency` 指向错误日期。
6. 负责人退回，成员状态 `rejected` 且收到退回通知。
7. 重提 v2，预审 `pass`；用旧版 v1 验收返回 `4090`，成员仍为 `submitted`、积分不变。
8. 最新 v2 验收通过，成员 `verified`、积分按 `credit_reward` +20、收到积分到账通知。
9. 第二名成员提交并验收，本人 `verified`，任务整体 `verified`。
10. 任务 A 验收后任务 B 依赖解锁，可报名。
11. 催办生成后改期：`reminders_stale == 1`，旧提醒 `stale=1`、不计未读，成员收到变更通知。
12. AI 问答：`mock=True`、回答非空、引用非空且仅属于 `{task_a, task_b}`；外组织任务不进入引用与正文；`usage +1`；同一 `request_id` 重放 `replayed=True` 且不重复扣额度。
13. 跨组织：外组织成员读活动/任务返回 `4040` + HTTP 404；外组织管理员改期同样被拒；列表不含活动内任务。
14. 通知列表仍返回失效提醒供追溯，未读数排除 `stale`。

## 4. 完整门禁真实计数

后端（`PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`，日志 `outputs/aiw06/backend-run-all.log`）：

| 步骤 | 结果 |
|---|---|
| `verify_tables.py` | 58 项断言（23 表）PASS |
| `test_applications.py` | 410 项断言 PASS |
| `test_api_e2e.py` | 255 项断言 PASS |
| `test_agent_mock.py`（default） | 229 项断言 PASS |
| `test_agent_incremental.py` | 358 项断言 PASS |
| `test_sse_and_reminder.py` | 105 项断言 PASS |
| `test_agent_mock.py`（unfiltered 观测） | 25 项断言 PASS |
| 总退出码 | **EXIT=0** |

前端（`PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`，日志 `outputs/aiw06/frontend-run-all.log`）：

- 构建门禁：**4/4 通过**，dist 已生成。
- 静态契约：**25/25 PASS**。
- 语音切片算法：**21 PASS / 0 FAIL**。
- 总退出码：**EXIT=0**。

安全红线（构建后执行，日志 `outputs/aiw06/security-redline.log`）：

- `bash tests/security/test_security_redline.sh`：**12 通过 / 0 PASS-LOCAL / 1 失败 / 共 13 项**，**EXIT=1**。
- 失败项仅为 **B5b 运行产物残留**：`outputs/`、`.playwright-mcp/`、`.codeartsdoer/temp/`、`work/` 等被 Git 忽略的本地日志与证据。未删除证据、未修改基线、未提高阈值；CI 干净检出不含这些文件。

## 5. 浏览器走查

环境：`http://127.0.0.1:8000` 同源 `frontend/dist` + `outputs/aiw06/demo.db`；`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、`AI_DAILY_QUOTA=50`。演示服务为本轮本地进程，走查结束后停止，8000 端口已释放。

截图索引（`codearts_proof/screenshots/stage24/`）：

| 文件 | 视口/尺寸 | 内容 |
|---|---|---|
| `01-ai-console-desktop.png` | 1425×1038 | AI 首页：待处理通知（改期、逾期）、问答空态、额度 0/50 |
| `02-task-hall-desktop.png` | 1440×900 | 事务大厅：活动 1 个、活动任务 1 个，任务卡显示所属活动与截止 |
| `03-activity-detail.png` | 1425×1635 | 活动详情：整体进度、任务、依赖与时间图、未排期区、资料检索入口 |
| `04-member-submission-v1.png` | 1425×2803 | 成员任务详情：已提交 v1、待验收、成果版本区块 |
| `05-precheck-fail.png` | 1425×2949 | 发布者任务详情：预审「不通过」、时间项失败、通过/退回入口 |
| `06-admin-change-impact.png` | 1440×900 | 后台改期确认卡：当前→拟调整、受影响成员 1、后续任务 0、通知接收人 2 |
| `07-mobile-ai-390.png` | 390×844 | 移动 AI 首页：菜单、通知、底部四项导航 |
| `08-mobile-task-detail-390.png` | 390×844 | 移动任务详情首屏 |

页面宽度实测（`browser_evaluate`，任务详情 `/tasks/1`）：`innerWidth=390`、`docScrollWidth=375`、`bodyScrollWidth=375`、`horizontalOverflow=false`。

**口径偏差**：`01/03/04/05` 实际宽度为 1425（含页面滚动条/窗口内宽），不是 design 要求的 1440×900；仅 `02/06` 为 1440×900，`07/08` 为 390×844。本轮未重拍，不声称全部满足 1440×900。移动端仅验证了首页与任务详情浏览，**未实测完整提交/验收操作**。

## 6. 独立审查

| 轮次 | 结论 | 处置 |
|---|---|---|
| 第一轮 | 0 Critical / 4 Important / 12 Suggestion | 补 AI 引用与权限范围断言、活动/任务字段断言、旧版验收无副作用、逐人 verified、精确 stale、HTTP 200；I2 留痕、I3 截图口径、I4 移动端按报告口径处理 |
| 第二轮 | 0 Critical / 2 Important / 5 Suggestion | 新增 I5：临时目录 atexit 清理实测无效；改为 `engine.dispose()` 后删除，探针前后均 11 个目录，已关闭。I2 留痕仍未落盘 |
| 第三轮 | **0 Critical / 0 Important / 3 Suggestion** | I5 关闭；Suggestion 为 skip 分支残留空目录、CI 文档建议注明单文件运行、测试固定日期，均不阻塞 |

第三轮为最终轮，之后未再开第四轮；本轮在第三轮后仅补文档留痕，未修改测试或业务代码。

## 7. 未验证范围

- 真实模型输出质量与引用质量（全程 `MAAS_MOCK=1`）。
- 真机、多真机并发、真实移动浏览器。
- 移动端完整提交/验收操作、深色主题。
- 部署与公网未验证。
- CI 已核对（2026-11-14 回填）：业务提交 `a728788` → run `43532974986` 四个 job success（Backend API and SSE integration、Frontend build/voice/public source security checks、Backend reliability ubuntu-latest、Backend reliability windows-latest）。
- 全量 `pytest tests/backend/` 下本套件 skip 的具体报告形态（未运行）。