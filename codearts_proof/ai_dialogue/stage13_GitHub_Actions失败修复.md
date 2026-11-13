# 阶段 13 · GitHub Actions 失败修复

> 归档日期：2026-11-13
> 本轮提交：`c5ccc2477b1aa37b125e4e62fecf7a6686fe88cc`（2026-11-12 17:24:26 +0800），父提交为基线 `1c45b7d349ebdf7c3f63ef20e06827b0056cffcc`。
> 使用 Agent：领航员（DeepSeek-V4.1-Flash-1017）→ 样式修复工程师 / 语音检查工程师 / CI 配置工程师；独立审查员（只读，3 轮）；独立验证员（独立执行）；书记官收口。
> 归档口径：只写本轮实际发生、可核验的文件、命令与数字。本轮**无浏览器走查、无真机语音验收**，第 4 节不写这两类结论；远程 CI 只取到 job/steps 级证据，日志正文因未认证被 GitHub 拒绝下载（见 §5 P8）。

## 1 用户反馈

### 1.1 用户原始诉求（保留原话细节）

用户要求修复仓库 `https://github.com/shanec7825/campus-task-agent` 当前 GitHub Actions 中**已确认的失败项**，并明确“保持现有业务功能不变”。本地目录为 `D:\Users\Lenovo\Downloads\campus-task-agent-delivery\campus-task-agent`，已知基线提交 `1c45b7d349ebdf7c3f63ef20e06827b0056cffcc`，失败运行链接为 `https://github.com/shanec7825/campus-task-agent/actions/runs/43188378487`。

用户给出的远程结果：

1. “通过：Backend reliability (ubuntu-latest) / Backend reliability (windows-latest) / Backend API and SSE integration”。
2. “失败：Frontend types, build and voice tests / Public source security checks”。
3. “前端失败发生在类型检查和生产构建通过之后，静态契约检查结果为 23 passed、2 failed。后续语音算法测试尚未执行，不能说它已通过。”

失败项一的原话要求：

- “远程检查报告：`frontend/src/views/AdminConsole.vue`：9 行，高于历史基线 8。`frontend/src/views/TaskDetail.vue`：17 行，高于历史基线 14。总计 97 行，高于历史基线 93。”
- “找到新增成员状态表、成员名称、退回原因及提示样式中的四处新增颜色硬编码。”
- “优先复用现有 Element Plus 语义变量或项目颜色变量。尽量保持视觉效果，不重构全站样式。”
- “不提高历史基线、不增加白名单、不关闭检查。低风险样式调整不额外编写只复述 CSS 的测试。”

失败项二的原话要求：

- 相关文件：`tests/frontend/check_contracts.py`、`frontend/src/composables/useVoiceComposer.ts`、`frontend/src/utils/voiceSlicer.ts`、`codearts_proof/ai_dialogue/stage11_第六轮语音定稿分层.md`。
- “远程失败：applyInterim() 未接入续接重吐裁剪。”
- “applyInterim() 只显示临时转写，不写 fullText，不参与切片。applyFinal() 先调用 trimResumedTranscript()，再追加有效定稿。”
- “先核对实际实现和既有记录，判断检查是否过时。”
- “如果确认检查过时：更新检查以约束当前正确行为……不仅删除旧断言，要补上对当前行为的有效约束。不为满足旧检查而让临时转写重新进入发送缓冲。”
- “运行现有语音算法测试。若需补测试，应验证有意义的行为，不只是复制源码结构。没有浏览器实测时，不宣称真实语音效果已验证。”

失败项三的原话要求：

- 相关文件：`.github/workflows/ci.yml`、`tests/security/test_security_redline.sh`。
- “安全脚本要求 frontend/dist 存在，但独立 security job 只 checkout，没有构建前端或获取构建产物。”
- 日志失败：“A2b frontend/dist 存在性：未找到 frontend/dist。”“这不是发现凭证泄露。”
- “不将 dist 提交到仓库。不删除产物安全扫描，不把产物缺失改成通过。”
- “若合并 job，同步更新 job 名称与 docs/CI.md。保持 contents: read、persist-credentials: false。使用普通 pull_request，不改成 pull_request_target。不添加真实模型密钥或其他 Secrets。”

范围与授权：

