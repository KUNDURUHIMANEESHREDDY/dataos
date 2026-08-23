"""
Rich document parsers for DataOS (Rule #49).
Parses DOCX, PPTX, and XLSX files into structured metadata without external dependencies.
Uses raw XML parsing for DOCX/PPTX and falls back gracefully if libraries are unavailable.
"""

from __future__ import annotations
import io
import zipfile
import xml.etree.ElementTree as ET
import os
from typing import Dict, Any, List, Optional


class DocxParser:
    """Parses Microsoft Word .docx files into structured metadata."""

    WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
    CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

    @classmethod
    def parse(cls, file_bytes: bytes, filename: str = "document.docx") -> Dict[str, Any]:
        """Parse a DOCX file and return structured metadata."""
        try:
            return cls._parse_docx(file_bytes, filename)
        except Exception as e:
            return {
                "format": "docx",
                "filename": filename,
                "error": str(e),
                "paragraph_count": 0,
                "word_count": 0,
                "sections": [],
                "preview": "",
            }

    @classmethod
    def _parse_docx(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
            doc_xml = z.read("word/document.xml")
            namespaces = {"w": cls.WORD_NS}
            tree = ET.fromstring(doc_xml)

            paragraphs = []
            full_text_parts = []
            for p in tree.iter(f"{{{cls.WORD_NS}}}p"):
                runs = []
                for r in p.iter(f"{{{cls.WORD_NS}}}r"):
                    for t in r.iter(f"{{{cls.WORD_NS}}}t"):
                        if t.text:
                            runs.append(t.text)
                text = "".join(runs).strip()
                if text:
                    paragraphs.append(text)
                    full_text_parts.append(text)

            headings = []
            sections = []
            current_section: Optional[Dict[str, Any]] = None
            for p in tree.iter(f"{{{cls.WORD_NS}}}p"):
                ppr = p.find(f"{{{cls.WORD_NS}}}pPr")
                style = ""
                if ppr is not None:
                    pstyle = ppr.find(f"{{{cls.WORD_NS}}}pStyle")
                    if pstyle is not None:
                        style = pstyle.get(f"{{{cls.WORD_NS}}}val", "")

                runs = []
                for r in p.iter(f"{{{cls.WORD_NS}}}r"):
                    for t in r.iter(f"{{{cls.WORD_NS}}}t"):
                        if t.text:
                            runs.append(t.text)
                text = "".join(runs).strip()

                is_heading = style.lower().startswith("heading") or style.lower().startswith("title")
                if is_heading and text:
                    headings.append(text)
                    current_section = {"heading": text, "style": style, "paragraphs": []}
                    sections.append(current_section)
                elif text and current_section is not None:
                    current_section["paragraphs"].append(text)
                elif text:
                    if not sections:
                        current_section = {"heading": "", "style": "body", "paragraphs": []}
                        sections.append(current_section)
                    current_section["paragraphs"].append(text)

            full_text = " ".join(full_text_parts)
            word_count = len(full_text.split()) if full_text else 0

            # Try to extract hyperlinks
            links = []
            try:
                rels_xml = z.read("word/_rels/document.xml.rels")
                rels_tree = ET.fromstring(rels_xml)
                for rel in rels_tree.iter(f"{{{cls.REL_NS}}}Relationship"):
                    target = rel.get("Target", "")
                    rel_type = rel.get("Type", "")
                    if "hyperlink" in rel_type.lower():
                        links.append(target)
            except (KeyError, ET.ParseError):
                pass

            # Try to count images
            image_count = 0
            try:
                content_types = z.read("[Content_Types].xml")
                ct_tree = ET.fromstring(content_types)
                for override in ct_tree.iter(f"{{{cls.CONTENT_TYPES_NS}}}Override"):
                    ct = override.get("ContentType", "")
                    if "image" in ct.lower():
                        image_count += 1
            except (KeyError, ET.ParseError):
                pass

            return {
                "format": "docx",
                "filename": filename,
                "paragraph_count": len(paragraphs),
                "word_count": word_count,
                "heading_count": len(headings),
                "headings": headings,
                "section_count": len(sections),
                "sections": sections,
                "links": links,
                "image_count": image_count,
                "preview": full_text[:500],
                "character_count": len(full_text),
            }


class PptxParser:
    """Parses Microsoft PowerPoint .pptx files into structured metadata."""

    PPT_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
    REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

    @classmethod
    def parse(cls, file_bytes: bytes, filename: str = "presentation.pptx") -> Dict[str, Any]:
        """Parse a PPTX file and return structured metadata."""
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
                slide_files = sorted([
                    name for name in z.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ])
                if not slide_files:
                    return {
                        "format": "pptx",
                        "filename": filename,
                        "slide_count": 0,
                        "slides": [],
                        "total_word_count": 0,
                        "image_count": 0,
                        "notes_count": 0,
                        "preview": "",
                    }
            return cls._parse_pptx(file_bytes, filename)
        except Exception as e:
            return {
                "format": "pptx",
                "filename": filename,
                "error": str(e),
                "slide_count": 0,
                "slides": [],
                "preview": "",
            }

    @classmethod
    def _parse_pptx(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
            slides = []
            all_text_parts = []
            slide_index = 1

            # Find all slide files
            slide_files = sorted([
                name for name in z.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ])

            for slide_file in slide_files:
                slide_xml = z.read(slide_file)
                tree = ET.fromstring(slide_xml)

                texts = []
                for t in tree.iter():
                    if t.text and t.text.strip():
                        texts.append(t.text.strip())

                slide_text = " ".join(texts)
                all_text_parts.extend(texts)

                # Count shapes
                shape_count = sum(1 for _ in tree.iter(f"{{{cls.PPT_NS}}}sp"))

                slides.append({
                    "slide_number": slide_index,
                    "text_content": slide_text,
                    "word_count": len(slide_text.split()) if slide_text else 0,
                    "shape_count": shape_count,
                    "text_segments": texts[:20],
                })
                slide_index += 1

            # Try to count images
            image_count = 0
            for name in z.namelist():
                if name.startswith("ppt/media/") and any(name.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".emf", ".wmf"]):
                    image_count += 1

            # Try to count notes
            notes_count = 0
            for name in z.namelist():
                if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml"):
                    notes_count += 1

            full_text = " ".join(all_text_parts)
            word_count = len(full_text.split()) if full_text else 0

            return {
                "format": "pptx",
                "filename": filename,
                "slide_count": len(slides),
                "total_word_count": word_count,
                "image_count": image_count,
                "notes_count": notes_count,
                "slides": slides,
                "preview": full_text[:500],
            }


class XlsxParser:
    """Parses Microsoft Excel .xlsx files into structured metadata."""

    SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    @classmethod
    def parse(cls, file_bytes: bytes, filename: str = "spreadsheet.xlsx") -> Dict[str, Any]:
        """Parse an XLSX file using pandas if available, else raw XML."""
        try:
            return cls._parse_with_pandas(file_bytes, filename)
        except Exception:
            try:
                return cls._parse_raw_xml(file_bytes, filename)
            except Exception as e:
                return {
                    "format": "xlsx",
                    "filename": filename,
                    "error": str(e),
                    "sheet_count": 0,
                    "sheets": [],
                    "preview": "",
                }

    @classmethod
    def _parse_with_pandas(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        import pandas as pd
        sheets = []
        all_text_parts = []

        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            columns = list(df.columns)
            dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
            null_counts = {col: int(df[col].isna().sum()) for col in columns}
            unique_counts = {col: int(df[col].nunique()) for col in columns}

            sample_rows = []
            for _, row in df.head(5).iterrows():
                sample_rows.append({col: _safe_value(row[col]) for col in columns})

            text_parts = []
            for col in columns:
                if df[col].dtype == object:
                    text_parts.extend([str(v) for v in df[col].dropna().head(50)])
            all_text_parts.extend(text_parts)

            sheets.append({
                "sheet_name": sheet_name,
                "row_count": len(df),
                "column_count": len(columns),
                "columns": columns,
                "dtypes": dtypes,
                "null_counts": null_counts,
                "unique_counts": unique_counts,
                "sample_rows": sample_rows,
            })

        full_text = " ".join(all_text_parts)
        return {
            "format": "xlsx",
            "filename": filename,
            "sheet_count": len(sheets),
            "sheets": sheets,
            "total_row_count": sum(s["row_count"] for s in sheets),
            "preview": full_text[:500],
        }

    @classmethod
    def _parse_raw_xml(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
            # Parse shared strings
            shared_strings = []
            try:
                ss_xml = z.read("xl/sharedStrings.xml")
                ss_tree = ET.fromstring(ss_xml)
                for si in ss_tree.iter():
                    if si.text:
                        shared_strings.append(si.text)
            except (KeyError, ET.ParseError):
                pass

            # Find all sheet files
            sheets = []
            sheet_files = sorted([
                name for name in z.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            ])

            for sf in sheet_files:
                sheet_xml = z.read(sf)
                tree = ET.fromstring(sheet_xml)
                rows = []
                for row in tree.iter(f"{{{cls.SHEET_NS}}}row"):
                    row_data = []
                    for cell in row:
                        cell_type = cell.get("t", "")
                        cell_value = ""
                        for v in cell:
                            if v.text:
                                cell_value = v.text
                        if cell_type == "s" and cell_value.isdigit():
                            idx = int(cell_value)
                            cell_value = shared_strings[idx] if idx < len(shared_strings) else ""
                        row_data.append(cell_value)
                    if any(c for c in row_data):
                        rows.append(row_data)

                if rows:
                    columns = rows[0] if rows else []
                    data_rows = rows[1:] if len(rows) > 1 else []
                    sheets.append({
                        "sheet_name": sf.split("/")[-1].replace(".xml", ""),
                        "row_count": len(data_rows),
                        "column_count": len(columns),
                        "columns": columns,
                        "sample_rows": [dict(zip(columns, r)) for r in data_rows[:5]],
                    })
                else:
                    sheets.append({
                        "sheet_name": sf.split("/")[-1].replace(".xml", ""),
                        "row_count": 0,
                        "column_count": 0,
                        "columns": [],
                        "sample_rows": [],
                    })

            all_text = " ".join(shared_strings[:100])
            return {
                "format": "xlsx",
                "filename": filename,
                "sheet_count": len(sheets),
                "sheets": sheets,
                "shared_string_count": len(shared_strings),
                "preview": all_text[:500],
            }


def _safe_value(val: Any) -> Any:
    """Convert numpy/pandas types to JSON-safe Python types."""
    try:
        import numpy as np
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        if isinstance(val, np.bool_):
            return bool(val)
    except ImportError:
        pass
    try:
        import pandas as pd
        if pd.isna(val):
            return None
    except ImportError:
        pass
    return val


class RichDocumentExtractorPatched(RichDocumentExtractor if False else object):
    """Placeholder for extending RichDocumentExtractor without circular imports."""


def parse_office_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Universal entry point: routes to the correct parser based on extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".docx":
        return DocxParser.parse(file_bytes, filename)
    elif ext == ".pptx":
        return PptxParser.parse(file_bytes, filename)
    elif ext == ".xlsx":
        return XlsxParser.parse(file_bytes, filename)
    return {"format": ext, "filename": filename, "error": f"Unsupported format: {ext}"}
