# 阶段 42 · V1 S3 + S4：组织资料库、文档解析、AI 检索与引用收藏

> 日期：2026-11-14（Asia/Shanghai）。前序：`1584e9d`（S2），CI `43595815147` success。
> 计划（本地）：`.codeartsdoer/plans/v1-baseline/s3-org-library/{design,task}.md`、`s4-ai-library/{design,task}.md`。

## 1. 需求来源与边界

- V1 §二 Library 规格（组织资料 + 开关 + 引用式收藏）、§三 文件处理第一版（PDF/DOCX/TXT/MD 上传与解析）、§四 两类检索、§五 P0「组织资料 AI 检索开关」+ P1「文档全文解析 / 学生个人 Library / AI 任务查询增强」。
- 本阶段合并交付 S3 与 S4：两者共用 `org_resources`、`search_allowed` 与 Library 页，且 S4 直接消费 S3 产物，分开提交会在同一文件中产生无法干净拆分的混合改动，故合并为一次提交并在本记录说明（偏离「一阶段一提交」的口径已如实登记）。
- 不涉及 S5（AI 任务树草案、PDF/DOCX 预审、成果归档）与 S6（部署验收）。

## 2. 决策与契约

- S3：新表 `org_resources`（18 列 + 两索引），文件落盘 `ORG_LIBRARY_UPLOAD_ROOT`；解析 `document_service.extract_text` 永不抛异常；开关 `allow_student_ai` 默认 0；归档从检索范围排除；下载 S3 期仅管理者，S4 起对有效引用开放。
- 解析上限：PDF ≤300 页且累计 ≤200k 字符提前停止；DOCX 读取前校验 `file_size ≤40MB` 与压缩比 ≤200，并分块累计读取；base64 解码前按声明大小反推长度并设 20MB 绝对上限。
- S4：`library_refs` 引用式收藏（不复制文件）；可见性实时判定，撤回只计数不展示；下载鉴权失败统一 4040（不区分不存在/无权限）。
- S4：`task_query_service.build_task_context` 按关键词/意图打分（标题/SOP/活动名 +2、逾期 +2、待验收/待办 +1、作用域 +1），无命中退化为最近任务；上下文带 SOP、验收要求、最新成果、验收结果。
- S4：文档上下文 ≤3 条、单片段 ≤300 字符、总量 ≤1200；citation 增加 `kind`/`resource_id`，旧数据缺省按 task；回答后 `record_citations` 独立短事务，失败不影响回答。
- AI 仍只做检索/建议，不代替发布、验收、归档。

## 3. 实际派工

| 角色 | 任务 | 说明 |
|---|---|---|
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T3-1 | 解析服务、`OrgResource`、schemas、requirements、解析测试 |
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T3-2 | 组织资料服务与四接口、`search_allowed`、测试 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T3-3 | Library 组织资料区、`api/orgResources.ts`、契约 ㊹ |
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T4-1 | `library_refs`、refs 接口、下载可见性、测试 |
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T4-2 | 任务查询服务、AI doc 上下文与 citation、测试 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T4-3 | 我的引用资料区、AI 来源标签、契约 ㊺ |
| 独立审查员（team-mate） | S3 审查 | 1 Critical / 3 Important / 11 Suggestion |
| 后端工程师（S3-2） | S3 修复 | 解析/上传上限、下载改管理者、检索限流、断言同步 4040 |
| team-leader | CI 门禁 | 新增 3 个独立 step（batch/policy、document parse、org library），避免同进程隔离失效 |

## 4. 产出

- 后端：`services/document_service.py`、`models.OrgResource`、`services/org_library_service.py`、`routers/org_resources.py`、`models.LibraryRef`、`services/library_ref_service.py`、`routers/library.py` 的 refs 接口、`services/task_query_service.py`、`ai_service` 上下文与 citation 扩展、`main.py` 注册、`requirements.txt`（`pypdf`）。
- 前端：`api/orgResources.ts`、`api/library.ts`、`types/models.ts`（`OrgResource`/`LibraryRef`/`AiCitation.kind`）、`LibraryPage.vue`（组织资料区 + 我的引用资料）、`AiConsole.vue`（来源标签与跳转）。
- 测试：`test_v1_document_parse.py`（26）、`test_v1_org_library.py`（10）、`test_v1_library_refs.py`（6）、`test_v1_ai_context.py`（9）；前端契约新增 ㊹/㊺（45 项）。

## 5. 真实问题

