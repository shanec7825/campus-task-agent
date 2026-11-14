#!/usr/bin/env python
"""S3 文档解析服务（`C-DOC-PARSE@1`）与 `org_resources` 表/模型（`C-ORG-LIBRARY@1`）测试。

覆盖：
1. TXT/MD：``utf-8-sig``、``gbk``、``latin-1`` 三级编码兜底、空内容 → failed；
2. DOCX：动态生成的最小 OOXML（zip + ``word/document.xml``）、坏 zip、缺 document.xml；
3. PDF：手写最小内容流（含文本 / 无文本）、损坏文件、扩展名大小写、扩展名不在白名单；
4. 输出规范化：``\\r\\n`` 归一、连续空行压缩、控制字符剔除、截断到 ``MAX_TEXT_CHARS``；
5. 任何输入都不抛异常；
6. ``org_resources`` 建表后的列、两个索引、默认值，以及 ``OrgResourceOut`` 序列化。

隔离性：导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立 SQLite
文件，并设置 ``MAAS_MOCK=1`` / ``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``。
可独立运行：``python -m pytest tests/backend/test_v1_document_parse.py -q``。
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-document-parse-"))
_TEST_DB_PATH = _TMP_DIR / "document_parse.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.models import OrgResource  # noqa: E402
from app.schemas import OrgResourceOut  # noqa: E402
from app.services.document_service import (  # noqa: E402
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
    PARSEABLE_EXTS,
    extract_text,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_bytes(paragraphs: list[str]) -> bytes:
    """生成仅含 ``word/document.xml`` 的最小 DOCX（足以覆盖解析路径）。"""
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    """手写最小 PDF（单页、Helvetica、单条 Tj），``text`` 为空时内容流为空。"""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET" if text else ""
    stream_bytes = stream.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}\nendstream".encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def _pdf_multipage(texts: list[str]) -> bytes:
    """手写多页 PDF：对象 1 目录、2 页树、3 字体，之后每页一对「页面 + 内容流」。"""
    total = len(texts)
    kids = b" ".join(f"{4 + 2 * index} 0 R".encode("ascii") for index in range(total))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(total).encode("ascii") + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(texts):
        stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode("latin-1")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(4 + 2 * index + 1).encode("ascii")
            + b" 0 R >>"
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


# --------------------------------------------------------------------------- #
# 1. 纯文本
# --------------------------------------------------------------------------- #


def test_txt_utf8_bom_ready() -> None:
    raw = "\ufeff迎新策划书正文".encode("utf-8")
    status, text = extract_text("plan.txt", raw)
    assert status == "ready"
    assert text == "迎新策划书正文"


def test_md_ready() -> None:
    status, text = extract_text("notes.md", "# 标题\n\n正文".encode("utf-8"))
    assert status == "ready"
    assert text.startswith("# 标题")


def test_txt_gbk_fallback() -> None:
    raw = "迎新策划 中文正文".encode("gbk")
    status, text = extract_text("gbk.txt", raw)
    assert status == "ready"
    assert "迎新策划" in text


def test_txt_latin1_fallback() -> None:
    # 0x81 0x30 既不是合法 UTF-8 也不是合法 GBK，只能落到 latin-1。
    status, text = extract_text("legacy.txt", bytes([0x81, 0x30]))
    assert status == "ready"
    assert text == "0"


def test_empty_text_failed() -> None:
    assert extract_text("blank.txt", b" \n\t\r\n ") == ("failed", "")


def test_plain_text_normalization() -> None:
    status, text = extract_text("mixed.md", b"a\r\n\r\n\r\nb\x00c\td")
    assert status == "ready"
    assert text == "a\n\nbc\td"


def test_truncated_to_max_chars() -> None:
    status, text = extract_text("long.txt", ("x" * (MAX_TEXT_CHARS + 50)).encode("utf-8"))
    assert status == "ready"
    assert len(text) == MAX_TEXT_CHARS


def test_unsupported_extension_failed() -> None:
    assert extract_text("report.exe", b"whatever") == ("failed", "")
    assert extract_text("noext", b"whatever") == ("failed", "")


def test_parseable_exts_contract() -> None:
    assert PARSEABLE_EXTS == frozenset({".pdf", ".docx", ".txt", ".md"})


# --------------------------------------------------------------------------- #
# 2. DOCX
# --------------------------------------------------------------------------- #


def test_docx_ready() -> None:
    status, text = extract_text("plan.docx", _docx_bytes(["迎新策划书", "第二段"]))
    assert status == "ready"
    assert text.splitlines() == ["迎新策划书", "第二段"]


def test_docx_bad_zip_failed() -> None:
    assert extract_text("broken.docx", b"not a zip archive") == ("failed", "")


def test_docx_missing_document_xml_failed() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/styles.xml", "<styles/>")
    assert extract_text("no-doc.docx", buffer.getvalue()) == ("failed", "")


def test_docx_high_compression_ratio_failed() -> None:
    """zip bomb：小体积压缩包声明超大解压内容（压缩比远超上限）直接 failed。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:document>" + " " * (2 * 1024 * 1024))
    data = buffer.getvalue()
    assert len(data) < 100 * 1024, "测试样本自身应当很小（高压缩比）"
    status, text = extract_text("bomb.docx", data)
    assert (status, text) == ("failed", "")