- 首轮：“本次仅修复代码、测试及 CI 配置。不要部署，不创建 Codespaces，不配置 Pages，不提交或推送。完成本地验证与独立审查后，交付结果供用户决定是否提交。”
- 提交轮另行授权：“将下述 6 个文件的修复提交到当前 main 分支；推送到 origin/main；查看本次提交触发的 GitHub Actions 状态及日志。不授权部署、强制推送、修改仓库权限、删除数据，或为使 CI 通过而继续修改代码。”
- 验收要求：“优先运行 bash tests/frontend/run_all.sh、bash tests/security/test_security_redline.sh”；“修复后由独立 Review Agent 审查本次 diff、需求与验证证据。最多三轮”；“无法独立审查时明确报告”。

### 1.2 复现环境

- 操作系统：Windows 11 Home China（win32 / git-bash）。
- Python：3.12.10；本机 git-bash 的 `python3` 是不可用占位程序（退出码 49、无输出），前端脚本需显式 `PYTHON_BIN=python`。
- Node：25.2.1；npm：11.6.2。
- 基线工作区：`git status` 干净，`HEAD` = `1c45b7d`，`origin/main` = `1c45b7d`，无分叉。
- 本地复现：`python tests/frontend/check_contracts.py --frontend frontend` 输出 **23 passed, 2 failed**，与远程一致；失败项为第 ⑪ 项硬编码色值行数超基线、第 ㉔ 项 `applyInterim()` 未接入 `trimResumedTranscript`。
- 本地安全脚本当时通过（工作区存在 `frontend/dist`），与远程“无 dist”失败不矛盾：远程 `security` job 是独立作业，只做 checkout。

## 2 Leader 决策与根因定位

### 2.1 基线代码定位

- `frontend/src/views/TaskDetail.vue`（基线 `1c45b7d`）：
  - 第 894 行 `.member-table :deep(.is-me)` 的 `background: #f5f9ff`；
  - 第 899 行 `.member-name` 的 `color: #303133`；
  - 第 907 行 `.member-reason` 的 `color: #f56c6c`。
- `frontend/src/views/AdminConsole.vue`（基线）：第 866 行 `.audit-hint` 的 `color: #909399`。
- `tests/frontend/check_contracts.py`（基线）：第 1996 行 `def check_trim_restart_overlap(...)`；第 2025 行 `for name in ("applyInterim", "applyFinal"):` 对两个函数统一断言“必须调用 `trimResumedTranscript(`”。
- `frontend/src/composables/useVoiceComposer.ts`（基线）：`applyInterim()` 只调用 `pushLiveText(transcript)`，不写 `fullText`；`applyFinal()` 先 `trimResumedTranscript()`，再 `fullText.value += frameText`，并有 `if (!frameText) { ... return }` 空帧守卫。

### 2.2 真实技术根因

1. **颜色基线**：近轮在成员状态表、成员名称、退回原因、审核提示四处新增十六进制色值，使 `TaskDetail.vue` 从 14 行增至 17 行、`AdminConsole.vue` 从 8 行增至 9 行、总计从 93 行增至 97 行，超过 `check_no_hardcoded_colors` 的历史基线常量。
2. **语音检查与实现脱节**：第六轮 G1 已把展示与发送分层——`applyInterim` 只做 live 显示，`applyFinal` 才进发送缓冲。第 ㉔ 项仍按第五轮口径要求 `applyInterim` 也调用 `trimResumedTranscript`，检查本身过时，不是实现回归。
3. **安全 job 缺构建产物**：`security` job 独立 `actions/checkout` 后直接执行 `tests/security/test_security_redline.sh`，脚本 A2b 要求 `frontend/dist` 存在；该 job 从未执行 `npm ci` / 构建，`frontend/dist` 必然缺失。

### 2.3 排除的无关猜测

- **不是凭证泄露**：A2b 失败文案是“未找到 frontend/dist”，A 层 Key 字面量扫描在本地 0 命中；用户亦明确“这不是发现凭证泄露”。
- **不是类型检查或生产构建失败**：远程前端 job 在失败前已通过 typecheck 与 build，失败发生在静态契约步骤。
- **不是语音运行逻辑错误**：`useVoiceComposer.ts` / `voiceSlicer.ts` 的第六轮分层实现符合用户描述；本轮未修改这两个文件。
- **不是后端回归**：三个后端 job 在失败运行中已通过，本轮未改后端。
- **不是权限或 Secret 配置问题**：工作流使用 `contents: read` 与 `persist-credentials: false`，未新增 Secrets。

### 2.4 收敛后的任务项与决策

