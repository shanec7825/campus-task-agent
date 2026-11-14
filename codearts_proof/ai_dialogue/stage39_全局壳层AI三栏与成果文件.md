# 阶段 39 · 全局壳层、AI 三栏、通知归档与成果文件

> 日期：2026-11-14（Asia/Shanghai）。平台：华为云码道（CodeArts）。主 Agent 串行实现与验证，独立只读审查 1 名 team-code-reviewer。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
> 需求来源：用户本轮原文（成就空窗；文件链路确认；全局 UI 改版；AI 三栏；悬浮输入三态；通知归档）。

## 1. 需求与边界

1. 成就规则保持空窗：不新增规则、接口、积分或奖励。
2. 文件方案确认：需要文件的是「成员提交成果 → 预审 → 人工验收」链路；Library 仍只存链接。按最小方案实现。
3. 全局 UI：折叠/展开仅图标；删除「最近」总标题，只保留「最近活动」「最近聊天」；发布入口改为 New chat 样式；搜索与折叠移到侧栏右上。
4. AI 页三栏：左全局导航 + 中 AI 问答 + 右通知/消息；移除独立「消息」入口。
5. 全局底部悬浮输入三态：小条 → 点 `^` 展开中框（可见部分问答）→ AI 页面；任意页可提问与语音。
6. 通知支持归档，左侧导航「归档通知」；未归档通知只在 AI 页右栏。
7. 不做：第三方 PDF/DOCX 解析依赖、成就规则、真机/真实模型、部署。

## 2. 决策与契约

| 决策 | 结论 |
| --- | --- |
| 文件传输 | 不安装 `python-multipart`（D-04 不擅自新增依赖），改为 JSON + base64 上传；下载用 `FileResponse` |
| 格式/大小 | TXT/Markdown/PDF/DOCX，≤10MB；TXT/Markdown 参与预审取文，PDF/DOCX 只存储并提示补文字 |
| 存储 | `backend/uploads/submissions/<task_id>/<uuid>.<ext>`，加入 `.gitignore`；DB 只存相对路径 |
| 下载权限 | 提交者本人或审核者（`require_submission_access`）；越权 4030/4040 |
| 通知归档 | `notifications.archived/archived_at` 增量列；默认列表不含归档；`POST /archive` 幂等；不改已读 |
| 未读口径 | 只统计未归档、未失效、`is_read=0` |
| AI 三栏 | `grid-template-columns: minmax(0,1fr) 320px`；<1024px 单列堆叠；右栏 `inbox/archive` 深链 `?panel=archive` |
| 旧消息路由 | `/messages` 重定向 `/ai?panel=inbox`；删除导航与「查看全部消息」 |
| 悬浮输入 | 非 AI 页显示；发送时先 `router.push('/ai')` 再走既有 `aiChat.send`；语音复用 `AgentVoiceButton` |
| 成就 | 空窗，不实现 |

契约：`C-NOTICE-ARCHIVE@1`、`C-AI-THREE-PANE@1`、`C-GLOBAL-COMPOSER@1`、`C-SHELL-ACTIONS@1`、`C-SUBMISSION-FILE@1`、`C-ACCOMPLISHMENT-EMPTY@1`（`ui-shell-chat/design.md` §2）。

## 3. 产出

- 后端：`models.py`（通知归档 2 列、成果文件 4 列）、`db.py`（幂等迁移）、`schemas.py`（`ArchiveIn`、`SubmissionFileIn`、成果/通知字段）、`routers/notifications.py`（列表归档参数、`/archive`）、`routers/tasks.py`（`/submissions/upload`、`/submissions/{id}/file`）、`services/submission_service.py`（校验/落盘/TXT-MD 取文）。
- 测试：`tests/backend/test_notice_archive.py`（3）、`tests/backend/test_submission_file.py`（4）。
- 前端：`layouts/AppLayout.vue`（图标折叠、右上操作区、New chat 发布、最近活动/最近聊天、归档导航、悬浮输入挂载）、`components/shell/GlobalComposer.vue`（三态）、`views/AiConsole.vue`（三栏 + 归档箱）、`stores/notifications.ts` + `api/notifications.ts`（归档）、`api/tasks.ts` + `views/TaskDetail.vue`（文件选择/上传/下载）、`components/nav/NavIcon.vue`（archive/panel-left/panel-right）、`router/index.ts`（旧消息重定向）。
- 契约：`check_contracts.py` 新增 ㊴–㊷ 共 4 项，更新 ㉗（最近聊天/New chat 发布）；`test_build.sh` 的 `: any` 正则加词边界（`overflow-wrap: anywhere` 误报）。

