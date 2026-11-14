#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T8 前端静态契约对齐检查（第二轮迭代终验）。

只依赖 Python 标准库做文本 / 正则级断言；需要实跑的模板检查会调用既有
``node_modules/.bin/tsc`` 与 ``node``（只读复用，不安装任何新依赖）。
逐项输出 ``PASS`` / ``FAIL``；失败时输出具体文件与行号；全部通过返回 0，否则返回 1。

P1 检查项（继续有效）：
1. ``src/api/tasks.ts`` 导出函数名 ⊇ ``2.2.10`` 的 10 个契约函数；
2. ``src/stores/draft.ts`` 的 store 导出（return 块）含 6 个契约 action；
3. ``src/utils/colorPool.ts`` 的 7 组色值与 ``2.2.9`` 完全一致；
4. ``components/VoiceComposer/FieldPanel.vue`` 的 props 名与 ``2.2.13`` 一致；
5. ``src/views`` / ``src/components`` 内无裸 ``fetch('/api...')``（必须走 api 层）。

P2（本轮新增，对应 plan T8 ⑨）：
6. ``TRACE_COLORS`` 4 个追溯色与 ``color-pool.css`` 同名变量逐字一致；
7. ``BlockKind`` 五值 + ``BlockText`` 非 raw 块只读 + live 虚线；
8. ``toTaskPayload`` 函数体不含 ``blocks``（防追溯块污染发布请求）；
9. ``api/applications.ts`` 5 个导出 + ``claimTask`` 返回 ``ApplyResult``；
10. ``traceText.formatChangeText`` 5 组模板（tsc 编译 + node 实跑，与后端交叉一致）；
11. 「无本轮新增硬编码色值」：历史 93 行白名单逐条标注「非本轮引入」+ 4 个追溯色零命中。

用法::

    python tests/frontend/check_contracts.py
    python tests/frontend/check_contracts.py --frontend /path/to/frontend
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# --------------------------------------------------------------------------- #
# 契约常量（唯一事实来源：plan.md 2.2.9 / 2.2.10 / 2.2.11 / 2.2.13）
# --------------------------------------------------------------------------- #

#: 2.2.10 中 api/tasks.ts 必须导出的函数名
EXPECTED_TASK_API: tuple[str, ...] = (
    "listTasks",
    "createTask",
    "getTask",
    "patchTask",
    "claimTask",
    "assignTask",
    "updateProgress",
    "submitTask",
    "verifyTask",
    "decomposeTask",
)

#: 2.2.11 中 stores/draft.ts 必须提供的 action（第三轮：markSuspended → finishStreaming）
EXPECTED_DRAFT_ACTIONS: tuple[str, ...] = (
    "applyExtract",
    "applyStream",
    "applyReview",
    "finishStreaming",
    "resetDraft",
    "toTaskPayload",
)

#: 2.2.9 颜色池：字段键 -> 色值（extra_tags / requirements 同色，unresolved / corrections 同色）
EXPECTED_FIELD_COLORS: dict[str, str] = {
    "time": "#3B82F6",
    "location": "#22C55E",
    "quota": "#F97316",
    "title": "#8B5CF6",
    "extra_tags": "#EAB308",
    "requirements": "#EAB308",
    "unresolved": "#EF4444",
    "corrections": "#EF4444",
}
EXPECTED_WARN_COLOR = "#EF4444"
EXPECTED_UNPARSED_COLOR = "#374151"

#: 2.2.13 中 FieldPanel.vue 的 props 名
EXPECTED_FIELD_PANEL_PROPS: frozenset[str] = frozenset(
    {"fields", "corrections", "ambiguities", "stylePrompt", "readonly"}
)


class ContractError(Exception):
    """单条契约断言失败（消息内需含文件与行号）。"""


@dataclass
class CheckResult:
    """一条检查项的结果。"""

    title: str
    ok: bool
    message: str
    details: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 通用文本工具
# --------------------------------------------------------------------------- #


def load_text(path: Path) -> str:
    """读取 UTF-8 文本（文件缺失时给出明确错误）。"""
    if not path.is_file():
        raise ContractError(f"文件不存在：{path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - 环境异常兜底
        raise ContractError(f"文件不是 UTF-8 编码：{path}（{exc}）") from exc


def find_line_number(text: str, pattern: str, flags: int = 0) -> int:
    """返回首个命中 ``pattern`` 的 1 基行号；无命中返回 0。"""
    match = re.search(pattern, text, flags)
    if match is None:
        return 0
    return text.count("\n", 0, match.start()) + 1


def render_location(rel_path: str, line_number: int, source_line: str = "") -> str:
    """格式化 ``文件:行号`` 形式的失败位置。"""
    suffix = f" | {source_line.strip()}" if source_line.strip() else ""
    return f"{rel_path}:{line_number}{suffix}"


def strip_ts_comments(text: str) -> str:
    """把 TS 注释替换为等长空白（保留换行，行号不偏移）。"""
    without_block = re.sub(
        r"/\*.*?\*/",
        lambda match: re.sub(r"[^\n]", " ", match.group(0)),
        text,
        flags=re.S,
    )
    without_line = re.sub(
        r"//[^\n]*",
        lambda match: " " * len(match.group(0)),
        without_block,
    )
    return without_line


def extract_balanced_braces(text: str, open_index: int) -> str:
    """从 ``text[open_index] == '{'`` 起提取配对的 ``{...}`` 片段。"""
    if open_index < 0 or open_index >= len(text) or text[open_index] != "{":
        raise ContractError("内部错误：括号提取起点不是 '{'")
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
    raise ContractError("内部错误：花括号未闭合")


def collect_exported_functions(text: str) -> dict[str, int]:
    """收集 ``export function name`` / ``export const name = ... =>`` 的名字与行号。"""
    function_pattern = re.compile(
        r"^\s*export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
        re.MULTILINE,
    )
    arrow_pattern = re.compile(
        r"^\s*export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
        r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
        re.MULTILINE,
    )

    exported: dict[str, int] = {}
    for pattern in (function_pattern, arrow_pattern):
        for match in pattern.finditer(text):
            exported.setdefault(match.group(1), text.count("\n", 0, match.start()) + 1)
    return exported


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #


def check_task_api(rel_path: str, src_dir: Path) -> str:
    """① api/tasks.ts 导出函数名 ⊇ 2.2.10 表。"""
    text = load_text(src_dir / rel_path)
    exported = collect_exported_functions(text)
    missing = [name for name in EXPECTED_TASK_API if name not in exported]

    if missing:
        details: list[str] = []
        for name in missing:
            defined_line = find_line_number(text, rf"function\s+{re.escape(name)}\s*\(")
            if defined_line:
                details.append(
                    f"{rel_path}:{defined_line} 定义了 {name} 但缺少 export 关键字"
                )
            else:
                details.append(f"{rel_path} 缺少导出函数 {name}()（契约 2.2.10）")
        raise ContractError("；".join(details))

    return f"{rel_path} 导出 {len(exported)} 个符号，契约要求的 10 个函数全部存在"


def check_draft_actions(rel_path: str, src_dir: Path) -> str:
    """② stores/draft.ts 的 store 导出含 applyExtract / applyStream / ... 6 个 action。"""
    raw_text = load_text(src_dir / rel_path)
    text = strip_ts_comments(raw_text)

    return_index = text.rfind("return {")
    if return_index < 0:
        raise ContractError(
            f"{render_location(rel_path, find_line_number(raw_text, r'defineStore\\s*\\('))}"
            " 未找到 store 的 `return { ... }` 导出块"
        )

    brace_index = text.index("{", return_index)
    return_block = extract_balanced_braces(text, brace_index)
    exported_names = set(re.findall(r"([A-Za-z_$][\w$]*)\s*(?=[,}])", return_block))

    missing = [name for name in EXPECTED_DRAFT_ACTIONS if name not in exported_names]
    if missing:
        details: list[str] = []
        for name in missing:
            defined_line = find_line_number(text, rf"function\s+{re.escape(name)}\s*\(")
            if defined_line:
                details.append(
                    f"{rel_path}:{defined_line} 定义了 {name} 但未在 store return 块中导出"
                )
            else:
                details.append(f"{rel_path} 缺少 action {name}()（契约 2.2.11）")
        raise ContractError("；".join(details))

    return (
        f"{rel_path} 的 store return 块共导出 {len(exported_names)} 个成员，"
        "6 个契约 action 全部存在"
    )


def check_color_pool(rel_path: str, src_dir: Path) -> str:
    """③ utils/colorPool.ts 的 7 组色值与 2.2.9 完全一致。"""
    text = load_text(src_dir / rel_path)

    block_match = re.search(r"FIELD_COLORS[^=]*=\s*\{([^}]*)\}", text, re.S)
    if block_match is None:
        raise ContractError(
            f"{render_location(rel_path, find_line_number(text, r'FIELD_COLORS'))}"
            " 未找到 FIELD_COLORS 映射"
        )

    actual = dict(
        re.findall(
            r"([A-Za-z_$][\w$]*)\s*:\s*['\"](#[0-9A-Fa-f]{6})['\"]",
            block_match.group(1),
        )
    )

    problems: list[str] = []
    for key, expected in EXPECTED_FIELD_COLORS.items():
        line = find_line_number(text, rf"\b{re.escape(key)}\s*:\s*['\"]")
        if key not in actual:
            problems.append(f"{rel_path}:{max(line, 1)} 缺少字段键 {key}（期望 {expected}）")
        elif actual[key].upper() != expected.upper():
            problems.append(
                f"{rel_path}:{line} 字段键 {key} 色值为 {actual[key]}，契约要求 {expected}"
            )

    for constant_name, expected in (
        ("WARN_COLOR", EXPECTED_WARN_COLOR),
        ("UNPARSED_COLOR", EXPECTED_UNPARSED_COLOR),
    ):
        match = re.search(
            rf"{constant_name}\s*(?::[^=]+)?=\s*['\"](#[0-9A-Fa-f]{{6}})['\"]", text
        )
        if match is None:
            problems.append(f"{rel_path} 缺少常量 {constant_name}（契约要求 {expected}）")
        elif match.group(1).upper() != expected.upper():
            line = text.count("\n", 0, match.start()) + 1
            problems.append(
                f"{rel_path}:{line} {constant_name} 为 {match.group(1)}，契约要求 {expected}"
            )

    if "export function colorForField" not in text:
        line = find_line_number(text, r"colorForField")
        problems.append(f"{rel_path}:{max(line, 1)} 缺少导出函数 colorForField()")
    elif "extra_tags." not in text:
        problems.append(
            f"{rel_path}:{find_line_number(text, r'colorForField')} "
            "colorForField 未处理 `extra_tags.` 前缀（契约 2.2.9）"
        )

    if problems:
        raise ContractError("；".join(problems))

    return f"{rel_path} 的 8 个字段键 + WARN/UNPARSED 常量与 2.2.9 逐字一致"


def check_field_panel_props(rel_path: str, src_dir: Path) -> str:
    """④ VoiceComposer/FieldPanel.vue 的 props 名与 2.2.13 一致。"""
    text = load_text(src_dir / rel_path)

    props_index = text.find("defineProps<")
    if props_index < 0:
        raise ContractError(f"{rel_path} 未找到 `defineProps<{...}>` 声明")
    brace_index = text.find("{", props_index)
    if brace_index < 0:
        raise ContractError(f"{rel_path} 的 defineProps 泛型内未找到 props 类型字面量")

    try:
        body = extract_balanced_braces(text, brace_index)
    except ContractError as exc:
        raise ContractError(f"{rel_path} 的 defineProps 类型字面量解析失败：{exc}") from exc

    actual_props = set(
        re.findall(r"^\s*([A-Za-z_$][\w$]*)\s*\??\s*:", body, re.MULTILINE)
    )

    missing = sorted(EXPECTED_FIELD_PANEL_PROPS - actual_props)
    extra = sorted(actual_props - EXPECTED_FIELD_PANEL_PROPS)
    if missing or extra:
        problems: list[str] = []
        for name in missing:
            problems.append(f"{rel_path} 缺少 prop `{name}`（契约 2.2.13）")
        for name in extra:
            line = find_line_number(text, rf"^\s*{re.escape(name)}\s*\??\s*:", re.MULTILINE)
            problems.append(f"{render_location(rel_path, line)} 出现契约外的 prop `{name}`")
        raise ContractError("；".join(problems))

    return f"{rel_path} 的 props 集合 = {sorted(actual_props)}，与 2.2.13 完全一致"


def check_no_bare_fetch(rel_dirs: tuple[str, ...], src_dir: Path) -> str:
    """⑤ views / components 内无裸 fetch('/api...')。"""
    bare_fetch_re = re.compile(r"fetch\s*\(\s*[\"'`]\s*/api")
    scanned = 0
    hits: list[str] = []

    for rel_dir in rel_dirs:
        directory = src_dir / rel_dir
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.rglob("*")):
            if file_path.suffix not in {".vue", ".ts", ".js"} or not file_path.is_file():
                continue
            scanned += 1
            rel_path = file_path.relative_to(src_dir).as_posix()
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if bare_fetch_re.search(line):
                    hits.append(render_location(rel_path, line_number, line))

    if hits:
        raise ContractError("发现裸 fetch('/api...')，必须走 api 层：\n    " + "\n    ".join(hits))

    return f"扫描 {scanned} 个文件，未发现裸 fetch('/api...')"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    (
        "api/tasks.ts 导出函数 ⊇ 2.2.10（10 个）",
        lambda: check_task_api("api/tasks.ts", SRC_DIR),
    ),
    (
        "stores/draft.ts 含 6 个契约 action",
        lambda: check_draft_actions("stores/draft.ts", SRC_DIR),
    ),
    (
        "utils/colorPool.ts 色值与 2.2.9 一致",
        lambda: check_color_pool("utils/colorPool.ts", SRC_DIR),
    ),
    (
        "VoiceComposer/FieldPanel.vue props 与 2.2.13 一致",
        lambda: check_field_panel_props("components/VoiceComposer/FieldPanel.vue", SRC_DIR),
    ),
    (
        "views/components 无裸 fetch('/api...')",
        lambda: check_no_bare_fetch(("views", "components"), SRC_DIR),
    ),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。"""
    default_frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
    parser = argparse.ArgumentParser(description="T11 前端静态契约对齐检查")
    parser.add_argument(
        "--frontend",
        type=Path,
        default=default_frontend,
        help=f"前端工程根目录（默认 {default_frontend}）",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """执行全部检查并返回进程退出码（0=全通过，1=有失败）。"""
    # Windows 控制台在非 UTF-8 代码页下会因中文报错，统一改为 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args(argv)
    global SRC_DIR  # noqa: PLW0603 - 供 CHECKS 中的 lambda 读取
    frontend_dir: Path = args.frontend.resolve()
    SRC_DIR = frontend_dir / "src"

    print("=" * 68)
    print("T11 前端静态契约对齐检查（文本 / 正则级，无新增工具）")
    print(f"前端根目录：{frontend_dir}")
    print("=" * 68)

    if not SRC_DIR.is_dir():
        print(f"[FAIL] 前端 src 目录不存在：{SRC_DIR}")
        print("-" * 68)
        print("RESULT: 0 passed, 1 failed")
        return 1

    results: list[CheckResult] = []
    total = len(CHECKS)
    for index, (title, runner) in enumerate(CHECKS, start=1):
        try:
            message = runner()
            result = CheckResult(title=title, ok=True, message=message)
        except ContractError as exc:
            result = CheckResult(title=title, ok=False, message=str(exc))
        except Exception as exc:  # pragma: no cover - 防御脚本自身异常
            result = CheckResult(
                title=title,
                ok=False,
                message=f"检查脚本内部异常：{type(exc).__name__}: {exc}",
            )
        results.append(result)

        status = "PASS" if result.ok else "FAIL"
        print(f"[{index}/{total}] {status}  {title}")
        print(f"        {result.message}")
        if not result.ok:
            print(f"        >>> 失败项：{title}")

    passed = sum(1 for item in results if item.ok)
    failed = len(results) - passed
    print("-" * 68)
    print(f"RESULT: {passed} passed, {failed} failed")

    if failed:
        print("\n失败明细（文件与行号见上）：")
        for item in results:
            if not item.ok:
                print(f"  - {item.title}\n      {item.message}")
        return 1

    print("全部契约检查通过。")
    return 0


SRC_DIR: Path = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"


# =========================================================================== #
# T8（第二轮迭代）新增契约检查：追溯染色 / 块类型 / 防污染 / API / 文案 / 色源
# =========================================================================== #

#: `C-TRACE@1` B 节：4 个追溯色（TS 唯一色源）
EXPECTED_TRACE_COLORS: dict[str, str] = {
    "ai_applied": "#8B5CF6",
    "user_edit": "#0891B2",
    "user_note": "#6B7280",
    "live": "#3B82F6",
}

#: 与 TS 逐字一致的 CSS 变量
EXPECTED_TRACE_CSS_VARS: dict[str, str] = {
    "--c-ai-applied": "#8B5CF6",
    "--c-user-edit": "#0891B2",
    "--c-user-note": "#6B7280",
    "--c-live": "#3B82F6",
}

#: `C-TRACE@1` A 节：BlockKind 的 5 个取值
EXPECTED_BLOCK_KINDS: frozenset[str] = frozenset(
    {"raw", "ai_applied", "user_edit", "user_note", "live"}
)

#: `C-FEAPI-APPLY@1`：api/applications.ts 的 5 个导出
EXPECTED_APPLICATION_API: tuple[str, ...] = (
    "applyTask",
    "withdrawApply",
    "listApplications",
    "decideApplication",
    "myApplications",
)

#: `C-TRACE@1` C 节：formatChangeText 的 5 组模板样例（与后端 applied_texts 交叉一致）
EXPECTED_TRACE_TEXT_CASES: tuple[tuple[dict[str, object], str], ...] = (
    (
        {"source": "ai", "op": "set", "field": "time", "old_value": None, "new_value": "14:00", "reason": ""},
        "AI建议：补充时间为「14:00」",
    ),
    (
        {"source": "ai", "op": "set", "field": "quota", "old_value": 3, "new_value": 6, "reason": ""},
        "AI建议：将名额由「3」改为「6」",
    ),
    (
        {"source": "ai", "op": "add_tag", "field": "extra_tags.摄影", "old_value": None, "new_value": "2 人", "reason": ""},
        "AI建议：新增扩展项「摄影」，内容为「2 人」",
    ),
    (
        {"source": "user", "op": "set", "field": "quota", "old_value": None, "new_value": "6", "reason": ""},
        "用户：新建名额，内容为「6」",
    ),
    (
        {"source": "user", "op": "set", "field": "quota", "old_value": 3, "new_value": 6, "reason": ""},
        "用户：将名额由「3」改为「6」",
    ),
)

#: 历史硬编码色值基线（相对 src，按**行**计数）：P1 的 12 个文件共 93 行 / 96 个色值
#: （LoginPage.vue:129 与 Profile.vue:621 为单行多色，故色值数 > 行数）。
#: 判定规则：任何超出基线的行 = 「本轮新增硬编码」，判 FAIL；4 个追溯色零命中。
HARDCODED_BASELINE_LINES: dict[str, int] = {
    "components/admin/AssignDialog.vue": 3,
    "components/admin/ReminderRuleForm.vue": 1,
    "components/common/EmptyState.vue": 1,
    "components/common/LoadingState.vue": 1,
    "components/task/SopSteps.vue": 4,
    "components/task/SubTaskTree.vue": 16,
    "components/task/TaskCard.vue": 7,
    "views/AdminConsole.vue": 8,
    "views/LoginPage.vue": 4,
    "views/Profile.vue": 30,
    "views/TaskDetail.vue": 14,
    "views/TaskHall.vue": 4,
}

#: 基线合计（行）
HARDCODED_BASELINE_TOTAL: int = sum(HARDCODED_BASELINE_LINES.values())


def check_trace_colors(rel_ts: str, rel_css: str, src_dir: Path) -> str:
    """⑥ TRACE_COLORS 4 色与 color-pool.css 逐字一致（C-TRACE@1 B）。"""
    text = load_text(src_dir / rel_ts)
    block_match = re.search(r"TRACE_COLORS[^=]*=\s*\{([^}]*)\}", text, re.S)
    if block_match is None:
        raise ContractError(
            f"{render_location(rel_ts, find_line_number(text, r'TRACE_COLORS'))} 未找到 TRACE_COLORS 映射"
        )
    actual = dict(
        re.findall(r"([A-Za-z_$][\w$]*)\s*:\s*['\"](#[0-9A-Fa-f]{6})['\"]", block_match.group(1))
    )
    if set(actual) != set(EXPECTED_TRACE_COLORS):
        raise ContractError(
            f"{rel_ts} TRACE_COLORS 键集合为 {sorted(actual)}，契约要求 {sorted(EXPECTED_TRACE_COLORS)}"
        )
    problems: list[str] = []
    for key, expected in EXPECTED_TRACE_COLORS.items():
        if actual[key].upper() != expected.upper():
            problems.append(
                f"{render_location(rel_ts, find_line_number(text, rf'\b{key}\s*:\s*[\"\']'))} "
                f"TRACE_COLORS.{key}={actual[key]}，契约要求 {expected}"
            )

    css = load_text(src_dir / rel_css)
    for variable, expected in EXPECTED_TRACE_CSS_VARS.items():
        match = re.search(rf"{re.escape(variable)}\s*:\s*(#[0-9A-Fa-f]{{6}})", css)
        if match is None:
            problems.append(f"{rel_css} 缺少 CSS 变量 {variable}（契约要求 {expected}）")
        elif match.group(1).upper() != expected.upper():
            line = css.count("\n", 0, match.start()) + 1
            problems.append(f"{render_location(rel_css, line)} {variable}={match.group(1)}，契约要求 {expected}")

    if "export function colorForBlock" not in text:
        problems.append(f"{rel_ts} 缺少 colorForBlock()（C-TRACE@1 B）")
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_ts} 的 4 个追溯色与 {rel_css} 的同名变量逐字一致（#8B5CF6/#0891B2/#6B7280/#3B82F6）"


def check_block_kinds(
    rel_store: str, rel_block_text: str, src_dir: Path, rel_types: str = "types/models.ts"
) -> str:
    """⑦ BlockKind 五值 + BlockText 非 raw 块只读 + live 虚线（C-TRACE@1 A/E）。

    ``BlockKind`` 的唯一类型源是 T1 的 ``types/models.ts``（``draft.ts`` 只做 import type）；
    同时兼容定义在 store 文件的实现，按 types → store 顺序查找。
    """
    store_text = load_text(src_dir / rel_store)
    types_text = load_text(src_dir / rel_types)
    kind_match = re.search(r"export type BlockKind\s*=\s*([^\n]+)", types_text, re.S)
    kind_source = rel_types
    if kind_match is None:
        kind_match = re.search(r"export type BlockKind\s*=\s*([^\n]+)", store_text, re.S)
        kind_source = rel_store
    if kind_match is None:
        raise ContractError(f"{rel_types} / {rel_store} 均未找到 `export type BlockKind = ...`")
    kinds = set(re.findall(r"'([^']+)'", kind_match.group(1)))
    if kinds != EXPECTED_BLOCK_KINDS:
        raise ContractError(
            f"{kind_source} BlockKind={sorted(kinds)}，契约要求 {sorted(EXPECTED_BLOCK_KINDS)}"
        )
    if not re.search(r"kind\s*:\s*BlockKind", store_text):
        raise ContractError(f"{rel_store} 的 Block 接口缺少 `kind: BlockKind` 字段")

    block_text = load_text(src_dir / rel_block_text)
    problems: list[str] = []
    if "kind !== 'raw'" not in block_text and 'kind !== "raw"' not in block_text:
        problems.append(f"{rel_block_text} 未按 kind !== 'raw' 判定追溯块（只读）")
    if "is-live" not in block_text:
        problems.append(f"{rel_block_text} 缺少 is-live 类（live 虚线）")
    if "border-bottom-style: dashed" not in block_text:
        problems.append(f"{rel_block_text} 缺少 `border-bottom-style: dashed`（C-TRACE@1 B）")
    # 第四轮 C3（C-VOICEUI@4 §B）：块内编辑浮层整体移除，raw 与追溯块共用单一 span + el-tooltip。
    # 旧口径（要求 el-popover 编辑浮层 + v-else 分支）已被 C3 反向断言取代，见 check_block_text_v4。
    popover_tag = "<el-" + "popover"
    if popover_tag in block_text:
        problems.append(
            f"{rel_block_text}:{find_line_number(block_text, popover_tag)} "
            "仍残留编辑浮层（第四轮 C3 已移除块内编辑）"
        )
    if "<el-tooltip" not in block_text:
        problems.append(f"{rel_block_text} 缺少 el-tooltip（非 raw 块需展示 meta.reason）")
    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{kind_source} BlockKind 五值齐全；{rel_block_text} 非 raw 块只读 + live 虚线"
    )

def check_to_task_payload(rel_path: str, src_dir: Path) -> str:
    """⑧ toTaskPayload 函数体不得读取 blocks（R14-AC5 防污染）。"""
    raw_text = load_text(src_dir / rel_path)
    text = strip_ts_comments(raw_text)
    match = re.search(
        r"function\s+toTaskPayload\s*\([^)]*\)\s*:\s*TaskCreatePayload\s*\{", text
    )
    if match is None:
        raise ContractError(f"{rel_path} 未找到 `function toTaskPayload(): TaskCreatePayload {{`")
    brace_index = text.index("{", match.end() - 1)
    body = extract_balanced_braces(text, brace_index)
    if re.search(r"\bblocks\b", body):
        offset = body.find("blocks")
        line = text.count("\n", 0, brace_index + offset) + 1
        raise ContractError(
            f"{render_location(rel_path, line)} toTaskPayload 函数体内出现 `blocks`"
            "（追溯块会污染发布请求，违反 R14-AC5）"
        )
    required = ("title", "description", "location", "start_time", "quota", "volunteer_hours", "extras", "style_note")
    missing = [key for key in required if key not in body]
    if missing:
        raise ContractError(
            f"{render_location(rel_path, text.count(chr(10), 0, brace_index) + 1)} "
            f"toTaskPayload 缺少字段映射：{missing}（C-DATA@1 映射表）"
        )
    if "buildDraft()" not in body:
        raise ContractError(f"{rel_path} toTaskPayload 未通过 buildDraft() 组装（只从 fields 取值）")
    return f"{rel_path} toTaskPayload 只从 fields 组装（函数体零 `blocks`），8 个字段映射齐全"


def check_applications_api(rel_api: str, rel_tasks_api: str, src_dir: Path) -> str:
    """⑨ api/applications.ts 5 导出 + claimTask 返回 ApplyResult（C-FEAPI-APPLY@1）。"""
    text = load_text(src_dir / rel_api)
    exported = collect_exported_functions(text)
    missing = [name for name in EXPECTED_APPLICATION_API if name not in exported]
    if missing:
        raise ContractError(f"{rel_api} 缺少导出函数：{missing}（契约 2.2.2 末尾函数表）")

    problems: list[str] = []
    signature_rules = (
        (r"listApplications\s*\([^)]*\)\s*:\s*Promise<\{\s*items:\s*ApplicationItem\[\]\s*\}>", "listApplications 返回 Promise<{ items: ApplicationItem[] }>"),
        (r"myApplications\s*\([^)]*\)\s*:\s*Promise<\{\s*items:\s*ApplicationWithTask\[\]\s*\}>", "myApplications 返回 Promise<{ items: ApplicationWithTask[] }>"),
        (r"decideApplication\s*\([^)]*approve:\s*boolean[^)]*reason\?\s*:\s*string[^)]*\)", "decideApplication(id, approve: boolean, reason?: string)"),
    )
    for pattern, label in signature_rules:
        if not re.search(pattern, text, re.S):
            problems.append(f"{rel_api} 签名不符：{label}")

    tasks_text = load_text(src_dir / rel_tasks_api)
    if not re.search(r"claimTask[\s\S]{0,400}?Promise<ApplyResult>", tasks_text):
        problems.append(f"{rel_tasks_api} 的 claimTask 未改为 `Promise<ApplyResult>`（C-APPLY@1 A6）")
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_api} 的 5 个导出与签名齐全；claimTask 已返回 ApplyResult"


def check_trace_text_templates(rel_path: str, src_dir: Path) -> str:
    """⑩ formatChangeText 5 组模板（tsc 单文件编译 + node 实跑，与后端 applied_texts 交叉一致）。"""
    import json as json_module
    import os
    import shutil
    import subprocess
    import tempfile

    frontend_dir = src_dir.parent
    tsc_name = "tsc.cmd" if os.name == "nt" else "tsc"
    tsc = frontend_dir / "node_modules" / ".bin" / tsc_name
    if not tsc.exists():
        raise ContractError(f"未找到 TypeScript 编译器：{tsc}（只读复用 node_modules，禁止安装新依赖）")

    # 产物必须放在 tests/frontend 下：frontend/package.json 含 "type": "module"，
    # 若输出到 frontend/ 内，Node 会把 CommonJS 产物当 ESM 解析而报 exports is not defined。
    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp-trace-", dir=str(Path(__file__).resolve().parent)))
    try:
        compiled = subprocess.run(
            [
                str(tsc),
                str(src_dir / rel_path),
                "--outDir",
                str(tmp_dir),
                "--module",
                "commonjs",
                "--target",
                "es2020",
                "--skipLibCheck",
            ],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if compiled.returncode != 0:
            raise ContractError(
                f"{rel_path} 单文件编译失败（exit={compiled.returncode}）："
                f"{(compiled.stdout + compiled.stderr)[:800]}"
            )
        candidates = sorted(tmp_dir.rglob("traceText.js"))
        if not candidates:
            raise ContractError(f"{rel_path} 编译后未找到 traceText.js（outDir={tmp_dir}）")

        probe_js = """
