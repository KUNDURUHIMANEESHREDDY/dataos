"""
Tests for Office Document Parsers (Rule #49).
Validates DOCX, PPTX, XLSX parsing and universal routing.
"""

import unittest
import io
import zipfile
import xml.etree.ElementTree as ET
from intelligence.document.office_parser import DocxParser, PptxParser, XlsxParser, parse_office_document


def _make_docx(paragraphs=None, headings=None):
    """Create minimal DOCX bytes for testing."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body_parts = []
    for text in (paragraphs or []):
        body_parts.append(
            f'<w:p xmlns:w="{ns}"><w:r><w:t>{text}</w:t></w:r></w:p>'
        )
    for h in (headings or []):
        body_parts.append(
            f'<w:p xmlns:w="{ns}"><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            f'<w:r><w:t>{h}</w:t></w:r></w:p>'
        )
    body = "".join(body_parts)
    doc_xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    content_types = f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    content_types += '</Types>'
    rels = f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml)
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("word/_rels/document.xml.rels", rels)
    return buf.getvalue()


def _make_pptx(slides=None):
    """Create minimal PPTX bytes for testing."""
    ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    slide_files = []
    for i, texts in enumerate(slides if slides is not None else [["Hello World"]], 1):
        text_parts = []
        for t in texts:
            text_parts.append(f'<p:sp xmlns:p="{ns}"><p:txBody><a:t xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{t}</a:t></p:txBody></p:sp>')
        slide_xml = f'<?xml version="1.0"?><p:sld xmlns:p="{ns}"><p:cSld><p:spTree>{"".join(text_parts)}</p:spTree></p:cSld></p:sld>'
        slide_files.append((f"ppt/slides/slide{i}.xml", slide_xml))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in slide_files:
            z.writestr(name, content)
    return buf.getvalue()


def _make_xlsx_simple():
    """Create minimal XLSX bytes with shared strings."""
    ss_xml = '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">'
    for s in ["Name", "Age", "Alice", "30"]:
        ss_xml += f'<si><t>{s}</t></si>'
    ss_xml += '</sst>'

    sheet_xml = f'''<?xml version="1.0"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
        <sheetData>
            <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
            <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
        </sheetData>
    </worksheet>'''

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", ss_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


class TestDocxParser(unittest.TestCase):

    def test_parse_basic(self):
        docx_bytes = _make_docx(paragraphs=["Hello world", "Second paragraph"])
        result = DocxParser.parse(docx_bytes, "test.docx")
        self.assertEqual(result["format"], "docx")
        self.assertEqual(result["paragraph_count"], 2)
        self.assertIn("Hello world", result["preview"])

    def test_parse_headings(self):
        docx_bytes = _make_docx(headings=["Chapter 1", "Chapter 2"])
        result = DocxParser.parse(docx_bytes, "doc.docx")
        self.assertEqual(result["heading_count"], 2)
        self.assertIn("Chapter 1", result["headings"])

    def test_parse_word_count(self):
        docx_bytes = _make_docx(paragraphs=["The quick brown fox"])
        result = DocxParser.parse(docx_bytes, "doc.docx")
        self.assertEqual(result["word_count"], 4)

    def test_parse_empty_docx(self):
        docx_bytes = _make_docx()
        result = DocxParser.parse(docx_bytes, "empty.docx")
        self.assertEqual(result["paragraph_count"], 0)
        self.assertEqual(result["word_count"], 0)

    def test_parse_invalid_bytes(self):
        result = DocxParser.parse(b"not a docx", "bad.docx")
        self.assertIn("error", result)

    def test_parse_with_mixed_content(self):
        docx_bytes = _make_docx(paragraphs=["Intro text", "More content"])
        result = DocxParser.parse(docx_bytes, "mixed.docx")
        self.assertGreater(result["section_count"], 0)


class TestPptxParser(unittest.TestCase):

    def test_parse_basic(self):
        pptx_bytes = _make_pptx(slides=[["Hello", "World"]])
        result = PptxParser.parse(pptx_bytes, "test.pptx")
        self.assertEqual(result["format"], "pptx")
        self.assertEqual(result["slide_count"], 1)

    def test_parse_multiple_slides(self):
        pptx_bytes = _make_pptx(slides=[["Slide 1"], ["Slide 2"], ["Slide 3"]])
        result = PptxParser.parse(pptx_bytes, "deck.pptx")
        self.assertEqual(result["slide_count"], 3)

    def test_parse_slide_content(self):
        pptx_bytes = _make_pptx(slides=[["Title text", "Body text"]])
        result = PptxParser.parse(pptx_bytes, "deck.pptx")
        slide = result["slides"][0]
        self.assertIn("Title text", slide["text_content"])

    def test_parse_empty_pptx(self):
        pptx_bytes = _make_pptx(slides=[])
        result = PptxParser.parse(pptx_bytes, "empty.pptx")
        self.assertEqual(result["slide_count"], 0)

    def test_parse_invalid_bytes(self):
        result = PptxParser.parse(b"not a pptx", "bad.pptx")
        self.assertIn("error", result)


class TestXlsxParser(unittest.TestCase):

    def test_parse_raw_xml(self):
        xlsx_bytes = _make_xlsx_simple()
        result = XlsxParser.parse(xlsx_bytes, "data.xlsx")
        self.assertEqual(result["format"], "xlsx")
        self.assertGreaterEqual(result["sheet_count"], 1)

    def test_parse_invalid_bytes(self):
        result = XlsxParser.parse(b"not xlsx", "bad.xlsx")
        self.assertIn("error", result)

    def test_parse_empty_xlsx(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/sharedStrings.xml", '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData></sheetData></worksheet>')
        result = XlsxParser.parse(buf.getvalue(), "empty.xlsx")
        self.assertEqual(result["sheet_count"], 1)


class TestParseOfficeDocument(unittest.TestCase):

    def test_routes_docx(self):
        result = parse_office_document(_make_docx(paragraphs=["test"]), "doc.docx")
        self.assertEqual(result["format"], "docx")

    def test_routes_pptx(self):
        result = parse_office_document(_make_pptx(), "deck.pptx")
        self.assertEqual(result["format"], "pptx")

    def test_routes_xlsx(self):
        result = parse_office_document(_make_xlsx_simple(), "data.xlsx")
        self.assertEqual(result["format"], "xlsx")

    def test_routes_unsupported(self):
        result = parse_office_document(b"data", "file.csv")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
