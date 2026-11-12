# 阶段 4 · 催办 + SSE 实时通知 + 签到 + 积分闭环

> **归档口径**：本文件是「AI 交互对话整理版」（官方硬性要求 md 格式）。
> 当前状态：**结构已建立，对话原文尚未归档 —— 待该阶段收尾由哨兵整理**。
> 下方「产出」清单全部为本仓库中**真实存在**的文件；「输入 Prompt」只摘录《校园任务协同AI-Agent-开发方案》第 12 章已有的指令要点，**不臆造任何对话内容**。

## 阶段

阶段 4：把「盯」这件事交给系统 —— 分级催办 + SSE 实时通知 + 签到 + 积分闭环。

- 能力目标：APScheduler 按三级规则扫描任务生成通知（同任务同等级去重）；通知通过 SSE 实时到达前端（红点 + 弹出提示）；签到成功通知发布者；验收加分 / 逾期扣分写流水。
- 契约依据：`C-SSE@1`、`C-NOTIFY@1`、`C-TASKS@1`（积分）、`C-BOOT@1`（`RUN_SCHEDULER` / `SSE_HEARTBEAT_SECONDS` / `REMINDER_INTERVAL_SECONDS`）。

## 使用的 Agent

| Agent | 模型 | 本阶段职责 |
|---|---|---|
| 领航员（Leader） | GLM-5.3-Flash | 冻结三级扫描条件、去重键、通知文案模板；明确调度器可关闭（`RUN_SCHEDULER=0`）以便自动化验收 |
| 构造师 | **DeepSeek-V4.1-Flash-1017** | SSE hub（多连接、跨线程 publish、心跳、背压）、催办调度器、通知唯一写入口、签到与积分扣减 |
| 画师 | **DeepSeek-V4.1-Flash-1017** | `useSSE` 订阅与 3 秒断线重连、导航红点、通知中心（列表 + 已读 + 快捷跳转） |
| 哨兵 | **DeepSeek-V4.1-Flash-1017** | 去重与"同 now 二次扫描新增 0"、逾期扣分仅 1 行、调度器 start/shutdown 幂等、催办模块不调用 LLM |

## 输入 Prompt

- 下发方式：接阶段 3 的连续会话，向 Leader 下发阶段 4 指令（**原文待归档**）。
- 要点（摘自《开发方案》第 12 章阶段 4）：
  1. APScheduler 按间隔执行 `scan_and_remind()`，按方案 5.3 三级规则生成 `notifications`（同 task 同 level 去重），验收加分 / 逾期扣分写 `credit_logs`；
  2. `GET /api/notifications/stream` 用 SSE 实现：连接挂起，新通知即时推送 `event: notify`；前端 `useSSE.ts` 订阅后红点亮起 + 右上角弹提示，点击进通知中心（列表 + 已读 + 快捷跳转：去接单 / 去签到 / 去验收）；
  3. `POST /api/checkin`（每任务每人一次），签到成功发通知给发布者；
  4. 画师实现通知中心页面 + 导航红点 + 个人中心积分流水页渲染；
  5. 验收：任务 deadline 设为 1 分钟后 → 1 分钟内负责人红点亮起并收到 urgent 通知；`student01` 签到后 `teacher01` 收到通知；验收通过积分到账且流水可查。
- **对话原文：待该阶段收尾由哨兵整理（占位，禁止编造）。**

## 产出

| 文件 | 说明 |
|---|---|
| `backend/app/services/notification_hub.py` | SSE 连接注册表：`bind_loop`、`publish`（跨线程安全）、心跳、队列背压（丢弃最旧） |
| `backend/app/services/reminder_scheduler.py` | APScheduler 封装：`start()` / `shutdown()` 幂等，`RUN_SCHEDULER=0` 时不启动 |
| `backend/app/routers/notifications.py` | 通知列表、未读数、标记已读、`GET /api/notifications/stream`（SSE） |
| `backend/app/services/notify_service.py` | 通知创建唯一入口（同时推 SSE） |
| `backend/app/services/credit.py` | 验收加分 / 逾期扣分，写 `credit_logs` |
| `backend/scripts/smoke_sse.sh` | SSE 与催办自检：多连接、跨线程 publish、三级扫描、二次扫描新增 0、逾期扣分仅 1 行、缺失/非法 deadline 跳过 |
| `frontend/src/composables/useSSE.ts` | `EventSource` 订阅（`/stream?token=`）、`onerror` 3 秒重连、`disconnect()` 后不再重连 |
| `frontend/src/stores/notifications.ts` | 未读数与通知列表状态 |
| `frontend/src/layouts/AppLayout.vue` | 顶部导航未读红点接入真实 store |
| `frontend/src/views/Profile.vue` | 通知中心：列表、已读、快捷跳转；积分流水与签到记录 |

## 问题

1. **重复催办**：同一任务同一等级在同一时间窗口内只能生成一条通知。处置：以 `(task_id, level)` 去重，并在自检脚本中断言"同 now 二次扫描新增 0"。
2. **逾期扣分重复扣**：逾期状态可能被周期性扫描反复命中。处置：扣分前检查该任务是否已有逾期流水，自检断言"逾期扣分仅 1 行"。
3. **SSE 跨线程推送**：调度器在后台线程生成通知，而 SSE 连接挂在事件循环线程。处置：`bind_loop` 保存主循环引用，`publish` 通过 `run_coroutine_threadsafe` 投递；未绑定循环时静默降级不抛异常。
4. **连接不释放**：客户端断开后队列需清理，并有队列上限（背压丢弃最旧），避免长时间运行内存增长。
5. **对话与截图未归档**：本阶段会话原文、红点点亮录屏待补，位置为 `prompts/agent_team_启动指令/`、`debug/`、`screenshots/`、`video/`。