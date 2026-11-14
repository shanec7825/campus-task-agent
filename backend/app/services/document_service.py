"""文档正文解析（契约 `C-DOC-PARSE@1`）。

纯函数：不写 DB、不落盘、不依赖请求上下文。上传层在同一事务内调用
:func:`extract_text`，解析失败只把 ``text_status`` 标记为 ``failed``，不阻断上传。

支持 ``.pdf`` / ``.docx`` / ``.txt`` / ``.md``：

* PDF 走可选依赖 ``pypdf``；缺失或文件损坏都降级为 ``failed``；
* DOCX 只用标准库 ``zipfile`` + ``xml.etree.ElementTree``；
* TXT/MD 依次尝试 ``utf-8-sig`` → ``gbk`` → ``latin-1``（后者恒可解码，作为兜底）。

资源上限（防止 zip bomb / 超大 PDF 拖垮进程）：DOCX 的 ``word/document.xml`` 解压后
≤ 40MB 且压缩比 ≤ 200；PDF 最多读取 300 页、正文累计到 :data:`MAX_TEXT_CHARS` 即停止。
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

PARSEABLE_EXTS = frozenset({".pdf", ".docx", ".txt", ".md"})
MAX_TEXT_CHARS = 200_000
MAX_PDF_PAGES = 300
MAX_DOCX_XML_BYTES = 40 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 200

_READ_CHUNK_BYTES = 64 * 1024

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# 保留 \n 与 \t，其余 C0/C1 控制字符与 DEL 剔除
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BLANK_LINES = re.compile(r"\n{3,}")


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """返回 ``(text_status, text)``；status ∈ ``{"ready", "failed"}``；永不抛异常。"""
    ext = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    if ext not in PARSEABLE_EXTS:
        return ("failed", "")

    try:
        if ext == ".pdf":
            raw = _pdf_text(data)
        elif ext == ".docx":
            raw = _docx_text(data)
        else:
            raw = _plain_text(data)
        text = normalize_text(raw)
    except Exception:  # noqa: BLE001 - 契约要求任何解析异常都降级为 failed
        logger.warning("文档解析失败：filename=%s", filename, exc_info=True)
        return ("failed", "")

    if not text.strip():
        return ("failed", "")
    return ("ready", text)


def normalize_text(raw: str) -> str:
    """把抽取到的正文规范化为检索/展示共用的文本（`C-DOC-PARSE@1` 输出规则）。"""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text[:MAX_TEXT_CHARS]


def _pdf_text(data: bytes) -> str:
    # 延迟导入：pypdf 是可降级依赖，缺失时由外层捕获 ImportError 并标记 failed。
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    total = 0
    # 逐页读取并累计：页数与字符数都设上限，避免超长 PDF 先拼完整字符串再截断。
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            break
        piece = page.extract_text() or ""
        if not piece:
            continue
        remaining = MAX_TEXT_CHARS - total
        if remaining <= 0:
            break
        parts.append(piece[:remaining])
        total += len(parts[-1])
        if total >= MAX_TEXT_CHARS:
            break
    return "\n\n".join(parts)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("word/document.xml")
        ratio = _compression_ratio(info)
        if info.file_size > MAX_DOCX_XML_BYTES or ratio > MAX_DOCX_COMPRESSION_RATIO:
            raise ValueError(
                f"word/document.xml 超出解析上限：{info.file_size} 字节，压缩比 {ratio:.1f}"
            )
        with archive.open(info) as stream:
            xml = _read_limited(stream, MAX_DOCX_XML_BYTES)
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{{{_W_NS}}}p"):
        runs = [node.text or "" for node in paragraph.iter(f"{{{_W_NS}}}t")]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def _compression_ratio(info: zipfile.ZipInfo) -> float:
    """解压后 / 压缩后大小之比；空条目视为 1，无压缩数据但声明有内容视为无穷大。"""
    if info.file_size <= 0:
        return 1.0
    if info.compress_size <= 0:
        return float("inf")
    return info.file_size / info.compress_size


def _read_limited(stream: BinaryIO, limit: int) -> bytes:
    """分块读取并累计上限：即便 ZIP 头声明的 ``file_size`` 不可信也不会无限膨胀。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError("word/document.xml 解压后超过上限")
        chunks.append(chunk)
    return b"".join(chunks)


def _plain_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""  # pragma: no cover - latin-1 不接受空以外的失败


__all__ = [
    "MAX_DOCX_COMPRESSION_RATIO",
    "MAX_DOCX_XML_BYTES",
    "MAX_PDF_PAGES",
    "MAX_TEXT_CHARS",
    "PARSEABLE_EXTS",
    "extract_text",
    "normalize_text",
]