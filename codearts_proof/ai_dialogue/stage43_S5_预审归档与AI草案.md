# 阶段 43 · V1 S5：成果正文预审、优秀成果归档、AI 任务树草案

> 日期：2026-11-14（Asia/Shanghai）。前序：`504f1a5`（S3+S4）。
> 计划（本地）：`.codeartsdoer/plans/v1-baseline/s5-precheck-archive-draft/{design,task}.md`。

## 1. 需求来源与边界

- V1 §五 P1「AI 参考资料生成活动和任务」、P2「文件内容 AI 预审」「优秀成果归档」。
- 本阶段同时修复 stage42 的 CI 失败（`verify_tables.py` 仍固定 24 张表，新增 `org_resources`/`library_refs` 后应为 26），并新增可复现的部署冒烟脚本。
- 不包含 S6 的远程部署；AI 仍不代替发布、验收、归档。

## 2. 决策与契约

- `C-PRECHECK-TEXT@2`：`PARSEABLE_FILE_EXTS` 扩到 PDF/DOCX，预审取文复用 `document_service.extract_text`（继承页数/压缩比/字符上限）；AI payload 截断 8000 字符，规则检查仍用全量正文。
- `C-ARCHIVE@1`：`POST /api/org-resources/from-submission`；归档等同成果审核，使用 `submission_service.require_task_review` 窄口径（不使用含 assignee 的 `authz.can_manage_task`）；仅允许最新且成员 `verified` 的成果；`allow_student_ai=0`、`archived=0`；文件复制到组织资料目录、链接成果转 link；失败清理。
- `C-AI-DRAFT@1`：`POST /api/ai/task-draft`；只读不写库；资料检索限定调用者**可管理组织**（指定 `org_id` 时仅该组织，无可管理组织 4030）；真实模型每用户 60 秒 3 次（4290，mock 不受限）；草案归一丢弃重复 key、成环、跨层依赖、多层父子并记 warning，剩余草案可直接通过整批发布校验。
- 路由：`agent.py` 去掉 router 级 prefix、既有 7 条路由显式写全 `/api/agent/...`（URL 不变），新增 `/api/ai/task-draft`。
- 表基线上调为 26 张（真实新增两张表），并补两张表的列/索引断言；未放宽检查。
- 前端：发布页「AI 生成任务草案」只填任务行、不自动提交；后台在已验收成员行提供持久「归档到资料库」入口，归档弹窗说明默认关闭。

## 3. 实际派工

| 角色 | 任务 | 说明 |
|---|---|---|
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T5-1 | 预审取文、归档服务与接口、测试 |
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T5-2 | 草案服务、Prompt、路由、测试 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T5-3 | 发布页草案面板、后台归档入口、契约 ㊻ |
| 独立审查员（team-mate） | S5 审查 | 1 Critical / 6 Important / 8 Suggestion |
| 三位原实现者 | 复审修复 | 归档窄口径、payload 截断、检索范围、限流、结构校验、持久入口 |
| team-leader | 门禁 | CI 新增 S5 两个独立 step；表基线 24→26；部署冒烟脚本 |

## 4. 产出

- 后端：`submission_service.PARSEABLE_FILE_EXTS`/`MAX_PRECHECK_AI_CHARS`、`org_library_service.archive_submission`、`routers/org_resources.py` 的 `from-submission`、`task_draft_service.py`、`agents/prompts.TASK_DRAFT_SYSTEM_PROMPT`、`routers/agent.py` 新路由、`schemas.TaskDraft*`/`ArchiveSubmissionIn`。
- 前端：`api/ai.ts`、`api/orgResources.archiveSubmission`、`PublishActivityPage` 草案面板、`AdminConsole` 归档对话框与持久入口。
- 测试：`test_v1_archive_precheck.py`（8）、`test_v1_task_draft.py`（14）；CI 21 步；`verify_tables.py` 26 表；`tests/backend/run_all.sh` 文案同步。
- 部署：`scripts/deploy_smoke.py`（本机生产形态冒烟）。

## 5. 真实问题

- **C1（审查，Critical）**：归档用 `authz.require_task_manage`（含 assignee），被指派成员若同时是组织 collaborator 可归档他人成果 → 改用 `require_task_review` 窄口径，补 assignee 用例。
- **I1（审查，Important）**：预审正文放宽到 200k 后直接进模型 payload（约 25 倍 token）。修复：AI payload 截断 8000，规则检查仍用全量。
- **I2（审查，Important）**：草案检索按 `authz.org_ids_for` 含普通成员组织，选定 A 时可能引用 B 的资料。修复：仅检索可管理组织，学生调用 4030。
- **I3（审查，Important）**：真实模型草案无额度/限流。修复：每用户 60 秒 3 次限流（4290），mock 不受限；未接入额度账本已在 docstring 说明。
- **I4（审查，Important）**：重复 key 用 `setdefault` 静默改写依赖。修复：丢弃重复/非法任务、环内任务与下游，保留合法结构并记 warning；测试调用批量发布校验证明可发布。
- **I5（审查，Important）**：S5 两个测试未进 CI（连续第四轮同类缺口）。修复：各自独立 step（CI 21 步）。
- **I6（审查，Important）**：归档入口只在验收通过瞬间打开，关闭后无法再发起。修复：已验收成员行持久「归档到资料库」入口 + 原自动打开保留。
- **stage42 CI 失败**：`verify_tables.py` 固定 24 表，实际 26 → run `43598431620` 失败（Backend integration）。修复后本地 `bash tests/backend/run_all.sh` 全流程通过。
- 未处置 Suggestion：草案覆盖已填任务行无二次确认、归档写入 OSError 清理、部分弱断言/缺失用例、归档不校验任务 cancelled、错误码可枚举等。

## 6. 验证（实际执行）

| 命令（工作目录） | 结果 |
|---|---|
| `python -m pytest tests/backend/test_v1_archive_precheck.py -q` | **8 passed** |
| `python -m pytest tests/backend/test_v1_task_draft.py -q` | **14 passed** |
| `python -m pytest tests/backend/test_v1_ai_context.py -q` | **14 passed** |
| `python -m pytest tests/backend/test_v1_org_library.py -q` | **10 passed** |
| `python -m pytest tests/backend/test_v1_batch_publish.py -q` | **14 passed** |
| `python -m pytest tests/backend/test_v1_submission_policy.py -q` | **10 passed** |
| `python -m pytest tests/backend/test_ai_console.py -q` | 11 passed（agent 执行） |
| `bash tests/backend/run_all.sh` | 全流程通过（含 26 表、报名审批、链式增量、SSE 催办） |
| `npm run typecheck` / `npm run build` | 退出码 0 / 构建成功 |
| `python tests/frontend/check_contracts.py --frontend .` | **46 passed, 0 failed** |
| `python scripts/deploy_smoke.py` | 11/11 通过（见 S6 报告） |

- 测试隔离：临时 `DATABASE_PATH`、`ORG_LIBRARY_UPLOAD_ROOT`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`；真实模型分支用 monkeypatch，无外部调用。
- **未验证**：浏览器端真实交互（AI 草案填入、归档入口、预审正文展示）；真实模型质量；移动端真机；远程部署（无目标与凭据）。

## 7. 状态

- 本地实现 + 审查修复完成 → 待提交（stage43）、推送、CI。
- 之后执行 S6：本机生产形态部署验收（`scripts/deploy_smoke.py`），远程部署需用户提供目标与凭据。