## 4. 验证（本轮实跑）

| 入口 | 结果 |
|---|---|
| `tests/backend/test_notice_archive.py` | **3 passed** |
| `tests/backend/test_submission_file.py` | **4 passed** |
| `tests/backend/test_aiw04_resource_review.py` | **15 passed** |
| `tests/frontend/run_all.sh` | **ALL PASS**（构建 4/4、契约 **43/43**、语音 21/21） |
| 浏览器 `work/aiw13/verify-stage39.cjs` | **42/42 PASS**：图标折叠、最近活动/最近聊天、New chat、搜索/折叠右上、小条 58px、中框未满屏、AI 页隐藏、**左问答右通知**、右栏折叠 48px、1025 不压侧栏、归档箱与全部已读、Profile 无通知中心、旧 `/messages` 重定向、390 不遮挡底栏与无溢出、文件选择/提示/上传/下载展示 |
| 后端 `run_all.sh` | 见 `work/aiw14/backend-runall-stage39.log`（收口核对，不覆盖 pytest） |

## 5. 真实问题与修复

1. `python-multipart` 未安装 → 不新增依赖，改 JSON base64 上传。
2. 下载路由最初漏 `require_submission_access`，越权测试返回 200 文件 → 已补权限校验并复测 4040/4030。
3. `list_submissions` 未投影文件字段 → `file_name` 为 null，已补。
4. 重复提交时非法文件曾返回 0 → 将格式/大小校验前置到 `record_submit` 之前。
5. 移动抽屉仍残留「最近」「最近任务」→ 同步改为「最近活动」「最近聊天」。
6. 前端构建门禁误报：`overflow-wrap: anywhere` 命中 `: any` → 正则加 `\b`，未放宽基线。
7. 旧契约 ㉗ 要求「最近任务/AI 历史」，与新需求冲突 → 按惯例更新断言口径并补「最近聊天/发布事务」断言。

## 6. 审查与修复（首轮 3 Critical / 15 Important）

首轮判定「不可提交」，已修复并复跑：
1. `test_build.sh` 的 any 门禁被写成退格字符 → 改为 `([^A-Za-z]|$)`，实测命中 `: any`/`as any`、不命中 `anywhere`。
2. AI 三栏 DOM 顺序导致通知在左 → 显式 grid 列（chat 1 / notice 2），浏览器 240 < 1088。
3. 移动端悬浮输入遮挡底部导航 → 底部偏移 bottom-nav 高度，浏览器 776 ≤ 784。
4. 右栏折叠 48px + `cta_ai_notice_panel`；<1024 明确为上下堆叠（design 同步，不做第二套抽屉）。
5. 通知列表补 `total`/`offset`；`design` 更新 base64 与 4030/4040 口径。
6. base64 先限长再解码；commit 失败删除已落盘文件；`changed=False` 返回 4090。
7. 下载补 `require_submission_access`；PDF/DOCX 无文字时固定 `ai_error`。
8. composer 等待历史加载、录音中禁用发送、`sent=false` 提示。
9. 桌面宽 1025–1440 改右侧悬浮；移动留白 104px。
10. Profile 删除通知中心，未读入口跳 AI（新增契约 ㊸）；AI 右栏补「全部已读」。
11. CI 接入 4 个 pytest 套件（AIW-10/14、归档、文件）。

仍未处置并登记：移动端通知抽屉（改堆叠）、MIME 非双检、`test_notice_archive` 测试间数据累积、composer 移动端仍用 transform、`list_submissions` 每提交者 digest 开销。
- 复核：已向同一审查会话提交修复清单请求第二轮复核，但该会话结束时未返回新的复核结论；因此**本轮最后一批修复未经独立第二轮复核**。为避免把自查冒充复核，本条如实登记。首轮 Critical/Important 的修复均有可复跑门禁或浏览器证据。
- 额外实测：`work/aiw13/verify-composer-send.cjs` 在非 AI 页小条输入并回车，实测落到 `/ai?conversation=5`、消息列表出现该问题、输入框清空（未丢发）。
- 未验证：PDF/DOCX 正文解析（无依赖，明确只存储）、真实模型、真机、人工晚会链路、深色主题复测、部署；成就保持空窗；移动端通知抽屉按设计改为堆叠、MIME 非双检。
- 已提交 `15e7e48`（133 files）并推送 origin/main；CI `43592712459` 四 job success（Frontend、Backend Windows、Backend Ubuntu、Integration）；未部署。
- 本地运行：后端 8000 + 前端 5173，迁移列已补齐。