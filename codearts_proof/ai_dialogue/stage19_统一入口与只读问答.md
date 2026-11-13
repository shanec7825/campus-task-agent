# 阶段 19：AIW-01 统一入口与权限内只读问答

> 状态：**本地完成，待提交**。本文件按 `docs/DEVELOPMENT_RECORDS.md` 的五节结构记录；提交、推送与 CI 状态在本轮实际发生后再回填。

## 1. 需求与开工基线（2026-11-13）

- 需求来源：用户本轮定时开发指令 + 本地总计划 AIW-01「统一入口」。
- 本轮边界：折叠侧栏、AI 默认首页、通知卡、持久会话、权限内只读问答；不做受控业务动作、额度账本、多会话面板、语音原生。
- 开工基线：分支 `main`，HEAD `f89481c`（stage18 文档回填），工作区 `git status --short` 为空；本轮无其他写入者迹象。
- AIW-00 / stage18 验收：提交 `4c3c875` 已推送，CI run 43453696153 四个 job success，故本次进入 AIW-01。
- 编号：沿用 `LOG.md` 下一顺位 **stage19**；历史行零改动。
- 计划：`.codeartsdoer/plans/aiw01-unified-entry/design.md`、`task.md`（本地忽略，未强制提交）。
- 本阶段未修改既有业务 Prompt 正文；新增只读问答 `QA_SYSTEM_PROMPT`，原因与验证见 §5。

## 2. 决策与实现

### 2.1 后端会话与只读问答

- 新增 `ai_conversations` / `ai_messages` 两张表，`create_all` 建表；旧库启动时自动补建，不删列、不删行。
- 会话按 `user_id` 归属：列表/详情/续写均校验；不存在或他人会话统一 4040「会话不存在」，HTTP 404。
- 上下文只来自 `authz.visible_task_filter`，按截止时间取最多 20 条，转换为纯值快照后交给模型。
- 引用由服务端把模型返回的 `ref` 映射为可见任务；无效/重复 ref 丢弃，模型输出的 ID/标题不落库。
- mock 模式不调用模型，使用同一可见上下文生成确定性回答，`mock=true`；真实路径失败按既有 5001/5002/5003。
- 事务边界：归属校验 → 可见上下文 → 结束只读事务（rollback，无写）→ 生成回答 → 写入两条消息并一次 commit；模型失败不留半条会话。

### 2.2 前端统一入口

- 新增 `/ai`（`AiConsole.vue`）；`/`、登录后、安全回退默认页均改为 `/ai`，`/workbench` 与旧深链保留。
- AI 页：通知卡复用通知 store（未读摘要，不依赖问答）；刷新恢复最近会话；引用可点击进入任务详情；mock 明确标注；历史加载失败不阻塞通知与发送。
- 桌面侧栏 208px ↔ 72px 折叠，状态存 `cta_sidebar_collapsed`；折叠后保留 `aria-label`/`title` 与 44px 触控；手机底部四项为 AI / 事务 / 消息 / 我的。
- 通知卡不提供“全部标为已读”，避免只处理部分列表却宣称全部；批量操作留在消息页。

### 2.3 数据与门禁

- `verify_tables.py` 期望表 16 → 18，新增两表断言；`/api/health` 由 `Base.metadata` 自动返回 18 表。
- `.github/workflows/ci.yml` 新增 `test_ai_console.py` 步骤（Ubuntu/Windows）；`docs/CI.md` 同步。
- `tests/backend/run_all.sh` 顶部注释与步骤名 9 表 → 18 表（仅文案，不改流程）。

## 3. 实际工具与派工

- 实现：主实现 Agent（本会话）完成全部代码、测试与文档；未使用其他实现型子 Agent，未开 worktree（单写入者）。
- 独立审查：使用 `general` 子 Agent 只读审查（任务 ID `ses_e2a64f48dffe3kmcp7fv6ry3pP`），共三轮。首轮 0 Critical / 8 Important / 14 Suggestion；第二轮 0 Critical / 3 Important（刷新失败静默、发送/刷新竞态、交接授权表述）；第三轮 0 Critical / 0 Important，仅要求回填 11 passed 与审查状态。Important 均由主实现 Agent 修复，后两轮只复核新增 diff 与未关闭项。
- 浏览器：Playwright MCP（8000 同源托管 `frontend/dist`，隔离 `outputs/phase2/demo.db`，`MAAS_MOCK=1`）。实际执行过程中同一消息重复发起 MCP 调用（详见 S19-I09），点击类操作出现重复；已停止后续 MCP 交互，避免把未验证项写成通过。
- 模型标识：平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验；真实业务模型未调用。

## 4. 产出

| 类型 | 路径 |
|---|---|
| 后端 | `backend/app/models.py`、`schemas.py`、`db.py`、`routers/agent.py`、`services/ai_service.py`、`agents/prompts.py` |
| 前端 | `frontend/src/views/AiConsole.vue`、`api/agent.ts`、`types/models.ts`、`router/index.ts`、`layouts/AppLayout.vue`、`views/LoginPage.vue`、`views/RegisterPage.vue` |
| 测试与门禁 | `tests/backend/test_ai_console.py`、`tests/backend/verify_tables.py`、`tests/backend/run_all.sh`、`.github/workflows/ci.yml`、`docs/CI.md` |
| 计划（本地忽略） | `.codeartsdoer/plans/aiw01-unified-entry/design.md`、`task.md` |
| 本地验证产物（忽略） | `outputs/phase19/`（门禁日志、后端服务日志、刷新后快照） |

