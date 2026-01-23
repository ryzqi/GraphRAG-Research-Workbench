import uuid
from io import BytesIO

import httpx
import pytest

from app.core.settings import Settings
from app.models.source_material import SourceMaterial, SourceType
from app.services.parsing import ParseError, parse_material
from app.services.parsing.material_parser import extract_pdf_chunks_from_middle_json


class _FakeStorage:
    def __init__(self, data: bytes):
        self._data = data

    async def ensure_buckets(self) -> None:  # pragma: no cover
        return None

    async def get_bytes(self, _ref) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_parse_text_material_ok() -> None:
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.TEXT,
        title="t",
        uri=None,
        mime_type=None,
        metadata_={"text": "hello"},
    )

    doc = await parse_material(material, settings=Settings())
    assert doc.text == "hello"


@pytest.mark.asyncio
async def test_parse_text_material_empty_fails() -> None:
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.TEXT,
        title="t",
        uri=None,
        mime_type=None,
        metadata_={"text": ""},
    )

    with pytest.raises(ParseError) as exc:
        await parse_material(material, settings=Settings())
    assert exc.value.error_code == "EMPTY_PARSE_RESULT"


@pytest.mark.asyncio
async def test_parse_upload_txt_utf8_and_gb18030_fallback() -> None:
    txt_gb = "中文".encode("gb18030")
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.UPLOAD,
        title="t",
        uri="minio://bucket/aaa/bbb/test.txt",
        mime_type="text/plain",
        metadata_=None,
    )

    doc = await parse_material(material, settings=Settings(), storage=_FakeStorage(txt_gb))
    assert "中文" in doc.text


@pytest.mark.asyncio
async def test_parse_upload_md_keeps_markdown() -> None:
    md = "# Title\n\nBody"
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.UPLOAD,
        title="t",
        uri="minio://bucket/aaa/bbb/test.md",
        mime_type="text/markdown",
        metadata_=None,
    )

    doc = await parse_material(material, settings=Settings(), storage=_FakeStorage(md.encode("utf-8")))
    assert doc.text.strip() == md


@pytest.mark.asyncio
async def test_parse_upload_docx_to_markdown() -> None:
    docx = pytest.importorskip("docx")
    Document = docx.Document  # type: ignore[attr-defined]

    buf = BytesIO()
    d = Document()
    d.add_paragraph("Hello DOCX")
    table = d.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "A"
    table.rows[0].cells[1].text = "B"
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "2"
    d.save(buf)

    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.UPLOAD,
        title="t",
        uri="minio://bucket/aaa/bbb/test.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata_=None,
    )

    doc = await parse_material(material, settings=Settings(), storage=_FakeStorage(buf.getvalue()))
    assert "Hello DOCX" in doc.text
    assert "| A | B |" in doc.text


@pytest.mark.asyncio
async def test_parse_url_to_markdown_with_locator() -> None:
    pytest.importorskip("readability")

    html = """
    <html>
      <head><title>Example Title</title></head>
      <body><article><p>Hello URL</p></article></body>
    </html>
    """.strip()

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        material = SourceMaterial(
            id=uuid.uuid4(),
            kb_id=uuid.uuid4(),
            source_type=SourceType.URL,
            title="t",
            uri="https://example.com/a",
            mime_type=None,
            metadata_=None,
        )

        settings = Settings(ingestion_url_max_bytes=1024 * 1024, ingestion_url_max_redirects=3)
        doc = await parse_material(material, settings=settings, http_client=client)

    assert doc.locator and doc.locator.get("url") == "https://example.com/a"
    assert "Hello URL" in doc.text


@pytest.mark.asyncio
async def test_upload_mime_extension_mismatch_fails() -> None:
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.UPLOAD,
        title="t",
        uri="minio://bucket/aaa/bbb/test.pdf",
        mime_type="text/plain",
        metadata_=None,
    )

    with pytest.raises(ParseError) as exc:
        await parse_material(material, settings=Settings(), storage=_FakeStorage(b"dummy"))
    assert exc.value.error_code == "MIME_EXTENSION_MISMATCH"


@pytest.mark.asyncio
async def test_upload_doc_not_supported() -> None:
    material = SourceMaterial(
        id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        source_type=SourceType.UPLOAD,
        title="t",
        uri="minio://bucket/aaa/bbb/test.doc",
        mime_type="application/msword",
        metadata_=None,
    )

    with pytest.raises(ParseError) as exc:
        await parse_material(material, settings=Settings(), storage=_FakeStorage(b"dummy"))
    assert exc.value.error_code == "DOC_NOT_SUPPORTED"


def test_extract_pdf_chunks_from_middle_json_smoke() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "text",
                        "bbox": [0, 0, 1, 1],
                        "lines": [
                            {"spans": [{"type": "text", "content": "hello "}]},
                            {"spans": [{"type": "text", "content": "world"}]},
                        ],
                    }
                ],
            }
        ]
    }
    chunks = extract_pdf_chunks_from_middle_json(middle)
    assert len(chunks) == 1
    assert chunks[0].text.strip() == "hello world"
    assert chunks[0].locator and chunks[0].locator.get("kind") == "pdf"