- T1 样式：只替换契约指定的四行颜色为 Element Plus 语义变量，其余硬编码保留（计入基线）。
- T2 检查：按“interim 只展示、final 先裁剪再追加”重写第 ㉔ 项断言，保留续接窗口、`resetLocalBuffer` 复位、`replaceTail` 零命中与停止收尾检查；不改语音实现。
- T3 CI：采用“同一前端 job 构建后扫描”，删除缺少 dist 的独立 `security` job；同步 job 名称与 `docs/CI.md`；不采用 artifact 上传下载（避免跨作业产物路径歧义）。
- T4/T6/T7 独立审查（最多三轮）；T5 独立执行验证。
- 明确不做：提高颜色基线、增加白名单、关闭检查、把 dist 提交仓库、用 `|| true` / `continue-on-error` 吞错、改 `pull_request_target`、改后端业务逻辑。

## 3 派工 Prompt 要点与契约登记

| 任务 | 派工 Prompt 要点（1~3 句） | 契约 ID |
|---|---|---|
| T1 样式修复工程师 | 只把成员状态表、成员名称、退回原因、审核提示四处新增色值替换为 Element Plus 语义变量；不提高基线、不加白名单、不重构其他样式。 | `C-COLOR@1` |
| T2 语音检查工程师 | 第 ㉔ 项按“interim 只调用 `pushLiveText`、不落缓冲/不切片/不发 AI；final 先 `trimResumedTranscript` 再追加、空帧守卫不追加”重写；保留续接窗口、复位与收尾断言，删除旧 interim 裁剪断言。 | `C-VOICE-CHECK@1` |
| T3 CI 配置工程师 | 在 `frontend` job 的 `run_all.sh`（已产出 dist）之后执行安全脚本，删除独立 `security` job，改 job 名并同步 `docs/CI.md`；保持只读权限与普通 `pull_request`。 | `C-CI-SECURITY@1` |
| T4 独立审查员（第 1 轮） | 只读审查本次 diff、需求与契约覆盖；按阻断/非阻断分级，不改文件。 | 依据 §2.2 三份契约 |
| T5 独立验证员 | 独立执行 `run_all.sh` 与安全脚本，核对退出码、契约项与 CI 依赖顺序，给出 PASS/FAIL 与未验证范围。 | 依据 §2.2 三份契约 |
| T6 独立审查员（第 2 轮） | 只审第 1 轮之后新增的修复与未解决问题，不重审未变化代码。 | 同上 |
| T7 独立审查员（第 3 轮） | 只审最后一处文档措辞修复，确认收敛。 | 同上 |

契约要点：

- `C-COLOR@1`：`AdminConsole.vue ≤ 8`、`TaskDetail.vue ≤ 14`、总计 `≤ 93`；只允许替换四处指定色值为 `var(--el-color-primary-light-9)` / `var(--el-text-color-primary)` / `var(--el-color-danger)` / `var(--el-text-color-secondary)`；基线常量不得修改。
- `C-VOICE-CHECK@1`：`applyInterim` 必含 `pushLiveText(transcript)`，不得出现 `trimResumedTranscript(` / `fullText.value` / `sentIndex` / `scheduleSlices(` / `enqueue(` / `streamParse(`；`applyFinal` 的 `trimResumedTranscript(` 必须早于 `fullText.value +=`，`if (!frameText)` 分支内必须 `return` 且不得追加；`replaceTail` 零命中；`RESUMED_RESTART_FRAME_BUDGET = 3` 与 `resetLocalBuffer()` 复位保留。
- `C-CI-SECURITY@1`：`frontend` job 顺序为 `npm ci` → `run_all.sh` → `test_security_redline.sh`；`contents: read`、`persist-credentials: false`、`push/pull_request/workflow_dispatch` 保持；不得删除 A2b 断言或用 `continue-on-error` 放行。

## 4 产出

### 4.1 本轮实际修改/新增文件

提交 `c5ccc24`（6 文件，+125 / −34）：

1. `.github/workflows/ci.yml`：`frontend` job 改名 `Frontend build, voice and public source security checks`，在 `run_all.sh` 后追加安全扫描，删除独立 `security` job。
2. `codearts_proof/ai_dialogue/stage11_第六轮语音定稿分层.md`：新增“## 5 静态契约检查口径同步（CI 修复轮）”，记录 7 条现行断言与旧口径删除原因。
3. `docs/CI.md`：检查表格合并为一行，补充“构建后执行安全扫描”的说明。
4. `frontend/src/views/AdminConsole.vue`：`.audit-hint` 颜色改为 `var(--el-text-color-secondary)`。
5. `frontend/src/views/TaskDetail.vue`：`.member-table :deep(.is-me)` → `var(--el-color-primary-light-9)`；`.member-name` → `var(--el-text-color-primary)`；`.member-reason` → `var(--el-color-danger)`。
6. `tests/frontend/check_contracts.py`：重写 `check_trim_restart_overlap()` 断言（第 ㉔ 项标题与通过文案同步改为“仅定稿追加路径接入”）。