- **S3 C1（审查，Critical）**：解析/上传缺资源上限，组织成员可用单请求打爆内存（DOCX zip bomb、PDF 无页数上限、base64 先解码后校验）。修复：三类上限均前移到解码/解压前，并补 3 条回归用例。
- **S3 I1（审查，Important）**：下载权限实现「仅上传者」与契约「admin/collaborator」冲突，前端对全部管理者显示下载却必失败。裁定：同组织 admin/collaborator 可下载；S4 再扩展有效引用；鉴权失败统一 4040。
- **S3 I2（审查，Important）**：`search_allowed` 对全文逐段分词，挂到 AI 路径会有秒级延迟。修复：候选资料 ≤50（按 `updated_at DESC`）、每段 ≤2000 字符、每份 ≤20 段、正文先截 20000 字符。
- **S3 I3（审查，Important）**：CI 把两个新测试放在同一 pytest 进程，第二个文件的 `DATABASE_PATH` 不生效，隔离是假象。修复：拆为两个独立 step。
- **S4 C1（审查，Critical）**：任务上下文把他人成果（content/resource_url/file_name/rejection_reason）送入模型，绕过成果可见性。修复：非审阅者只取本人最新提交与本人成员行，`review_result` 只依据 `task.status`；补「学生 B 查询学生 A 已提交任务」用例。
- **S4 I1（审查，Important）**：`has_active_ref` 缺组织可见性，学生被移出组织后仍可下载。修复：引用可见性统一走 `_accessible_resources`，补「移出组织→撤回计数+下载 4040→重新加入恢复」用例。
- **S4 I2（审查，Important）**：`kind="activity"` 永不产生，前端活动标签是死代码。裁定：来源标签收敛为「任务 / 资料」二值，`AiCitation.type` 补 `doc`，未知 kind 兜底 task；契约 ㊺ 改为结构化断言。
- **S4 I3（审查，Important）**：`_with_docs` 让任务 citation 占满 5 条导致 doc citation 被丢，正文却列出参考资料。修复：doc 预留槽位且优先保留，补满额用例。
- **S4 I4（审查，Important）**：`test_v1_library_refs.py` / `test_v1_ai_context.py` 未进 CI。修复：各自独立 step（CI 现有 19 步）。
- **S4 I5（审查，Important）**：任务检索每次对 SOP 全文分词，问答链路可能秒级。修复：无关键词跳过打分、问题 ≤500 字符、标题/SOP/描述 ≤2000 字符再分词、成员与成果查询只对最终入选任务执行（补查询数 <40 用例）。
- **S4 跨阶段冲突**：S3 测试对 member/外组织下载断言 4030，与 `C-LIB-REF@1` 的 4040 冲突；裁决以 4040 为准，S3 测试同步更新。
- **S4-2 契约缺口**：`build_task_context` 追加 `activity_id`/`description` 以便复用旧 citation 与上下文展示；QA Prompt 未覆盖 D ref（不在写集），真实模型可能不引用文档，mock 已保证离线演示。
- 未处置 Suggestion：`Extras` 大小写/规范化口径、列表无分页、`_save_file` OSError、开关并发 PATCH 的 pending 态、`text_status` Literal 脏值、`authz` 未过滤 Organization.status、`search_allowed` 标题命中的 snippet 取首段、`limit=0` 返回 1 条等。

## 6. 验证（实际执行）

| 命令（工作目录） | 结果 |
|---|---|
| `python -m pytest tests/backend/test_v1_document_parse.py -q` | **26 passed** |
| `python -m pytest tests/backend/test_v1_org_library.py -q` | **10 passed** |
| `python -m pytest tests/backend/test_v1_library_refs.py -q` | **7 passed** |
| `python -m pytest tests/backend/test_v1_ai_context.py -q` | **14 passed** |
| `python -m pytest tests/backend/test_v1_batch_publish.py -q` | 14 passed |
| `python -m pytest tests/backend/test_v1_submission_policy.py -q` | 10 passed |
| AI 回归 6 文件（agent 执行） | 49 passed |
| 资料/引用回归 5 文件（agent 执行） | 39 passed, 2 skipped |
| `python -m pytest tests/backend -q`（agent 执行） | 247 passed, 5 skipped, 10 errors（全部在 `test_reliability.py`，同进程引擎绑定所致；单文件 11 passed） |
| `npm run typecheck` / `npm run build`（frontend） | 退出码 0 |
| `python tests/frontend/check_contracts.py --frontend .` | **45 passed, 0 failed** |
| `python -c "yaml.safe_load(ci.yml)"` | 3 jobs / 17 steps，YAML 合法 |

- 测试隔离：临时 `DATABASE_PATH`、`ORG_LIBRARY_UPLOAD_ROOT`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`；只走 mock，无真实模型调用。
- **未验证**：浏览器端真实联调（AI 问答带资料引用、引用区下载）；真实模型路径；移动端真机；后端全量 `run_all` 仅部分覆盖；CI 结果提交后补记。

## 7. 状态

- 本地实现 + S3/S4 两轮审查修复完成 → 待提交（S3+S4 合并）、推送、CI。
- 下一阶段：S5（AI 任务树草案、PDF/DOCX 预审、成果归档），S6 部署验收。