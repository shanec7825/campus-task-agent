#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T12 · 交付物完整性 / 契约一致性核验（仅使用 Python 标准库）。

被验证对象（只读）：
    readme/、codearts_proof/、仓库根 README.md

检查维度（与 plan.md 2.2.14 / T12 验收 ② 对应）：
    D01~D05  readme/ 交付物 5 件套
    D06~D13  codearts_proof/ 三层结构（LOG / ai_dialogue / prompts / debug / screenshots / video）
    D14~D20  端口、演示账号、env 变量名与默认值、根 README 启动命令一致性
    D21~D25  留痕真实性与产出路径可核验性（防编造）
    D26~D27  附加：.env.example 变量集合、根 README 账号表一致性
D28~D31  第二轮迭代（C-DELIVERY@2）：stage7 五节、LOG 阶段 7、两份 README 四项功能、
              stage7 第 4/5 节是否真实收口（B 段占位 → FAIL）
    D32~D34  第三轮迭代（C-DELIVERY@3）：stage8 五节、LOG 阶段 8、两份 README 四项
    D35~D37  第四轮迭代（C-DELIVERY@4）：stage9 五节 + B 段收口、LOG 阶段 9、两份 README 四项
    D38~D40  第五轮迭代（C-DELIVERY@5）：stage10 五节 + 根因关键词 + 第 4/5 节收口、
              LOG 阶段 10、两份 README（allowedHosts / takin.cc / dedupTail / 续接）

用法::

    python tests/security/verify_delivery.py
    python tests/security/verify_delivery.py --root campus-task-agent

退出码：0 = 全部 PASS；1 = 存在任一 FAIL。
DEFERRED 项不由本脚本判定（本脚本只对"当前仓库事实"做二元断言）。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# 契约常量（唯一事实来源：plan.md 2.2.1 / 2.2.9 / 2.2.14 与 T12 验收）
# --------------------------------------------------------------------------- #

#: 2.2.14 要求的 readme/ 5 个文件
README_FILES: tuple[str, ...] = (
    "readme/README.md",
    "readme/install.sh",
    "readme/install.bat",
    "readme/开源组件说明.md",
    "readme/码道应用总结.md",
)

#: 2.2.14 要求的 ai_dialogue 6 份阶段文件
AI_DIALOGUE_FILES: tuple[str, ...] = (
    "codearts_proof/ai_dialogue/stage0_骨架搭建.md",
    "codearts_proof/ai_dialogue/stage1_任务CRUD.md",
    "codearts_proof/ai_dialogue/stage2_双Agent闭环.md",
    "codearts_proof/ai_dialogue/stage3_语音流式.md",
    "codearts_proof/ai_dialogue/stage4_催办通知.md",
    "codearts_proof/ai_dialogue/stage6_部署上线.md",
)

#: 2.2.14 要求的 prompt 资产目录与迭代记录
PROMPT_ASSETS: tuple[str, ...] = (
    "codearts_proof/prompts/agent_team_启动指令",
    "codearts_proof/prompts/业务Agent",
    "codearts_proof/prompts/prompt迭代记录.md",
)

#: 2.2.1 的 9 个环境变量名（默认值**不在此硬编码**，运行时从 plan 2.2.1 表格解析）
ENV_VAR_NAMES: tuple[str, ...] = (
    "MAAS_API_KEY",
    "MAAS_BASE_URL",
    "MAAS_MODEL",
    "MAAS_MOCK",
    "DATABASE_PATH",
    "RUN_SCHEDULER",
    "SSE_HEARTBEAT_SECONDS",
    "REMINDER_INTERVAL_SECONDS",
    "CORS_ORIGINS",
)

#: 相对工程根上一级的规划契约路径（唯一事实来源：plan.md 2.2.1）
PLAN_RELATIVE_PATH: str = ".codeartsdoer/plans/campus-task-agent/plan.md"

#: plan 2.2.1 小节的起止标记（用于把解析范围限定在 env 表格内）
PLAN_SECTION_START: str = "#### 2.2.1"
PLAN_SECTION_END: str = "**统一响应与错误**"

#: .env.example 中必须与契约默认值精确一致的变量（不允许被占位值豁免）
STRICT_EXAMPLE_VARS: frozenset[str] = frozenset({"MAAS_MODEL"})

#: .env.example 中允许为离线演示预置不同值的变量（2.2.1 已注明 MAAS_MOCK 示例为 1）
EXAMPLE_DEMO_OVERRIDES: frozenset[str] = frozenset({"MAAS_MOCK"})

#: 判定"占位值"的关键词：命中的示例值不参与与契约默认值的精确比对
PLACEHOLDER_HINTS: tuple[str, ...] = (
    "your-",
    "your_",
    "example.com",
    "example.invalid",
    "placeholder",
    "changeme",
)

#: 演示账号（2.2.14 / readme 第 4 节）
ACCOUNTS: tuple[str, ...] = ("teacher01", "student01", "student02", "student03")

#: 2.2.14 列出的 14 个开源组件（名称, 用于定位表格行的正则）
OPENSOURCE_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("FastAPI", r"\bFastAPI\b"),
    ("Uvicorn", r"\bUvicorn\b"),
    ("SQLAlchemy", r"\bSQLAlchemy\b"),
    ("Pydantic", r"\bPydantic\b"),
    ("openai-python", r"OpenAI"),
    ("APScheduler", r"APScheduler"),
    ("python-dotenv", r"python-dotenv"),
    ("jieba", r"jieba"),
    ("Vue 3", r"Vue 3"),
    ("Vite", r"Vite"),
    ("Element Plus", r"Element Plus"),
    ("Pinia", r"Pinia"),
    ("vue-router", r"vue-router"),
    ("TypeScript", r"TypeScript"),
)