const mod = require(process.argv[2]);
const cases = CASES_PLACEHOLDER;
let failed = 0;
for (const [input, expected] of cases) {
  const actual = mod.formatChangeText(input);
  if (actual !== expected) {
    console.error(`FAIL ${JSON.stringify(input)} => ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
    failed += 1;
  } else {
    console.log(`PASS ${actual}`);
  }
}
if (failed > 0) process.exit(1);
""".replace(
            "CASES_PLACEHOLDER", json_module.dumps(EXPECTED_TRACE_TEXT_CASES, ensure_ascii=False)
        )
        probe = tmp_dir / "probe.cjs"
        probe.write_text(probe_js, encoding="utf-8")
        executed = subprocess.run(
            ["node", str(probe), str(candidates[0])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if executed.returncode != 0:
            raise ContractError(
                "formatChangeText 模板断言失败：\n" + (executed.stdout + executed.stderr)[:1200]
            )
        return f"{rel_path} formatChangeText 5 组模板逐字一致（node 实跑通过）"
    except FileNotFoundError as exc:
        raise ContractError(f"缺少 node / tsc 可执行文件：{exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def check_no_hardcoded_colors(rel_dirs: tuple[str, ...], src_dir: Path) -> str:
    """⑪ 本轮新增硬编码色值判定：历史 93 行白名单 + 4 个追溯色零命中（R14-AC6）。

    口径：以**行**为单位统计 `#[0-9A-Fa-f]{6}`（与 Leader 提示的「93 处」一致：
    96 个色值分布在 93 行，其中 LoginPage.vue:129 与 Profile.vue:621 为单行多色）。
    任何超出历史基线的行 = 本轮新增硬编码 → FAIL；并逐条打印「非本轮引入」清单。
    """
    hex_re = re.compile(r"#[0-9A-Fa-f]{6}")
    trace_values = {value.upper() for value in EXPECTED_TRACE_COLORS.values()}
    rows: list[tuple[str, int, list[str]]] = []
    scanned = 0

    for rel_dir in rel_dirs:
        directory = src_dir / rel_dir
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.rglob("*")):
            if file_path.suffix not in {".vue", ".ts", ".js"} or not file_path.is_file():
                continue
            scanned += 1
            rel_path = file_path.relative_to(src_dir).as_posix()
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                colors = hex_re.findall(line)
                if colors:
                    rows.append((rel_path, line_number, colors))

    problems: list[str] = []
    counts: dict[str, int] = {}
    for rel_path, line_number, colors in rows:
        counts[rel_path] = counts.get(rel_path, 0) + 1
        for color in colors:
            if color.upper() in trace_values:
                problems.append(
                    f"{render_location(rel_path, line_number)} 出现追溯色 {color}"
                    "（本轮新增语义色只允许在 colorPool.ts / color-pool.css）"
                )

    for rel_path, count in sorted(counts.items()):
        baseline = HARDCODED_BASELINE_LINES.get(rel_path)
        if baseline is None:
            problems.append(f"{rel_path} 不在历史白名单（{count} 行硬编码，视为本轮新增）")
        elif count > baseline:
            problems.append(f"{rel_path} 硬编码行数 {count} > 历史基线 {baseline}（本轮新增 {count - baseline} 行）")

    total_lines = len(rows)
    total_colors = sum(len(colors) for _, _, colors in rows)
    if total_lines > HARDCODED_BASELINE_TOTAL:
        problems.append(f"总硬编码行数 {total_lines} > 历史基线 {HARDCODED_BASELINE_TOTAL}（本轮新增）")

    print("        ---- 历史硬编码色值逐条清单（全部标注「非本轮引入」）----")
    for rel_path, line_number, colors in rows:
        print(f"        INFO 非本轮引入（P1 遗留）：{rel_path}:{line_number} {'/'.join(colors)}")

    if problems:
        raise ContractError(
            "；".join(problems)
            + f"（扫描 {scanned} 个文件，命中 {total_lines} 行 / {total_colors} 个色值）"
        )
    return (
        f"扫描 {scanned} 个文件，命中 {total_lines} 行 / {total_colors} 个硬编码色值："
        f"全部落在 12 个 P1 文件的历史基线 {HARDCODED_BASELINE_TOTAL} 行内（非本轮引入），"
        "4 个追溯色零命中；本轮新增色值仅在 colorPool.ts / color-pool.css"
    )


# 追加到既有 5 项之后（第二轮迭代契约检查）
CHECKS = CHECKS + (
    (
        "⑥ utils/colorPool.ts TRACE_COLORS 4 色与 CSS 同值",
        lambda: check_trace_colors("utils/colorPool.ts", "styles/color-pool.css", SRC_DIR),
    ),
    (
        "⑦ stores/draft.ts BlockKind 五值 + BlockText 非 raw 只读",
        lambda: check_block_kinds(
            "stores/draft.ts", "components/VoiceComposer/BlockText.vue", SRC_DIR
        ),
    ),
    (
        "⑧ toTaskPayload 函数体不含 blocks（防污染）",
        lambda: check_to_task_payload("stores/draft.ts", SRC_DIR),
    ),
    (
        "⑨ api/applications.ts 5 导出 + claimTask 返回 ApplyResult",
        lambda: check_applications_api("api/applications.ts", "api/tasks.ts", SRC_DIR),
    ),
    (
        "⑩ utils/traceText.formatChangeText 5 组模板",
        lambda: check_trace_text_templates("utils/traceText.ts", SRC_DIR),
    ),
    (
        "⑪ 无本轮新增硬编码色值（历史 93 行白名单 + 追溯色零命中）",
        lambda: check_no_hardcoded_colors(("components", "views"), SRC_DIR),
    ),
)


# =========================================================================== #
# 第三轮（T5）新增契约检查：B9 零引用 / C-STORE@3 / C-VOICEUI@3（B2/B3/B5/B11）
# =========================================================================== #

#: 扫描源码时排除的目录名（构建产物 / 依赖 / 缓存）
EXCLUDED_DIR_PARTS: frozenset[str] = frozenset({"node_modules", ".venv", "__pycache__", ".git", "dist"})


def iter_source_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """递归收集源码文件；排除依赖、构建产物、缓存与临时目录（行号无关扫描）。"""
    files: list[Path] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in suffixes:
            continue
        relative_parts = file_path.relative_to(root).parts
        if any(part in EXCLUDED_DIR_PARTS or part.startswith("dist-t") or part.startswith(".tmp")
               for part in relative_parts):
            continue
        files.append(file_path)
    return files


def check_b9_zero_references(src_dir: Path) -> str:
    """⑫ B9 零引用：悬浮确认组件 + 旧 action 在全仓源码/测试中 0 命中（R20-AC4/Q5）。

    组件名与旧 action 名在脚本内**拼接构造**，避免检查器自身造成自指命中。
    """
    project_root = src_dir.parent.parent
    component_name = "Suspended" + "Confirm"
    legacy_action = "mark" + "Suspended"
    hits_component: list[str] = []
    hits_action: list[str] = []
    scanned = 0

    # 排除检查器自身：本文件需以文字说明「旧 action 已删除」，否则自指假失败
    self_path = Path(__file__).resolve()
    for file_path in iter_source_files(project_root, (".vue", ".ts", ".js", ".cjs", ".py")):
        if file_path.resolve() == self_path:
            continue
        scanned += 1
        text = file_path.read_text(encoding="utf-8", errors="replace")
        relative = file_path.relative_to(project_root).as_posix()
        if component_name in text:
            hits_component.append(relative)
        if legacy_action in text:
            hits_action.append(relative)

    problems: list[str] = []
    if hits_component:
        problems.append(f"命中悬浮确认组件名 {component_name}：{hits_component}")
    if hits_action:
        problems.append(f"命中旧 action {legacy_action}：{hits_action}")
    if problems:
        raise ContractError("；".join(problems))
    return (
        f"扫描 {scanned} 个源码/测试文件：{component_name} 与 {legacy_action} "
        "均 0 引用（历史 markdown 留痕不在源码扫描范围内）"
    )


def check_store_v3(rel_path: str, src_dir: Path) -> str:
    """⑬ C-STORE@3：持久化键/版本/防抖 + DraftMode 收窄 + finishStreaming + corrections 只警示。"""
    text = load_text(src_dir / rel_path)
    stripped = strip_ts_comments(text)
    problems: list[str] = []

    if not re.search(r"DRAFT_STORAGE_KEY\s*=\s*['\"]cta_draft_v1['\"]", text):
        problems.append(f"{rel_path}:{max(find_line_number(text, r'DRAFT_STORAGE_KEY'), 1)} 缺少 DRAFT_STORAGE_KEY = 'cta_draft_v1'")
    if not re.search(r"DRAFT_VERSION\s*=\s*1\b", text):
        problems.append(f"{rel_path}:{max(find_line_number(text, r'DRAFT_VERSION'), 1)} 缺少 DRAFT_VERSION = 1")
    if not re.search(r"DRAFT_SAVE_DEBOUNCE_MS\s*=\s*300\b", text):
        problems.append(f"{rel_path}:{max(find_line_number(text, r'DRAFT_SAVE_DEBOUNCE_MS'), 1)} 缺少 300ms 防抖常量")
    for name in ("restoreFromStorage", "clearPersistedDraft", "isEmptyDraft"):
        if name not in stripped:
            problems.append(f"{rel_path} 缺少持久化函数 {name}()")

    mode_match = re.search(r"export type DraftMode\s*=\s*([\s\S]*?)(?=\n\n|\nexport |\Z)", text)
    if mode_match is None:
        problems.append(f"{rel_path} 未找到 `export type DraftMode = ...`")
    else:
        mode_block = mode_match.group(1)
        if "'confirmed'" in mode_block or '"confirmed"' in mode_block:
            problems.append(f"{rel_path}:{find_line_number(text, r'export type DraftMode')} DraftMode 仍含 'confirmed'（应删除）")
        if "'suspended'" not in mode_block:
            problems.append(f"{rel_path} DraftMode 缺少 'suspended'（历史数据兼容）")
        elif "@deprecated" not in mode_block:
            problems.append(f"{rel_path} DraftMode 的 'suspended' 未标注 @deprecated")

    finish_index = stripped.find("function finishStreaming")
    if finish_index < 0:
        problems.append(f"{rel_path} 缺少 finishStreaming()")
    else:
        finish_block = extract_balanced_braces(stripped, stripped.index("{", finish_index))
        if "'streaming'" not in finish_block and '"streaming"' not in finish_block:
            problems.append(f"{rel_path} finishStreaming 未处理 'streaming'")
        if "'suspended'" not in finish_block and '"suspended"' not in finish_block:
            problems.append(f"{rel_path} finishStreaming 未兼容历史 'suspended'")
        if "liveText.value = ''" not in finish_block:
            problems.append(f"{rel_path} finishStreaming 未清空 liveText")

    merge_index = stripped.find("function mergeCorrectionsInternal")
    if merge_index < 0:
        problems.append(f"{rel_path} 缺少 mergeCorrectionsInternal()")
    else:
        merge_block = extract_balanced_braces(stripped, stripped.index("{", merge_index))
        if re.search(r"\.value\s*=\s*correction\.new_value", merge_block):
            problems.append(f"{rel_path}:{find_line_number(text, r'function mergeCorrectionsInternal')} corrections 仍直接写字段值（B1 回归）")
        if "warned = true" not in merge_block:
            problems.append(f"{rel_path} mergeCorrectionsInternal 未置 warned = true")

    persisted_match = re.search(r"interface PersistedDraftData\s*\{", text)
    if persisted_match is None:
        problems.append(f"{rel_path} 缺少 PersistedDraftData 接口")
    else:
        body = extract_balanced_braces(text, text.index("{", persisted_match.start()))
        for forbidden in (r"(?<![A-Za-z])mode\s*:", r"\bliveText\b", r"\bsessionId\b", r"\bappendedText\b"):
            if re.search(forbidden, body):
                problems.append(f"{rel_path} PersistedDraftData 落盘了瞬态字段（{forbidden}）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：cta_draft_v1 + DRAFT_VERSION=1 + 300ms 防抖；DraftMode 无 'confirmed'、"
        "'suspended' 带 @deprecated；finishStreaming 导出；corrections 只警示不写值"
    )


def check_subtask_include(src_dir: Path) -> str:
    """⑭ C-VOICEUI@3 D：SubTaskCard 受控 include（默认 false）+ AiPanel 默认不勾选 + ≥2 渲染。"""
    card_rel = "components/Publish/SubTaskCard.vue"
    panel_rel = "components/Publish/AiPanel.vue"
    card = load_text(src_dir / card_rel)
    panel = load_text(src_dir / panel_rel)
    problems: list[str] = []

    if not re.search(r"include\?\s*:\s*boolean", card):
        problems.append(f"{card_rel} 缺少受控 prop `include?: boolean`")
    if not re.search(r"include\s*:\s*false", card):
        problems.append(f"{card_rel} 的 include 默认值不是 false")
    if not re.search(r"\(e:\s*['\"]update:include['\"],\s*value:\s*boolean\)", card):
        problems.append(f"{card_rel} 缺少 emit `update:include`")
    if "emit('update:include'" not in card and 'emit("update:include"' not in card:
        problems.append(f"{card_rel} 未派发 update:include")
    if not re.search(r"watch\(\s*\(\)\s*=>\s*props\.tasks", card):
        problems.append(f"{card_rel} 缺少 `watch(() => props.tasks)` 重置双保险")

    if not re.search(r"const\s+includeSubtasks\s*=\s*ref\(false\)", panel):
        problems.append(f"{panel_rel} 未声明 includeSubtasks = ref(false)（默认不勾选）")
    if 'v-if="draft.suggestedSubTasks.length >= 2"' not in panel and 'v-if="subtaskTotal >= 2"' not in panel:
        problems.append(f"{panel_rel} 拆解卡片未按 ≥2 条渲染")
    if 'v-model:include="includeSubtasks"' not in panel:
        problems.append(f"{panel_rel} 未用 v-model:include 绑定受控状态")
    if not re.search(r"const\s+publishSubtasks\s*=\s*includeSubtasks\.value\s*&&", panel):
        problems.append(f"{panel_rel} 未按 `includeSubtasks && total > 0` 决定是否发布子任务")
    if not re.search(r"\.publishAll\(\s*mainTask\.id\s*\)", panel):
        problems.append(f"{panel_rel} 勾选后未调用 publishAll(mainTask.id)")
    if not re.search(r"watch\(\s*\(\)\s*=>\s*draft\.suggestedSubTasks", panel):
        problems.append(f"{panel_rel} 未在建议刷新时重置勾选")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{card_rel} include 默认 false + update:include 受控 + tasks 变化重置；"
        f"{panel_rel} includeSubtasks=ref(false) + ≥2 渲染 + 仅勾选才 publishAll"
    )


def check_ai_panel_v3(rel_path: str, src_dir: Path) -> str:
    """⑮ C-VOICEUI@3 A/B：刷新恢复块容器 + 纯语音自动切块 + 全量解析确认 + 自动 review。"""
    text = load_text(src_dir / rel_path)
    problems: list[str] = []

    mounted_index = text.find("onMounted(")
    if mounted_index < 0:
        problems.append(f"{rel_path} 缺少 onMounted()")
    else:
        mounted_block = extract_balanced_braces(text, text.index("{", mounted_index))
        if "draft.blocks.length > 0" not in mounted_block:
            problems.append(f"{rel_path}:{find_line_number(text, r'onMounted\(')} onMounted 未按恢复的 blocks 判断")
        if "showRawEditor.value = false" not in mounted_block:
            problems.append(f"{rel_path} onMounted 未在 blocks>0 时置 showRawEditor=false（B6 恢复被空 textarea 遮挡）")

    watch_match = re.search(r"watch\(\s*\(\)\s*=>\s*draft\.blocks\.length", text)
    if watch_match is None:
        problems.append(f"{rel_path} 缺少 `watch(() => draft.blocks.length)` 纯语音自动切块")
    else:
        watch_block = extract_balanced_braces(text, text.index("{", watch_match.end()))
        if "draft.mode === 'streaming'" not in watch_block:
            problems.append(f"{rel_path} 自动切块未限定 mode === 'streaming'")
        if "showRawEditor.value = false" not in watch_block:
            problems.append(f"{rel_path} 自动切块未置 showRawEditor=false")

    if "重新全量解析" not in text:
        problems.append(f"{rel_path} 主按钮缺少「重新全量解析」文案")
    if "ElMessageBox.confirm" not in text:
        problems.append(f"{rel_path} 重新全量解析缺少二次确认")
    if "无法恢复" not in text or "只想修改部分内容" not in text:
        problems.append(f"{rel_path} 清空草稿文案缺少「无法恢复 / 只想修改部分内容」说明")

    if "onAllChunksSent" not in text or "runReview" not in text:
        problems.append(f"{rel_path} 未注册 onAllChunksSent → runReview（语音结束自动审核）")
    unmount_match = re.search(r"on(?:Before)?Unmount\(\(\)\s*=>\s*\{([\s\S]*?)\n\s*\}\)", text)
    if unmount_match is None:
        problems.append(f"{rel_path} 缺少 onBeforeUnmount/onUnmounted 注销块")
    elif "stopAllChunksSent" not in unmount_match.group(1):
        problems.append(f"{rel_path} 卸载时未调用 stopAllChunksSent() 注销订阅")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：onMounted 恢复 blocks>0 即切块容器；blocks 0→非空且 streaming 自动切块；"
        "全量解析二次确认；语音结束注册 runReview 并在卸载注销"
    )


def check_block_text_v3_removed_placeholder() -> None:
    """占位：第三轮 ⑯ `check_block_text_v3` 已按第四轮 C3 **整体删除**（不是叠加）。

    旧断言的 ``v-model:visible="editing"`` / ``:trigger="[]"`` / ``if (editing.value) return``
    / document mousedown 外部点击 / popperClass 与 C3「块内编辑入口整体移除」直接冲突，
    保留任意一条都会让契约检查必然 FAIL。第四轮口径的唯一实现见 ``check_block_text_v4``。
    """


# 追加到既有 11 项之后（第三轮契约检查）
CHECKS = CHECKS + (
    (
        "⑫ B9 零引用：悬浮确认组件 + 旧 action",
        lambda: check_b9_zero_references(SRC_DIR),
    ),
    (
        "⑬ C-STORE@3 持久化 / DraftMode / finishStreaming / corrections 只警示",
        lambda: check_store_v3("stores/draft.ts", SRC_DIR),
    ),
    (
        "⑭ C-VOICEUI@3 D 子任务 include 受控 + 默认不勾选",
        lambda: check_subtask_include(SRC_DIR),
    ),
    (
        "⑮ C-VOICEUI@3 A/B 刷新恢复块容器 + 自动切块 + 自动 review",
        lambda: check_ai_panel_v3("components/Publish/AiPanel.vue", SRC_DIR),
    ),
    (
        "⑯ C-VOICEUI@4 §B BlockText 编辑能力零残留（反向断言）",
        lambda: check_block_text_v4(
            "components/VoiceComposer/BlockText.vue",
            "components/Publish/AiPanel.vue",
            SRC_DIR,
        ),
    ),
    (
        "⑰ C-VOICEUI@4 §A 发布页默认 AI 智能模式 + 双面板 v-show",
        lambda: check_publish_default_ai("views/PublishPage.vue", SRC_DIR),
    ),
    (
        "⑱ C-TYPO@1 A/B typography.css 6 变量 + main.ts 引入顺序",
        lambda: check_typography_baseline("styles/typography.css", "main.ts", SRC_DIR),
    ),
    (
        "⑲ C-TYPO@1 C 字号 +1 梯度：12px 归零 + BlockText/AiPanel 集合 + 逐文件分布",
        lambda: check_font_sizes(SRC_DIR),
    ),
    (
        "⑳ C-TRACE@2 解析不留痕：appliedTextAt 零命中 + 三处显式采纳留痕",
        lambda: check_trace_v4("stores/draft.ts", SRC_DIR),
    ),
    (
        "㉑ C-VOICEUI@4 §C 语音收尾：stopping 窗口 + onend 结算 + 零散切片守卫",
        lambda: check_voice_v4(
            "composables/useVoiceComposer.ts", "utils/voiceSlicer.ts", SRC_DIR
        ),
    ),
)


# =========================================================================== #
# 第四轮（T6）新增契约检查：C1 默认 AI / C2 字号基线 / C3 块编辑移除 /
#                            C4 解析不留痕 / C5 语音收尾
# 契约来源：plan `campus-task-agent-iteration4` P4 的
#   C-VOICEUI@4（§A 默认态 / §B 块展示 / §C 语音收尾）· C-TYPO@1 · C-TRACE@2
# =========================================================================== #

#: `C-TYPO@1` A：typography.css 必须逐字包含的 6 个变量
EXPECTED_TYPOGRAPHY_VARS: dict[str, str] = {
    "--el-font-size-extra-large": "22px",
    "--el-font-size-large": "18px",
    "--el-font-size-medium": "16px",
    "--el-font-size-base": "15px",
    "--el-font-size-small": "14px",
    "--el-font-size-extra-small": "13px",
}

#: `.vue` 内 `font-size: 12px|13px|...` 的取值提取
FONT_SIZE_PATTERN = re.compile(r"font-size:\s*(\d+)px")

#: `C-TYPO@1` C 的 AiPanel 映射证据：该文件基线为 12px×5 / 13px×6 / 15px×2
#: （Leader 第四轮核验），按 12→13 / 13→14 / 15→16 抬升后，13px 恰为 5 处，
#: 且必须是原 12px 的 5 个语义类——出现 13px 本身不是缺陷，而是正确的 +1 结果。
AI_PANEL_EXPECTED_13PX_SELECTORS: frozenset[str] = frozenset(
    {
        ".composer__hint",
        ".composer__legend",
        ".review__note",
        ".polished__label",
        ".publish-bar__reason",
    }
)


def css_font_size_selectors(text: str, size: int) -> list[tuple[str, int]]:
    """返回声明 ``font-size: {size}px`` 的「选择器 + 1 基行号」列表。

    实现按行回溯到最近含 ``{`` 的行取选择器（本项目单文件 scoped CSS 无嵌套规则）；
    用于把「某档字号的处数」与「具体语义类」绑定，避免只看总数造成误判。
    """
    lines = text.splitlines()
    pattern = re.compile(rf"font-size:\s*{size}px\b")
    hits: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        if pattern.search(line) is None:
            continue
        selector = ""
        for back in range(index, -1, -1):
            if "{" in lines[back]:
                selector = lines[back].split("{")[0].strip()
                break
        hits.append((selector, index + 1))
    return hits

#: `C-TYPO@1` C：逐处 +1 的迁移梯度
FONT_SIZE_SHIFT: dict[int, int] = {12: 13, 13: 14, 14: 15, 15: 16}

#: `C-VOICEUI@4` §B-2 / `Q4` 的 5 个语音常量（`voiceSlicer.ts` 本轮零改动）
EXPECTED_VOICE_SLICER_CONSTANTS: dict[str, str] = {
    "PUNCT_THRESHOLD": "1",
    "MAX_CHUNK_CHARS": "12",
    "SILENCE_CUT_MS": "800",
    "FINAL_DELAY_MS": "800",
    "LIVE_MAX_REFRESH_MS": "200",
}


def function_body(text: str, name: str) -> tuple[str, int]:
    """按符号名提取 ``function name(...) { ... }`` 的函数体（返回 1 基起始行号）。

    断言一律按**符号锚定**（不依赖施工期会漂移的固定行号）；参数列表内无对象解构，
    因此「参数闭合后第一个 ``{``」即函数体起点。调用方应传入已 ``strip_ts_comments``
    的文本，避免注释里的示例片段造成假命中。
    """
    pattern = re.compile(
        rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*\(",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        raise ContractError(f"未找到函数 `{name}()` 的定义")
    # 参数列表内可能出现默认值对象（如 `options: StartOptions = {}`），
    # 必须先按括号配对跨过参数表，再取函数体起点，否则会被默认值的 `{}` 误判。
    open_paren = text.find("(", match.end() - 1)
    depth = 0
    close_paren = -1
    for index in range(open_paren, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren < 0:
        raise ContractError(f"函数 `{name}()` 的参数列表未闭合")
    brace_index = text.find("{", close_paren)
    if brace_index < 0:
        raise ContractError(f"函数 `{name}()` 的签名后未找到函数体 `{{`")
    body = extract_balanced_braces(text, brace_index)
    return body, text.count("\n", 0, brace_index) + 1


def arrow_property_body(text: str, property_name: str) -> tuple[str, int]:
    """按符号名提取 ``x.<prop> = () => { ... }`` 之类的箭头函数体。"""
    pattern = re.compile(rf"\.{re.escape(property_name)}\s*=\s*\(\s*\)\s*=>\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise ContractError(f"未找到箭头回调 `.`{property_name}` = () => {{ ... }}`")
    brace_index = text.index("{", match.end() - 1)
    body = extract_balanced_braces(text, brace_index)
    return body, text.count("\n", 0, brace_index) + 1


def collect_vue_font_sizes(src_dir: Path) -> dict[str, dict[int, int]]:
    """统计 ``src/**/*.vue`` 内每个文件的 ``font-size: NNpx`` 处数（排除构建/依赖目录）。"""
    table: dict[str, dict[int, int]] = {}
    for file_path in iter_source_files(src_dir, (".vue",)):
        rel_path = file_path.relative_to(src_dir).as_posix()
        counts: dict[int, int] = {}
        for match in FONT_SIZE_PATTERN.finditer(file_path.read_text(encoding="utf-8")):
            size = int(match.group(1))
            counts[size] = counts.get(size, 0) + 1
        if counts:
            table[rel_path] = counts
    return table


def format_font_distribution(table: dict[str, dict[int, int]]) -> str:
    """把逐文件字号统计渲染为「文件 → 13/14/15/16 处数」的紧凑表格文本。"""
    rows: list[str] = []
    for rel_path, counts in sorted(table.items()):
        cell = " ".join(f"{size}px×{counts[size]}" for size in sorted(counts))
        rows.append(f"{rel_path} → {cell}")
    return "；".join(rows)


def check_publish_default_ai(rel_path: str, src_dir: Path) -> str:
    """⑰ `C-VOICEUI@4 §A`（C1）：发布页默认 AI 智能模式 + 双面板 v-show 保活。"""
    text = load_text(src_dir / rel_path)
    problems: list[str] = []

    if not re.search(r"ref<PublishMode>\(\s*'ai'\s*\)", text):
        problems.append(
            f"{render_location(rel_path, max(find_line_number(text, r'const\s+activeTab'), 1))} "
            "`activeTab` 初值不是 `ref<PublishMode>('ai')`（R21-AC1 默认智能模式）"
        )
    manual_default = re.search(r"ref<PublishMode>\(\s*'manual'\s*\)", text)
    if manual_default is not None:
        manual_line = text.count("\n", 0, manual_default.start()) + 1
        problems.append(
            f"{render_location(rel_path, manual_line)} "
            "仍存在 `ref<PublishMode>('manual')` 旧默认值"
        )
    for mode in ("manual", "ai"):
        # 注意：此处不能用 raw f-string（`\'` 在 raw 串中会保留反斜杠，导致永不命中）
        pattern = 'v-show="activeTab === ' + "'" + mode + "'" + '"'
        if pattern not in text:
            problems.append(f"{rel_path} 缺少 `{pattern}`（双面板必须同时挂载，R21-AC2）")

    # 只允许在 `.mode-panel` 上出现 `v-show`；其它元素（如徽标 el-tag）上的 v-if 属正常条件渲染
    mode_panel_vif = [
        line
        for line in text.splitlines()
        if "mode-panel" in line and 'v-if="activeTab' in line
    ]
    if mode_panel_vif:
        line_number = find_line_number(text, r"mode-panel[^\n]*v-if=\"activeTab")
        problems.append(
            f"{render_location(rel_path, line_number, mode_panel_vif[0])} "
            "`.mode-panel` 使用了 `v-if=\"activeTab`（会销毁 AI 草稿，违反 R21-AC2/AC3）"
        )
    if "默认智能模式" not in text or "手动为兜底" not in text:
        problems.append(f"{rel_path} 缺少「默认智能模式，手动为兜底」注释（R21-AC1）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：`activeTab` 初值 `'ai'`（注释「默认智能模式，手动为兜底」）；"
        "manual/ai 两个 `.mode-panel` 均为 `v-show`，无 `v-if=\"activeTab`"
    )


def check_typography_baseline(rel_css: str, rel_main: str, src_dir: Path) -> str:
    """⑱ `C-TYPO@1` A/B（C2）：typography.css 6 变量逐字一致 + main.ts 引入顺序。"""
    css_text = load_text(src_dir / rel_css)
    main_text = load_text(src_dir / rel_main)
    problems: list[str] = []

    for variable, expected in EXPECTED_TYPOGRAPHY_VARS.items():
        match = re.search(rf"{re.escape(variable)}\s*:\s*([^;]+);", css_text)
        if match is None:
            problems.append(f"{rel_css} 缺少变量 {variable}（契约要求 {expected}）")
        elif match.group(1).strip() != expected:
            problems.append(
                f"{render_location(rel_css, css_text.count(chr(10), 0, match.start()) + 1)} "
                f"{variable} = {match.group(1).strip()}，契约要求 {expected}"
            )

    actual_vars = set(re.findall(r"(--el-font-size-[\w-]+)\s*:", css_text))
    extra = sorted(actual_vars - set(EXPECTED_TYPOGRAPHY_VARS))
    if extra:
        problems.append(f"{rel_css} 出现契约外的字号变量：{extra}")
    for forbidden, label in (
        (r"font-family\s*:", "font-family"),
        (r"font-size\s*:", "组件级 font-size 声明"),
        (r"^\s*\*\s*\{", "`*` 选择器"),
        (r"\brem\b", "rem 单位"),
        (r"clamp\(", "clamp()"),
    ):
        if re.search(forbidden, css_text, re.MULTILINE):
            problems.append(f"{rel_css} 含禁止内容 `{label}`（C-TYPO@1 A 内容冻结）")
    if "#" in css_text:
        problems.append(f"{rel_css} 含色值（颜色职责属 color-pool.css，Q3）")

    element_line = find_line_number(main_text, r"element-plus/dist/index\.css")
    typography_line = find_line_number(main_text, r"\./styles/typography\.css")
    app_line = find_line_number(main_text, r"import\s+App\s+from\s+['\"]\./App\.vue['\"]")
    color_pool_line = find_line_number(main_text, r"\./styles/color-pool\.css")
    if element_line == 0:
        problems.append(f"{rel_main} 未引入 `element-plus/dist/index.css`")
    if typography_line == 0:
        problems.append(f"{rel_main} 未引入 `./styles/typography.css`（R21-AC5）")
    if color_pool_line == 0:
        problems.append(f"{rel_main} 未引入 `./styles/color-pool.css`（位置不得变更）")
    if element_line and typography_line and not element_line < typography_line:
        problems.append(
            f"{rel_main}:{typography_line} typography.css 必须在 "
            f"element-plus/dist/index.css（第 {element_line} 行）之后引入（R21-AC5）"
        )
    if typography_line and app_line and not typography_line < app_line:
        problems.append(
            f"{rel_main}:{typography_line} typography.css 必须在首个项目内 import"
            f"（App.vue，第 {app_line} 行）之前引入"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_css} 6 个字号变量逐字一致（22/18/16/15/14/13px），无 color/font-family/"
        f"`*` 选择器/rem/clamp；{rel_main} 引入顺序：index.css:第 {element_line} 行 → "
        f"typography.css:第 {typography_line} 行 → App.vue:第 {app_line} 行（color-pool.css 保留）"
    )


def check_font_sizes(src_dir: Path) -> str:
    """⑲ `C-TYPO@1` C（C2）：字号 +1 梯度（12px 归零 + 两文件集合 + 逐文件分布）。

    口径（Leader 第四轮终验）：
    1. ``font-size: 12px`` 在 ``src/**/*.vue``（含排除 BlockText/AiPanel 后的子集）为 **0**；
    2. ``BlockText.vue`` 的集合必须恰为 ``{16px, 15px}``；
    3. ``AiPanel.vue`` **不得出现 13px**（其原 13px 已 +1 为 14px）；
    4. **不做**「总处数 = 固定值」断言（施工期处数会漂移），改为逐文件枚举 13/14/15/16 分布；
    5. 打印 ``15px → 16px`` 的逐处清单，作为「原 15px 处数 = 现 16px 新增处数」的人工复核依据。
    """
    table = collect_vue_font_sizes(src_dir)
    if not table:
        raise ContractError("在 src/**/*.vue 内未统计到任何 `font-size: NNpx` 声明")

    block_text_rel = "components/VoiceComposer/BlockText.vue"
    ai_panel_rel = "components/Publish/AiPanel.vue"
    problems: list[str] = []

    total_12 = sum(counts.get(12, 0) for counts in table.values())
    others_12 = sum(
        counts.get(12, 0)
        for rel_path, counts in table.items()
        if rel_path not in {block_text_rel, ai_panel_rel}
    )
    if total_12:
        hits = [
            rel_path for rel_path, counts in table.items() if counts.get(12, 0)
        ]
        problems.append(f"`font-size: 12px` 仍有 {total_12} 处（R21-AC7 要求 0）：{hits}")
    if others_12:
        problems.append(
            f"排除 BlockText/AiPanel 后仍有 {others_12} 处 `font-size: 12px`"
            f"（Leader 第四轮终验口径要求 0）"
        )

    block_text_counts = table.get(block_text_rel, {})
    block_text_set = {size for size, count in block_text_counts.items() if count}
    if block_text_set != {16, 15}:
        problems.append(
            f"{block_text_rel} 的 font-size 集合 = {sorted(block_text_set)}，"
            "契约 C-VOICEUI@4 §D 要求恰为 {15px, 16px}"
        )

    ai_panel_counts = table.get(ai_panel_rel, {})
    ai_panel_text = load_text(src_dir / ai_panel_rel)

    # AiPanel 的基线映射（Leader 第四轮核验）：12px×5 / 13px×6 / 15px×2
    #   → 按 C2 梯度（12→13、13→14、15→16）+1 后应为 13px×5 / 14px×6 / 16px×2。
    # 因此该文件出现 13px 不是缺陷，而是「原 12px 抬升而来」的**正确结果**；
    # 判据改为「12px 归零 + 13px 恰 5 处且落在 5 个语义类上」。
    ai_panel_12 = css_font_size_selectors(ai_panel_text, 12)
    if ai_panel_12:
        problems.append(
            f"{ai_panel_rel} 仍有 {len(ai_panel_12)} 处 `font-size: 12px`"
            f"（{[f'{sel}@{line}' for sel, line in ai_panel_12]}）——C2 要求 12px 归零"
        )

    ai_panel_13 = css_font_size_selectors(ai_panel_text, 13)
    if len(ai_panel_13) != 5:
        problems.append(
            f"{ai_panel_rel} 的 13px 为 {len(ai_panel_13)} 处"
            f"（{[f'{sel}@{line}' for sel, line in ai_panel_13]}），"
            "基线映射（原 12px×5 → 13px×5）要求恰 5 处"
        )
    ai_13_selectors = {selector for selector, _ in ai_panel_13}
    if ai_13_selectors != AI_PANEL_EXPECTED_13PX_SELECTORS:
        problems.append(
            f"{ai_panel_rel} 的 13px 选择器集合 {sorted(ai_13_selectors)} 与基线映射证据 "
            f"{sorted(AI_PANEL_EXPECTED_13PX_SELECTORS)} 不一致"
            "（这 5 处必须正是原 12px 的 5 个语义类）"
        )

    ai_panel_16 = css_font_size_selectors(ai_panel_text, 16)
    if len(ai_panel_16) != 2:
        problems.append(
            f"{ai_panel_rel} 的 16px 为 {len(ai_panel_16)} 处，"
            "基线映射（原 15px×2 → 16px×2）要求恰 2 处"
        )
    print(
        "        INFO "
        f"{ai_panel_rel} 基线映射核对：12px→{len(ai_panel_12)} 处（要求 0）｜"
        f"13px→{len(ai_panel_13)} 处（原 12px×5）｜14px→{ai_panel_counts.get(14, 0)} 处（原 13px×6）｜"
        f"16px→{len(ai_panel_16)} 处（原 15px×2）"
    )
    print(
        "        INFO 13px 的 5 个语义类："
        + "、".join(f"{sel}@{line}" for sel, line in ai_panel_13)
    )

    distribution = format_font_distribution(table)
    totals = {size: sum(c.get(size, 0) for c in table.values()) for size in (11, 12, 13, 14, 15, 16)}
    sixteen_hits: list[str] = []
    for rel_path, counts in sorted(table.items()):
        if not counts.get(16):
            continue
        for line_number, line in enumerate(
            load_text(src_dir / rel_path).splitlines(), start=1
        ):
            if FONT_SIZE_PATTERN.search(line) and "16px" in line:
                sixteen_hits.append(f"{rel_path}:{line_number}")

    print("        ---- 逐文件字号分布（13/14/15/16；附 11/12 便于核对）----")
    for rel_path, counts in sorted(table.items()):
        cells = " ".join(f"{size}px×{counts[size]}" for size in sorted(counts))
        print(f"        INFO {rel_path} → {cells}")
    print(
        f"        ---- 全局合计：11px={totals[11]} / 12px={totals[12]} / 13px={totals[13]}"
        f" / 14px={totals[14]} / 15px={totals[15]} / 16px={totals[16]} ----"
    )
    print(
        f"        ---- 现 16px 逐处清单（{len(sixteen_hits)} 处，应为原 15px 逐处 +1；"
        f"BlockText 原 15px→16px 见 plan 2.1.0）----"
    )
    for hit in sixteen_hits:
        print(f"        INFO {hit}")

    if problems:
        raise ContractError("；".join(problems))

    return (
        f"`font-size: 12px` 全局 {totals[12]} 处（含排除 BlockText/AiPanel 后 {others_12} 处）；"
        f"分布 13px={totals[13]} / 14px={totals[14]} / 15px={totals[15]} / 16px={totals[16]}；"
        f"{block_text_rel} 集合={{16px,15px}}；"
        f"{ai_panel_rel} 基线映射正确：12px→0 处、13px→{len(ai_panel_13)} 处（原 12px×5，"
        f"落在 {sorted(ai_13_selectors)}）、"
        f"14px→{ai_panel_counts.get(14, 0)} 处（原 13px×6）、16px→{len(ai_panel_16)} 处（原 15px×2）；"
        "逐文件分布见上方 INFO 清单"
    )


def check_block_text_v4(rel_block_text: str, rel_ai_panel: str, src_dir: Path) -> str:
    """⑯ `C-VOICEUI@4 §B`（C3）：块内编辑能力**零残留**（反向断言，取代第三轮正向断言）。

    覆盖：
    1. ``BlockText.vue`` 禁用词（编辑浮层 / 编辑态 / 编辑缓冲 / 提交与取消 / document 外部点击 /
       popper class / 编辑器样式）零命中；
    2. 全仓（src + tests/frontend）``onEditBlock`` / ``blockOverrides`` / ``resolveBlockFieldKey``
       与模板 ``@edit=`` 零命中；
    3. ``@select`` 与 ``el-tooltip`` 保留（非 raw 块 tooltip 展示 reason）；
    4. ``AiPanel.vue`` 无 ``@edit`` 绑定，``displayBlocks`` 无 override 合并；
    5. 清空草稿文案已改为「右侧字段面板 / 增量解析」，旧引导短语零命中。
    """
    block_text = load_text(src_dir / rel_block_text)
    ai_panel = load_text(src_dir / rel_ai_panel)
    problems: list[str] = []

    # 禁用词用拼接构造：避免本脚本自身成为「零残留」扫描的假命中（plan 实现要点 4）
    forbidden_tokens: tuple[tuple[str, str], ...] = (
        ("el-" + "popover", "编辑浮层"),
        ("edit" + "ing", "编辑态 / 编辑守卫"),
        ("draft" + "Text", "编辑缓冲"),
        ("confirm" + "Edit", "编辑提交"),
        ("cancel" + "Edit", "编辑取消"),
        ("onDocument" + "PointerDown", "document 外部点击监听"),
        ("popper" + "Class", "编辑浮层 popper class"),
        ("block-" + "editor", "编辑器样式"),
    )
    for token, label in forbidden_tokens:
        if token in block_text:
            problems.append(
                f"{render_location(rel_block_text, find_line_number(block_text, re.escape(token)))} "
                f"仍残留 {label}（`{token}`）——C3 要求块内编辑能力零残留"
            )

    if "emit('select'" not in block_text and 'emit("select"' not in block_text:
        problems.append(f"{rel_block_text} 缺少 `emit('select')`（R22-AC1 选中高亮保留）")
    if "(e: 'select', block: Block): void" not in block_text:
        problems.append(f"{rel_block_text} 的 emits 未声明 `(e: 'select', block: Block)`")
    if "<el-tooltip" not in block_text:
        problems.append(f"{rel_block_text} 缺少 `el-tooltip`（R22-AC3 追溯块展示 reason）")
    if ':disabled="!isTraceBlock"' not in block_text:
        problems.append(
            f"{rel_block_text} 的 el-tooltip 缺少 `:disabled=\"!isTraceBlock\"`"
            "（raw 块不应弹 tooltip）"
        )
    if "kind !== 'raw'" not in block_text and 'kind !== "raw"' not in block_text:
        problems.append(f"{rel_block_text} 未按 `kind !== 'raw'` 判定追溯块")

    # 全仓零残留：src（组件/仓库/视图） + tests/frontend（排除本脚本自身）
    legacy_symbols = (
        "on" + "EditBlock",
        "block" + "Overrides",
        "resolve" + "BlockFieldKey",
        "@ed" + "it=",
    )
    scan_roots = (src_dir, Path(__file__).resolve().parent)
    self_path = Path(__file__).resolve()
    hits: list[str] = []
    scanned = 0
    for root in scan_roots:
        for file_path in iter_source_files(root, (".vue", ".ts", ".js", ".cjs", ".py")):
            if file_path.resolve() == self_path:
                continue
            scanned += 1
            text = file_path.read_text(encoding="utf-8", errors="replace")
            for symbol in legacy_symbols:
                if symbol in text:
                    hits.append(f"{file_path.relative_to(root).as_posix()}（{symbol}）")
    if hits:
        problems.append("块编辑残留符号命中：" + "、".join(sorted(set(hits))))

    if "@ed" + "it=" in ai_panel:
        problems.append(
            f"{render_location(rel_ai_panel, find_line_number(ai_panel, '@ed' + 'it='))} "
            "AiPanel 仍绑定 `@edit`（R22-AC4 要求模板无 @edit）"
        )
    override_merge = "block" + "Overrides"
    if override_merge in ai_panel:
        problems.append(f"{rel_ai_panel} 仍持有 `{override_merge}` 覆盖态")
    if re.search(r"\?\?\s*block\.text", ai_panel):
        problems.append(
            f"{render_location(rel_ai_panel, find_line_number(ai_panel, r'\\?\\?\\s*block\\.text'))} "
            "displayBlocks 仍做块内文本覆盖（R22-AC4 只允许草稿块 + live 虚拟块）"
        )
    if "[...draft.blocks]" not in ai_panel:
        problems.append(f"{rel_ai_panel} 的 displayBlocks 未直接展开 `[...draft.blocks]`")
    if "LIVE_BLOCK_ID" not in ai_panel:
        problems.append(f"{rel_ai_panel} 缺少 `LIVE_BLOCK_ID` live 虚拟块")
    if "@select=\"onSelectBlock\"" not in ai_panel:
        problems.append(f"{rel_ai_panel} 未保留 `@select=\"onSelectBlock\"`（R22-AC1）")
    if "draft.setField(" not in ai_panel:
        problems.append(f"{rel_ai_panel} 缺少 `draft.setField(`（R22-AC5 右侧手改路径不回退）")
    if "draft.applyExtractIncremental(" not in ai_panel:
        problems.append(f"{rel_ai_panel} 缺少 `draft.applyExtractIncremental(`（R22-AC6 不回退）")
    if "请在右侧字段面板编辑对应字段，或补一句话做增量解析" not in ai_panel:
        problems.append(f"{rel_ai_panel} 清空草稿文案未改为「右侧字段面板 / 增量解析」（R22-AC7）")
    if "点击左侧文字块" in ai_panel:
        problems.append(
            f"{render_location(rel_ai_panel, find_line_number(ai_panel, '点击左侧文字块'))} "
            "仍存在旧引导「点击左侧文字块」（R22-AC7）"
        )

    # 观察项（不判 FAIL）：cursor 值。plan §B-2 写 `cursor: default`，O-D4-6 又写
    # 「契约只固定『与追溯块一致』」，两处口径冲突；此处只输出事实，交由 Leader 裁定。
    cursor_match = re.search(r"\.block-text\s*\{[^}]*?cursor:\s*(\w+)", block_text, re.S)
    if cursor_match:
        print(
            f"        INFO {rel_block_text} `.block-text` 的 cursor = {cursor_match.group(1)}"
            f"（plan §B-2 期望 default；O-D4-6 期望「与追溯块一致」——观察项，不计 FAIL）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_block_text}：编辑浮层/编辑态/编辑缓冲/document 监听/popper/编辑器样式 全部 0 命中，"
        f"`@select` + `el-tooltip(:disabled=!isTraceBlock)` 保留；扫描 {scanned} 个文件，"
        f"`{'`/`'.join(legacy_symbols)}` 全仓 0 命中；{rel_ai_panel} 无 @edit / 无覆盖态、"
        "displayBlocks 直接展开 draft.blocks + live 虚拟块，清空文案已改为右侧字段面板/增量解析"
    )


def check_trace_v4(rel_path: str, src_dir: Path) -> str:
    """⑳ `C-TRACE@2`（C4）：解析自动落值不留痕，仅三处显式采纳留痕。"""
    raw_text = load_text(src_dir / rel_path)
    text = strip_ts_comments(raw_text)
    problems: list[str] = []

    legacy_helper = "applied" + "TextAt"
    if legacy_helper in raw_text:
        problems.append(
            f"{render_location(rel_path, find_line_number(raw_text, legacy_helper))} "
            f"仍存在 `{legacy_helper}()`（R22-AC10 要求全仓零命中，且不得保留别名）"
        )

    applied_calls = len(re.findall(r"pushTraceBlock\('ai_applied'", text))
    if applied_calls != 3:
        problems.append(
            f"{rel_path} 的 `pushTraceBlock('ai_applied'` 共 {applied_calls} 处，契约要求恰 3 处"
            "（adoptChange / adoptSuggestion / adoptPolished）"
        )
    for function_name in ("adoptChange", "adoptSuggestion", "adoptPolished"):
        body, line = function_body(text, function_name)
        if "pushTraceBlock('ai_applied'" not in body:
            problems.append(
                f"{render_location(rel_path, line)} {function_name}() 函数体内缺少 "
                "`pushTraceBlock('ai_applied'`（R22-AC9 显式采纳留痕）"
            )
    for function_name in ("applyExtract", "applyExtractIncremental"):
        body, line = function_body(text, function_name)
        if "ai_applied" in body:
            problems.append(
                f"{render_location(rel_path, line)} {function_name}() 函数体内仍出现 `ai_applied`"
                "（R22-AC8 解析自动落值不得留痕）"
            )

    if re.search(r"(?<![\w.])res\.applied_texts", text) or re.search(r"\.applied_texts\b", text):
        problems.append(
            f"{render_location(rel_path, find_line_number(text, r'\\.applied_texts'))} "
            "仍读取 `applied_texts`（后端契约保留，但前端不得消费，C-TRACE@2 §C）"
        )
    if "appendUserNote" not in text:
        problems.append(f"{rel_path} 丢失 `appendUserNote()`（增量解析的用户补充原文留痕不得误删）")
    if "pushTraceBlock('user_edit'" not in text:
        problems.append(f"{rel_path} 丢失 `pushTraceBlock('user_edit'`（R14 手改留痕不得回退）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：`{legacy_helper}` 0 命中；`pushTraceBlock('ai_applied'` 恰 3 处且分别落在 "
        "adoptChange/adoptSuggestion/adoptPolished；applyExtract 与 applyExtractIncremental 体内 "
        "0 命中；`applied_texts` 仅注释；appendUserNote 与 user_edit 留痕保留"
    )


def check_voice_v4(rel_composer: str, rel_slicer: str, src_dir: Path) -> str:
    """㉑ `C-VOICEUI@4 §C`（C5）：`stopping` 收尾窗口 + onend 结算 + 零散切片守卫。"""
    raw_text = load_text(src_dir / rel_composer)
    text = strip_ts_comments(raw_text)
    slicer_text = load_text(src_dir / rel_slicer)
    problems: list[str] = []

    legacy_timer = "stop" + "Timer"
    if legacy_timer in text:
        # 去注释后仍命中 = 存在旧声明/别名（Q5 禁止）；仅注释提及则属演进说明，不计 FAIL
        problems.append(
            f"{render_location(rel_composer, find_line_number(text, legacy_timer))} "
            f"仍存在 `{legacy_timer}` 声明或别名（已由 forceFinalizeTimer 取代，Q5 不得留旧名）"
        )
    elif legacy_timer in raw_text:
        print(
            f"        INFO {rel_composer} 仅在注释中提及旧名 `{legacy_timer}`"
            f"（重命名演进说明，非声明/别名，不计 FAIL）"
        )
    if not re.search(r"FORCE_FINALIZE_MS\s*=\s*3000\b", text):
        problems.append(f"{rel_composer} 缺少 `FORCE_FINALIZE_MS = 3000`（3s 兜底）")
    for symbol in ("stopping", "forceFinalizeTimer", "finalizeTimer", "commitStoppedSession"):
        if symbol not in text:
            problems.append(f"{rel_composer} 缺少收尾符号 `{symbol}`")

    # stop()：只置窗口 + 兜底，不得自己发尾片 / 清缓冲
    stop_body, stop_line = function_body(text, "stop")
    if "stopping = true" not in stop_body:
        problems.append(f"{render_location(rel_composer, stop_line)} stop() 未置 `stopping = true`")
    for forbidden in ("resetLocalBuffer(", "enqueue(", "FINAL_DELAY_MS"):
        if forbidden in stop_body:
            problems.append(
                f"{render_location(rel_composer, stop_line)} stop() 体内出现 `{forbidden}`"
                "（R23-AC1 禁止：不得清缓冲 / 不得入队 / 不得启动 800ms 尾片定时器）"
            )
    if "detachRecognition" not in text:
        problems.append(
            f"{rel_composer} 缺少 `detachRecognition()`（3s 兜底先摘回调，防提交后晚到帧改写缓冲）"
        )
    elif "detachRecognition()" not in stop_body:
        problems.append(
            f"{render_location(rel_composer, stop_line)} stop() 的 3s 兜底路径未调用 "
            "`detachRecognition()`（兜底结算前必须摘掉识别回调）"
        )

    # scheduleSlices()：首条语句为收尾守卫
    slices_body, slices_line = function_body(text, "scheduleSlices")
    first_statement = slices_body.lstrip("{").strip()
    if not first_statement.startswith("if (stopping) return"):
        problems.append(
            f"{render_location(rel_composer, slices_line)} scheduleSlices() 首条语句不是 "
            "`if (stopping) return`（R23-AC4/R23-AC8：收尾窗口内不得零散发 is_final=false）"
        )

    # onend：两分支互斥
    onend_body, onend_line = arrow_property_body(text, "onend")
    if "if (stopping)" not in onend_body:
        problems.append(
            f"{render_location(rel_composer, onend_line)} onend 缺少 `if (stopping)` 分支"
        )
    if "finalizeTimer" not in onend_body:
        problems.append(f"{rel_composer} onend 未设置 `finalizeTimer`")
    if "FINAL_DELAY_MS" not in onend_body:
        problems.append(
            f"{rel_composer} onend 未使用 `FINAL_DELAY_MS`（R23-AC2 需延迟 800ms 结算）"
        )
    if "commitStoppedSession()" not in onend_body:
        problems.append(f"{rel_composer} onend 分支未调用 `commitStoppedSession()`")
    if "forceFinalizeTimer" not in onend_body:
        problems.append(f"{rel_composer} onend 未先清理 `forceFinalizeTimer`（兜底与 onend 二选一）")

    # commitStoppedSession()：五步顺序
    commit_body, commit_line = function_body(text, "commitStoppedSession")
    ordered = ("pendingText", "sentIndex", "stopping = false", "enqueue(", "clearLiveText")
    positions = [commit_body.find(token) for token in ordered]
    if any(position < 0 for position in positions):
        missing = [token for token, position in zip(ordered, positions) if position < 0]
        problems.append(
            f"{render_location(rel_composer, commit_line)} commitStoppedSession() 缺少步骤 {missing}"
        )
    elif positions != sorted(positions):
        problems.append(
            f"{render_location(rel_composer, commit_line)} commitStoppedSession() 步骤顺序错误："
            "应为 pendingText → sentIndex → stopping=false → enqueue(tail, true) → clearLiveText"
        )
    if "if (!stopping) return" not in commit_body:
        # 第五轮 D4 已补齐首行幂等守卫（R25-AC8）；本条由「观察项」升级为**硬断言**，
        # 与 ㉕ `check_commit_guard` 保持同一口径（plan 2.1.0：不得保留双口径）。
        problems.append(
            f"{render_location(rel_composer, commit_line)} commitStoppedSession() 缺少首行 "
            "`if (!stopping) return`（R25-AC8 幂等守卫：onend 延迟结算与 3s 兜底不可双发尾片）"
        )

    # start() / abort()：清 stopping 与两个定时器
    for function_name in ("start", "abort"):
        body, line = function_body(text, function_name)
        if "stopping = false" not in body:
            problems.append(
                f"{render_location(rel_composer, line)} {function_name}() 未清 `stopping = false`"
                "（R23-AC6）"
            )
        for timer in ("forceFinalizeTimer", "finalizeTimer"):
            if timer not in body:
                problems.append(
                    f"{render_location(rel_composer, line)} {function_name}() 未清理 `{timer}`"
                )

    # 既有收尾链不回退
    drain_body, drain_line = function_body(text, "drain")
    if "resetLocalBuffer()" not in drain_body:
        problems.append(
            f"{render_location(rel_composer, drain_line)} drain() 尾片成功后丢失 "
            "`resetLocalBuffer()`（唯一清空点，R23-AC5）"
        )
    finalize_body, finalize_line = function_body(text, "finalizeIfIdle")
    if "finishStreaming()" not in finalize_body or "notifyAllChunksSent()" not in finalize_body:
        problems.append(
            f"{render_location(rel_composer, finalize_line)} finalizeIfIdle() 缺少 "
            "`finishStreaming()` / `notifyAllChunksSent()`（R23-AC9 两 agent 顺序）"
        )
    elif finalize_body.find("finishStreaming()") > finalize_body.find("notifyAllChunksSent()"):
        problems.append(
            f"{render_location(rel_composer, finalize_line)} finalizeIfIdle() 顺序错误："
            "必须先 finishStreaming() 再 notifyAllChunksSent()"
        )

    handler_body, handler_line = function_body(text, "handleRecognitionResult")
    for call in ("applyFinal(", "applyInterim("):
        if call not in handler_body:
            problems.append(
                f"{render_location(rel_composer, handler_line)} handleRecognitionResult() 丢失 "
                f"`{call}`（R23-AC4 收尾窗口内仍需保帧）"
            )

    # Q4：voiceSlicer 5 常量不变
    for name, value in EXPECTED_VOICE_SLICER_CONSTANTS.items():
        match = re.search(rf"{name}\s*(?::\s*number)?\s*=\s*(\d+)", slicer_text)
        if match is None:
            problems.append(f"{rel_slicer} 缺少常量 {name} = {value}")
        elif match.group(1) != value:
            problems.append(
                f"{render_location(rel_slicer, slicer_text.count(chr(10), 0, match.start()) + 1)} "
                f"{name} = {match.group(1)}，契约要求 {value}（Q4 本轮常量不动）"
            )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_composer}：`{legacy_timer}` 0 命中、`FORCE_FINALIZE_MS=3000`；"
        f"stop() 只置 `stopping=true` + 3s 兜底（无 resetLocalBuffer/enqueue/FINAL_DELAY_MS，"
        "兜底先 detachRecognition）；scheduleSlices 首条 `if (stopping) return`；"
        f"onend 含 `if (stopping)` → finalizeTimer(FINAL_DELAY_MS)；commitStoppedSession 五步顺序正确；"
        "start/abort 均清 stopping + 两个定时器；drain 保留 resetLocalBuffer；"
        "finalizeIfIdle 为 finishStreaming → notifyAllChunksSent；handleRecognitionResult 仍保帧；"
        f"{rel_slicer} 5 常量不变（1/12/800/800/200）"
    )


# =========================================================================== #
# 第五轮（T4）新增契约检查：D1 穿透白名单 / D2 续接保留去重链 /
#   D3 续接重叠裁剪 / D4 尾片结算幂等
# 契约来源：plan `campus-task-agent-iteration5` P5 的
#   `C-DEV@1`（§2.2.1）· `C-VOICEUI@5`（§2.2.2 §1~§4）· R26-AC4
# =========================================================================== #

#: `C-DEV@1`：`server.allowedHosts` 的唯一合法数组元素（前导点覆盖全部子域）
EXPECTED_ALLOWED_HOSTS: tuple[str, ...] = (".takin.cc",)

#: `C-VOICEUI@5 §1`：`start()` 内的会话分支条件（D2 位置断言锚点）
KEEP_SESSION_CONDITION: str = r"if\s*\(\s*options\.keepSession\s*&&\s*sessionId\s*\)\s*\{"


def _code_lines(text: str) -> list[str]:
    """按行拆分并去掉空行与行首空白（调用方应先 ``strip_ts_comments``）。"""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _extract_if_else_branches(code: str, condition_pattern: str) -> tuple[str, str]:
    """提取 ``if (<条件>) { A } else { B }`` 的 A / B 两个分支体。

    入参必须是已 ``strip_ts_comments`` 的文本（注释里的伪代码不得参与结构判定）。
    用途：D2 的位置断言——``dedupTail = ''`` 只允许出现在 else（新建会话）分支内。
    """
    match = re.search(condition_pattern, code)
    if match is None:
        raise ContractError(f"未找到分支条件 `{condition_pattern}`")
    open_index = code.find("{", match.end() - 1)
    if open_index < 0:
        raise ContractError(f"条件 `{condition_pattern}` 之后未找到分支体 `{{`")
    if_body = extract_balanced_braces(code, open_index)
    tail = code[open_index + len(if_body) :]
    else_match = re.match(r"\s*else\s*\{", tail)
    if else_match is None:
        raise ContractError(f"条件 `{condition_pattern}` 之后未找到 else 分支")
    else_open = open_index + len(if_body) + else_match.end() - 1
    else_body = extract_balanced_braces(code, else_open)
    return if_body, else_body


def check_dev_allowed_hosts(rel_path: str, src_dir: Path) -> str:
    """㉒ `C-DEV@1`（D1）：allowedHosts 恰 1 个元素 + port / proxy 冻结值一字不动。"""
    frontend_dir = src_dir.parent
    raw = load_text(frontend_dir / rel_path)

    problems: list[str] = []
    occurrences = len(re.findall(r"\ballowedHosts\b", raw))
    if occurrences != 1:
        problems.append(
            f"{rel_path} 的 `allowedHosts` 出现 {occurrences} 处（契约要求恰 1 处，防重复追加键）"
        )

    block_match = re.search(r"allowedHosts\s*:\s*\[([^\]]*)\]", raw)
    if block_match is None:
        problems.append(f"{rel_path} 缺少 `allowedHosts: [...]`（R25-AC2）")
    else:
        elements = tuple(re.findall(r"['\"]([^'\"]+)['\"]", block_match.group(1)))
        if elements != EXPECTED_ALLOWED_HOSTS:
            problems.append(
                f"{rel_path} 的 allowedHosts 数组为 {list(elements)}，契约要求恰 1 个 "
                f"{list(EXPECTED_ALLOWED_HOSTS)}（RK-5-4：不得重复追加）"
            )
        host_index = block_match.start()
        # 用结构锚点而非裸单词：文件顶部注释含 "dev server" 字样，裸 find("server") 会误锚。
        server_match = re.search(r"server\s*:\s*\{", raw)
        proxy_match = re.search(r"proxy\s*:\s*\{", raw)
        if server_match is None or proxy_match is None:
            problems.append(f"{rel_path} 缺少 `server: {{` 或 `proxy: {{` 结构锚点")
        elif not (server_match.start() < host_index < proxy_match.start()):
            problems.append(
                f"{render_location(rel_path, find_line_number(raw, r'allowedHosts'))} "
                "allowedHosts 未位于 `server: {` 与 `proxy: {` 之间（C-DEV@1 键路径断言）"
            )

    frozen = (
        ("port: 5173", r"port\s*:\s*5173"),
        (
            "target: 'http://127.0.0.1:8000'",
            r"target\s*:\s*['\"]http://127\.0\.0\.1:8000['\"]",
        ),
        ("changeOrigin: true", r"changeOrigin\s*:\s*true"),
        ("plugins: [vue()]", r"plugins\s*:\s*\[\s*vue\(\)\s*\]"),
    )
    for label, pattern in frozen:
        if re.search(pattern, raw) is None:
            problems.append(f"{rel_path} 缺少冻结配置 `{label}`（R25-AC2：其余配置一字不动）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：`allowedHosts: ['.takin.cc']` 恰 1 处且数组恰 1 个元素，"
        "位于 server 与 proxy 之间；port 5173 / proxy target / changeOrigin / plugins 冻结值未变"
    )


def check_voice_v5_dedup_chain(rel_path: str, src_dir: Path) -> str:
    """㉓ `C-VOICEUI@5 §1`（D2）：dedupTail 只在新建会话分支清空，续接分支零命中。"""
    raw = load_text(src_dir / rel_path)
    text = strip_ts_comments(raw)
    start_body, start_line = function_body(text, "start")
    if_body, else_body = _extract_if_else_branches(start_body, KEEP_SESSION_CONDITION)

    problems: list[str] = []
    if "dedupTail = ''" in if_body:
        problems.append(
            f"{render_location(rel_path, start_line)} keepSession 续接分支内仍清空 "
            "`dedupTail = ''`（R25-AC3：续接必须保留去重链，否则 Edge 重吐前缀被当新内容）"
        )
    if "dedupTail = ''" not in else_body:
        problems.append(
            f"{render_location(rel_path, start_line)} 新建会话 else 分支缺少 "
            "`dedupTail = ''`（R25-AC4：新一轮录音必须与上一轮上下文隔离）"
        )
    if "resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET" not in if_body:
        problems.append(
            f"{render_location(rel_path, start_line)} 续接分支未进入重吐裁剪窗口"
            "（缺少 `resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET`，R25-AC6/AC7）"
        )
    if "resumedRestartFrames = 0" not in else_body:
        problems.append(
            f"{render_location(rel_path, start_line)} 新建会话分支未把重吐裁剪窗口归零"
            "（R25-AC7）"
        )
    created_index = else_body.find("sessionId = created")
    clear_index = else_body.find("dedupTail = ''")
    if 0 <= created_index < clear_index:
        pass
    elif created_index >= 0 and clear_index >= 0:
        problems.append(
            f"{render_location(rel_path, start_line)} else 分支的 `dedupTail = ''` "
            "出现在 `sessionId = created` 之前（RK-5-2：新建会话后再清去重链）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_path}：`dedupTail = ''` 在 else（新建会话）分支内、keepSession 分支 0 命中；"
        "续接进入 3 帧重吐窗口，新会话窗口归零"
    )


def check_trim_restart_overlap(rel_slicer: str, rel_composer: str, src_dir: Path) -> str:
    """㉔ `C-VOICEUI@5 §2/§3`（D3）：纯函数导出 + 仅定稿追加路径接入。

    第六轮 G1 起展示与发送分层：`applyInterim` 只调用 `pushLiveText`，**不落缓冲、
    不切片、不发 AI**；只有 ITN 定稿帧（`applyFinal`）先裁剪再追加。检查口径随之
    从「interim 与 final 都必须裁剪」改为「interim 只展示、final 先裁剪再追加」。
    """
    slicer_text = strip_ts_comments(load_text(src_dir / rel_slicer))
    composer = strip_ts_comments(load_text(src_dir / rel_composer))

    problems: list[str] = []
    exported = collect_exported_functions(slicer_text)
    if "trimRestartOverlap" not in exported:
        problems.append(f"{rel_slicer} 未导出 `trimRestartOverlap()`（C-VOICEUI@5 §2）")
    if re.search(r"^\s*import\s", slicer_text, re.MULTILINE):
        problems.append(f"{rel_slicer} 出现 import 语句（Q8：voiceSlicer 必须零 import）")

    import_pattern = (
        r"import\s*\{[^}]*\btrimRestartOverlap\b[^}]*\}\s*from\s*"
        r"['\"][^'\"]*utils/voiceSlicer['\"]"
    )
    if re.search(import_pattern, composer) is None:
        problems.append(
            f"{rel_composer} 未从 utils/voiceSlicer 引入 `trimRestartOverlap`"
            "（C-VOICEUI@5 §3 接入层）"
        )

    try:
        trim_body, trim_line = function_body(composer, "trimResumedTranscript")
    except ContractError as exc:
        problems.append(f"{rel_composer} 缺少接入层包装 `trimResumedTranscript()`：{exc}")
        trim_body, trim_line = "", 0
    if trim_body and "trimRestartOverlap(" not in trim_body:
        problems.append(
            f"{render_location(rel_composer, trim_line)} trimResumedTranscript() "
            "未调用 `trimRestartOverlap()`"
        )

    try:
        interim_body, interim_line = function_body(composer, "applyInterim")
    except ContractError as exc:
        problems.append(f"{rel_composer} 缺少函数 `applyInterim()`：{exc}")
        interim_body, interim_line = "", 0
    if interim_body:
        if "pushLiveText(transcript)" not in interim_body:
            problems.append(
                f"{render_location(rel_composer, interim_line)} applyInterim() 未调用 "
                "`pushLiveText(transcript)`（interim 只做实时显示）"
            )
        forbidden = (
            "trimResumedTranscript(",
            "fullText.value",
            "sentIndex",
            "scheduleSlices(",
            "enqueue(",
            "streamParse(",
        )
        hits = [token for token in forbidden if token in interim_body]
        if hits:
            problems.append(
                f"{render_location(rel_composer, interim_line)} applyInterim() 体仍出现 "
                + " / ".join(f"`{token}`" for token in hits)
                + "（第六轮 G1：临时结果只展示，不落缓冲、不切片、不发 AI）"
            )

    try:
        final_body, final_line = function_body(composer, "applyFinal")
    except ContractError as exc:
        problems.append(f"{rel_composer} 缺少函数 `applyFinal()`：{exc}")
        final_body, final_line = "", 0
    if final_body:
        trim_index = final_body.find("trimResumedTranscript(")
        append_index = final_body.find("fullText.value +=")
        if trim_index < 0:
            problems.append(
                f"{render_location(rel_composer, final_line)} applyFinal() 未接入续接重吐裁剪"
                "（C-VOICEUI@5 §3：仅定稿追加路径先裁剪再追加）"
            )
        elif append_index < 0:
            problems.append(
                f"{render_location(rel_composer, final_line)} applyFinal() 缺少定稿追加语句 "
                "`fullText.value +=`（C-VOICEUI@5 §3：定稿是唯一写入缓冲的入口）"
            )
        elif trim_index > append_index:
            problems.append(
                f"{render_location(rel_composer, final_line)} applyFinal() 的裁剪调用晚于追加语句"
                "（R25-AC6：必须先裁剪再追加）"
            )

        guard_index = final_body.find("if (!frameText)")
        if guard_index < 0:
            problems.append(
                f"{render_location(rel_composer, final_line)} applyFinal() 缺少空帧守卫 "
                "`if (!frameText)`"
            )
        else:
            guard_open = final_body.find("{", guard_index)
            if guard_open < 0:
                problems.append(
                    f"{render_location(rel_composer, final_line)} applyFinal() 的 "
                    "`if (!frameText)` 之后未找到分支体 `{`"
                )
            else:
                try:
                    guard_body = extract_balanced_braces(final_body, guard_open)
                except ContractError as exc:
                    problems.append(
                        f"{render_location(rel_composer, final_line)} applyFinal() 的空帧守卫分支"
                        f"无法解析：{exc}"
                    )
                else:
                    if re.search(r"\breturn\b", guard_body) is None:
                        problems.append(
                            f"{render_location(rel_composer, final_line)} applyFinal() 的空帧守卫"
                            "分支缺少 `return`（空帧必须直接返回）"
                        )
                    if "fullText.value +=" in guard_body:
                        problems.append(
                            f"{render_location(rel_composer, final_line)} applyFinal() 的空帧守卫"
                            "分支内出现 `fullText.value +=`（空帧不得写入缓冲）"
                        )

    try:
        replace_body, replace_line = function_body(composer, "replaceTail")
    except ContractError as exc:
        problems.append(f"{rel_composer} 缺少函数 `replaceTail()`：{exc}")
        replace_body, replace_line = "", 0
    if replace_body and (
        "trimResumedTranscript(" in replace_body or "trimRestartOverlap(" in replace_body
    ):
        problems.append(
            f"{render_location(rel_composer, replace_line)} replaceTail() 内出现重吐裁剪"
            "（C-VOICEUI@5 §3：replaceTail 路径不得二次裁剪，避免丢字）"
        )

    if "RESUMED_RESTART_FRAME_BUDGET = 3" not in composer:
        problems.append(
            f"{rel_composer} 缺少 `RESUMED_RESTART_FRAME_BUDGET = 3`（续接后前 3 帧窗口）"
        )

    # 第五轮 T2 补修（O-T4-5-1 / R25-AC7）：resetLocalBuffer() 必须把重吐窗口归零，
    # 否则上一轮残留的窗口计数会污染下一次会话（本轮新增的实现点，必须有断言）。
    try:
        reset_body, reset_line = function_body(composer, "resetLocalBuffer")
    except ContractError as exc:
        problems.append(f"{rel_composer} 缺少函数 `resetLocalBuffer()`：{exc}")
        reset_body, reset_line = "", 0
    if reset_body and "resumedRestartFrames = 0" not in reset_body:
        problems.append(
            f"{render_location(rel_composer, reset_line)} resetLocalBuffer() 未复位 "
            "`resumedRestartFrames = 0`（R25-AC7：防跨会话误裁）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_slicer} 导出零 import 纯函数 `trimRestartOverlap()`；{rel_composer} 在 "
        "applyInterim 只调用 `pushLiveText(transcript)`（不落缓冲、不切片、不发 AI），"
        "applyFinal 在追加语句前调用 `trimResumedTranscript()`（窗口 3 帧）且空帧守卫内不追加，"
        "resetLocalBuffer() 复位 `resumedRestartFrames = 0`，replaceTail 路径 0 命中"
    )


def check_commit_guard(rel_path: str, src_dir: Path) -> str:
    """㉕ `C-VOICEUI@5 §4`（D4）：commitStoppedSession 首条有效语句为幂等守卫。"""
    text = strip_ts_comments(load_text(src_dir / rel_path))
    body, line = function_body(text, "commitStoppedSession")
    lines = _code_lines(body)
    first = lines[1] if lines and lines[0] == "{" else (lines[0] if lines else "")

    problems: list[str] = []
    if not first.startswith("if (!stopping) return"):
        problems.append(
            f"{render_location(rel_path, line)} commitStoppedSession() 首条有效语句为 "
            f"`{first}`，契约要求 `if (!stopping) return`（R25-AC8 幂等守卫）"
        )
    guard_index = body.find("if (!stopping) return")
    tail_index = body.find("const tail")
    if guard_index >= 0 and tail_index >= 0 and guard_index > tail_index:
        problems.append(
            f"{render_location(rel_path, line)} 幂等守卫出现在 `const tail` 之后"
            "（守卫必须是函数体第一条语句）"
        )
    ordered = ("pendingText", "sentIndex", "stopping = false", "enqueue(", "clearLiveText")
    positions = [body.find(token) for token in ordered]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        problems.append(
            f"{render_location(rel_path, line)} commitStoppedSession() 五步顺序被改动"
            "（Q10：守卫之后 pendingText → sentIndex → stopping=false → enqueue(tail,true) → clearLiveText）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        "commitStoppedSession() 首条有效语句为 `if (!stopping) return`；"
        "其后五步顺序保持不变（Q10 收尾时序冻结）"
    )


def check_voice_r2_sink(
    rel_composer: str, rel_dock: str, rel_console: str, src_dir: Path
) -> str:
    """㉖ `C-VOICE-SINK@1` / `C-AI-VOICE@1` / `C-AI-VOICEUI@1`（AIW-09 r2）。

    固定首轮审查修复后的行为：
    - 新轮不得复用上一轮未释放的 `sessionSink`；
    - 每个切片携带发起轮 sink/轮次，收尾落到发起轮 sink；
    - 录音中 AI 输入框禁用，避免手打被 interim/定稿整体覆盖。
    """
    text = strip_ts_comments(load_text(src_dir / rel_composer))
    problems: list[str] = []

    current_body, current_line = function_body(text, "currentSink")
    if "sessionSink" in current_body:
        problems.append(
            f"{render_location(rel_composer, current_line)} currentSink() 仍引用 sessionSink"
            "（R2-C1：上一轮尾片未释放时会串目标）"
        )
    if "sessionSink ?? currentSink()" not in text:
        problems.append(
            f"{rel_composer} 缺少 `activeSink()` 的 `sessionSink ?? currentSink()` 回退"
        )

    queued = re.search(r"interface QueuedChunk\s*\{(.*?)\}", text, re.S)
    if queued is None:
        problems.append(f"{rel_composer} 缺少 `interface QueuedChunk`")
    else:
        for token in ("sink: VoiceSink", "round: number"):
            if token not in queued.group(1):
                problems.append(
                    f"{rel_composer} QueuedChunk 缺少 `{token}`（R2-C1：队列项必须固定发起轮目标）"
                )

    start_body, start_line = function_body(text, "start")
    if "if (!options.keepSession)" not in start_body or "settlePreviousSession()" not in start_body:
        problems.append(
            f"{render_location(rel_composer, start_line)} start() 非续接分支未先 "
            "`settlePreviousSession()`（R2-C1：旧轮尾片窗口内再开录不得丢尾句）"
        )
    if "finalizeSinks.length = 0" in start_body:
        problems.append(
            f"{render_location(rel_composer, start_line)} start() 整批清空 finalizeSinks"
            "（R2-I1：已落地旧轮 sink 的 finishStreaming 会被丢弃）"
        )

    drain_body, drain_line = function_body(text, "drain")
    if "item.sink.applyStream" not in drain_body:
        problems.append(
            f"{render_location(rel_composer, drain_line)} drain() 未使用 `item.sink.applyStream`"
            "（R2-I1：在飞切片必须写回发起轮目标）"
        )
    if "currentSink()" in drain_body:
        problems.append(
            f"{render_location(rel_composer, drain_line)} drain() 仍使用 currentSink()"
        )

    finalize_body, finalize_line = function_body(text, "finalizeIfIdle")
    if "finalizeSinks" not in text or "finalizeSinks" not in finalize_body:
        problems.append(
            f"{render_location(rel_composer, finalize_line)} finalizeIfIdle() 未使用 finalizeSinks"
            "（R2-I1：旧轮尾片晚到不得被新轮 sink 覆盖，finishStreaming 必须逐轮落地）"
        )
    commit_body, commit_line = function_body(text, "commitStoppedSession")
    if "const sink = activeSink()" not in commit_body or "enqueue(tail, true, sink)" not in commit_body:
        problems.append(
            f"{render_location(rel_composer, commit_line)} commitStoppedSession() 未先固定发起轮 sink"
            "（R2-I1：空尾片入队释放 sessionSink 后不能再用当前 sink 清 live）"
        )
    enqueue_body, enqueue_line = function_body(text, "enqueue")
    if (
        "function enqueue(chunk: string, isFinal: boolean, sink: VoiceSink = activeSink())"
        not in text
    ):
        problems.append(
            f"{render_location(rel_composer, enqueue_line)} enqueue() 签名未显式接收/固定 sink"
            "（R2-I1：队列项必须携带发起轮目标）"
        )
    if "queue.push({ chunk, isFinal, sink, round: roundId })" not in enqueue_body:
        problems.append(
            f"{render_location(rel_composer, enqueue_line)} enqueue() 入队项未携带 sink/round"
            "（R2-I1）"
        )
    settle_body, settle_line = function_body(text, "settlePreviousSession")
    if "resumeTimer" not in settle_body:
        problems.append(
            f"{render_location(rel_composer, settle_line)} settlePreviousSession() 未清理 resumeTimer"
            "（R2-C1：旧轮自动续接不得在新页面重开）"
        )

    page_expectations = {
        rel_dock: ("dock-input", "dock-send", "dock-voice"),
        rel_console: ("composer-input", "send-button", "composer-voice"),
    }

    def binding_of(page: str, class_name: str) -> str | None:
        """取指定 class 元素上 `:disabled` 的真实表达式（240 字符内）。"""
        match = re.search(
            rf'class="{re.escape(class_name)}"[\s\S]{{0,240}}?:disabled="([^"]*)"', page
        )
        return match.group(1) if match else None

    for rel_path, (input_class, send_class, voice_class) in page_expectations.items():
        # 先剥离 TS 与 HTML 注释，注释里的伪绑定不能替代真实模板
        page = strip_ts_comments(load_text(src_dir / rel_path))
        page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
        if re.search(r"const voiceRecording = computed\(\(\) => voice\.recording\.value\)", page) is None:
            problems.append(
                f"{rel_path} 缺少 `const voiceRecording = computed(() => voice.recording.value)`"
                "（R2-I2：录音态必须来自共享 composer）"
            )
        for class_name, label in ((input_class, "输入框"), (send_class, "发送按钮")):
            expr = binding_of(page, class_name)
            if expr is None or "voiceRecording" not in expr or "!voiceRecording" in expr:
                problems.append(
                    f"{rel_path} {label}（class=\"{class_name}\"）disabled 未绑定录音态（R2-I2）"
                )
        voice_expr = binding_of(page, voice_class)
        if voice_expr is None or "!voiceRecording &&" not in voice_expr:
            problems.append(
                f"{rel_path} 语音按钮（class=\"{voice_class}\"）录音中必须可停止"
                "（disabled 需为 `!voiceRecording && ...`）"
            )

    sink_text = load_text(src_dir / "composables/useAiVoiceSink.ts")
    for token in ("createAiChatVoiceSink", "setInputForScope", "applyStream"):
        if token not in sink_text:
            problems.append(f"composables/useAiVoiceSink.ts 缺少 `{token}`（C-AI-VOICE@1）")
    chat_text = load_text(src_dir / "stores/aiChat.ts")
    if "setInputForScope(" not in chat_text:
        problems.append("stores/aiChat.ts 缺少 `setInputForScope()`（C-AI-VOICE@1）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_composer}：currentSink 不复用 sessionSink；QueuedChunk 固定 sink+round；"
        "start 非续接先 settlePreviousSession（含 resumeTimer）；drain 用 item.sink；"
        "finalize 用 finalizeSinks 多轮队列；commit/enqueue 固定发起轮 sink；"
        f"{rel_dock}/{rel_console} 录音中禁用输入与发送；useAiVoiceSink/aiChat 写回接口齐备"
    )


# 追加到既有 21 项之后（第五轮契约检查；D1 / D2 / D3 / D4）
CHECKS = CHECKS + (
    (
        "㉒ C-DEV@1 穿透白名单 allowedHosts 恰 1 元素 + port/proxy 冻结",
        lambda: check_dev_allowed_hosts("vite.config.ts", SRC_DIR),
    ),
    (
        "㉓ C-VOICEUI@5 §1 续接保留 dedupTail + 新建会话清空",
        lambda: check_voice_v5_dedup_chain("composables/useVoiceComposer.ts", SRC_DIR),
    ),
    (
        "㉔ C-VOICEUI@5 §2/§3 trimRestartOverlap 导出 + 仅定稿追加路径接入 + resetLocalBuffer 复位",
        lambda: check_trim_restart_overlap(
            "utils/voiceSlicer.ts", "composables/useVoiceComposer.ts", SRC_DIR
        ),
    ),
    (
        "㉕ C-VOICEUI@5 §4 commitStoppedSession 首行幂等守卫",
        lambda: check_commit_guard("composables/useVoiceComposer.ts", SRC_DIR),
    ),
    (
        "㉖ C-VOICE-SINK@1 / C-AI-VOICEUI@1 r2：发起轮 sink 归属 + 录音中禁用输入",
        lambda: check_voice_r2_sink(
            "composables/useVoiceComposer.ts",
            "components/ai/AgentDock.vue",
            "views/AiConsole.vue",
            SRC_DIR,
        ),
    ),
)


# --------------------------------------------------------------------------- #
# r1（AIW-14 C-NAV-GROUPS@3 / C-BROWSE-TABS@3 / C-BROWSE-SPLIT@1 / C-FE-PEEK@2）
# --------------------------------------------------------------------------- #


def _media_blocks(text: str, query_pattern: str) -> list[str]:
    """收集 `@media (<query>) { ... }` 的块体（CSS 无嵌套，按花括号配对截取）。"""
    blocks: list[str] = []
    for match in re.finditer(r"@media\s*\(\s*" + query_pattern + r"\s*\)\s*\{", text):
        blocks.append(extract_balanced_braces(text, text.index("{", match.start())))
    return blocks


def _require(
    problems: list[str],
    text: str,
    token: str,
    rel_path: str,
    detail: str,
) -> int:
    """断言 `token` 出现；缺失时记录带文件行号的失败并返回 0。"""
    line = find_line_number(text, re.escape(token))
    if line == 0:
        problems.append(f"{rel_path} 缺少 `{token}`（{detail}）")
    return line


def check_nav_groups(rel_layout: str, rel_icon: str, src_dir: Path) -> str:
    """㉗ `C-NAV-GROUPS@3`：分组导航 + 本地内联 SVG + 折叠保留可访问名称。"""
    layout = strip_ts_comments(load_text(src_dir / rel_layout))
    icon = load_text(src_dir / rel_icon)
    problems: list[str] = []

    icon_import = _require(
        problems, layout, "import NavIcon", rel_layout, "导航必须复用本地内联 SVG 图标"
    )
    _require(problems, layout, "import SearchOverlay", rel_layout, "顶部搜索入口")
    if "<svg" not in icon:
        problems.append(f"{rel_icon} 不含内联 `<svg>`（不引入图标依赖）")
    for icon_name in ("library", "search", "new-chat", "recent", "history", "theme"):
        if f"'{icon_name}'" not in icon:
            problems.append(f"{rel_icon} NavIconName 缺少 `{icon_name}`")

    for group_label, group_title in (
        ("主导航", "顶部搜索按钮 + New chat 发布 + 主导航"),
        ("管理", "管理者我发布活动 / 发布者后台"),
        ("最近条目", "最近活动分组"),
        ("最近聊天", "最近聊天分组"),
        ("底部导航", "移动端底部导航保留主要入口"),
    ):
        _require(problems, layout, f'aria-label="{group_label}"', rel_layout, group_title)

    layout_line = _require(
        problems, layout, "icon: 'library'", rel_layout, "Library 必须进入主导航分组"
    )
    for token, detail in (
        (':aria-label="item.label"', "折叠时保留 aria-label"),
        (':title="item.label"', "折叠时保留 title"),
        (
            ":aria-current=\"isActive(item.name) ? 'page' : undefined\"",
            "当前页 aria-current=\"page\"",
        ),
        ("<NavIcon :name=\"item.icon\" />", "折叠时仍渲染 SVG"),
        ('<span v-if="!collapsed" class="nav-link__label">', "展开时显示文字"),
    ):
        _require(problems, layout, token, rel_layout, detail)

    _require(problems, layout, '<span>最近活动</span>', rel_layout, "最近活动分组")
    _require(problems, layout, '>最近聊天<', rel_layout, "最近聊天分组标题")
    for token, detail in (
        ('aria-label="搜索"', "顶部搜索按钮"),
        ('aria-label="发布事务"', "New chat 发布入口"),
        ('aria-label="退出登录"', "底部退出入口"),
    ):
        _require(problems, layout, token, rel_layout, detail)

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_layout}:{icon_import} 复用 {rel_icon} 内联 SVG；"
        f"library 导航项在第 {layout_line} 行；分组为 主导航/管理/最近条目/最近聊天/底部导航；"
        "折叠态保留 SVG + aria-label + title + aria-current=\"page\""
    )


def check_library_route(rel_router: str, rel_layout: str, rel_page: str, src_dir: Path) -> str:
    """㉘ `C-NAV-GROUPS@3`：Library 路由与入口存在，页面组件可解析。"""
    router_text = strip_ts_comments(load_text(src_dir / rel_router))
    layout = strip_ts_comments(load_text(src_dir / rel_layout))
    page = load_text(src_dir / rel_page)
    problems: list[str] = []

    route_match = re.search(
        r"name:\s*'library'\s*,\s*path:\s*'/library'\s*,\s*"
        r"component:\s*\(\)\s*=>\s*import\('\.\./views/LibraryPage\.vue'\)",
        router_text,
    )
    route_line = 0
    if route_match is None:
        problems.append(
            f"{rel_router} 缺少 Library 路由（name: 'library' + path: '/library' + "
            "component: () => import('../views/LibraryPage.vue')）"
        )
    else:
        route_line = router_text.count("\n", 0, route_match.start()) + 1

    entry_line = _require(
        problems,
        layout,
        "name: 'library', path: '/library', label: 'Library'",
        rel_layout,
        "主导航 Library 入口",
    )
    if '<h1 class="app-page-title">Library</h1>' not in page:
        problems.append(f"{rel_page} 缺少页面标题 `Library`（入口落地页）")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_router}:{route_line} Library 路由 name/path/component 齐备；"
        f"{rel_layout}:{entry_line} 主导航入口指向 /library；{rel_page} 标题为 Library"
    )


def check_ai_history(
    rel_console: str, rel_layout: str, rel_entry: str, src_dir: Path
) -> str:
    """㉙ `C-AI-HISTORY@3`：完整页历史抽屉 + `?conversation=` 恢复 + 侧栏最近 5 条真实记录。"""
    console = strip_ts_comments(load_text(src_dir / rel_console))
    layout = strip_ts_comments(load_text(src_dir / rel_layout))
    entry = strip_ts_comments(load_text(src_dir / rel_entry))
    problems: list[str] = []

    block_match = re.search(
        r'<div class="sidebar-group sidebar-history"[^>]*>(.*?)</div>(?=\s*<div class="sidebar-foot")',
        layout,
        re.S,
    )
    if block_match is None:
        problems.append(f"{rel_layout} 缺少 `sidebar-history` 分组")
    else:
        block = block_match.group(1)
        block_line = layout.count("\n", 0, block_match.start()) + 1
        if "历史即将接入" in layout:
            problems.append(
                f"{render_location(rel_layout, block_line)} AI 历史仍是「历史即将接入」占位"
            )
        for token, detail in (
            ("<HistoryEntry", "历史条目复用 HistoryEntry 摘要"),
            ('v-for="item in recentAiHistory"', "渲染真实最近会话"),
            (':conversation="item"', "传入真实会话摘要"),
            ('@select="goConversation"', "点击条目跳转会话"),
            ("查看全部", "提供查看全部入口"),
            ("/ai?history=1", "查看全部打开完整页历史抽屉"),
        ):
            _require(problems, block, token, rel_layout, detail)
        if '<p v-if="recentAiHistory.length === 0" class="recent-empty">' not in block:
            problems.append(
                f"{render_location(rel_layout, block_line)} AI 历史空态未按真实列表长度判断"
            )

    _require(problems, layout, "import HistoryEntry", rel_layout, "复用单条摘要组件")
    _require(problems, layout, "const RECENT_LIMIT = 5", rel_layout, "侧栏最近历史上限 5 条")
    _require(problems, layout, "listConversations(RECENT_LIMIT)", rel_layout, "读取本人全部近期会话")
    _require(problems, layout, "recentAiHistory.value = []", rel_layout, "加载失败只清空该组")
    _require(
        problems,
        layout,
        "query: { conversation: String(id) }",
        rel_layout,
        "条目跳转带 ?conversation=<id>",
    )

    _require(problems, console, "import HistoryEntry", rel_console, "抽屉复用单条摘要")
    for token, detail in (
        ("historyItems", "历史抽屉使用真实列表"),
        ("historyTotal", "展示会话总数"),
        ("historyHasMore", "按总数判断是否加载更多"),
        ("loadConversationHistory(true, false)", "打开抽屉重载本人全部历史"),
        ("loadConversationHistory(false", "加载更多追加下一页"),
        ("historyError", "失败可重试且不清空已有条目"),
        ("historyOpen", "抽屉状态来自 store"),
        ("newConversation()", "新对话清空当前视图"),
        ("route.query.conversation", "选中 ID 与 query 同步"),
        ("openConversation(requested)", "按 ?conversation= 恢复选中会话"),
        ("router.replace", "选中后更新 query"),
        ("selectConversation", "前进后退按 query 恢复"),
    ):
        _require(problems, console, token, rel_console, detail)
    if re.search(r"post\s*\(\s*['\"]/api/agent/chat|ai_usage_ledger", console, re.I):
        problems.append(f"{rel_console} 加载历史/切换会话不得调用问答接口或写用量")

    for token, detail in (
        ("conversation.title", "单条摘要显示标题"),
        ("conversation.updated_at", "单条摘要显示更新时间"),
        ("scope_type", "单条摘要显示作用对象"),
        ("/ai?conversation=", "摘要链接带会话 ID"),
        ("emit('select', conversation.id)", "点击回传会话 ID"),
    ):
        _require(problems, entry, token, rel_entry, detail)

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_layout} AI 历史渲染最近 5 条真实会话并可跳 /ai?conversation=；"
        f"{rel_console} 抽屉分页/失败重试与 ?conversation= 恢复齐备；"
        f"{rel_entry} 摘要含标题、时间与作用对象"
    )


def check_browse_tabs(rel_tabs: str, rel_hall: str, src_dir: Path) -> str:
    """㉚ `C-BROWSE-TABS@3`：胶囊 tab 语义 + `?type=` 缺省与持久化键。"""
    tabs = strip_ts_comments(load_text(src_dir / rel_tabs))
    hall = strip_ts_comments(load_text(src_dir / rel_hall))
    problems: list[str] = []

    tablist_line = _require(problems, tabs, 'role="tablist"', rel_tabs, "容器语义")
    _require(problems, tabs, 'role="tab"', rel_tabs, "每个胶囊按钮为 tab")
    selected_line = _require(problems, tabs, ":aria-selected=", rel_tabs, "选中态可读")
    _require(problems, tabs, ":tabindex=\"modelValue === tab.value ? 0 : -1\"", rel_tabs, "roving tabindex")
    for key in ("ArrowRight", "ArrowLeft"):
        _require(problems, tabs, key, rel_tabs, "左右方向键切换")
    if not re.search(r":aria-selected=\"modelValue === tab\.value \? 'true' : 'false'\"", tabs):
        problems.append(f"{rel_tabs} `aria-selected` 未由 `modelValue` 决定")

    _require(problems, hall, "import HallTabs", rel_hall, "consumers 复用胶囊 tab")
    _require(problems, hall, "<HallTabs", rel_hall, "模板渲染胶囊 tab")
    type_line = _require(problems, hall, "route.query.type", rel_hall, "选择状态来自 query")
    if "route.query.type === 'task' ? 'task' : 'activity'" not in hall:
        problems.append(
            f"{rel_hall} `activeType` 缺省值不是 `activity`（契约缺省 activity）"
        )
    for view_key in (
        "cta_hall_view_activity",
        "cta_hall_view_task",
        "cta_my_tasks_view_activity",
        "cta_my_tasks_view_task",
    ):
        _require(problems, hall, view_key, rel_hall, "两类集合各自持久化筛选")
    if "delete query.selectedType" not in hall or "delete query.selectedId" not in hall:
        problems.append(
            f"{rel_hall} 切换集合时未清除不匹配的 `selectedType/selectedId`（契约切换副作用）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_tabs}:{tablist_line} role=tablist/tab + aria-selected（第 {selected_line} 行）；"
        f"左右方向键切换；{rel_hall}:{type_line} 缺省 activity，"
        "四个持久化键齐备，切换时清除不匹配选中态"
    )


def check_browse_split(
    rel_hall: str, rel_panel: str, src_dir: Path
) -> str:
    """㉛ `C-BROWSE-SPLIT@1`：三列/分栏断点 + `selectedType/selectedId` 晚到丢弃。"""
    hall = strip_ts_comments(load_text(src_dir / rel_hall))
    panel = strip_ts_comments(load_text(src_dir / rel_panel))
    problems: list[str] = []

    wide_block = _media_blocks(hall, r"min-width:\s*1200px")
    if not wide_block or "repeat(3" not in "".join(wide_block):
        problems.append(
            f"{rel_hall} 缺少 `@media (min-width: 1200px)` 三列短卡片（C-BROWSE-SPLIT@1）"
        )
    split_block = _media_blocks(hall, r"min-width:\s*768px")
    split_css = "".join(split_block)
    if ".hall-results--split" not in split_css:
        problems.append(f"{rel_hall} 缺少 `@media (min-width: 768px)` 分栏布局")
    if "minmax(0, 1fr) minmax(0, 2fr)" not in split_css:
        problems.append(f"{rel_hall} 分栏不是「左单列 + 右侧占原两列」")
    narrow_block = _media_blocks(hall, r"max-width:\s*767px")
    if not narrow_block or "grid-template-columns: minmax(0, 1fr)" not in "".join(narrow_block):
        problems.append(f"{rel_hall} 缺少 `<768px` 单列断点")

    selected_type_line = _require(
        problems, hall, "route.query.selectedType", rel_hall, "选中类型来自 query"
    )
    _require(problems, hall, "route.query.selectedId", rel_hall, "选中 ID 来自 query")
    _require(problems, hall, "selectedType: type", rel_hall, "写回 selectedType")
    _require(problems, hall, "selectedId: String(id)", rel_hall, "写回 selectedId")
    _require(problems, hall, "window.innerWidth < 768", rel_hall, "移动端不启用分栏")
    _require(problems, hall, "import BrowseDetailPanel", rel_hall, "分栏详情组件")

    seq_line = _require(
        problems, panel, "let requestSeq", rel_panel, "请求序号丢弃晚到响应"
    )
    if panel.count("if (current !== requestSeq || disposed) return") < 2:
        problems.append(
            f"{rel_panel} 未在活动/任务两条请求路径都按 `current !== requestSeq` 丢弃晚到响应"
        )
    _require(problems, panel, "(e: 'close'): void", rel_panel, "关闭恢复原列表")
    _require(problems, panel, 'role="region"', rel_panel, "右侧详情语义")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_hall}:{selected_type_line} 三列≥1200px / 两列 768–1199px / 单列<768px；"
        f"query 键 selectedType+selectedId 读写齐备；{rel_panel}:{seq_line} "
        "按 requestSeq 丢弃 A 晚到响应，关闭事件回到原列表"
    )


def check_hover_peek(rel_peek: str, rel_hall: str, src_dir: Path) -> str:
    """㉜ `C-FE-PEEK@2`：8px 间隙桥接 + 120ms 关闭缓冲 + 精确指针启用。"""
    peek = strip_ts_comments(load_text(src_dir / rel_peek))
    hall = strip_ts_comments(load_text(src_dir / rel_hall))
    problems: list[str] = []

    buffer_line = _require(
        problems, peek, "const CLOSE_BUFFER_MS = 120", rel_peek, "120ms 关闭缓冲"
    )
    _require(problems, peek, "bottom: -8px", rel_peek, "8px 伪元素命中桥接")
    _require(problems, peek, "height: 8px", rel_peek, "间隙高度与视觉间距一致")
    _require(problems, peek, "top: calc(100% + 8px)", rel_peek, "面板紧邻 8px 间隙")
    _require(
        problems,
        peek,
        "window.matchMedia('(hover: hover) and (pointer: fine)')",
        rel_peek,
        "仅精确指针 + hover 启用",
    )
    _require(problems, peek, "event.key === 'Escape'", rel_peek, "Esc 关闭")
    _require(problems, peek, "isJointHovered()", rel_peek, "移入面板不关闭")
    _require(problems, peek, "hasInnerFocus()", rel_peek, "内部有焦点不关闭")
    if "@media (hover: none), (pointer: coarse)" not in peek:
        problems.append(f"{rel_peek} 缺少触摸设备禁用预览的媒体查询")
    if ".hover-peek__panel" not in peek or "display: none" not in peek:
        problems.append(f"{rel_peek} 触摸设备未隐藏预览面板（点击进入详情）")

    hall_line = _require(problems, hall, "import HoverPeek", rel_hall, "consumers 使用悬浮预览")
    _require(problems, hall, "<HoverPeek", rel_hall, "卡片包裹在联合区根内")
    _require(problems, hall, "#preview", rel_hall, "预览面板插槽")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_peek}:{buffer_line} `::before` bottom:-8px/height:8px 桥接间隙；"
        "面板 top: calc(100% + 8px)；离开联合区后 120ms 关闭，移回或内部焦点取消；"
        f"Esc 关闭；触摸禁用；{rel_hall}:{hall_line} 使用 HoverPeek + #preview"
    )


# 追加到既有 26 项之后（AIW-14 r1 三条前端契约）
CHECKS = CHECKS + (
    (
        "㉗ C-NAV-GROUPS@3 分组导航 + 本地内联 SVG + 折叠保留可访问名称",
        lambda: check_nav_groups(
            "layouts/AppLayout.vue", "components/nav/NavIcon.vue", SRC_DIR
        ),
    ),
    (
        "㉘ C-NAV-GROUPS@3 Library 路由与主导航入口存在",
        lambda: check_library_route(
            "router/index.ts",
            "layouts/AppLayout.vue",
            "views/LibraryPage.vue",
            SRC_DIR,
        ),
    ),
    (
        "㉙ C-AI-HISTORY@3 历史抽屉 + ?conversation= 恢复 + 侧栏最近 5 条",
        lambda: check_ai_history(
            "views/AiConsole.vue",
            "layouts/AppLayout.vue",
            "components/nav/HistoryEntry.vue",
            SRC_DIR,
        ),
    ),
    (
        "㉚ C-BROWSE-TABS@3 胶囊 tab 语义 + ?type= 缺省与持久化键",
        lambda: check_browse_tabs(
            "components/browse/HallTabs.vue", "views/TaskHall.vue", SRC_DIR
        ),
    ),
    (
        "㉛ C-BROWSE-SPLIT@1 三列/分栏断点 + selectedType/selectedId 晚到丢弃",
        lambda: check_browse_split(
            "views/TaskHall.vue", "components/browse/BrowseDetailPanel.vue", SRC_DIR
        ),
    ),
    (
        "㉜ C-FE-PEEK@2 HoverPeek 8px 间隙桥接 + 120ms 关闭缓冲",
        lambda: check_hover_peek(
            "components/common/HoverPeek.vue", "views/TaskHall.vue", SRC_DIR
        ),
    ),
)


# --------------------------------------------------------------------------- #
# r4（AIW-14 §10 C-USER-AVATAR@1 / C-BROWSE-CARD@2 / C-ACTIVITY-TABLE@1 /
#     C-ACTIVITY-SWITCH@1 / C-ADMIN-TABLE-REUSE@1）
# --------------------------------------------------------------------------- #

#: 契约禁止在卡片/头像内新增裸十六进制色值（颜色只能来自主题变量组合）
_BARE_HEX_COLOR: re.Pattern[str] = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


def check_user_avatar(
    rel_avatar: str,
    rel_activity_card: str,
    rel_task_card: str,
    rel_table: str,
    src_dir: Path,
) -> str:
    """㉝ `C-USER-AVATAR@1`：按 `userId` 稳定的四组色调 + 中性待分配形象。"""
    avatar = strip_ts_comments(load_text(src_dir / rel_avatar))
    cards = (
        (rel_activity_card, strip_ts_comments(load_text(src_dir / rel_activity_card))),
        (rel_task_card, strip_ts_comments(load_text(src_dir / rel_task_card))),
    )
    table = strip_ts_comments(load_text(src_dir / rel_table))
    problems: list[str] = []

    props_line = _require(
        problems, avatar, "userId: number | null", rel_avatar, "props.userId 允许待分配"
    )
    for token, detail in (
        ("name: string", "props.name"),
        ("size?: UserAvatarSize", "props.size 可选 xs|md"),
        ("{ size: 'xs' }", "默认 size 为 xs"),
        ("Math.abs(props.userId ?? 0) % 4", "按 userId 稳定取模取色"),
        ("+ 1}`", "tone 落到 1..4"),
        ("avatar--vacant", "userId === null 使用中性待分配形象"),
        (':title="displayName"', "title 为姓名"),
        (':aria-label="displayName"', "aria-label 为姓名"),
        ('aria-hidden="true"', "装饰字母不重复朗读"),
        ("'待分配'", "空名回退「待分配」"),
        ("\\u4e00-\\u9fa5", "中文取首字，其余取首字母"),
    ):
        _require(problems, avatar, token, rel_avatar, detail)

    for tone in ("avatar--tone-1", "avatar--tone-2", "avatar--tone-3", "avatar--tone-4"):
        _require(problems, avatar, f".{tone}", rel_avatar, "四组柔和色")
    for pixel in ("width: 18px", "width: 32px"):
        _require(problems, avatar, pixel, rel_avatar, "xs 18px / md 32px")
    if _BARE_HEX_COLOR.search(avatar):
        problems.append(f"{rel_avatar} 出现裸十六进制色值（颜色须组合主题变量）")
    if re.search(r"https?://|<img\b", avatar):
        problems.append(f"{rel_avatar} 请求了外部头像（契约要求本地生成）")

    for rel_card, card in cards:
        _require(problems, card, "import UserAvatar", rel_card, "卡片主行复用统一头像")
        _require(problems, card, "<UserAvatar", rel_card, "渲染头像")
        _require(problems, card, 'size="md"', rel_card, "卡片主行使用 md 32px")
    _require(problems, table, "import UserAvatar", rel_table, "表格成员列复用统一头像")
    _require(problems, table, 'size="xs"', rel_table, "表格使用 xs 18px")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_avatar}:{props_line} props userId/name/size 与四组 tone + vacant 齐备；"
        f"两张卡片 size=\"md\"，{rel_table} size=\"xs\""
    )


def check_browse_card(rel_activity_card: str, rel_task_card: str, src_dir: Path) -> str:
    """㉞ `C-BROWSE-CARD@2`：整卡柔和色底 + 头像主行 + `aria-pressed` 交互面。"""
    problems: list[str] = []
    texts: dict[str, str] = {}
    tone_lines: dict[str, int] = {}
    for rel_card, id_field in (
        (rel_activity_card, "activity"),
        (rel_task_card, "task"),
    ):
        card = strip_ts_comments(load_text(src_dir / rel_card))
        texts[rel_card] = card

        tone_match = re.search(
            r"`browse-card--tone-\$\{props\." + id_field + r"\.id\s*%\s*4\}`", card
        )
        if tone_match is None:
            problems.append(
                f"{rel_card} 缺少 `browse-card--tone-${{{id_field}.id % 4}}`（整卡柔和色底）"
            )
        else:
            tone_lines[rel_card] = card.count("\n", 0, tone_match.start()) + 1

        for token, detail in (
            ('role="button"', "整卡即主操作"),
            ('tabindex="0"', "键盘可达"),
            (':aria-pressed="selected"', "选中态可读"),
            ('@keydown.enter.prevent="handleSelect"', "Enter 选中"),
            ('@keydown.space.prevent="handleSelect"', "Space 选中"),
            ("import UserAvatar", "头像主行"),
            ('size="md"', "主行头像 32px"),
            ("padding: var(--app-space-4)", "内边距 16px"),
            ("border-radius: var(--app-radius-sm)", "圆角 8px"),
            ("background: var(--browse-tone-bg", "底色来自主题变量组合"),
            ("font-size: var(--app-font-card-title, 16px)", "标题 16px 令牌"),
            ("font-weight: 400", "标题常规字重"),
            ("-webkit-line-clamp: 2", "标题最多两行"),
        ):
            _require(problems, card, token, rel_card, detail)

        for tone in (
            "browse-card--tone-0",
            "browse-card--tone-1",
            "browse-card--tone-2",
            "browse-card--tone-3",
        ):
            _require(problems, card, f".{tone}", rel_card, "四组主题色组合")
        _require(
            problems,
            card,
            "border-color: var(--el-color-primary)",
            rel_card,
            "选中只叠加主色描边",
        )
        if _BARE_HEX_COLOR.search(card):
            problems.append(f"{rel_card} 出现裸十六进制色值（不新增颜色字面量）")
        if "transform:" in card:
            problems.append(f"{rel_card} hover/focus 含位移变换（契约禁止位移动画）")

    activity_card = texts[rel_activity_card]
    for token, detail in (
        ("时间待定", "开始时间空值回退"),
        ("地点待定", "地点空值回退"),
        ("activity.owner_name", "负责人"),
        ("activity.progress.completed_tasks", "已完成任务数"),
        ("activity.progress.total_tasks", "任务总数"),
    ):
        _require(problems, activity_card, token, rel_activity_card, detail)

    task_card = texts[rel_task_card]
    for token, detail in (
        ("props.task.members.slice(0, 3)", "最多 3 枚成员头像"),
        ("leadMembers", "成员头像组"),
        ('avatar-extra', "溢出 +n"),
        (':user-id="null"', "无成员时显示待分配形象"),
        ("activityTitle", "所属活动"),
        ("statusText", "状态"),
        ("quotaText", "名额/逐人验收"),
        ("formatDeadline", "截止时间"),
    ):
        _require(problems, task_card, token, rel_task_card, detail)

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_activity_card}:{tone_lines.get(rel_activity_card, 0)} / "
        f"{rel_task_card}:{tone_lines.get(rel_task_card, 0)} 整卡主题柔和色底 + md 头像主行，"
        "四组 tone-0..3 齐备，选中仅换主色描边；角色/键盘/aria-pressed 保留"
    )


def check_activity_table(rel_table: str, src_dir: Path) -> str:
    """㉟ `C-ACTIVITY-TABLE@1`：列顺序 + `aria-expanded`/`aria-controls` + 只读投影。"""
    table = strip_ts_comments(load_text(src_dir / rel_table))
    problems: list[str] = []

    props_line = _require(problems, table, "tasks: ActivityTaskNode[]", rel_table, "props.tasks")
    for token, detail in (
        ("expanded: number[]", "props.expanded 由父视图持有"),
        ("showActivity?: boolean", "可选所属活动列"),
        ("activityTitles?: Record<number, string>", "活动标题映射"),
        ("showActivity: false", "showActivity 默认 false"),
        ("(e: 'toggle', id: number): void", "emit toggle"),
        ('<div v-else class="task-table__scroll">', "横向滚动容器"),
        ('<table class="task-table">', "表格根"),
        ('<slot name="actions" :task="task" />', "actions 插槽仅后台传入"),
        ("overflow-x: auto", "容器横向滚动"),
        ('aria-expanded="', "展开态可读"),
        ("isExpanded(task.id) ? 'true' : 'false'", "aria-expanded 由展开状态决定"),
        (':aria-controls="`task-table-subtasks-${task.id}`"', "aria-controls 指向本人子行容器"),
        (':id="`task-table-subtasks-${task.id}`"', "子行容器 id 稳定"),
        ('class="task-table__toggle"', "父任务首列展开按钮"),
        ('v-show="isExpanded(task.id)"', "子任务跟随父行展开"),
        ('v-for="child in task.children"', "子任务只随父任务渲染一次"),
        ("padding-left: var(--app-space-5)", "子任务缩进"),
        ('<StatusTag :status="task.status" size="small" />', "状态复用 StatusTag"),
        ('size="xs"', "成员列头像 18px"),
        ("VISIBLE_ASSIGNEES = 2", "成员列最多 2 枚头像"),
        ("'—'", "开始/截止空值显示 —"),
        ("/${task.total_children} 子任务", "完成情况显示 completed/total"),
        ("task.completed_children", "完成数来自只读投影"),
        ("`#${task.activity_id}`", "缺活动标题回退 #id"),
        ("'独立任务'", "activity_id 为空显示独立任务"),
        ("statusText", "无子任务时显示状态文案"),
    ):
        _require(problems, table, token, rel_table, detail)

    headers = [name.strip() for name in re.findall(r"<th[^>]*>([^<]+)</th>", table)]
    expected_columns = (
        "任务",
        "所属活动",
        "状态",
        "执行成员",
        "开始时间",
        "截止时间",
        "完成情况",
        "操作",
    )
    if tuple(headers) != expected_columns:
        problems.append(
            f"{rel_table} 列顺序不符：期望 {'/'.join(expected_columns)}，"
            f"实际 {'/'.join(headers) or '（未解析到列头）'}"
        )
    for conditional in ("所属活动", "操作"):
        if f'<th v-if="showActivity" scope="col">{conditional}</th>' not in table and not (
            conditional == "操作" and '<th v-if="slots.actions" scope="col">操作</th>' in table
        ):
            problems.append(f"{rel_table} 可选列 `{conditional}` 缺 v-if 条件")

    detail_link = re.search(
        r"<router-link[^>]*:to=\"\{ name: 'detail', params: \{ id: task\.id \} \}\"", table
    )
    link_line = 0
    if detail_link is None:
        problems.append(
            rel_table
            + " 任务标题未用 `<router-link :to=\"{ name: 'detail', ... }\">`"
            "（契约要求站内跳转、不整页刷新）"
        )
    else:
        link_line = table.count("\n", 0, detail_link.start()) + 1
    _require(problems, table, "task-table__link", rel_table, "任务链接样式类")
    _require(problems, table, "slots.meta", rel_table, "`meta` 作用域插槽缺省不渲染")
    _require(
        problems,
        table,
        '<slot name="meta" :task="task" />',
        rel_table,
        "`#meta` 作用域插槽透传 `{ task }`",
    )
    _require(problems, table, "task-table__meta", rel_table, "meta 摘要类 `.task-table__meta`")
    _require(problems, table, "task-table__badge", rel_table, "子任务行角标")
    if re.search(r"task-table__badge[^>]*>\s*子任务", table) is None:
        problems.append(f"{rel_table} 子任务行 `.task-table__badge` 未标注「子任务」")
    if re.search(r"fetch\s*\(|/api/|axios\.", table):
        problems.append(f"{rel_table} 为只读组件，不得发起请求或新增写入路径")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_table}:{props_line} props tasks/expanded/showActivity/activityTitles + "
        "emit toggle + actions 插槽；列顺序精确为 任务/所属活动/状态/执行成员/开始时间/"
        f"截止时间/完成情况/操作；标题 router-link 第 {link_line} 行 + `#meta` 摘要 + "
        "子任务 badge；aria-expanded + aria-controls 指向 task-table-subtasks-<id>"
    )


def check_activity_switch(rel_detail: str, src_dir: Path) -> str:
    """㊱ `C-ACTIVITY-SWITCH@1`：标题区切换器走 `router.replace` 并保留 from/q。"""
    detail = strip_ts_comments(load_text(src_dir / rel_detail))
    problems: list[str] = []

    replace_line = _require(
        problems,
        detail,
        "void router.replace({ name: 'activity', params: { id: String(nextId) }, query })",
        rel_detail,
        "切换用 router.replace 且保留 query",
    )
    for token, detail_text in (
        ("scope: 'all'", "数据来源为可见活动列表"),
        ("items.slice(0, 20)", "选项最多 20 条"),
        ("switchOptions", "当前活动必要时置顶补入"),
        ("route.query.from !== undefined", "保留 from"),
        ("route.query.q !== undefined", "保留 q"),
        (">切换活动<", "标题区切换器标签"),
        ("<select", "切换器"),
        ('@change="switchActivity"', "切换事件"),
        ('expanded.value = []', "切换后清空展开"),
        ("clearResourceSearch()", "切换后清空资料检索"),
        ("if (current !== requestSeq) return", "丢弃晚到旧响应"),
        ("活动列表加载失败", "选项失败只提示不阻塞主体"),
        ("import ActivityTaskTable", "任务树替换为共用表格"),
        (
            '<ActivityTaskTable :tasks="activity.tasks" :expanded="expanded" '
            '@toggle="toggleTask" />',
            "表格接入",
        ),
        ("allExpanded", "保留展开全部/收起全部"),
        ("TaskGraph", "保留图谱"),
    ):
        _require(problems, detail, token, rel_detail, detail_text)

    watch_match = re.search(
        r"watch\(\s*\(\) => route\.params\.id,\s*\(\) => \{(.*?)\}\s*\)", detail, re.S
    )
    if watch_match is None or "expanded.value = []" not in watch_match.group(1):
        problems.append(f"{rel_detail} 未在活动 id 变化时清空 expanded 并重新加载")

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_detail}:{replace_line} 切换器走 `router.replace` 保留 from/q，"
        "选项 ≤20 且包含当前活动；切换清空 expanded/资料检索并按序号丢弃旧响应；"
        "任务区由 ActivityTaskTable 承担"
    )


def check_admin_table_reuse(rel_admin: str, src_dir: Path) -> str:
    """㊲ `C-ADMIN-TABLE-REUSE@1`：桌面复用共用表格 + 只过滤已加载任务的活动筛选。"""
    admin = strip_ts_comments(load_text(src_dir / rel_admin))
    problems: list[str] = []

    import_line = _require(
        problems, admin, "import ActivityTaskTable", rel_admin, "桌面任务区复用共用表格"
    )
    for token, detail in (
        ("app-desktop-table app-desktop-only", "表格仅在桌面端"),
        (":tasks=\"tableTasks\"", "传入已加载任务"),
        (":expanded=\"expanded\"", "展开状态由页面持有"),
        (':show-activity="true"', "显示所属活动列"),
        (':activity-titles="activityTitles"', "活动标题映射"),
        ('@toggle="toggleExpanded"', "展开事件"),
        ('<template #actions="{ task }">', "操作列插槽"),
        ("canAssign(asRow(task))", "保留指派判定"),
        ("canVerify(asRow(task))", "保留验收判定"),
        ("openAssign(asRow(task))", "保留指派 handler"),
        ("openVerify(asRow(task))", "保留验收 handler"),
        ("activityTitles = computed<Record<number, string>>", "标题映射由已加载活动构建"),
        ("activities.value", "标题来源为活动列表"),
        ("app-mobile-list app-mobile-only", "移动端保留原卡片列表"),
        ('aria-label="活动筛选"', "筛选器可读名称"),
        ('label="全部活动" value="all"', "全部活动选项"),
        ('label="独立任务" value="standalone"', "独立任务选项"),
        (
            "const activityFilter = ref<'all' | 'standalone' | number>('all')",
            "筛选状态与默认值",
        ),
    ):
        _require(problems, admin, token, rel_admin, detail)

    filter_start = admin.find("const filteredTasks = computed")
    filter_block = ""
    if filter_start >= 0:
        brace = admin.find("{", filter_start)
        if brace >= 0:
            filter_block = extract_balanced_braces(admin, brace)
    if not filter_block:
        problems.append(f"{rel_admin} 缺少 `filteredTasks` 计算属性（活动筛选）")
    else:
        filter_line = admin.count("\n", 0, filter_start) + 1
        for token, detail in (
            ("filter === 'all'", "全部活动不过滤"),
            ("filter === 'standalone'", "独立任务只匹配 activity_id === null"),
            ("task.activity_id === filter", "具体活动按 activity_id 匹配"),
        ):
            if token not in filter_block:
                problems.append(
                    f"{render_location(rel_admin, filter_line)} 活动筛选缺少 `{token}`（{detail}）"
                )
        if re.search(r"await|listTasks|fetch\s*\(|/api/", filter_block):
            problems.append(f"{rel_admin} 活动筛选不得新增请求（只过滤已加载 tasks）")

    # 契约补充：桌面表格须保留原 el-table 只读信息（parent_id 组装 + meta 摘要）
    table_match = re.search(
        r"^const tableTasks\b.*?^(?=const |function |export )", admin, re.S | re.M
    )
    if table_match is None:
        problems.append(f"{rel_admin} 缺少 `tableTasks` 计算属性（后台表格投影）")
    else:
        table_block = table_match.group(0)
        table_line = admin.count("\n", 0, table_match.start()) + 1
        if "parent_id" not in table_block:
            problems.append(
                f"{render_location(rel_admin, table_line)} "
                "`tableTasks` 未按 `parent_id` 识别并组装子任务"
            )
        if re.search(r"children\s*,|children\s*:|children\.push|\.children\s*=", table_block) is None:
            problems.append(
                f"{render_location(rel_admin, table_line)} "
                "`tableTasks` 未把子任务挂到父任务 `children`"
            )

    meta_marker = '#meta="{ task }"'
    if meta_marker not in admin:
        problems.append(f"{rel_admin} 缺少 `{meta_marker}` 摘要插槽（后台只读信息）")
    else:
        meta_line = admin.count("\n", 0, admin.find(meta_marker)) + 1
        if "metaSummary(task)" not in admin:
            problems.append(
                f"{render_location(rel_admin, meta_line)} "
                "`#meta` 槽未调用 `metaSummary(task)` 输出摘要"
            )
        try:
            summary_body, summary_line = function_body(admin, "metaSummary")
        except ContractError:
            problems.append(f"{rel_admin} 缺少 `metaSummary()` 摘要函数")
            summary_body, summary_line = "", meta_line
        for field in (
            "claim_type",
            "quota",
            "applied_count",
            "approved_count",
            "credit_reward",
            "reminder_rule",
        ):
            if field not in summary_body:
                problems.append(
                    f"{render_location(rel_admin, summary_line)} "
                    f"`metaSummary()` 摘要缺少 `{field}`"
                )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_admin}:{import_line} 桌面任务区复用 ActivityTaskTable（showActivity + "
        "activityTitles + actions 插槽保留指派/验收）；活动筛选只过滤已加载 tasks；"
        "tableTasks 按 parent_id 组装 children + `#meta` 摘要；移动端保留原卡片列表"
    )


# 追加到既有 32 项之后（AIW-14 r4 五条前端契约）
CHECKS = CHECKS + (
    (
        "㉝ C-USER-AVATAR@1 统一头像 props/四组 tone/待分配形象",
        lambda: check_user_avatar(
            "components/common/UserAvatar.vue",
            "components/browse/ActivityBrowseCard.vue",
            "components/browse/TaskBrowseCard.vue",
            "components/task/ActivityTaskTable.vue",
            SRC_DIR,
        ),
    ),
    (
        "㉞ C-BROWSE-CARD@2 头像彩色短卡 + aria-pressed 交互面",
        lambda: check_browse_card(
            "components/browse/ActivityBrowseCard.vue",
            "components/browse/TaskBrowseCard.vue",
            SRC_DIR,
        ),
    ),
    (
        "㉟ C-ACTIVITY-TABLE@1 共用任务表格列/展开/只读投影",
        lambda: check_activity_table("components/task/ActivityTaskTable.vue", SRC_DIR),
    ),
    (
        "㊱ C-ACTIVITY-SWITCH@1 活动详情切换 router.replace + 状态清理",
        lambda: check_activity_switch("views/ActivityDetail.vue", SRC_DIR),
    ),
    (
        "㊲ C-ADMIN-TABLE-REUSE@1 后台复用表格 + 活动筛选",
        lambda: check_admin_table_reuse("views/AdminConsole.vue", SRC_DIR),
    ),
    (
        "㊳ C-PRECHECK-EVIDENCE@2 后台验收过期预审标记与禁用",
        lambda: check_admin_verify_stale("views/AdminConsole.vue", SRC_DIR),
    ),
    (
        "㊴ C-SHELL-ACTIONS@1 图标折叠/最近分组/New chat 发布/归档导航",
        lambda: check_shell_actions("layouts/AppLayout.vue", SRC_DIR),
    ),
    (
        "㊵ C-GLOBAL-COMPOSER@1 三态悬浮输入与任意页提问",
        lambda: check_global_composer(
            "components/shell/GlobalComposer.vue", "layouts/AppLayout.vue", SRC_DIR
        ),
    ),
    (
        "㊶ C-AI-THREE-PANE@1 左问答 + 右通知/归档，移除消息入口",
        lambda: check_ai_three_pane("views/AiConsole.vue", "router/index.ts", SRC_DIR),
    ),
    (
        "㊷ C-SUBMISSION-FILE@1 成果文件上传接线与下载入口",
        lambda: check_submission_file_ui("api/tasks.ts", "views/TaskDetail.vue", SRC_DIR),
    ),
    (
        "㊸ C-AI-THREE-PANE@1 个人页只保留未读数，通知正文仅在 AI 页",
        lambda: check_profile_notice_entry("views/Profile.vue", SRC_DIR),
    ),
    (
        "㊹ C-ORG-LIBRARY@1 Library 组织资料开关默认关闭与免责提示",
        lambda: check_org_library_ui("api/orgResources.ts", "views/LibraryPage.vue", SRC_DIR),
    ),
)


def check_admin_verify_stale(rel_admin: str, src_dir: Path) -> str:
    """㊳ `C-PRECHECK-EVIDENCE@2`：后台验收对话框展示过期预审并禁用「确认通过」。"""
    admin = strip_ts_comments(load_text(src_dir / rel_admin))
    problems: list[str] = []
    for token, detail in (
        ("import { assignTask, getTaskChangeImpact, getTaskSubmissions", "读取成果列表判断预审新鲜度"),
        ("const verifyStaleUsers", "按 user_id 记录过期预审"),
        ("const verifyStaleCurrent", "当前选中成员是否过期"),
        ("void loadVerifyStale(task)", "打开验收对话框触发只读加载"),
        ("item.latest && item.precheck?.stale", "只取最新成果的过期预审"),
        ("verifyStaleUsers.includes(member.user_id)", "成员项展示过期标记"),
        ("预审已过期", "过期标记/预警文案"),
        ("请先重新预审", "过期预警文案"),
        ("verifyChoice === 'pass' && verifyStaleCurrent", "通过时禁用确认按钮"),
        ("verifyChoice === 'pass' && (verifyStaleLoading || verifyStaleCurrent)", "加载中也不允许确认通过，退回不受影响"),
        ("退回（回到进行中）", "退回选项保留"),
        ("退回不受影响", "退回不受过期预审影响"),
        ("verifyStaleSeq", "迟到响应按序号丢弃"),
    ):
        _require(problems, admin, token, rel_admin, detail)
    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_admin} 后台验收按成果最新预审 stale 展示并禁用确认通过（含加载中）；"
        "退回不受影响，迟到响应按序号丢弃，后端 4090 兜底不变"
    )



def check_shell_actions(rel_layout: str, src_dir: Path) -> str:
    """㊴ `C-SHELL-ACTIONS@1`：图标折叠、最近分组、New chat 发布、归档通知导航。"""
    text = strip_ts_comments(load_text(src_dir / rel_layout))
    problems: list[str] = []
    for token, detail in (
        ("sidebar-head__actions", "搜索/折叠置于侧栏右上"),
        ("panel-left", "展开态折叠图标"),
        ("panel-right", "折叠态展开图标"),
        ("new-chat-button", "发布入口为 New chat 样式"),
        ("最近聊天", "最近分组标题改为最近聊天"),
        ("归档通知", "左侧导航归档入口"),
        ("icon: 'archive'", "归档图标"),
    ):
        _require(problems, text, token, rel_layout, detail)
    for forbidden, detail in (
        ("sidebar-quick", "旧的搜索/新对话双列"),
        ("最近任务", "最近任务分组"),
        (">最近<", "最近总标题"),
        ("label: '消息'", "消息导航项"),
        (">展开<", "折叠按钮文字"),
        (">收起<", "折叠按钮文字"),
    ):
        if forbidden in text:
            problems.append(f"{rel_layout} 仍包含已移除的{detail}：{forbidden}")
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_layout} 侧栏为图标折叠 + 右上搜索/折叠 + New chat 发布 + 最近活动/最近聊天 + 归档通知"


def check_global_composer(rel_comp: str, rel_layout: str, src_dir: Path) -> str:
    """㊵ `C-GLOBAL-COMPOSER@1`：三态悬浮输入 + 任意页发送 + 语音复用。"""
    text = strip_ts_comments(load_text(src_dir / rel_comp))
    layout = strip_ts_comments(load_text(src_dir / rel_layout))
    problems: list[str] = []
    for token, detail in (
        ("const expanded = ref(false)", "小条/中框两态"),
        ("is-expanded", "展开态样式"),
        ("AgentVoiceButton", "语音入口复用"),
        ("aiChat.send()", "发送复用既有 AI 通道"),
        ("route.name !== 'ai'", "非 AI 页显示"),
        ("position: fixed", "底部悬浮"),
        ("max-width: 768px", "窄屏适配"),
        ("打开 AI 页面", "第三态入口"),
    ):
        _require(problems, text, token, rel_comp, detail)
    _require(problems, layout, "<GlobalComposer />", rel_layout, "壳层挂载")
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_comp} 三态悬浮输入（小条/中框/AI 页）+ 语音与发送复用 aiChat；{rel_layout} 挂载"


def check_ai_three_pane(rel_ai: str, rel_router: str, src_dir: Path) -> str:
    """㊶ `C-AI-THREE-PANE@1`：左问答 + 右通知/归档，移除独立消息入口。"""
    text = strip_ts_comments(load_text(src_dir / rel_ai))
    router = strip_ts_comments(load_text(src_dir / rel_router))
    problems: list[str] = []
    for token, detail in (
        ("ai-three-pane", "三栏容器"),
        ("grid-template-columns: minmax(0, 1fr) 320px", "左问答右通知宽度"),
        ("ai-notice-pane", "右栏通知面板"),
        ("switchNoticePanel", "待处理/归档切换"),
        ("archiveNotice", "通知归档动作"),
        ("archivedItems", "归档箱数据"),
        ("noticePanel === 'archive'", "归档视图分支"),
        ("<aside", "右栏语义"),
        ("has-collapsed-notice", "右栏折叠态"),
        ("noticeCollapsed", "右栏折叠状态"),
        ("cta_ai_notice_panel", "折叠状态持久化"),
        ("markAllNoticesRead", "全部已读"),
        ("全部已读", "全部已读按钮"),
    ):
        _require(problems, text, token, rel_ai, detail)
    for forbidden in ("openMessages", "查看全部消息"):
        if forbidden in text:
            problems.append(f"{rel_ai} 仍保留已移除的消息入口：{forbidden}")
    _require(problems, router, "redirect: { name: 'ai', query: { panel: 'inbox' } }", rel_router, "旧 /messages 兼容重定向")
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_ai} 左问答 + 右通知/归档，归档动作与面板切换齐全；{rel_router} 旧消息路由重定向"


def check_submission_file_ui(rel_api: str, rel_view: str, src_dir: Path) -> str:
    """㊷ `C-SUBMISSION-FILE@1`（前端）：上传接线、格式/大小提示、下载入口。"""
    api = strip_ts_comments(load_text(src_dir / rel_api))
    view = strip_ts_comments(load_text(src_dir / rel_view))
    problems: list[str] = []
    for token, detail in (
        ("export async function uploadSubmission", "上传 API"),
        ("file_base64", "base64 上传载荷"),
        ("request<TaskItem>('POST', `/api/tasks/${id}/submissions/upload`", "上传端点"),
    ):
        _require(problems, api, token, rel_api, detail)
    for token, detail in (
        ("submitFile", "文件状态"),
        ("fileInputRef", "文件选择"),
        ("FILE_MAX_BYTES", "大小上限"),
        ("FILE_EXTS", "格式白名单"),
        ("uploadSubmission(task.value.id, submitFile.value", "选文件时走上传"),
        ("下载附件", "成果文件下载入口"),
    ):
        _require(problems, view, token, rel_view, detail)
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_api} 提供 base64 上传；{rel_view} 支持选择/校验/上传/下载"





def check_profile_notice_entry(rel_view: str, src_dir: Path) -> str:
    """㊸ `C-AI-THREE-PANE@1`：个人页只保留未读数入口，通知正文只在 AI 页。"""
    text = strip_ts_comments(load_text(src_dir / rel_view))
    problems: list[str] = []
    for forbidden, detail in (
        ('id="notifications"', "通知中心区块"),
        ("通知中心", "通知中心标题"),
        ("markAllRead", "个人页全部已读"),
    ):
        if forbidden in text:
            problems.append(f"{rel_view} 仍保留已移除的{detail}：{forbidden}")
    for token, detail in (
        ("const unreadCount", "保留未读数"),
        ("openAiNotices", "点击去 AI 页通知"),
        ("query: { panel: 'inbox' }", "只保留 AI 页通知"),
    ):
        _require(problems, text, token, rel_view, detail)
    if problems:
        raise ContractError("；".join(problems))
    return f"{rel_view} 通知中心已移除，未读数入口跳到 AI 页 `panel=inbox`"



def check_org_library_ui(rel_api: str, rel_view: str, src_dir: Path) -> str:
    """㊹ `C-ORG-LIBRARY@1`（前端）：4 个 API 导出 + 组织资料区默认关闭与免责提示。"""
    api = strip_ts_comments(load_text(src_dir / rel_api))
    view = strip_ts_comments(load_text(src_dir / rel_view))
    problems: list[str] = []

    exported = collect_exported_functions(api)
    missing = [
        name
        for name in (
            "listOrgResources",
            "createOrgResource",
            "patchOrgResource",
            "downloadOrgResourceUrl",
        )
        if name not in exported
    ]
    if missing:
        problems.append(f"{rel_api} 缺少导出函数：{missing}（C-ORG-LIBRARY@1 前端消费者契约）")

    for token, detail in (
        ("allow_student_ai", "组织资料 AI 检索开关字段"),
        ("ORG_AI_NOTICE", "开关风险提示常量"),
        ("开启后学生可能通过 AI 回答看到资料内容，不等于文件保密", "免责提示文案"),
        ("(org.role === 'admin' || org.role === 'collaborator')", "组织资料区仅限 admin/collaborator"),
        ('v-if="manageableOrgs.length > 0"', "无管理权组织时不渲染组织资料区"),
        ("include_archived", "归档资料可查看"),
        ("downloadOrgResourceUrl", "文件下载入口"),
        ("'归档'", "归档动作"),
        ("'恢复'", "归档后恢复动作"),
        ("statusMeta(item.text_status)", "解析状态展示"),
    ):
        _require(problems, view, token, rel_view, detail)

    for status in ("pending", "ready", "failed"):
        if f"{status}:" not in view:
            problems.append(f"{rel_view} 未展示解析状态 `{status}`（C-ORG-LIBRARY@1）")

    for forbidden in ("allow_student_ai = true", "allow_student_ai: true"):
        if forbidden in view:
            problems.append(
                f"{rel_view} 出现 `{forbidden}`（默认开启学生 AI 检索，契约要求缺省关闭）"
            )

    if not re.search(r':model-value="flagOn\(item\.allow_student_ai\)"', view):
        problems.append(
            f"{rel_view} 的检索开关未绑定服务端 `allow_student_ai`（默认取回 0 = 关闭）"
        )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_api} 导出 listOrgResources/createOrgResource/patchOrgResource/"
        f"downloadOrgResourceUrl；{rel_view} 组织资料区仅 admin/collaborator 可见，"
        "开关默认关闭并提示「开启后学生可能通过 AI 回答看到资料内容，不等于文件保密」，"
        "支持归档/恢复、下载与 pending/ready/failed 状态"
    )


def check_library_refs_ui(
    rel_api: str, rel_view: str, rel_ai: str, rel_types: str, src_dir: Path
) -> str:
    """㊺ `C-LIB-REF@1` / `C-AI-DOC-CONTEXT@1`（前端）：引用收藏区 + AI 来源标签。"""
    api = strip_ts_comments(load_text(src_dir / rel_api))
    view = strip_ts_comments(load_text(src_dir / rel_view))
    ai = strip_ts_comments(load_text(src_dir / rel_ai))
    types_text = strip_ts_comments(load_text(src_dir / rel_types))
    problems: list[str] = []

    exported = collect_exported_functions(api)
    missing = [name for name in ("listLibraryRefs", "saveLibraryRef") if name not in exported]
    if missing:
        problems.append(f"{rel_api} 缺少导出函数：{missing}（C-LIB-REF@1 前端消费者契约）")
    for token, detail in (
        ("'/api/library/refs'", "引用列表 / 保存端点"),
        ("revoked_count", "撤回数量字段"),
        ("{ resource_id: resourceId }", "保存引用请求体"),
    ):
        _require(problems, api, token, rel_api, detail)

    for token, detail in (
        ("我的引用资料", "引用区标题"),
        ("listLibraryRefs", "引用区读取接口"),
        ("refRevokedCount", "撤回数量状态"),
        ("条引用已撤回或归档", "撤回数量提示"),
        ("在 AI 中引用后自动收藏", "空态说明"),
        ("downloadOrgResourceUrl(ref.resource_id)", "引用资料下载入口"),
        ("refTypeLabel(ref.resource_type)", "引用资料类型标签"),
    ):
        _require(problems, view, token, rel_view, detail)

    for token, detail in (
        ("CITATION_KIND_LABELS", "来源类型标签映射"),
        ("openCitationLibrary", "资料项跳 Library"),
        ('@click="openCitationLibrary"', "资料项点击跳 Library"),
        ("name: 'library'", "Library 路由"),
        ("citation-tag", "来源标签渲染"),
    ):
        _require(problems, ai, token, rel_ai, detail)

    labels_match = re.search(r"CITATION_KIND_LABELS[^=]*=\s*\{([^}]*)\}", ai, re.S)
    if labels_match is None:
        problems.append(f"{rel_ai} 未找到 `CITATION_KIND_LABELS` 映射（C-AI-DOC-CONTEXT@1）")
    else:
        labels = dict(
            re.findall(
                r"([A-Za-z_$][\w$]*)\s*:\s*'([^']*)'", labels_match.group(1)
            )
        )
        if set(labels) != {"task", "doc"}:
            problems.append(
                f"{rel_ai} CITATION_KIND_LABELS 的键为 {sorted(labels)}，"
                "契约要求 task / doc 二值（`kind='activity'` 永不产生）"
            )
        elif labels["task"] != "任务" or labels["doc"] != "资料":
            problems.append(
                f"{rel_ai} 来源标签值不符：task={labels['task']!r} / doc={labels['doc']!r}"
                "（要求「任务」/「资料」）"
            )
    if not re.search(
        r"citation\.kind\s*===\s*'doc'\s*\?\s*'doc'\s*:\s*'task'", ai
    ):
        problems.append(
            f"{rel_ai} 的 citationKind() 未按 `kind === 'doc' ? 'doc' : 'task'` 兜底"
            "（未知 kind 必须落回 task）"
        )

    ref_iface = re.search(r"export interface LibraryRef\s*\{([^}]*)\}", types_text, re.S)
    if ref_iface is None:
        problems.append(f"{rel_types} 缺少 `export interface LibraryRef`（C-LIB-REF@1）")
    else:
        body = ref_iface.group(1)
        for field in (
            "resource_id",
            "title",
            "summary",
            "resource_type",
            "file_name",
            "file_size",
            "url",
            "org_id",
            "added_at",
            "last_used_at",
        ):
            if not re.search(rf"\b{field}\s*:", body):
                problems.append(
                    f"{rel_types} 的 LibraryRef 缺少字段 `{field}`（C-LIB-REF@1）"
                )

    kind_match = re.search(r"export type AiCitationKind\s*=\s*([^\n]+)", types_text)
    if kind_match is None:
        problems.append(
            f"{rel_types} 缺少 `export type AiCitationKind`（C-AI-DOC-CONTEXT@1）"
        )
    else:
        kinds = set(re.findall(r"'([^']+)'", kind_match.group(1)))
        if kinds != {"task", "doc"}:
            problems.append(
                f"{rel_types} AiCitationKind={sorted(kinds)}，"
                "契约要求 task / doc 二值（`kind='activity'` 永不产生）"
            )
    citation_match = re.search(r"export interface AiCitation\s*\{([^}]*)\}", types_text, re.S)
    if citation_match is None:
        problems.append(f"{rel_types} 缺少 `export interface AiCitation`")
    else:
        citation_body = citation_match.group(1)
        if not re.search(r"\bkind\s*:\s*AiCitationKind", citation_body):
            problems.append(
                f"{rel_types} 的 AiCitation 缺少 `kind: AiCitationKind`（C-AI-DOC-CONTEXT@1）"
            )
        if not re.search(r"\btype\s*:\s*'task'\s*\|\s*'doc'", citation_body):
            problems.append(
                f"{rel_types} 的 AiCitation.type 必须为 `'task' | 'doc'`（doc 来源）"
            )
        if not re.search(r"\bresource_id\s*\??\s*:", citation_body):
            problems.append(
                f"{rel_types} 的 AiCitation 缺少 `resource_id` 字段（doc 引用）"
            )

    if problems:
        raise ContractError("；".join(problems))
    return (
        f"{rel_api} 导出 listLibraryRefs/saveLibraryRef 并指向 /api/library/refs；"
        f"{rel_view} 新增「我的引用资料」区（类型标签、下载、撤回数量、空态说明）；"
        f"{rel_ai} 来源标签为 task「任务」/ doc「资料」二值（无活动标签），"
        "未知 kind 兜底 task，doc 项跳 Library；"
        f"{rel_types} 的 AiCitationKind 二值、AiCitation.type 含 doc、"
        "LibraryRef 字段与 resource_id 齐备"
    )


# 追加到既有 44 项之后（S4 引用区与 AI 来源标签）
CHECKS = CHECKS + (
    (
        "㊺ C-LIB-REF@1 / C-AI-DOC-CONTEXT@1 引用区与 AI 来源标签",
        lambda: check_library_refs_ui(
            "api/library.ts",
            "views/LibraryPage.vue",
            "views/AiConsole.vue",
            "types/models.ts",
            SRC_DIR,
        ),
    ),
)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))