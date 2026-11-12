#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5 · 交付包重打与包内自检（仅 Python 标准库 `zipfile`）。

用法::

    python tests/security/pack_delivery.py
    python tests/security/pack_delivery.py --root ../.. --out /path/to/out.zip

行为：
1. 遍历工程根 `campus-task-agent/`，按 `C-DELIVERY@3` 排除敏感/依赖/临时文件；
2. 用 `zipfile.ZIP_DEFLATED` 写出 `campus-task-agent-delivery.zip`；
3. 重新打开 zip 做包内自检并打印：
   - `PACKED_FILES=` / `ZIP_SIZE_MB=`
   - `SENSITIVE_IN_ZIP=`（必须为 0，列出命中）
   - 关键文件存在性（README / backend/app/main.py / frontend/src/main.ts / stage8 /
     stage9 / stage10 / ACCEPTANCE / readme/install.sh）
   - `DIST_FILES_IN_ZIP=`（frontend/dist 必须包含）
4. **二次开包校验**（第五轮，T4）：包内 stage10 与磁盘字节一致、包内 ACCEPTANCE 与磁盘字节
   一致、唯一 `VERDICT` 可解析；且「stage10 第 4/5 节仍占位」时 `VERDICT` 不得为 `PASS`
   （防止 A 段未收口却给出 PASS 的交付假象）。

退出码：0 = 打包与自检全部通过；1 = 自检失败。
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

#: 目录名黑名单（依赖 / 虚拟环境 / 缓存）
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({"node_modules", ".venv", "__pycache__", ".git"})

#: 文件名/后缀黑名单（敏感、运行时、临时、日志）
EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".db",
    ".db-journal",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".log",
)

#: 关键文件（相对工程根；zip 内需带 `campus-task-agent/` 前缀）
KEY_FILES: tuple[str, ...] = (
    "README.md",
    "backend/app/main.py",
    "frontend/src/main.ts",
    "codearts_proof/ai_dialogue/stage8_第三轮体验修复.md",
    "codearts_proof/ai_dialogue/stage9_第四轮体验微调.md",
    "codearts_proof/ai_dialogue/stage10_第五轮体验修复.md",
    "tests/security/ACCEPTANCE.md",
    "readme/install.sh",
)

#: 二次开包校验对象（第五轮交付一致性）
STAGE10_REL: str = "codearts_proof/ai_dialogue/stage10_第五轮体验修复.md"
ACCEPTANCE_REL: str = "tests/security/ACCEPTANCE.md"

#: stage10 第 4/5 节的占位标记（与 verify_delivery.py D38 同口径）
STAGE10_PLACEHOLDER_MARKS: tuple[str, ...] = (
    "待补",
    "B 段待补",
    "待 T1",
    "待 T4",
    "占位",
    "待收口",
)

#: zip 内工程目录名前缀
PREFIX = "campus-task-agent/"