#: ai_dialogue 每份必须包含的五个小节（2.2.14）
REQUIRED_DIALOGUE_SECTIONS: tuple[str, ...] = (
    "## 阶段",
    "## 使用的 Agent",
    "## 输入 Prompt",
    "## 产出",
    "## 问题",
)

#: 声明"尚未归档/占位"的标记；出现即视为如实标注，不允许再声称已完成
PLACEHOLDER_MARKS: tuple[str, ...] = (
    "待该阶段收尾",
    "原文待归档",
    "待归档",
    "占位",
    "禁止编造",
)

#: 产出表中表示"未发生/待产出"的标记，路径存在性不参与断言
NOT_YET_MARKS: tuple[str, ...] = ("⏳", "待产出", "未执行", "待办", "尚未")


# --------------------------------------------------------------------------- #
# 结果收集
# --------------------------------------------------------------------------- #
@dataclass
class Result:
    item_id: str
    title: str
    ok: bool
    detail: str = ""


class Checker:
    def __init__(self, root: Path, plan_path: Path | None = None) -> None:
        self.root = root
        # plan 默认位于工程根的上一级：<repo>/.codeartsdoer/plans/campus-task-agent/plan.md
        self.plan_path = plan_path or (root.parent / PLAN_RELATIVE_PATH)
        self.results: list[Result] = []
        # 延迟解析：D19/D26 共用同一份解析结果，避免重复读盘
        self._plan_defaults: dict[str, str] | None = None
        self._plan_error: str = ""

    # -- helpers -----------------------------------------------------------
    def add(self, item_id: str, title: str, ok: bool, detail: str = "") -> None:
        self.results.append(Result(item_id, title, ok, detail))

    def path(self, rel: str) -> Path:
        return self.root / rel

    def read_text(self, rel: str) -> str:
        try:
            return self.path(rel).read_text(encoding="utf-8")
        except OSError as exc:  # 文件缺失/编码异常都转成可读的失败原因
            return f"__READ_ERROR__: {exc}"

    def require_file(self, item_id: str, rel: str) -> None:
        p = self.path(rel)
        self.add(item_id, f"文件存在：{rel}", p.is_file(),
                 "" if p.is_file() else f"未找到（期望文件）：{p}")

    def require_dir(self, item_id: str, rel: str) -> None:
        p = self.path(rel)
        self.add(item_id, f"目录存在：{rel}", p.is_dir(),
                 "" if p.is_dir() else f"未找到（期望目录）：{p}")

    # -- 检查项 ------------------------------------------------------------
    def check_readme_files(self) -> None:
        for idx, rel in enumerate(README_FILES, start=1):
            self.require_file(f"D{idx:02d}", rel)

    def check_codearts_structure(self) -> None:
        self.require_file("D06", "codearts_proof/LOG.md")

        missing = [rel for rel in AI_DIALOGUE_FILES if not self.path(rel).is_file()]
        self.add("D07", f"ai_dialogue 阶段文件 6 份（{len(AI_DIALOGUE_FILES)} 份）",
                 not missing, "" if not missing else "缺失：" + "、".join(missing))

        for idx, rel in enumerate(PROMPT_ASSETS, start=8):
            p = self.path(rel)
            ok = p.is_dir() if idx <= 9 else p.is_file()
            self.add(f"D{idx:02d}", f"{'目录' if idx <= 9 else '文件'}存在：{rel}", ok,
                     "" if ok else f"未找到：{p}")

        self.require_file("D11", "codearts_proof/debug/template.md")

        for item_id, rel in (("D12", "codearts_proof/screenshots"), ("D13", "codearts_proof/video")):
            d = self.path(rel)
            keep = d / ".gitkeep"
            ok = d.is_dir() and keep.is_file()
            self.add(item_id, f"{rel}/ 目录 + .gitkeep 索引占位", ok,
                     "" if ok else f"目录或 .gitkeep 缺失：{d}")

        self.require_file("D14", "README.md")

    # -- D19：plan 2.2.1 动态解析与三方比对 --------------------------------
    def plan_env_defaults(self) -> tuple[dict[str, str], str]:
        """从 plan.md 2.2.1 表格解析 9 个 env 默认值。

        返回 ``(defaults, error)``；解析失败时 defaults 为空、error 为可读原因。
        不硬编码任何默认值（尤其是 ``MAAS_MODEL``，其契约值可被 Leader 裁定修订）。
        """
        if self._plan_defaults is not None or self._plan_error:
            return self._plan_defaults or {}, self._plan_error
        try:
            plan_text = self.plan_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._plan_error = f"无法读取规划契约 {self.plan_path}：{exc}"
            return {}, self._plan_error

        section = slice_section(plan_text, PLAN_SECTION_START, PLAN_SECTION_END)
        if not section:
            self._plan_error = (
                f"在 {self.plan_path} 中未找到 2.2.1 小节"
                f"（起止标记 {PLAN_SECTION_START!r} / {PLAN_SECTION_END!r}）"
            )
            return {}, self._plan_error

        parsed = parse_env_table(section)
        missing = [name for name in ENV_VAR_NAMES if name not in parsed]
        if missing:
            self._plan_error = f"plan 2.2.1 表格缺少变量：{'、'.join(missing)}"
            return {}, self._plan_error

        self._plan_defaults = {
            name: normalize_contract_value(first_tick_value(parsed[name]))
            for name in ENV_VAR_NAMES
        }
        return self._plan_defaults, ""

    def compare_env_defaults(
        self, readme_parsed: dict[str, str], root_parsed: dict[str, str]
    ) -> list[str]:
        """把 readme / 根 README / .env.example 三方与 plan 2.2.1 逐项比对。"""
        defaults, plan_error = self.plan_env_defaults()
        if plan_error:
            return [plan_error]

        problems: list[str] = []
        for name in ENV_VAR_NAMES:
            expected = defaults[name]

            for label, parsed in (("readme/README.md", readme_parsed), ("根 README.md", root_parsed)):
                cell = parsed.get(name)
                if cell is None:
                    problems.append(f"{label} 表格缺少 {name}")
                    continue
                actual = normalize_contract_value(first_tick_value(cell))
                if actual != expected:
                    problems.append(
                        f'{label} {name}="{actual}" ≠ plan 2.2.1 "{expected}"'
                    )

        # .env.example：占位值允许与契约不同，但 MAAS_MODEL 必须与契约一致
        example_text = self.read_text("backend/.env.example")
        if example_text.startswith("__READ_ERROR__"):
            problems.append(f"backend/.env.example 不可读：{example_text}")
            return problems
        example_values = parse_dotenv_values(example_text)
        for name in ENV_VAR_NAMES:
            if name not in example_values:
                problems.append(f"backend/.env.example 缺少 {name}")
                continue
            actual = example_values[name].strip()
            if name in STRICT_EXAMPLE_VARS:
                if actual != defaults[name]:
                    problems.append(
                        f'backend/.env.example {name}="{actual}" ≠ plan 2.2.1 "{defaults[name]}"'
                    )
                continue
            if name in EXAMPLE_DEMO_OVERRIDES:
                continue  # 示例文件允许为离线演示预置不同值（如 MAAS_MOCK=1）
            if is_placeholder_value(actual):
                continue  # 占位值（your-... / example.com）不参与精确比对
            if actual != defaults[name]:
                problems.append(
                    f'backend/.env.example {name}="{actual}" ≠ plan 2.2.1 "{defaults[name]}"'
                )
        return problems

    def check_text_contract(self) -> None:
        readme_rel = "readme/README.md"
        text = self.read_text(readme_rel)
        if text.startswith("__READ_ERROR__"):
            self.add("D15", "readme/README.md 可读取", False, text)
            self.add("D16", "启动端口 8000 / 5173", False, "readme/README.md 不可读")
            self.add("D17", "演示账号齐全", False, "readme/README.md 不可读")
            self.add("D18", "9 个 env 变量名齐全", False, "readme/README.md 不可读")
            self.add("D19", "env 默认值与 2.2.1 一致", False, "readme/README.md 不可读")
            self.add("D20", "根 README 与 readme/README.md 启动命令一致", False,
                     "readme/README.md 不可读")
            return

        # D15/D16: 端口
        has_8000 = "8000" in text
        has_5173 = "5173" in text
        backend_ports = sorted(set(re.findall(r"--port\s+(\d+)", text)))
        self.add("D15", "readme/README.md 声明后端 8000 / 前端 5173",
                 has_8000 and has_5173,
                 "" if (has_8000 and has_5173) else f"8000={has_8000}, 5173={has_5173}")
        self.add("D16", "后端启动命令使用 --port 8000",
                 backend_ports == ["8000"],
                 "" if backend_ports == ["8000"] else f"实际 --port 取值为 {backend_ports}")

        # D17: 演示账号
        missing_accounts = [name for name in ACCOUNTS if name not in text]
        self.add("D17", "演示账号 teacher01 / student01~03 齐全", not missing_accounts,
                 "" if not missing_accounts else "缺失：" + "、".join(missing_accounts))

        # D18: env 变量名（以 2.2.1 的固定变量清单为准）
        missing_env = [name for name in ENV_VAR_NAMES if name not in text]
        self.add("D18", f"env 变量名 {len(ENV_VAR_NAMES)} 个齐全", not missing_env,
                 "" if not missing_env else "缺失：" + "、".join(missing_env))

        # D19: env 默认值三方比对（plan 2.2.1 动态解析 vs readme vs 根 README vs .env.example）
        root_text = self.read_text("README.md")
        root_parsed = {} if root_text.startswith("__READ_ERROR__") else parse_env_table(root_text)
        problems = self.compare_env_defaults(parse_env_table(text), root_parsed)
        self.add("D19", "env 默认值与 plan 2.2.1 逐项一致（readme / 根 README / .env.example）",
                 not problems, "" if not problems else "不一致：" + "；".join(problems))

        # D20: 根 README 启动命令段落一致性
        root_text = self.read_text("README.md")
        if root_text.startswith("__READ_ERROR__"):
            self.add("D20", "根 README 启动命令一致性", False, root_text)
            return
        readme_cmds = extract_launch_commands(text, "## 3. 部署运行步骤", "## 4. 演示账号")
        root_cmds = extract_launch_commands(root_text, "### 5.2 启动", "### 5.3 环境变量")
        expected_cmds = {"cd backend", "uvicorn app.main:app --port 8000", "cd frontend", "npm run dev"}
        problems: list[str] = []
        if not expected_cmds.issubset(readme_cmds):
            problems.append(f"readme/README.md 缺少启动命令：{sorted(expected_cmds - readme_cmds)}")
        if not expected_cmds.issubset(root_cmds):
            problems.append(f"根 README.md 缺少启动命令：{sorted(expected_cmds - root_cmds)}")
        readme_ports = sorted(set(re.findall(r"--port\s+(\d+)", "\n".join(readme_cmds))))
        root_ports = sorted(set(re.findall(r"--port\s+(\d+)", "\n".join(root_cmds))))
        if readme_ports != root_ports:
            problems.append(f"启动端口不一致：readme={readme_ports}, root={root_ports}")
        self.add("D20", "根 README 与 readme/README.md 启动命令段落一致", not problems,
                 "" if not problems else "；".join(problems))

    def check_proof_authenticity(self) -> None:
        # D21: 五个小节 + 占位标注与归档状态一致（防"占位被写成已完成"）
        problems: list[str] = []
        archive_dir = self.path("codearts_proof/prompts/agent_team_启动指令")
        archived_files = [
            p for p in archive_dir.glob("*") if p.is_file() and p.name != ".gitkeep"
        ] if archive_dir.is_dir() else []
        for rel in AI_DIALOGUE_FILES:
            text = self.read_text(rel)
            if text.startswith("__READ_ERROR__"):
                problems.append(f"{rel}: 不可读")
                continue
            missing = [s for s in REQUIRED_DIALOGUE_SECTIONS if s not in text]
            if missing:
                problems.append(f"{rel}: 缺少小节 {missing}")
            prompt_section = slice_section(text, "## 输入 Prompt", "## 产出")
            claims_archived = prompt_section and not any(
                mark in prompt_section for mark in PLACEHOLDER_MARKS
            )
            if claims_archived and not archived_files:
                problems.append(
                    f"{rel}: 「输入 Prompt」未标注占位，但 prompts/agent_team_启动指令/ 无归档文件"
                )
        self.add("D21", "ai_dialogue 五小节齐全且占位标注与归档状态一致",
                 not problems, "" if not problems else "；".join(problems))

        # D22: LOG.md ≥ 6 行真实记录
        log_text = self.read_text("codearts_proof/LOG.md")
        rows = count_real_log_rows(log_text)
        self.add("D22", "LOG.md 至少 6 行真实记录", rows >= 6, f"实际有效记录行数：{rows}")

        # D23: debug/ 至少 3 篇实例（2.2.14 明确要求）
        debug_dir = self.path("codearts_proof/debug")
        instances = (
            [p for p in debug_dir.glob("*.md") if p.name != "template.md"]
            if debug_dir.is_dir() else []
        )
        self.add("D23", "debug/ 至少 3 篇排错实例（template.md 之外）",
                 len(instances) >= 3,
                 f"实际实例数：{len(instances)}（仅 template.md 属模板，不计实例）")

        # D24: 开源组件说明 14 项且每行有版本与用途
        oss_text = self.read_text("readme/开源组件说明.md")
        if oss_text.startswith("__READ_ERROR__"):
            self.add("D24", "开源组件说明 14 项齐全", False, oss_text)
        else:
            rows_table = [line for line in oss_text.splitlines() if line.strip().startswith("|")]
            missing = []
            for name, pattern in OPENSOURCE_COMPONENTS:
                matched = [
                    line for line in rows_table
                    if re.search(pattern, line) and len(line.split("|")) >= 6
                ]
                if not matched:
                    missing.append(name)
            self.add("D24", "开源组件说明覆盖 2.2.14 的 14 项（含版本/用途列）",
                     not missing, "" if not missing else "缺少组件行：" + "、".join(missing))

        # D25: 产出表中声明的路径真实存在（编造检测）
        # 口径：历史阶段文档记录的是「当时产出」；若该路径在本轮 stage8 中明确记录为删除，
        # 则属于「有据的历史删除」，不算编造（否则 B9 删除组件会把历史留痕误判为 FAIL）。
        phantom: list[str] = []
        removed_history: list[str] = []
        stage8_text = self.read_text("codearts_proof/ai_dialogue/stage8_第三轮体验修复.md")
        for rel in AI_DIALOGUE_FILES:
            text = self.read_text(rel)
            if text.startswith("__READ_ERROR__"):
                continue
            section = slice_section(text, "## 产出", "## 问题")
            for path_str in extract_produced_paths(section):
                if self.path(path_str).exists():
                    continue
                documented_removed = (
                    not stage8_text.startswith("__READ_ERROR__")
                    and any(
                        path_str in line and "删除" in line
                        for line in stage8_text.splitlines()
                    )
                )
                if documented_removed:
                    removed_history.append(f"{path_str}（stage8 记录已删除）")
                else:
                    phantom.append(f"{rel} 声明 `{path_str}` 但不存在")
        detail_parts: list[str] = []
        if phantom:
            detail_parts.append("；".join(phantom))
        if removed_history:
            detail_parts.append("有据历史删除（不计编造）：" + "、".join(removed_history))
        self.add("D25", "ai_dialogue「产出」表声明的路径均可核验存在",
                 not phantom, "；".join(detail_parts))

    def check_extra_consistency(self) -> None:
        # D26: readme 的 9 个变量与 .env.example 变量集合一致
        example_text = self.read_text("backend/.env.example")
        if example_text.startswith("__READ_ERROR__"):
            self.add("D26", ".env.example 变量集合一致", False, example_text)
        else:
            example_vars = set(parse_dotenv_values(example_text))
            diff = set(ENV_VAR_NAMES) ^ example_vars
            self.add("D26", ".env.example 的变量集合与 2.2.1 一致", not diff,
                     "" if not diff else f"差异：{sorted(diff)}")

        # D27: 根 README 账号表与 readme/README.md 一致
        root_text = self.read_text("README.md")
        if root_text.startswith("__READ_ERROR__"):
            self.add("D27", "根 README 演示账号一致", False, root_text)
        else:
            missing = [name for name in ACCOUNTS if name not in root_text]
            self.add("D27", "根 README.md 演示账号与 readme/README.md 一致",
                     not missing, "" if not missing else "缺失：" + "、".join(missing))

    def check_round2_delivery(self) -> None:
        """第二轮迭代（`C-DELIVERY@2`）：stage7 / LOG 阶段 7 / README 四项 / B 段收口（D28~D31）。"""
        stage7_rel = "codearts_proof/ai_dialogue/stage7_体验迭代.md"
        stage7 = self.read_text(stage7_rel)
        exists = not stage7.startswith("__READ_ERROR__")
        sections = (
            "## 1 用户反馈",
            "## 2 Leader 决策",
            "## 3 派工 Prompt 要点",
            "## 4 产出",
            "## 5 问题与修复",
        )
        missing = [section for section in sections if exists and section not in stage7]
        self.add(
            "D28",
            f"stage7_体验迭代.md 存在且含 5 个二级标题（{len(sections)} 个）",
            exists and not missing,
            "" if (exists and not missing) else ("文件缺失：" + stage7_rel if not exists else f"缺少小节：{missing}"),
        )

        log_text = self.read_text("codearts_proof/LOG.md")
        log_ok = not log_text.startswith("__READ_ERROR__") and "阶段 7" in log_text
        self.add("D29", "LOG.md 含「阶段 7」本轮记录", log_ok, "" if log_ok else "LOG.md 未找到「阶段 7」")

        keywords = ("报名审批", "增量解析", "追溯块", "语音实时")
        problems: list[str] = []
        for label, text in (
            ("readme/README.md", self.read_text("readme/README.md")),
            ("根 README.md", self.read_text("README.md")),
        ):
            if text.startswith("__READ_ERROR__"):
                problems.append(f"{label} 不可读")
                continue
            miss = [keyword for keyword in keywords if keyword not in text]
            if miss:
                problems.append(f"{label} 缺少关键词 {miss}")
        self.add("D30", "两份 README 均含四项功能关键词（报名审批/增量解析/追溯块/语音实时）",
                 not problems, "" if not problems else "；".join(problems))

        # D31：B 段（第 4/5 节）必须真实收口；若仍是占位，R17-AC1 不能 PASS（真实缺陷，不得 DEFERRED 掩盖）
        b4 = slice_section(stage7, "## 4 产出", "## 5 问题与修复")
        b5 = stage7[stage7.find("## 5 问题与修复") :] if "## 5 问题与修复" in stage7 else ""
        placeholders = ("待实现完成后补写", "B 段待补")
        hits = [mark for mark in placeholders if mark in b4 or mark in b5]
        closed = exists and bool(b4) and bool(b5) and not hits
        self.add(
            "D31",
            "stage7 第 4/5 节已真实收口（B 段非占位）",
            closed,
            "" if closed else f"仍为占位（命中 {hits}）：T7 B 段未收口，R17-AC1 不能记 PASS",
        )

    def check_round3_delivery(self) -> None:
        """第三轮（`C-DELIVERY@3`）：stage8 / LOG 阶段 8 / 两份 README 四项（D32~D34）。"""
        stage8_rel = "codearts_proof/ai_dialogue/stage8_第三轮体验修复.md"
        stage8 = self.read_text(stage8_rel)
        exists = not stage8.startswith("__READ_ERROR__")
        # stage8 的五节标题：`## 1 用户反馈` / `## 2 Leader 决策...` / `## 3 派工...`
        # / `## 4 产出` / `## 5 问题与修复`（允许标题后附带括号说明）
        required = (
            (r"^## 1[^\n]*用户反馈", "## 1 用户反馈"),
            (r"^## 2[^\n]*Leader\s*决策", "## 2 Leader 决策"),
            (r"^## 3[^\n]*派工", "## 3 派工"),
            (r"^## 4[^\n]*产出", "## 4 产出"),
            (r"^## 5[^\n]*问题与修复", "## 5 问题与修复"),
        )
        missing = [
            label for pattern, label in required
            if not exists or re.search(pattern, stage8, re.MULTILINE) is None
        ]
        self.add(
            "D32",
            f"stage8_第三轮体验修复.md 存在且含 5 个二级标题（{len(required)} 个）",
            exists and not missing,
            "" if (exists and not missing) else (
                f"文件缺失：{stage8_rel}" if not exists else f"缺少小节：{missing}"
            ),
        )

        log_text = self.read_text("codearts_proof/LOG.md")
        log_ok = not log_text.startswith("__READ_ERROR__") and "阶段 8" in log_text
        self.add("D33", "LOG.md 含「阶段 8」本轮记录", log_ok, "" if log_ok else "LOG.md 未找到「阶段 8」")

        # D34：两份 README 的第三轮四项功能（按语义匹配，兼容 markdown 粗体与「层/已彻底」等修饰）
        problems: list[str] = []
        for label, text in (
            ("readme/README.md", self.read_text("readme/README.md")),
            ("根 README.md", self.read_text("README.md")),
        ):
            if text.startswith("__READ_ERROR__"):
                problems.append(f"{label} 不可读")
                continue
            normalized = normalize_markdown_text(text)
            checks = (
                ("悬浮确认已删除", re.search(r"悬浮确认[^\n。]{0,8}已[^\n。]{0,4}删除", normalized)),
                (
                    "子任务默认不随主任务发布",
                    re.search(r"子任务默认不(?:随主任务发布|勾选)", normalized),
                ),
                ("草稿自动本地持久化", "草稿自动本地持久化" in normalized),
                ("关闭 DeepSeek 思考模式", "关闭 DeepSeek 思考模式" in normalized),
            )
            miss = [name for name, matched in checks if not matched]
            if miss:
                problems.append(f"{label} 缺少关键词 {miss}")
        self.add(
            "D34",
            "两份 README 均含第三轮四项（悬浮确认已删除/子任务默认不随主任务发布/"
            "草稿自动本地持久化/关闭 DeepSeek 思考模式）",
            not problems,
            "" if not problems else "；".join(problems),
        )

    def check_round4_delivery(self) -> None:
        """第四轮（`C-DELIVERY@4`）：stage9 五节 + B 段收口 / LOG 阶段 9 / 两份 README 四项（D35~D37）。

        口径与 D31（第二轮 stage7）保持一致：**第 4/5 节仍是占位就判 FAIL**，
        不因「A 段已写」而放过；B 段由书记官按 T6 实测数字回填后本项才可 PASS。
        """
        stage9_rel = "codearts_proof/ai_dialogue/stage9_第四轮体验微调.md"
        stage9 = self.read_text(stage9_rel)
        exists = not stage9.startswith("__READ_ERROR__")
        required = (
            (r"^## 1[^\n]*用户", "## 1 用户反馈"),
            (r"^## 2[^\n]*Leader", "## 2 Leader 决策与核验修正"),
            (r"^## 3[^\n]*派工", "## 3 派工与契约要点"),
            (r"^## 4[^\n]*产出", "## 4 真实产出"),
            (r"^## 5[^\n]*问题与修复", "## 5 真实问题与修复"),
        )
        missing = [
            label
            for pattern, label in required
            if not exists or re.search(pattern, stage9, re.MULTILINE) is None
        ]

        # 第 1 节必须覆盖 C1~C5；第 2 节必须记录 C5 v1→v2 与 C3 覆盖第三轮 B5
        first_section = slice_section(stage9, "## 1", "## 2") if exists else ""
        missing_codes = [code for code in ("C1", "C2", "C3", "C4", "C5") if code not in first_section]
        second_section = slice_section(stage9, "## 2", "## 3") if exists else ""
        decision_problems: list[str] = []
        for keyword in ("v1", "否决"):
            if keyword not in second_section:
                decision_problems.append(f"第 2 节缺少「{keyword}」")
        # C3 对第三轮 B5 的口径反转：允许「覆盖 / 反转 / 作废」三种等价表述
        if not re.search(r"(覆盖|反转|作废)", second_section):
            decision_problems.append("第 2 节未记录 C3 对第三轮 B5 的口径反转（覆盖/反转/作废）")
        third_section = slice_section(stage9, "## 3", "## 4") if exists else ""
        contract_ids = ("C-VOICEUI@4", "C-TYPO@1", "C-TRACE@2", "C-DELIVERY@4")
        missing_contracts = [cid for cid in contract_ids if cid not in third_section]

        # B 段（第 4/5 节）是否真实收口：占位标记零命中才算收口
        b4 = slice_section(stage9, "## 4", "## 5") if exists else ""
        b5 = slice_section(stage9, "## 5", "\n---\n## ") if exists else ""
        if exists and not b5:
            b5 = stage9[stage9.find("## 5") :] if "## 5" in stage9 else ""
        placeholder_marks = ("B 段待补", "待补写", "待 T1", "（待", "占位")
        hits = [mark for mark in placeholder_marks if mark in b4 or mark in b5]
        b_closed = bool(b4.strip()) and bool(b5.strip()) and not hits

        detail_parts: list[str] = []
        if not exists:
            detail_parts.append(f"文件缺失：{stage9_rel}")
        if missing:
            detail_parts.append(f"缺少小节：{missing}")
        if missing_codes:
            detail_parts.append(f"第 1 节未覆盖 {missing_codes}")
        detail_parts.extend(decision_problems)
        if missing_contracts:
            detail_parts.append(f"第 3 节缺少契约 ID {missing_contracts}")
        if exists and not b_closed:
            detail_parts.append(
                f"第 4/5 节仍为占位（命中 {hits}）：B 段未收口，R24-AC3 不能记 PASS"
            )

        stage_ok = (
            exists
            and not missing
            and not missing_codes
            and not decision_problems
            and not missing_contracts
            and b_closed
        )
        self.add(
            "D35",
            "stage9_第四轮体验微调.md 存在、含 5 个二级标题、第 1 节覆盖 C1~C5、"
            "第 2 节记录 v1/否决/覆盖、第 3 节含 4 个契约 ID，且第 4/5 节非占位",
            stage_ok,
            "" if stage_ok else "；".join(detail_parts),
        )

        log_text = self.read_text("codearts_proof/LOG.md")
        log_ok = not log_text.startswith("__READ_ERROR__") and "阶段 9" in log_text
        self.add("D36", "LOG.md 含「阶段 9」本轮记录", log_ok, "" if log_ok else "LOG.md 未找到「阶段 9」")

        # D37：两份 README 的第四轮四项（语义匹配，兼容 markdown 粗体与空格）
        problems: list[str] = []
        for label, text in (
            ("readme/README.md", self.read_text("readme/README.md")),
            ("根 README.md", self.read_text("README.md")),
        ):
            if text.startswith("__READ_ERROR__"):
                problems.append(f"{label} 不可读")
                continue
            normalized = normalize_markdown_text(text)
            checks = (
                ("发布页默认 AI 智能模式", re.search(r"默认\s*AI\s*智能模式", normalized)),
                (
                    "块内编辑已移除",
                    re.search(
                        r"(块内编辑|块编辑|文字块点击编辑)[^\n。]{0,16}(已)?移除",
                        normalized,
                    ),
                ),
                (
                    "解析不留痕（仅显式采纳留痕）",
                    re.search(r"解析[^\n。]{0,24}(不再自动生成|不留痕)", normalized),
                ),
                (
                    "语音 onend 收尾",
                    re.search(r"(onend[^\n。]{0,16}收尾|语音停止改由\s*onend)", normalized),
                ),
            )
            miss = [name for name, matched in checks if not matched]
            if miss:
                problems.append(f"{label} 缺少关键词 {miss}")
        self.add(
            "D37",
            "两份 README 均含第四轮四项（默认智能模式/块内编辑已移除/"
            "解析不留痕/语音 onend 收尾）",
            not problems,
            "" if not problems else "；".join(problems),
        )

    def check_round5_delivery(self) -> None:
        """第五轮（`C-DELIVERY@5`）：stage10 / LOG 阶段 10 / 两份 README（D38~D40）。

        口径与 D31/D35 一致：**第 4/5 节仍是占位就判 FAIL**，不因 A 段（第 1~3 节）已写而放过；
        B 段由书记官按 T4 实测数字回填后 D38 才可 PASS。
        """
        stage10_rel = "codearts_proof/ai_dialogue/stage10_第五轮体验修复.md"
        stage10 = self.read_text(stage10_rel)
        exists = not stage10.startswith("__READ_ERROR__")

        # 五节标题按语义匹配（A 段实际标题为「## 1 用户反馈（第五轮，2 项）」等，
        # 不按逐字标题卡死；序号 1~5 与语义关键词必须同时命中）
        required = (
            (r"^## 1[^\n]*用户", "## 1 用户反馈"),
            (r"^## 2[^\n]*(根因|核验)", "## 2 根因核验"),
            (r"^## 3[^\n]*派工", "## 3 派工"),
            (r"^## 4[^\n]*产出", "## 4 产出"),
            (r"^## 5[^\n]*问题与修复", "## 5 问题与修复"),
        )
        missing = [
            label
            for pattern, label in required
            if not exists or re.search(pattern, stage10, re.MULTILINE) is None
        ]

        # 第 1 节：两项反馈各成小节 + 用户原话「录两遍」+ 403 现象
        first_section = slice_section(stage10, "## 1", "## 2") if exists else ""
        first_problems: list[str] = []
        if "录两遍" not in first_section:
            first_problems.append("第 1 节缺少用户原话「录两遍」")
        if re.search(r"403|Blocked request", first_section, re.IGNORECASE) is None:
            first_problems.append("第 1 节缺少「403 Blocked request」现象")
        for marker in ("### 1.1", "### 1.2"):
            if marker not in first_section:
                first_problems.append(f"第 1 节缺少 {marker} 小节（两项反馈须各自成节）")

        # 第 2 节：根因关键词（dedupTail / keepSession / B7 / C5 收尾时序）
        second_section = slice_section(stage10, "## 2", "## 3") if exists else ""
        root_keywords = ("dedupTail", "keepSession", "B7", "C5 收尾时序")
        missing_root = [keyword for keyword in root_keywords if keyword not in second_section]

        # 第 3 节契约 ID：属 plan 2.2.3 要求，但 T3 A 段声明「B 段回填时登记」——
        # 当前缺失记为观察项（不计 FAIL），避免与「唯一原因 = B 段未收口」的口径分叉。
        third_section = slice_section(stage10, "## 3", "## 4") if exists else ""
        contract_ids = ("C-VOICEUI@5", "C-DEV@1", "C-DELIVERY@5")
        missing_contracts = [cid for cid in contract_ids if cid not in third_section]

        # 第 4/5 节：B 段必须真实收口（占位标记零命中），且第 4 节须有实测计数
        b4 = slice_section(stage10, "## 4", "## 5") if exists else ""
        b5 = stage10[stage10.find("## 5") :] if exists and "## 5" in stage10 else ""
        placeholder_marks = ("待补", "B 段待补", "待 T1", "待 T4", "占位", "待收口")
        hits = [mark for mark in placeholder_marks if mark in b4 or mark in b5]
        b_closed = bool(b4.strip()) and bool(b5.strip()) and not hits
        counter_ok = (not b_closed) or re.search(r"\d{2,}", b4) is not None

        detail_parts: list[str] = []
        if not exists:
            detail_parts.append(f"文件缺失：{stage10_rel}")
        if missing:
            detail_parts.append(f"缺少小节：{missing}")
        detail_parts.extend(first_problems)
        if missing_root:
            detail_parts.append(f"第 2 节缺少根因关键词 {missing_root}")
        if exists and not b_closed:
            detail_parts.append(
                f"第 4/5 节仍为占位（命中 {hits}）：B 段未收口，R26-AC3 不能记 PASS"
            )
        elif not counter_ok:
            detail_parts.append("第 4 节已去占位但未出现任何实测计数（至少 2 位数）")
        if missing_contracts:
            detail_parts.append(
                f"观察（不计 FAIL）：第 3 节尚未登记契约 ID {missing_contracts}"
                "（T3 A 段声明由 B 段回填时补齐）"
            )

        stage_ok = (
            exists
            and not missing
            and not first_problems
            and not missing_root
            and b_closed
            and counter_ok
        )
        self.add(
            "D38",
            "stage10_第五轮体验修复.md 存在、含 5 节、第 1 节两项反馈（录两遍/403）、"
            "第 2 节含 dedupTail/keepSession/B7/C5 收尾时序，且第 4/5 节非占位",
            stage_ok,
            "" if stage_ok else "；".join(detail_parts),
        )

        log_text = self.read_text("codearts_proof/LOG.md")
        log_ok = not log_text.startswith("__READ_ERROR__") and "阶段 10" in log_text
        self.add(
            "D39",
            "LOG.md 含「阶段 10」本轮记录",
            log_ok,
            "" if log_ok else "LOG.md 未找到「阶段 10」",
        )

        # D40：两份 README 的第五轮关键词（与 plan 2.2.3 对齐；「录两遍」不在本轮
        # README 硬性关键词内，避免把文档措辞差异误判为交付缺陷）
        problems: list[str] = []
        keywords = ("allowedHosts", "takin.cc", "dedupTail", "续接")
        for label, text in (
            ("readme/README.md", self.read_text("readme/README.md")),
            ("根 README.md", self.read_text("README.md")),
        ):
            if text.startswith("__READ_ERROR__"):
                problems.append(f"{label} 不可读")
                continue
            miss = [keyword for keyword in keywords if keyword not in text]
            if miss:
                problems.append(f"{label} 缺少关键词 {miss}")
        self.add(
            "D40",
            "两份 README 均含第五轮关键词（allowedHosts / takin.cc / dedupTail / 续接）",
            not problems,
            "" if not problems else "；".join(problems),
        )

    # -- run ---------------------------------------------------------------
    def run(self) -> int:
        self.check_readme_files()
        self.check_codearts_structure()
        self.check_text_contract()
        self.check_proof_authenticity()
        self.check_extra_consistency()
        self.check_round2_delivery()
        self.check_round3_delivery()
        self.check_round4_delivery()
        self.check_round5_delivery()

        total = len(self.results)
        failed = [r for r in self.results if not r.ok]

        print("=" * 72)
        print(" T12 交付物完整性 / 契约一致性核验")
        print(f" 工程根：{self.root}")
        print("=" * 72)
        for result in self.results:
            status = "PASS" if result.ok else "FAIL"
            print(f"[{status}] {result.item_id} · {result.title}")
            if not result.ok and result.detail:
                print(f"       → {result.detail}")
        print("-" * 72)
        print(f" 汇总：{total - len(failed)} PASS / {len(failed)} FAIL / 共 {total} 项")
        if failed:
            print(" 失败项：")
            for result in failed:
                print(f"  ✗ {result.item_id} {result.title}")
            print(" 结论：交付物核验 FAIL")
            print("=" * 72)
            return 1
        print(" 结论：交付物核验 PASS")
        print("=" * 72)
        return 0


