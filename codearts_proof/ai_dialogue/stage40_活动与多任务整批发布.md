# 阶段 40 · V1 需求基线与 S1 活动 + 多任务整批原子发布

> 日期：2026-11-14（Asia/Shanghai）。起点基线 `main` @ `374f29e`（工作区干净）。
> 计划（本地、Git 忽略）：`.codeartsdoer/plans/v1-baseline/roadmap.md`、`s1-batch-publish/{design,task}.md`。

## 1. 需求来源与边界

- 用户本轮下发《校园任务助手：功能需求整理（V1）》，并要求「参照此规划；设计完整计划，并进行持续开发，每一次阶段进行一次提交推送 CI 检测，最后进行部署验收」。
- 本轮据此建立 V1 基线（P0/P1/P2 共 9 项），拆成 S1～S6 六个交付阶段，每阶段一次提交 + 推送 + CI。
- 阶段 40 只做 S1（P0 第一项）：活动 + 多任务一次发布，失败整体回滚。其余 P0/P1 不在本阶段实施。
- 用户本轮明确授权：阶段提交、推送、对应 CI 检查；部署验收放在最后阶段，届时按实际目标确认。
- AIW-11 曾整体取消「整批原子发布」；本轮按用户 V1 明确要求恢复该能力，但不恢复 AIW-11 一并放弃的自动推荐、业务动作卡等。

## 2. 决策与契约

- 新接口 `POST /api/activities/publish-batch`（契约 `C-BATCH-PUBLISH@1`），保留 `POST /api/activities` 与 `POST /api/tasks` 原行为。
- 任务之间用批内 `key` 引用前置（`depends_on_keys`）与父任务（`parent_key`），不支持跨批次引用；依赖写入复用 `task_graph_service.replace_dependencies`。
- `tasks=[]` 合法（V1：不强制必须有任务）；父任务只允许一层，父任务自身不得再声明 `parent_key`。
- 所有校验在 `db.add` 之前完成，写入段包 try，异常 `rollback` 后重抛；提交仅一次。
- 契约按字面保留了 `parent_id` 字段，服务层对非空值返回 4001 并提示改用 `parent_key`（避免跨批次父子引用绕过 R1-05）。
- 不设幂等键；前端 `saving` 期间禁用提交。
- 依赖写入后，复用单任务发布的 `_index_task_safe` 在 commit 后写知识库，索引失败不影响已提交的发布。

## 3. 实际派工

| 角色 | 任务 | 说明 |
|---|---|---|
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T1-1 | schemas / activities 路由 / activity_service / 新增测试 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T1-2 | 发布页多任务编辑、api/activities.ts、types/models.ts |
| 独立审查员（team-mate） | S1 审查 | 只读 diff 与契约，给出 Critical/Important/Suggestion |
| 两位原实现者 | 复审修复 | C1（前端）、I1/I2（后端与测试） |

## 4. 产出

- `backend/app/schemas.py`：`ActivityBatchTaskDraft`、`ActivityPublishBatchIn`。
- `backend/app/services/activity_service.py`：`publish_batch` 及 `_resolve_batch_keys` / `_assert_acyclic` / `_validate_batch_drafts` / `_build_batch_task`。
- `backend/app/routers/activities.py`：`POST /api/activities/publish-batch`，响应 `{activity, tasks}`，commit 后知识库索引。
- `frontend/src/api/activities.ts`：`publishActivityBatch`；`frontend/src/types/models.ts`：批量发布类型。
- `frontend/src/views/PublishActivityPage.vue`：多任务编辑区、依赖/父任务选择、前端校验、成功后跳活动详情。
- `tests/backend/test_v1_batch_publish.py`：12 个用例（成功 0 任务、4 任务含依赖/子任务/自动 key、KB 索引、flush 后失败回滚、成环、未知 key、跨层级、重复 key、父自指、三层父任务、org 不存在、member 4030）。

## 5. 真实问题

- **C1（审查，Critical）**：父任务 `el-select` 清空时 element-plus 2.14.8 发出 `undefined`，页面 `=== null` 判断失效，误报「父任务已不存在」并阻止提交。
  修复：`:model-value` + `@update:model-value` 统一归一到 `string|null`，`@clear` 兜底；校验/候选/预览全部走 `normalizeParentKey`；顺带补依赖同层过滤与按钮 `aria-label`。
- **I1（审查，Important）**：批量发布任务未写 `kb_entries`，会永久缺席相似任务提示。
  修复：commit 后按任务复用 `_index_task_safe`；先固化响应快照再索引，索引失败不回滚已发布数据。
- **I2（审查，Important）**：原有 4 个失败用例都在写库前抛出，`rollback` 分支从未执行，属假通过成分。
  修复：新增 `monkeypatch replace_dependencies` 在 flush 后抛异常的用例，断言活动/任务/依赖计数不变；补重复 key、父自指、三层、4040 边界。
- 未处置 Suggestion（记录在审查结论中）：`depends_on_keys` 未 strip、`parent_id` 语义、无 tasks 上限、commit 后序列化失败会 5000、跨路由私有导入、预览口径差异、测试辅助死代码、临时目录清理。

## 6. 验证（实际执行）

| 命令（工作目录） | 结果 |
|---|---|
| `python -m pytest tests/backend/test_v1_batch_publish.py -q`（仓库根，`PYTHON_BIN=$(command -v python)`） | **12 passed** in 2.87s |
| `python -m pytest tests/backend/test_activity_hierarchy.py -q` | **13 passed** |
| `python -m pytest tests/backend/test_task_graph.py -q` | **13 passed** |
| `python -m pytest tests/backend/test_activity_workflow.py -q` | **8 passed** |
| `npm run typecheck`（frontend） | 退出码 0，无输出 |
| `npm run build`（frontend） | 退出码 0（仅既有 chunk >500kB 提示） |
| `python tests/frontend/check_contracts.py --frontend .`（frontend） | **43 passed, 0 failed** |
| `git status --short` | 仅 6 个修改文件 + 1 个新增测试 |

- 测试隔离：import app 前设置临时 `DATABASE_PATH`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`；未触碰 `backend/campus.db`，无 `.coverage` 残留。
- 独立审查：1 Critical / 2 Important / 9 Suggestion，C 与 I 全部关闭；未开第二轮复审（修复后门禁已复跑）。
- **未验证**：浏览器端真实交互（未启动服务/未授权浏览器动作）；后端全量 `run_all`；CI 结果在提交后补记。

## 7. 状态

- 本地完成 + 独立审查修复完成 → 待提交、推送、CI。
- 下一阶段：S2 成果提交方式与验收要求（契约 `C-SUBMISSION-POLICY@1` 已冻结）。