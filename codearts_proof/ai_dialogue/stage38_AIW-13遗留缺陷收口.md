# 阶段 38 · AIW-13 遗留缺陷收口：后台验收过期预审一致性

> 日期：2026-11-14（Asia/Shanghai）。平台：华为云码道（CodeArts）。编排 team-leader；实现由主 Agent 直接完成两处小修复；独立只读审查 1 名 team-code-reviewer（首轮 1 Critical/2 Important，修复后复核）。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
> 需求来源：用户「继续开发」+ HANDOFF §4 遗留观察 + AIW-10 审查 Suggestion S5。

## 1. 本轮目标与边界

路线图 AIW-14/09/10/12/13 的可执行部分均已完成，剩余为 D-04/D-05/D-06 条件项。本轮只收口已确认范围内、无新产品规则的缺陷：

1. 复测 HANDOFF「整页直连时侧栏最近与 AI 历史偶不发起请求」。
2. 修复后台验收入口不展示过期预审、可通过按钮仍可点击（与任务详情不一致，AIW-10 S5）。

不做：新接口、文件能力、成就规则、真机/真实模型、部署。

## 2. 复测结论：侧栏请求问题未复现

- 首次监听说 `/api/ai/conversations`，误报 25/25 缺失；核对 `frontend/src/api/agent.ts:99` 实际路径为 `/api/agent/conversations`，侧栏调用 `limit=5`。
- 修正监听后重跑：`/ai`、`/tasks`、`/activities/1`、`/tasks/1`、`/my-tasks` 各 5 次全新整页 `goto`，**25/25 全部发起** 最近活动、最近任务与 AI 历史请求（`work/aiw14/sidebar-init-report.json`）。
- 结论：当前版本**不可复现**；按「未复现不判定缺陷」不修改代码，交接中把该观察改为「已复测通过（25 次整页直连）」，保留历史记录不删。

## 3. 后台验收过期预审一致性（S5）

改动仅 `frontend/src/views/AdminConsole.vue`：

- 打开验收对话框时新增只读 `getTaskSubmissions(task.id)`，按 `item.latest && item.precheck?.stale` 收集过期成员，**不新增接口、不改后端**。
- 成员选项旁显示「预审已过期」；选择「通过」时显示过期预警并禁用「确认通过」；「退回」不受影响。
- `submitVerify` 增加前置拦截；后端 `verify_task` 的 4090 兜底不变。
- 迟到响应保护：`verifyStaleSeq` + `verifyTarget.id` 双重校验，避免 A 任务迟到响应覆盖 B 任务。
- 加载/失败态：`verifyStaleLoading` 期间禁用确认通过；加载失败显示「预审状态未加载，通过时仍会由服务端校验」，不阻塞退回。

契约：`C-PRECHECK-EVIDENCE@2`（design.md §6）；新增静态断言 ㊳。

## 4. 独立审查与修复

首轮：**1 Critical / 2 Important / 4 Suggestion**，判定「有条件提交」。

| 项 | 问题 | 处置 |
|---|---|---|
| C1 | ㊳ 断言恒真空转（problems 未抛错、返回三元组、打印整份源码） | 改为 `raise ContractError` + 单行 `str` 摘要 + `strip_ts_comments`；补负向 token |
| I1 | `loadVerifyStale` 无序号，A 任务迟到响应覆盖 B | 新增 `verifyStaleSeq` + target id 校验 |
| I2 | `verifyStaleLoading` 未使用，加载期间可通过 | 确认按钮禁用条件加 loading；补加载/失败提示 |
| S1 | `catch {}` 静默 | 增加「预审状态未加载，通过时仍会由服务端校验」提示 |
| S2 | `list.items ?? []` 与类型不符 | 改为直接 `list.items` |
| S3 | ㊳ 缺负向断言 | 已补加载中禁用、退回保留/不受影响、序号 token |
| S4 | run_all 日志不全 | 本轮完整日志 `work/aiw13/frontend-runall.log` |

复核：第二轮仅复核新增修复与未关闭项（结论见 §6）。

## 5. 验证（本轮实跑）

| 入口 | 结果 |
|---|---|
| `npm run typecheck`（frontend） | EXIT=0，无错误 |
| `npm run build`（frontend） | EXIT=0 |
| `python tests/frontend/check_contracts.py --frontend frontend` | **38 passed / 0 failed**（含 ㊳） |
| `bash tests/frontend/run_all.sh` | **EXIT=0 / ALL PASS**（构建 4/4、契约 38/38、语音 21/21） |
| `node work/aiw13/verify-ac09-stale-ui.cjs` | **18/18 PASS**（任务详情 + 后台 + 390，含「确认通过」disabled） |
| `node work/aiw14/repro-sidebar-init.cjs` | **25/25 请求齐备**，问题未复现 |

后端未改动，未重跑后端套件；沿用 stage36 的 8 passed / 15 passed+1 skipped 证据。

## 6. 复核结论与未验证

- 第二轮复核（仅新增 diff）：Critical 1 与 Important 1/2 **已关闭**；复核实测空文件注入会抛 `ContractError`（空转不再成立），契约 38/38 输出为单行摘要。
- 复核指出唯一遗留：`verifyStaleLoading || (pass && stale)` 会在加载窗口内把「退回」一并禁用，且被契约 token 锁定 → 已改为 `pass && (verifyStaleLoading || verifyStaleCurrent)`，契约 token 同步；复跑 typecheck/build/契约/浏览器全部通过。
- 复核结论：**可提交**（无 Critical、无未关闭 Important）。
- 未验证：加载中/加载失败后「退回可用」的浏览器注入场景（仅断言表达式与失败提示）、真机、真实模型、深色主题复测、人工晚会链路；本轮未提交、未推送、无新 CI、未部署。
- 已知未处置 Suggestion（AIW-10）：`list_submissions` 每提交者各算 digest、资源窗口保守 false stale、`PrecheckResult` 未含 `resource_snapshot`；本条后台已展示 stale，不再列为缺口。