# --------------------------------------------------------------------------- #
# 解析工具
# --------------------------------------------------------------------------- #
def first_tick_value(cell: str) -> str:
    """从表格单元格提取契约取值：优先取第一组反引号内容。"""
    match = re.search(r"`([^`]+)`", cell)
    if match:
        return match.group(1).strip()
    return cell.strip()


def normalize_contract_value(value: str) -> str:
    """规范化契约取值：空串与"空"等价（如 ``MAAS_API_KEY`` 为空）。"""
    stripped = value.strip()
    return "空" if stripped in {"", "（空）", "(空)"} else stripped


def normalize_markdown_text(text: str) -> str:
    """去掉 markdown 行内标记（粗体 / 行内代码 / 表格分隔），供关键词语义匹配。"""
    return re.sub(r"[*_`|]", "", text)


def parse_dotenv_values(text: str) -> dict[str, str]:
    """解析 ``.env`` / ``.env.example`` 的 ``KEY=VALUE`` 行（忽略注释与空行）。"""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            values[key] = value.strip()
    return values


def is_placeholder_value(value: str) -> bool:
    """判断示例值是否为占位值（占位值允许与契约默认值不同）。"""
    lowered = value.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


def parse_env_table(text: str) -> dict[str, str]:
    """解析 readme 中的 env 表格：``| `VAR` | 默认值 | 语义 |``。"""
    rows: dict[str, str] = {}
    pattern = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|\s*(.*?)\s*\|")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def slice_section(text: str, start_marker: str, end_marker: str) -> str:
    """截取 markdown 中两个小节标题之间的正文；缺失返回空串。"""
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = text.find(end_marker, start + len(start_marker))
    return text[start:end] if end > start else text[start:]