## 5. 问题、验证与未完成项

### 5.1 问题与处置

| 编号 | 现象 / 证据 | 处置 | 状态 |
|---|---|---|---|
| S19-I01 | 历史加载失败后发送成功，消息仍被错误态遮住（AiConsole 原 `v-else-if="historyError"`） | 错误态改为 `historyError && !hasMessages`；发送成功清空 `historyError` | 已修复 |
| S19-I02 | “全部标为已读”只处理当前 20 条，文案与行为不符 | 移除 AI 页批量按钮，改由“查看全部消息”进入消息页处理 | 已修复 |
| S19-I03 | 真实模型调用期间持有 SQLite 事务 | 上下文改纯值快照；模型调用前 `rollback` 释放只读事务；写库改到回答生成之后 | 已修复 |
| S19-I04 | `_real_answer` 只捕获 `LLMError`，客户端初始化等异常会冒泡 5000 | 增加 `except Exception` → 5001，warning 不输出凭据 | 已修复 |
| S19-I05 | 失败路径无测试：模型失败残留、空回答、重复 ref | 新增 3 个用例，断言失败前后会话/消息计数不变、空回答 5003、重复 ref 去重 | 已修复 |
| S19-I06 | 只读断言仅覆盖任务与通知 | 扩展 Activity / TaskApplication / TaskMember / CreditLog / Notification 计数与任务状态快照 | 已修复 |
| S19-I07 | mock 正文可能包含不可见任务而只断言引用 | 增加正文不含他人可见任务标题的断言 | 已修复 |
| S19-I08 | 阶段留痕未回填 | 本文件 + `LOG.md` + `HANDOFF.md` + 计划勾选 | 本文件即产出 |
| S19-I09 | Playwright MCP 同一消息重复 invoke（`tool_call` 与直接工具名双通道），点击被重复执行 | 立即停止后续 MCP 交互，保留已取得的页面快照；未把未验证项写成通过；后续单通道调用 | 流程已纠正，复验范围受限 |
| S19-I10 | 第二轮：已有消息时刷新失败被 `historyError && !hasMessages` 静默吞掉 | 已有消息时改用 `ElMessage.error` 提示；无消息时仍显示 ErrorState | 已修复 |
| S19-I11 | 第二轮：发送期间仍可点“刷新对话”，历史替换与追加可能竞态 | `loadHistory` 开头 `if (sending) return`；刷新按钮 `:disabled="sending"` | 已修复 |
| S19-I12 | 第二轮：HANDOFF 的提交授权表述被审查者误读为自行新增授权 | 改为精确引用用户本轮第七节授权，并注明审查者只收到只读复核提示 | 已澄清 |
| S19-I13 | 第三轮：留痕仍写 10 passed / 第二轮待复核 | 回填 11 passed 与三轮审查结论（本表、LOG、HANDOFF） | 已回填 |

### 5.2 验证（命令与真实结果）

| 命令 / 场景 | 环境 | 结果 |
|---|---|---|
| `python -m pytest tests/backend/test_ai_console.py -q` | 临时库、`MAAS_MOCK=1`、`RUN_SCHEDULER=0` | **11 passed**（最终；首轮 7 passed、第一轮修复后 10 passed、第二轮后补续写失败用例） |
| `python -m pytest tests/backend/test_reliability.py -q` | 同上 | **11 passed** |
| `python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py -q` | 同上 | **68 passed** |
| `bash tests/backend/run_all.sh`（`PYTHON_BIN` 显式） | 临时库、本机 Git Bash | **EXIT=0**；`verify_tables` 30 项断言（18 表）；合计 **1412 条 PASS**；无 FAIL 行 |
| `bash tests/frontend/run_all.sh`（`PYTHON_BIN` 显式） | 本机 Git Bash | **EXIT=0**；构建 4/4、静态契约 25/25、语音切片 21/21 |
| 浏览器：member01 登录 | 1440×900，8000 同源 dist，mock | 登录后落在 `/ai`；侧栏 AI/工作台/事务/消息/我的；通知卡显示“未读 0 条” |
| 浏览器：建议问题“我有哪些临近截止的事务？” | 同上 | mock 回答列出“外语角志愿者招募（外语角筹备）”并给出来源按钮；演示模式提示可见 |
| 浏览器：刷新 `/ai` | 同上 | 用户消息、助手回答与来源仍在（持久会话恢复） |
| 浏览器：点击“收起侧栏” | 同上 | 侧栏变为 72px，品牌“校园”、导航短标签、展开按钮；发布主按钮隐藏 |

### 5.3 真实模型 / 浏览器未验证范围

- 未调用真实业务模型；问答为 `MAAS_MOCK=1` 的本地规则回答。
- 未验证管理员/协作者账号的 AI 页入口与管理导航（只核对了既有前端权限判断代码）。
- 未验证 390px 手机视口、深色主题、软键盘与真实触控；未保存阶段截图（快照文件在本地忽略目录）。
- 未验证真实浏览器刷新后的滚动位置与长会话性能。
- CI 尚未发生，提交/推送状态待本轮后续动作回填。

### 5.4 新增 Prompt 说明

- `QA_SYSTEM_PROMPT` 仅用于只读问答，要求只依据“可见事务”回答、只引用给定 `ref`、不承诺写操作；mock 分支不读取该 Prompt。
- 本轮没有同案例前后对比或真实模型效果数据；不得据此宣称问答准确率或真实模型可用。未登记新的 P 编号（无既有业务 Prompt 正文修改）。