# --------------------------------------------------------------------------- #
# 3. PDF
# --------------------------------------------------------------------------- #


def test_pdf_ready() -> None:
    status, text = extract_text("plan.pdf", _pdf_bytes("Hello Org Library"))
    assert status == "ready"
    assert "Hello Org Library" in text


def test_pdf_uppercase_extension_ready() -> None:
    status, _ = extract_text("PLAN.PDF", _pdf_bytes("Uppercase"))
    assert status == "ready"


def test_pdf_without_text_failed() -> None:
    assert extract_text("empty.pdf", _pdf_bytes("")) == ("failed", "")


def test_pdf_corrupt_failed() -> None:
    assert extract_text("corrupt.pdf", b"%PDF-1.4\nnot really a pdf") == ("failed", "")


def test_pdf_page_limit_stops_early() -> None:
    """超过页数上限的页面不再解析：第 1~300 页可读，第 301 页起被跳过。"""
    texts = [f"page {index}" for index in range(1, MAX_PDF_PAGES + 6)]
    status, text = extract_text("many-pages.pdf", _pdf_multipage(texts))
    assert status == "ready"
    assert f"page {MAX_PDF_PAGES}" in text
    assert f"page {MAX_PDF_PAGES + 1}" not in text


def test_pdf_char_limit_stops_early() -> None:
    """首段即达到字符上限时立即停止，后续页面不再进入结果。"""
    data = _pdf_multipage(["x" * (MAX_TEXT_CHARS + 1000), "SECOND PAGE"])
    status, text = extract_text("long-pages.pdf", data)
    assert status == "ready"
    assert len(text) == MAX_TEXT_CHARS
    assert "SECOND PAGE" not in text


# --------------------------------------------------------------------------- #
# 4. 永不抛异常
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("filename", sorted(PARSEABLE_EXTS & {".pdf", ".docx", ".txt", ".md"}))
def test_garbage_bytes_never_raise(filename: str) -> None:
    status, text = extract_text(filename, b"\x00\xff\xfe garbage")
    assert status in {"ready", "failed"}
    assert isinstance(text, str)


def test_empty_bytes_never_raise() -> None:
    for filename in ("a.pdf", "a.docx", "a.txt", "a.md", "a.csv"):
        status, text = extract_text(filename, b"")
        assert status in {"ready", "failed"}
        assert isinstance(text, str)


# --------------------------------------------------------------------------- #
# 5. org_resources 表与 schema
# --------------------------------------------------------------------------- #


def test_org_resources_table_columns_and_indexes() -> None:
    init_db()
    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(org_resources)").fetchall()
        }
        indexes = {
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list(org_resources)").fetchall()
        }

    assert {
        "id",
        "org_id",
        "title",
        "summary",
        "resource_type",
        "url",
        "file_name",
        "file_mime",
        "file_size",
        "file_path",
        "content_text",
        "search_text",
        "text_status",
        "allow_student_ai",
        "archived",
        "created_by",
        "created_at",
        "updated_at",
    } <= columns
    assert {"ix_org_resources_org_id", "ix_org_resources_org_allow"} <= indexes


def test_org_resource_defaults_and_out_schema() -> None:
    init_db()
    with SessionLocal() as db:
        row = OrgResource(org_id=3, title="迎新策划书", created_by=7)
        db.add(row)
        db.commit()
        db.refresh(row)

        assert row.resource_type == "file"
        assert row.text_status == "pending"
        assert row.allow_student_ai == 0
        assert row.archived == 0
        assert row.created_at and row.updated_at

        payload = OrgResourceOut.model_validate(row).model_dump()

    assert payload["text_status"] == "pending"
    assert payload["allow_student_ai"] is False
    assert payload["archived"] is False
    # 契约：响应不含正文与落盘路径
    assert "content_text" not in payload
    assert "search_text" not in payload
    assert "file_path" not in payload