def extract_launch_commands(text: str, start_marker: str, end_marker: str) -> set[str]:
    """从启动步骤段落提取命令集合（去掉注释、围栏与说明文字）。"""
    section = slice_section(text, start_marker, end_marker)
    commands: set[str] = set()
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith("#"):  # 纯注释行
            continue
        # 行尾注释（如 “# macOS / Linux：...”）不影响命令本体
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if not line:
            continue
        # 仅保留命令类文本：以 cd / npm / npx / .venv / uvicorn / curl 开头
        if re.match(r"^(cd|npm|npx|\.venv|\./|uvicorn|curl)\b", line):
            commands.add(re.sub(r"\s+", " ", line))
        # 兼容行内断言：只要包含关键命令片段也收录，供 issubset 比对
        for key in ("uvicorn app.main:app --port 8000", "npm run dev"):
            if key in line:
                commands.add(key)
    return commands


def count_real_log_rows(log_text: str) -> int:
    """统计 LOG.md 表格中真实的记录行（排除表头、分隔行与待办行）。"""
    count = 0
    for line in log_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if set(stripped) <= set("|-: "):  # 分隔行
            continue
        if "日期" in stripped and "阶段" in stripped:  # 表头
            continue
        if any(mark in stripped for mark in NOT_YET_MARKS) or "—" == stripped.split("|")[1].strip():
            continue
        count += 1
    return count


