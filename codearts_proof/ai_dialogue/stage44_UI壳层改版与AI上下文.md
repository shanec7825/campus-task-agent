# 阶段 44 · UI 壳层改版、Library 收敛与 AI 上下文

> 日期：2026-11-14（Asia/Shanghai）。起点：`f4963bd`（工作区干净）。
> 计划（本地，Git 忽略）：`.codeartsdoer/plans/v1-ui-shell-refine/{design,task}.md`。
> 记录口径：本阶段未提交、未推送、无新 CI、未部署。

## 1. 需求来源与边界

用户以 7 张截图 + 6 条文字提出界面与交互问题，要求「分析需求、制定计划、逐步实现」：

1. 左侧导航改为 ChatGPT 式默认展开、打开即可看全，不再靠滚动；历史区改为「活动 / 任务 / 聊天」三选一胶囊，只显示最近条目；「查看全部」跳到对应浏览页，不在侧栏继续堆文字历史；删除与「任务大厅」重复的「我的任务」一级入口；底部「个人主页」文字图标改为头像（默认头像 + 可上传），点击进个人主页。
2. 任务大厅「全部 / 我的」与活动/任务切换统一为胶囊分段控件。
3. Library 删除「我的参考链接」区，只保留 AI 检索/引用资料。
4. 「归档通知」作为垃圾箱放到侧栏最底部，页面只保留一行行圆角长条消息，去掉说明性文字。
5. AI 助手页删除说明性文字，只保留聊天历史；输入框附近增加权限选择（只分析 / 可操作）。
6. 输入框支持 `@` 弹出「任务上下文 / 活动上下文 / 我的 Library 资料上下文」；删除右上角无效的「打开工作台」，只保留「新对话」「历史记录」。

边界与取舍：
- 「可操作」按用户括注「如果 ai 可以实现操作、提交的话」处理：后端当前没有 AI 写操作通道，因此该选项保留但禁用，`changeAccessMode` 拒绝写入 `operate`，**不会发出任何写请求**，不伪造能力。
- 头像上传的前端校验（类型 + ≤200KB）与后端二次校验（前缀、长度、base64 可解码）都实现，但未做真实浏览器上传端到端。
- 归档页只读，不提供取消归档（后端无该接口）。
- `/my-tasks` 路由与既有深链保留，只从一级导航移除。
- 移动端底部导航、AI 只读语义、全局悬浮输入、权限模型均不改。

## 2. 决策与契约

- `C-AVATAR-API@1`：`users.avatar TEXT NULL` 存 `data:image/png|jpeg|webp;base64,…`；幂等 ALTER 补丁；`PATCH /api/auth/avatar`（CSRF、本人写入、`4001` 格式无效、≤280000 字符、返回 `UserOut`）。
- `C-AVATAR-UI@1`：`User.avatar`、`updateAvatar()`、`userStore.setAvatar()`、`UserAvatar.avatar` prop + `<img class="avatar__image">` 分支、Profile 上传/移除。
- `C-SEGMENTED@1`：`SegmentedTabs.vue`（`modelValue/options/ariaLabel`、`update:modelValue/change`、tablist/tab、方向键、`--app-touch` 与 999px 胶囊、768px 铺满）。
- `C-SIDEBAR@1`：折叠键改为 `cta_sidebar_collapsed_v2`（首次必展开）；`.sidebar-scroll` 改 `overflow: hidden`；`HISTORY_TABS` 与 `cta_sidebar_history_tab`；三组「查看全部」分别跳 `/my-tasks?type=activity`、`/my-tasks?type=task`、`/ai?history=1`；`mainNav` 只留 AI / 任务大厅 / Library；归档入口固定在底部并指向 `name:'archive'`；个人入口改 `foot-user` 头像按钮。
- `C-TASKHALL-FILTER@1`：桌面与抽屉两处共 6 个 `el-radio-group` 换成 `SegmentedTabs`（范围/状态/类型），查询与清理逻辑不变。
- `C-LIBRARY-PAGE@1`：删除「我的参考链接」整块及其状态、函数、import；保留我的引用资料 / 活动任务资料 / 组织资料；后端 `/api/library/links` 接口保留。
- `C-ARCHIVE-PAGE@1`：新增 `/archive`（`name:'archive'`），一行长条圆角、仅标题 + 时间、有 `task_id` 跳详情，空态仅「暂无归档」。
- `C-AI-CONTEXT@1`：`AiChatIn.resource_ids`、`ai_service.chat(..., resource_ids=)`、去重升序取前 5、按组织/`allow_student_ai`/`archived=0`/`text_status='ready'` 过滤、与关键词结果按 `resource_id` 去重、命中即经既有自动收藏入引用。
- `C-AI-PAGE@1`：删除副标题、当前目标、`section-hint`、演示模式标签/提示、建议区、额度说明、输入提示、空态说明、「打开工作台」「刷新对话」；保留标题/消息/引用/新对话/历史记录/额度单行/输入框/语音/发送；权限胶囊 `analyze|operate`（operate 禁用）；`ContextPicker` 三组上下文。