计划与留痕文件（`.codeartsdoer/plans/ci-failure-fix/{design,task}.md` 被 `.gitignore` 忽略，未进入提交）：

- `.codeartsdoer/plans/ci-failure-fix/design.md`：需求 R1–R3、§2.1 边界、三份契约 `C-COLOR@1` / `C-VOICE-CHECK@1` / `C-CI-SECURITY@1`、§2.3 交互矩阵。
- `.codeartsdoer/plans/ci-failure-fix/task.md`：T1–T3 实现、T4/T6/T7 审查、T5 验证。

### 4.2 自动化测试原始结果

修复后本地实测（命令原样）：

```text
$ PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh
# ALL PASS：构建门禁 + 静态契约对齐 + 语音算法单测均通过
# check_contracts.py：RESULT: 25 passed, 0 failed
# check_voice_slicer.cjs：21 PASS / 0 FAIL（7 切片 + 8 重吐裁剪 + 5 常量 + 1 旧名零命中）
# 产物：frontend/dist/index.html（正式 dist）
```

```text
$ bash tests/security/test_security_redline.sh
# EXIT=0
# 结果：13 通过 / 0 PASS-LOCAL / 0 失败 / 共 13 项
# 结论：安全红线 PASS（A 层 0 命中；B 层本地运行时文件合规或不存在）
```

```text
$ python -B tests/frontend/check_contracts.py --frontend frontend
# RESULT: 25 passed, 0 failed
# ⑪ 硬编码色值 PASS：views/TaskDetail.vue=14（基线 14）、views/AdminConsole.vue=8（基线 8）、合计 93
# ㉔ PASS：applyInterim 只调用 pushLiveText(transcript)；applyFinal 先裁剪再追加且空帧守卫不追加
```

```text
$ git diff --check
# EXIT=0（仅 Git 的 LF→CRLF 转换提示，无空白错误）
```

对抗性验证（独立验证员执行，临时副本，不落仓库）：

- 对第 ㉔ 项做 3 组变异：`interim` 内加入 `trimResumedTranscript(` → FAIL；`interim` 写入 `fullText.value +=` → FAIL；空帧守卫内写入 `fullText.value +=` 且缺 `return` → FAIL。说明新检查非空转。
- 临时改名 `frontend/dist` → 安全脚本 EXIT 1（A2b FAIL），恢复后 EXIT 0。说明“缺失即失败”未被改成通过。

提交与远程结果（可核验）：

- 提交：`c5ccc2477b1aa37b125e4e62fecf7a6686fe88cc`；推送输出 `1c45b7d..c5ccc24 main -> main`，`PUSH_EXIT=0`；推送后本地 `HEAD` 与 `refs/heads/main` 同为 `c5ccc24`。
- Actions run：`https://github.com/shanec7825/campus-task-agent/actions/runs/43191196344`（CI #2，触发 SHA `c5ccc24`），整体 `completed / success`；4 个 job 全部 success：
  - `Backend reliability (ubuntu-latest)` success；
  - `Backend reliability (windows-latest)` success；
  - `Backend API and SSE integration` success；
  - `Frontend build, voice and public source security checks` success（steps：`npm ci` success 09:24:38→09:24:42、`bash tests/frontend/run_all.sh` success 09:24:42→09:24:54、`bash tests/security/test_security_redline.sh` success 09:24:54）。
- 限制：未认证无法下载 job 日志正文（GitHub API 403 `Must have admin rights to Repository`；网页显示 `Sign in to view logs`），因此契约 25 项、语音 21 项、A2b 的具体输出行**未能从远程日志逐行抄录**；job/step 级结论来自公开 REST API 的 `steps[].conclusion`。

未验证范围（不宣称通过）：

- 浏览器视觉观感（四处颜色替换后的实际渲染色）；
- 真机语音与真实麦克风下的分层效果；
- CI Node 22 与本机 Node 25 的差异；
- 后端测试套件（本轮未改后端；远程三个后端 job 已通过，但未在本机重复执行）；
- 远程日志正文。

本轮没有浏览器走查与真机走查，因此不写这两类数字。