def is_excluded(rel_posix: str) -> bool:
    """按路径判断是否排除（敏感文件 / 依赖 / 构建临时目录 / 日志）。"""
    parts = rel_posix.split("/")
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    if any(part.startswith("dist-t") for part in parts):
        return True
    if rel_posix == "backend/.env":
        return True
    # 交接文档是「给同学」的内部材料（2026-11-11 定位修正）：
    # 比赛交付包只放给评委看的 AI 使用留痕，不含任何交接文档。
    if rel_posix in {"codearts_proof/handover.md", "HANDOVER.md"}:
        return True
    name = parts[-1]
    if name.startswith(".tmp"):
        return True
    if any(name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    return False


def collect_files(root: Path) -> tuple[list[Path], list[str]]:
    """返回 (待打包文件, 被排除的相对路径)。"""
    included: list[Path] = []
    excluded: list[str] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(root).as_posix()
        if is_excluded(rel):
            excluded.append(rel)
        else:
            included.append(file_path)
    return included, excluded


def extract_verdict(text: str) -> str:
    """提取唯一的 ``VERDICT: PASS|PARTIAL|FAIL`` 行；缺失返回 ``MISSING``。"""
    match = re.search(r"^VERDICT:\s*(PASS|PARTIAL|FAIL)\s*$", text, re.MULTILINE)
    return match.group(1) if match else "MISSING"


def stage10_has_placeholder(text: str) -> bool:
    """判断 stage10 第 4/5 节是否仍含占位标记（与 verify_delivery.py D38 同口径）。"""
    start = text.find("## 4")
    if start < 0:
        return True
    tail = text[start:]
    return any(mark in tail for mark in STAGE10_PLACEHOLDER_MARKS)


def pack(root: Path, out_path: Path) -> int:
    print("=" * 72)
    print(" T5 交付包重打（Python zipfile）")
    print(f" 工程根：{root}")
    print(f" 输出包：{out_path}")
    print("=" * 72)

    if not root.is_dir():
        print(f"[FATAL] 工程根不存在：{root}", file=sys.stderr)
        return 2

    included, excluded = collect_files(root)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in included:
            rel = file_path.relative_to(root).as_posix()
            archive.write(file_path, PREFIX + rel)

    # ------------------------- 包内自检 ------------------------- #
    with zipfile.ZipFile(out_path, "r") as archive:
        names = archive.namelist()
        stage10_name = PREFIX + STAGE10_REL
        acceptance_name = PREFIX + ACCEPTANCE_REL
        zipped_stage10 = (
            archive.read(stage10_name) if stage10_name in names else None
        )
        zipped_acceptance = (
            archive.read(acceptance_name) if acceptance_name in names else None
        )

    packed_files = sum(1 for name in names if not name.endswith("/"))
    size_mb = out_path.stat().st_size / (1024 * 1024)

    sensitive_hits = [
        name for name in names
        if name.startswith(PREFIX) and is_excluded(name[len(PREFIX):])
    ]
    # 双重保险：直接按包内路径再匹配一次敏感后缀（防止前缀判断遗漏）
    for name in names:
        rel = name[len(PREFIX):] if name.startswith(PREFIX) else name
        if is_excluded(rel) and name not in sensitive_hits:
            sensitive_hits.append(name)

    print(f"PACKED_FILES={packed_files}")
    print(f"ZIP_SIZE_MB={size_mb:.2f}")
    print(f"SENSITIVE_IN_ZIP={len(sensitive_hits)}")
    for hit in sensitive_hits:
        print(f"  SENSITIVE_HIT {hit}")
    print(f"EXCLUDED_FILES={len(excluded)}")
    for rel in excluded[:12]:
        print(f"  EXCLUDED {rel}")

    print("关键文件存在性：")
    key_ok = True
    for rel in KEY_FILES:
        exists = (PREFIX + rel) in names
        key_ok = key_ok and exists
        print(f"  {'OK' if exists else 'MISSING'} {PREFIX + rel}")

    dist_files = [name for name in names if name.startswith(PREFIX + "frontend/dist/")]
    dist_ok = len(dist_files) >= 2 and any(name.endswith("index.html") for name in dist_files)
    print(f"DIST_FILES_IN_ZIP={len(dist_files)}")
    for name in dist_files[:10]:
        print(f"  DIST {name}")

    # ---------------------- 二次开包校验（第五轮） ---------------------- #
    # 口径：
    # ① 包内 stage10 / ACCEPTANCE 必须与磁盘字节一致（确认包内就是本次验收版本）；
    # ② 包内 ACCEPTANCE 必须能解析出唯一 VERDICT；
    # ③ stage10 第 4/5 节仍是占位时，VERDICT **不得**为 PASS（A 段未收口不得交付 PASS）。
    print("二次开包校验：")
    disk_stage10_path = root / STAGE10_REL
    disk_acceptance_path = root / ACCEPTANCE_REL
    stage10_bytes_match = (
        zipped_stage10 is not None
        and disk_stage10_path.is_file()
        and zipped_stage10 == disk_stage10_path.read_bytes()
    )
    acceptance_bytes_match = (
        zipped_acceptance is not None
        and disk_acceptance_path.is_file()
        and zipped_acceptance == disk_acceptance_path.read_bytes()
    )
    zipped_acceptance_text = (
        zipped_acceptance.decode("utf-8", errors="replace")
        if zipped_acceptance is not None
        else ""
    )
    zipped_stage10_text = (
        zipped_stage10.decode("utf-8", errors="replace")
        if zipped_stage10 is not None
        else ""
    )
    verdict = extract_verdict(zipped_acceptance_text)
    verdict_count = len(
        re.findall(r"^VERDICT:\s*(?:PASS|PARTIAL|FAIL)\s*$", zipped_acceptance_text, re.MULTILINE)
    )
    placeholder = stage10_has_placeholder(zipped_stage10_text)
    consistency_problems: list[str] = []
    if not stage10_bytes_match:
        consistency_problems.append("包内 stage10 与磁盘不一致（打包时被并发修改？）")
    if not acceptance_bytes_match:
        consistency_problems.append("包内 ACCEPTANCE 与磁盘不一致（打包时被并发修改？）")
    if verdict == "MISSING":
        consistency_problems.append("包内 ACCEPTANCE 缺少 VERDICT 行")
    if verdict_count > 1:
        consistency_problems.append(f"包内 ACCEPTANCE 出现 {verdict_count} 个 VERDICT 行（必须唯一）")
    if placeholder and verdict == "PASS":
        consistency_problems.append(
            "stage10 第 4/5 节仍占位，但 ACCEPTANCE VERDICT=PASS（应至少 PARTIAL）"
        )

    print(f"SECOND_OPEN_STAGE10_MATCH={'YES' if stage10_bytes_match else 'NO'}")
    print(f"SECOND_OPEN_ACCEPTANCE_MATCH={'YES' if acceptance_bytes_match else 'NO'}")
    print(f"ACCEPTANCE_VERDICT={verdict}（VERDICT 行数={verdict_count}）")
    print(f"STAGE10_PLACEHOLDER={'YES' if placeholder else 'NO'}")
    print(f"SECOND_OPEN_CHECK={'PASS' if not consistency_problems else 'FAIL'}")
    for problem in consistency_problems:
        print(f"  CONSISTENCY_PROBLEM {problem}")
    print(f"ENV_IN_ZIP={'YES' if (PREFIX + 'backend/.env') in names else 'NO'}")
    print(f"DB_IN_ZIP={sum(1 for name in names if name.endswith('.db'))}")

    ok = (
        sensitive_hits == []
        and key_ok
        and dist_ok
        and packed_files > 0
        and (PREFIX + "backend/.env") not in names
        and not consistency_problems
    )
    print("-" * 72)
    print(f"结论：{'PASS' if ok else 'FAIL'}")
    print("=" * 72)
    return 0 if ok else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T5 交付包重打与包内自检")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="工程根目录（默认 tests/security 上两级）",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="输出 zip 路径（默认：工程根上一级 / campus-task-agent-delivery.zip）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    out_path = Path(args.out).resolve() if args.out else (root.parent / "campus-task-agent-delivery.zip")
    return pack(root, out_path)


if __name__ == "__main__":
    raise SystemExit(main())