## 3. 实际派工

| 角色 | 任务 | 说明 |
|---|---|---|
| 后端工程师（DeepSeek-V4.1-Flash-1017） | T1 | 头像列/接口 + `resource_ids` 服务 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T2 | 头像组件、store、Profile 上传 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T3 | 侧栏展开/胶囊/底部入口 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T4 | 胶囊组件 + 大厅筛选 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T5 | Library 收敛 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T6 | 归档页 + 路由 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T7 | AI 页精简 + 权限 + `@` 面板 |
| 前端工程师（DeepSeek-V4.1-Flash-1017） | T8/T9 | 静态契约 50 项同步与 5 项口径修正 |
| 独立审查员（team-code-reviewer） | T10 | 本轮 diff 只读审查 |
| team-leader | 编排 | 契约冻结、派工、门禁、留痕 |

初始 ready set = 7（T1–T7 全部 `blocked_by: []`）；T8 依赖全部前端任务，T9 依赖 T8，均按序解锁。

## 4. 产出

- 后端：`backend/app/{models,db,schemas}.py`、`routers/auth.py`、`routers/agent.py`、`services/ai_service.py`。
- 前端新增：`components/common/SegmentedTabs.vue`、`components/ai/ContextPicker.vue`、`views/ArchivePage.vue`。
- 前端修改：`layouts/AppLayout.vue`、`views/{AiConsole,LibraryPage,Profile,TaskHall}.vue`、`router/index.ts`、`api/{auth,agent}.ts`、`stores/{user,aiChat}.ts`、`types/models.ts`、`components/common/UserAvatar.vue`。
- 门禁：`tests/frontend/check_contracts.py`（㉗/㉙/㉝/㊴/㊶/㊽ 更新 + ㊼–㊿ 新增，共 50 项）。

## 5. 真实问题

1. **静态契约 5 项首跑失败，全部是断言口径过严，不是实现缺陷**：
   - `historyTab` 初值为 `readHistoryTab()`，函数体内 `return 'activity'` 兜底；断言要求字面量 `ref('activity')` → 改为接受函数兜底。
   - `withDefaults(..., { size: 'xs', avatar: null })` 同行书写，断言找 `{ size: 'xs' }` → 改为窗口内匹配。
   - `archiveNav` 与 `bottomNav` 第三项合法使用 `icon: 'archive'`（契约要求的底部入口），旧断言「全文件禁止」误伤 → 收窄为「`mainNav` 块内禁止」。
   - 移动端归档项一行书写且键序不同 → 改为同对象字面量内三键同时存在。
   - `刷新对话失败` 是错误提示文案，被按钮禁用词误伤 → 改为只禁 `>刷新对话<`。
   - `aria-disabled`/`title` 由运行时 `setAttribute`/`.title =` 设置，静态 token 找不到 → 改为等价正则。
   - Profile 移除走 `applyAvatar(null)` 间接调用 `updateAvatar` → 接受两种路径。
   - 处理原则：不删检查项、不放宽业务语义，只承认等价写法。
2. **契约缺口**：`SegmentedTabs` 没有单选项禁用能力，T7 只能在挂载后用 `.segmented-tabs__tab` 补 `disabled/aria-disabled/title`，并同时由 `changeAccessMode` 拒绝 `operate` 双重保障。若后续要长期保留禁用项，应给组件加 `disabledValues` prop（本阶段未扩大契约）。
3. **契约文字与实现偏差（已登记未改）**：`AiChatIn.resource_ids: list[int]` 在 Pydantic 层对非整数字符串直接 422，而契约写「非法 id 忽略」；服务层已做 `isinstance` 防御，schema 层不忽略。当前前端只会发整数，实际不可达。
4. **响应包装不一致（已登记）**：`PATCH /api/auth/avatar` 按契约返回裸 `UserOut`，不套 `{code,msg,data}`；与项目统一约定不一致。前端按 `Promise<User>` 消费，功能可用，但风格偏离。
5. **侧栏不滚动的裁切风险**：`.sidebar-scroll` 改为 `overflow: hidden` 后，若视口高度不足会裁掉底部内容，且无法通过滚动到达。本阶段未做浏览器视口实测，只在 1080p 量级做了结构估算。
6. **独立审查 1 Critical / 4 Important**（详见 §7），全部处置：头像接口改为 `ok()` 包装 + 新增 12 个后端用例；侧栏改「隐藏滚动条 + 纵向兜底」并压到 3 条；`SegmentedTabs` 增加 `disabledValues` 与窄屏横向滚动；AI 页删除 DOM 补丁、`@` 不再进入正文。