def extract_produced_paths(section: str) -> list[str]:
    """从「产出」小节提取可核验的仓库相对路径。

    过滤掉通配符、占位符、URL、中文说明与未发生的行。
    """
    allowed_prefixes = ("backend/", "frontend/", "readme/", "codearts_proof/", "tests/")
    allowed_exact = {"README.md", ".gitignore", "backend/.env.example"}
    paths: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if any(mark in line for mark in NOT_YET_MARKS):
            continue
        for candidate in re.findall(r"`([^`]+)`", line):
            value = candidate.strip()
            if not value or value.startswith("http"):
                continue
            if any(ch in value for ch in "*{}<>…") or "..." in value:
                continue
            if re.search(r"[\u4e00-\u9fff]", value):
                continue
            if value in allowed_exact or value.startswith(allowed_prefixes):
                if value not in paths:
                    paths.append(value)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T12 交付物完整性与契约一致性核验（只读）"
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="工程根目录（默认：tests/security 上两级）",
    )
    parser.add_argument(
        "--plan",
        default=None,
        help="规划契约 plan.md 路径（默认：<工程根上一级>/.codeartsdoer/plans/campus-task-agent/plan.md）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # 非交互式输出流或旧版本 Python
        pass

    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FATAL] 工程根不存在：{root}", file=sys.stderr)
        return 2
    plan_path = Path(args.plan).resolve() if args.plan else None
    return Checker(root, plan_path).run()


if __name__ == "__main__":
    raise SystemExit(main())