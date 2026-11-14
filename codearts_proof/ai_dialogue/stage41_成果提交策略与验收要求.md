# 阶段 41 · V1 S2：成果提交方式与验收要求

> 日期：2026-11-14（Asia/Shanghai）。前序：`54bc81e`（S1），CI `43594367179` success。
> 计划（本地）：`.codeartsdoer/plans/v1-baseline/s2-submission-policy/{design,task}.md`。

## 1. 需求来源与边界

- V1 需求 §三「文件提交还应该改造任务发布表单」与 §五 P0「任务文件提交与验收」。
- 本阶段只做「任务级成果要求 + 服务端强制校验 + 验收要求编辑入口」；文件上传/下载/版本/退回/通过沿用 stage39 既有实现，不改其协议。
- 不涉及组织资料库、文档解析、AI 检索（S3 起）。

## 2. 决策与契约（`C-SUBMISSION-POLICY@1`）

- 策略存于既有 `tasks.extras["acceptance"]`，不新增表/列：`{modes:["text","link","file"], allowed_exts:[...], ai_precheck:bool}`。
- 未配置策略的历史任务保持宽松（空提交仍允许）；已配置任务按策略强制，非法通道/扩展名 4001 且无副作用（不落盘、不新增版本、不改成员状态）。
- `allowed_exts` 为空集语义 = 未限定类型，回退全局白名单（`.pdf/.docx/.txt/.md`），前后端统一。
- PATCH `extras` 改为**合并语义**：保留其它键，仅替换 `acceptance`；显式 `acceptance:null` 移除该键。
- 批量发布同样在写库前 `normalize_acceptance`，非法 acceptance → 4001，整批回滚。
- 编辑既有任务的成果要求落在后台任务操作区（新增「成果要求」对话框），保存时先取最新 `extras` 再合并，避免清空其它扩展键。
- 新增两个测试文件加入 CI 逐文件清单，避免「写了测试但门禁不跑」。

## 3. 实际派工

| 角色 | 任务 | 说明 |
|---|---|---|
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T2-1 + I2 修复 | schemas/submission_service/tasks 路由 + 测试；后续补批量归一与 PATCH 合并 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T2-2 + C1/I1 修复 | 发布表单成果要求、任务详情按策略渲染；后续补空扩展名回退与后台编辑入口 |
| 独立审查员（team-mate） | S2 审查 | 只读 diff 与契约，1 Critical / 3 Important / 8 Suggestion |
| team-leader | CI 门禁 | `.github/workflows/ci.yml` 增加 V1 两套测试步骤 |

## 4. 产出

- 后端：`schemas.SubmissionAcceptance` / `normalize_acceptance`；`submission_service.task_acceptance` / `enforce_submit_policy` / `validate_upload_against_policy`；`tasks.py` 创建/编辑/提交/上传四处接入；`activity_service` 批量发布归一。
- 前端：`types/models.ts` 的 `SubmissionAcceptance`、`parseSubmissionAcceptance`、`effectiveSubmissionFileExts`、`submissionAcceptanceSummary`；`ManualForm.vue`「成果要求」区块；`TaskDetail.vue` 按策略渲染；`AdminConsole.vue` 成果要求编辑对话框与摘要。
- 测试：`tests/backend/test_v1_submission_policy.py`（10 用例）、`tests/backend/test_v1_batch_publish.py` 扩到 14 用例；CI 新增步骤。

## 5. 真实问题

- **C1（审查，Critical）**：`allowed_exts=[]` 时前端 `some()` 恒 false → 学生文件通道完全不可用，且 `accept=""` 不限类型。修复：`effectiveSubmissionFileExts` 空集回退四类；扩展名统一 `toLowerCase()`；删除「允许类型：无」文案。
- **I1（审查，Important）**：`ManualForm` 的 `task` 回显是死代码，前端没有编辑既有任务的入口，R2-01 编辑部分缺失。修复：后台任务操作区新增「成果要求」对话框，先取最新 `extras` 再合并保存。
- **I2（审查，Important）**：批量发布直接写原始 `extras`，非法 acceptance 不报错而静默降级；PATCH extras 整体替换会清空其它键。修复：校验阶段返回规范化 extras 供写入；PATCH 改合并语义。
- **I3（审查，Important）**：新增测试未进 CI，等于无回归门禁。修复：`.github/workflows/ci.yml` 增加 V1 两套测试步骤。
- Suggestion 未处置（记录在审查结论）：手动发布默认写策略导致空提交变严格、PATCH 丢键风险已消除但通用 null-delete 未做、upload 的 content 未受策略约束、前后端规范化口径细节、AI extra_tags 未排除保留键、预审按钮 primary 语义、部分边界用例缺失。

## 6. 验证（实际执行）

| 命令（工作目录） | 结果 |
|---|---|
| `python -m pytest tests/backend/test_v1_submission_policy.py -q` | **10 passed** |
| `python -m pytest tests/backend/test_v1_batch_publish.py -q` | **14 passed** |
| `python -m pytest tests/backend/test_submission_file.py -q` | **4 passed** |
| `python -m pytest tests/backend/test_aiw06_acceptance.py -q` | **1 passed** |
| `npm run typecheck`（frontend） | 退出码 0 |
| `npm run build`（frontend） | 退出码 0 |
| `python tests/frontend/check_contracts.py --frontend .` | **43 passed, 0 failed** |
| `python -c "yaml.safe_load(ci.yml)"` | 3 jobs / 15 steps，YAML 合法 |

- 测试隔离：临时 `DATABASE_PATH`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、临时上传目录。
- 独立审查：1 Critical / 3 Important 全部关闭；未开第二轮独立复审（修复后门禁已复跑，如实登记）。
- **未验证**：浏览器端成果要求编辑与提交端到端（未启动服务）；移动端 768px 实际布局；后端全量 `run_all`；CI 结果提交后补记。

## 7. 状态

- 本地实现 + 审查修复完成 → 待提交、推送、CI。
- 下一阶段：S3 组织资料库 + 文档解析 + 检索开关（契约 `C-DOC-PARSE@1`、`C-ORG-LIBRARY@1` 已冻结）。