## 7. 独立审查与修复

审查范围：19 个修改文件 + 3 个新增文件（只读，未改代码）。结论首轮「不可提交（需修 1 Critical）」。

- **C1（Critical）**：`PATCH /api/auth/avatar` 返回裸 `UserOut`，而 `frontend/src/api/client.ts` 的 `request()` 强制解包 `{code,msg,data}` → 后端写库成功但前端必抛「响应格式异常」，头像功能整体不可用，且 50 项静态契约只查前端文本查不到。
  修复：改为 `return ok(UserOut.model_validate(current_user).model_dump())`，去掉 `response_model`（避免 FastAPI 二次过滤）；新增 `tests/backend/test_v1_avatar.py` 12 用例（png/jpeg/webp 成功、覆盖、null/空串清除、非法前缀/非 data URL/不可解码 4001、超长 4001、缺 CSRF 4030、未登录 4010、幂等），并写入 `ci.yml` 独立 step。
- **I2（Important）侧栏裁切**：`overflow: hidden` + 4 条历史 + 底部 4 行，1440×900 管理者视图约 1000px，会裁掉「查看全部」。修复：`.sidebar-scroll` 改 `overflow-y: auto; overflow-x: hidden; scrollbar-width: none` + 隐藏 webkit 滚动条，`RECENT_LIMIT` 4→3（常态不出现滚动条，极端高度仍可达）。
- **I3（Important）/my-tasks 折叠不可达**：审查建议恢复入口。**不采纳并说明**：用户明确要求删除重复的「我的任务」一级入口；折叠是用户主动状态，展开即恢复；任务大厅的「我的」范围胶囊提供同类内容浏览。
- **I4（Important）头像无测试**：已由 C1 修复中的 12 个用例覆盖，并接入 CI。
- **I5（Important）移动端状态筛选溢出**：`all+7 状态` 共 8 项在 360px 抽屉内被 `flex:1 1 0` 压到约 36px。修复：`SegmentedTabs` 窄屏改 `overflow-x: auto` + 选项 `flex: 0 0 auto; white-space: nowrap`（横向滚动，不压缩）。
- **Suggestion 采纳**：`disabledValues` prop 替代 DOM 补丁（顺带修掉方向键落到禁用项的静默无反应）；`@` 键入改为 `preventDefault` 后打开面板（不残留字符、不会被当作空语义发送）。
- **Suggestion 未处置（登记）**：`HISTORY_TABS/ACCESS_OPTIONS` 的 `string` 类型可进一步收紧；localStorage 仍缓存 data URL 头像；未校验文件魔数；`resource_ids` 非整数在 schema 层为 422；`_pinned_doc_context` 独立 1200 字符预算；`ContextPicker` 无 Escape/焦点管理；Library/TaskHall/AppLayout 有残留空行与 `.library-link__url` 死选择器。
- 复审：修复后未开第二轮独立审查（按「最多三轮」内本可开，但修复项均有新断言与用例覆盖），如实登记。

## 8. 验证与未完成项

实际执行的命令与结果：

- `frontend && npx vue-tsc --noEmit` → **EXIT=0**（0 error）。
- `frontend && npm run build` → **EXIT=0**（`vite build` 成功，7.80s，仅 chunk 体积告警）。
- `python tests/frontend/check_contracts.py` → **51 passed / 0 failed**（首轮机 50 项；T15 后新增 `C-AVATAR-API@1` 包装断言）。
- `python -m py_compile backend/app/{models,db,schemas,routers/auth,routers/agent,services/ai_service}.py` → **EXIT=0**。
- 后端 pytest（每个进程独立临时 `DATABASE_PATH`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：
  - `test_ai_console.py` + `test_agent_mock.py` → **11 passed**；
  - `test_v1_ai_context.py` + `test_notice_archive.py` → **14 passed / 1 skipped**；
  - `test_auth_org_permissions.py` → **47 passed**；
  - `test_aiw09_context_scope.py` + `test_aiw09_history.py` → **14 passed**；
  - `test_v1_avatar.py`（本阶段新增）→ **12 passed**。
- 修复后复跑：`frontend && npx vue-tsc --noEmit` → **EXIT=0**；`npm run build` → **EXIT=0**（7.58s）；契约 **51/51**。

未验证（如实登记）：
- 浏览器实际交互与视觉：侧栏在 1440×900 / 1920×1080 是否真的无需滚动、深色主题、移动抽屉、头像真实上传、`@` 面板键盘路径、归档长条点击跳转。
- 「可操作」禁用态的实际渲染（依赖运行时 DOM 补属性）。
- 真机、真实模型、部署。
- 后端全量 `tests/backend/run_all.sh` 与安全红线脚本本轮未跑；CI 未触发（未提交）。