## 5 真实问题与修复

### P1 静态检查与第六轮实现相反（过时断言）

- 现象：第 ㉔ 项要求 `applyInterim` 调用 `trimResumedTranscript`，而实现自第六轮起只让 interim 走 `pushLiveText`。
- 原因：第五轮 D3 的检查口径没有随第六轮 G1 的展示/发送分层更新。
- 处置：删除“两个函数都必须裁剪”的循环，改为分别断言 interim 只展示、final 先裁剪再追加；新增空帧守卫、禁止切片/发送等断言；不修改 `useVoiceComposer.ts`。

### P2 颜色行数恰好落在基线而非低于基线

- 现象：四处替换后 `TaskDetail.vue` 17→14、`AdminConsole.vue` 9→8、总计 97→93，等于基线而非低于。
- 原因：只替换了新增的四处，未动既有 93 行中的其他硬编码。
- 处置：按契约只改四处，不提高基线、不新增白名单；检查以 `count > baseline` 判定，等于基线即通过。独立审查确认“其余硬编码仍在基线内”。

### P3 独立 security job 无构建产物

- 现象：远程 A2b 报“未找到 frontend/dist”，安全 job 失败。
- 原因：`security` job 只 checkout，没有 `npm ci` 与构建步骤。
- 处置：把安全脚本并入 `frontend` job，放在 `run_all.sh` 之后；删除独立 job；`Frontend build, voice and public source security checks` 名称与 `docs/CI.md` 同步；未使用 artifact 上传下载，未提交 dist。

### P4 合并 job 后 `ci.yml` 留有一个空行

- 现象：CI 配置工程师的编辑器对 `.yml` 报 `parse is not a function`，三次删除空行被拒。
- 原因：编辑器自身 YAML 解析器缺失，与文件内容无关。
- 处置：保留空行（YAML 语义无影响）；独立验证员用 PyYAML 解析确认 3 个 job、步骤顺序、权限与触发条件均正确。

### P5 第一轮独立审查的 6 条非阻断建议

- 已处理 4 条：守卫 `return` 断言改为词边界 `\breturn\b`；`docs/CI.md` 补“语音切片算法检查”；`stage11` 文档 `## 5` 前补空行、末尾补换行；设计文档中“既有 `@deprecated` 说明”的措辞改为“既有断言，口径保持不变”。
- 保留 2 条：空帧守卫 `{` 定位方式（契约本身按有花括号描述，实现与契约一致）；`run_all.sh` 步骤注释 `1/2、2/2` 与实际 3 步不符（既有问题，不在本轮写集）。

### P6 第二轮审查发现文档悬空引用

- 现象：`stage11` 文档改为“本轮本地检查结果见 CI 修复交付记录”，但仓库内不存在该记录，且 `.codeartsdoer/` 被忽略。
- 原因：收口时为了说明“已运行”引入了不存在的外部指针。
- 处置：改为“本节只记录检查口径的更新，不写任何未发生的验证结论”；第三轮审查复核为 0 阻断 / 0 重要 / 0 建议，审查收敛。

### P7 本机 `python3` 不可用

- 现象：`tests/frontend/run_all.sh` 默认解析顺序会选中 git-bash 的 `python3` 占位程序（退出码 49、无输出）。
- 原因：本机 Python 安装方式导致 `python3` 不可用。
- 处置：本地验证显式设置 `PYTHON_BIN="$(command -v python)"`；CI 的 Ubuntu runner 不受影响。

### P8 未认证无法读取远程日志正文

- 现象：`/actions/jobs/{job_id}/logs` 返回 403 `Must have admin rights to Repository`；job 网页显示 `Sign in to view logs`。
- 原因：GitHub 对 job 日志下载要求仓库读权限，本机无 `gh` 且未配置令牌。
- 处置：改用公开 REST API 的 `steps[].conclusion` 与时间戳作为 job 级证据；结合脚本“失败即非零退出”的语义说明内部检查通过；在交付报告中明确“未能逐行确认日志”，不把 steps 级 success 描述为逐行日志证据。

### P9 中文文件路径的精确暂存

- 现象：`git status` 把 `stage11_第六轮语音定稿分层.md` 显示为转义路径，直接复制路径易出错。
- 原因：Git 默认 `core.quotePath` 会转义非 ASCII 文件名。
- 处置：使用 `git add codearts_proof/ai_dialogue/stage11_*.md` 通配符精确暂存单个文件，未使用 `git add .`；提交后 `git status` 为空。