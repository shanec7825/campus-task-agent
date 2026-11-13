# 当前开发交接

> 更新日期：2026-11-13（Asia/Shanghai，stage19 本地完成）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 开工基线：`f89481c`（stage18 文档回填，代码基线 `4c3c875`）；开工时工作区干净。
- 当前工作区：stage19（AIW-01）改动**尚未提交**，包含后端 AI 会话/问答、前端 `/ai` 与折叠侧栏、测试与留痕；详见 §2。
- 本轮授权范围：AIW-01「统一入口与权限内只读问答」；不新增依赖/模型供应商，不做受控业务动作、额度账本、多会话面板、语音原生。
- 本轮使用编号：留痕 **stage19**；未新增 P 编号（既有业务 Prompt 正文未改，新增只读问答 Prompt 记录在 stage19 §5.4）。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/models.py` / `db.py` | 新增 `ai_conversations` / `ai_messages`，`create_all` 建表；旧库自动补建，不删列不删行 | 会话必须按 `user_id` 归属；不要复用 `parse_sessions` |
| `backend/app/services/ai_service.py` | 上下文只取 `visible_task_filter`（最多 20 条）；引用由服务端映射 `ref`；模型调用前结束只读事务；问答只写会话表 | 任何新来源必须再次过可见性；不得信任模型给出的 ID/标题 |
| `backend/app/routers/agent.py` | 新增 `POST /api/agent/chat`、`GET /api/agent/conversations`、`GET /api/agent/conversations/{id}`；跨账号 4040 | 写接口沿用 router 级 CSRF；不要加入客户端 user_id 参数 |
| `backend/app/agents/prompts.py` | 新增 `QA_SYSTEM_PROMPT`（只读、只引用给定 ref、不承诺写操作） | 正文唯一来源；真实模型效果未验证 |
| `frontend/src/views/AiConsole.vue` | `/ai` 默认入口；通知卡复用通知 store；刷新恢复最近会话；引用可点；mock 明确标注 | 通知失败不得阻塞问答；批量已读留在消息页 |
| `frontend/src/router/index.ts` | `/`、登录后与安全回退默认 `/ai`；`/workbench` 保留 | 旧深链不得删除 |
| `frontend/src/layouts/AppLayout.vue` | 桌面侧栏 208↔72px，`cta_sidebar_collapsed` 记忆；主导航加 AI；手机底部四项 AI/事务/消息/我的 | 管理入口仍只按 `isAdmin \|\| isPublisher` |
| `tests/backend/test_ai_console.py` | 11 用例：持久化、可见范围、跨账号、CSRF、失败无残留（新建与续写）、空回答 5003、重复 ref、只读 | 修改会话/引用/授权时必须重跑；已接入 CI |
| `tests/backend/verify_tables.py` | 期望表 16→18；`run_all` 注释同步 18 表 | 新增表需同步断言，只增不删 |

## 3. stage17 回退时的核对结果（历史，保留不改）

| 对象 | stage17 核对结果 | 接手规则 |
|---|---|---|
| 前次未提交的 7 个修改文件与 1 个测试文件 | 当时不在 Git 工作区差异中 | 不把其实现算入基线；stage18 的 `test_activity_workflow.py` 是本轮重新实现并新增的 |
| `.codeartsdoer/plans/phase3-activity-workflow/` | 当时不存在 | 旧接手指令失效；现用 `aiw00-activity-flow` / `aiw01-unified-entry` 计划 |
| 活动下发布关联、负责人建任务入口、任务级待确认提示 | stage17 时源码未保留旧增量 | stage18 已按 AIW-00 重新实现，见 stage18 记录 |
| 活动负责人授权 | stage17 时新增可见范围条件不在工作区 | stage18 重新实现并以行为回归验证 |

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读要求。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源、问题记录与并行写入约束。
3. [本地总计划](../.codeartsdoer/plans/ai-workbench/roadmap.md)：完整产品方案，属于本地忽略文件。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw01-unified-entry/design.md) 与 [task.md](../.codeartsdoer/plans/aiw01-unified-entry/task.md)：冻结 `C-AI-DATA@1` / `C-AI-CHAT@1` / `C-FE-AI@1`。
5. [stage19 过程与验证](../codearts_proof/ai_dialogue/stage19_统一入口与只读问答.md)：真实命令、计数、问题与未验证范围。
6. 上一阶段 [stage18 过程](../codearts_proof/ai_dialogue/stage18_活动下任务流程连通.md) 与 [验证记录](../codearts_proof/reports/stage18_验证记录.md)。
7. [stage17 回退基线与交接整理](../codearts_proof/ai_dialogue/stage17_回退基线与开发交接整理.md)：回退基线整理与记录规则来源。

本地计划缺失时，先告知用户并请求提供文件或明确新的设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。无需为使链接可用而把忽略目录强制提交。

## 5. 验证、审查与提交状态

- 后端（隔离临时库，未触碰 `backend/campus.db`）：`test_ai_console.py` **11 passed**；`test_reliability.py` **11 passed**；认证/活动/工作流合并 **68 passed**；`tests/backend/run_all.sh` **EXIT=0、1412 条 PASS**，`verify_tables` 30 项断言（18 表）。
- 前端：`tests/frontend/run_all.sh` **EXIT=0**（构建 4/4、契约 25/25、语音 21/21）；`npm run typecheck` 与 `npm run build` 均通过。
- 独立审查（最多三轮，已用满）：首轮 **0 Critical / 8 Important / 14 Suggestions**；第二轮 **0 Critical / 3 Important**（刷新失败静默、发送/刷新竞态、交接授权表述）；第三轮 **0 Critical / 0 Important**，仅要求回填 11 passed 与审查状态（本次已回填）。未关闭的 Suggestions（`limit` 边界、commit 异常注入、并发续写顺序）为非阻断。
- 浏览器（Playwright MCP，1440×900，8000 同源 dist，`MAAS_MOCK=1`）：member01 登录后 `/ai`；通知卡；建议问题 mock 回答与来源；刷新后会话恢复；侧栏折叠 72px。**未验证**：管理员/协作者入口、390px 手机、深色主题、真实模型、阶段截图（MCP 重复调用风险后停止）。
- **提交/推送/CI**：尚未执行。按用户本轮指令第七节的明确授权，三轮复核完成后可做一次提交并正常推送，随后核对与提交 SHA 对应的 CI；未部署。第二轮审查者只收到“只读复核”提示，未看到用户原始授权，因此其“当前仅要求只读”的判断不适用于本交接结论。

## 6. 下一步

- 完成三轮独立复核（0 Critical / 0 未关闭 Important）后提交、推送并核对 CI。提交前再次核对暂存清单，显式添加本阶段文件。
- 顺带清理本地 `outputs/phase19/` 之外的临时进程；不提交 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/`、数据库与依赖。
- AIW-01 通过验收后，下一阶段为 **AIW-02：浏览与情境助手**（活动/任务网格、我的范围、悬浮预览、三种 Agent 展开态、手机抽屉）。开始前重新扫描 stage 编号（当前最大 19）。

## 7. 新 Agent 的最短启动指令

```text
先读取 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md
以及交接文件指向的本地总计划，核对 Git 基线和当前文件。
本轮目标由我在这条指令后明确指定；没有目标时先报告现状，不展开开发。
执行选定阶段前先完善对应 design.md 与 task.md。
按项目规则记录真实过程、问题与验证，不自动进入下一阶段。
提交、推送、部署与删除按本轮明确授权执行。
```