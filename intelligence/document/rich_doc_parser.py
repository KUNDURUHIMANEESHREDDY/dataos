"""
Rich Document & Multi-Modal Structure Extractor for DataOS (Rule #54).
Extracts embedded tables, figures, footnote citations, headings, and tabular matrices
from DOCX, XLSX, PDF, and Markdown files into first-class DataOS objects and relationships.
"""

from __future__ import annotations
import re
import os
import io
import csv
from typing import Dict, Any, List, Optional
import pandas as pd
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend


class RichDocumentExtractor:
    """Extracts structured tables, concepts, figures, and citations from rich documents."""

    @classmethod
    def extract_markdown_tables_and_figures(cls, content: str) -> Dict[str, Any]:
        """Extract Markdown pipe tables, image figure captions, and citations."""
        lines = content.splitlines()
        tables: List[Dict[str, Any]] = []
        figures: List[Dict[str, Any]] = []
        citations: List[Dict[str, str]] = []

        # 1. Extract pipe tables
        table_lines = []
        table_start = 0
        in_table = False

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                if not in_table:
                    in_table = True
                    table_start = line_num
                    table_lines = [stripped]
                else:
                    table_lines.append(stripped)
            else:
                if in_table:
                    if len(table_lines) >= 2:
                        parsed_tbl = cls._parse_pipe_table(table_lines, table_start)
                        if parsed_tbl:
                            tables.append(parsed_tbl)
                    in_table = False
                    table_lines = []

        if in_table and len(table_lines) >= 2:
            parsed_tbl = cls._parse_pipe_table(table_lines, table_start)
            if parsed_tbl:
                tables.append(parsed_tbl)

        # 2. Extract Figures: ![Caption](url_or_path)
        fig_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
        for line_num, line in enumerate(lines, 1):
            for match in fig_pattern.finditer(line):
                figures.append({
                    "caption": match.group(1) or f"Figure at line {line_num}",
                    "path": match.group(2),
                    "line": line_num
                })

        # 3. Extract Footnotes / Citations: [^1]: Citation text or [1] Citation
        footnote_pattern = re.compile(r"^\[\^?([0-9A-Za-z_-]+)\]:\s*(.+)$")
        for line_num, line in enumerate(lines, 1):
            fn_match = footnote_pattern.match(line.strip())
            if fn_match:
                citations.append({
                    "key": fn_match.group(1),
                    "text": fn_match.group(2),
                    "line": line_num
                })

        return {
            "tables": tables,
            "figures": figures,
            "citations": citations,
            "table_count": len(tables),
            "figure_count": len(figures),
            "citation_count": len(citations)
        }

    @classmethod
    def _parse_pipe_table(cls, lines: List[str], start_line: int) -> Optional[Dict[str, Any]]:
        """Parse pipe-separated Markdown table lines into DataFrame / records."""
        try:
            # Header
            header_row = [c.strip() for c in lines[0].strip("|").split("|")]
            # Skip separator row (e.g. |---|---|)
            data_rows = []
            for row_line in lines[1:]:
                if re.match(r"^[\s|:-]+$", row_line):
                    continue
                row_cells = [c.strip() for c in row_line.strip("|").split("|")]
                # Pad or truncate to match header length
                if len(row_cells) < len(header_row):
                    row_cells.extend([""] * (len(header_row) - len(row_cells)))
                data_rows.append(row_cells[:len(header_row)])

            if not data_rows:
                return None

            df = pd.DataFrame(data_rows, columns=header_row)
            return {
                "start_line": start_line,
                "row_count": len(df),
                "column_count": len(header_row),
                "columns": header_row,
                "sample_rows": df.head(10).to_dict(orient="records"),
                "dataframe": df
            }
        except Exception:
            return None

    @classmethod
    def extract_xlsx_sheets(cls, file_bytes_or_path: Any, filename: str = "data.xlsx") -> Dict[str, Any]:
        """Extract multi-sheet tables from XLSX / Spreadsheet files."""
        try:
            excel_file = pd.ExcelFile(file_bytes_or_path)
            sheets_data = []

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                # Replace NaNs for JSON safety
                clean_df = df.where(pd.notnull(df), None)
                sheets_data.append({
                    "sheet_name": sheet_name,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "columns": [str(c) for c in df.columns],
                    "sample_rows": clean_df.head(10).to_dict(orient="records")
                })

            return {
                "format": "xlsx",
                "filename": filename,
                "sheet_count": len(sheets_data),
                "sheets": sheets_data
            }
        except Exception as e:
            return {
                "format": "xlsx",
                "filename": filename,
                "error": str(e),
                "sheet_count": 0,
                "sheets": []
            }

    @classmethod
    def ingest_rich_document_to_graph(
        cls,
        raw_text: str,
        filename: str,
        storage: StorageBackend
    ) -> Dict[str, Any]:
        """
        Ingest a rich document into DataOS:
        1. Create parent Document DataObject
        2. Extract embedded tables -> create first-class Table DataObjects linked via CONTAINS
        3. Extract figures and citations -> create Concept / Evidence DataObjects linked via CITES / REFERENCES
        """
        extracted = cls.extract_markdown_tables_and_figures(raw_text)

        # 1. Parent Document Object
        doc_obj = DataObject(
            type=ObjectType.DOCUMENT.value,
            schema="document.v1",
            properties={
                "filename": filename,
                "title": os.path.splitext(filename)[0],
                "table_count": extracted["table_count"],
                "figure_count": extracted["figure_count"],
                "citation_count": extracted["citation_count"]
            },
            content=raw_text,
            source=f"file://{filename}"
        )
        storage.save_object(doc_obj)

        created_table_ids = []
        # 2. Save extracted tables as first-class dataset/table objects
        for idx, tbl in enumerate(extracted["tables"], 1):
            tbl_name = f"{os.path.splitext(filename)[0]}_table_{idx}"
            tbl_obj = DataObject(
                type=ObjectType.TABLE.value,
                schema="dataset.v1",
                properties={
                    "table_name": tbl_name,
                    "parent_document_id": doc_obj.id,
                    "start_line": tbl["start_line"],
                    "row_count": tbl["row_count"],
                    "column_count": tbl["column_count"],
                    "columns": tbl["columns"],
                    "sample_rows": tbl["sample_rows"]
                },
                content=tbl["sample_rows"],
                source=f"derived://{doc_obj.id}/table/{idx}"
            )
            storage.save_object(tbl_obj)
            created_table_ids.append(tbl_obj.id)

            # Link doc -> contains -> table
            storage.save_relationship(Relationship(
                source=doc_obj.id,
                target=tbl_obj.id,
                relation_type=RelationType.CONTAINS.value,
                confidence=1.0,
                metadata={"embedded_table_index": idx}
            ))

        # 3. Save citations as Evidence/Citation objects
        created_citation_ids = []
        for cit in extracted["citations"]:
            cit_obj = DataObject(
                type=ObjectType.EVIDENCE.value,
                schema="evidence.v1",
                properties={
                    "parent_document_id": doc_obj.id,
                    "citation_key": cit["key"],
                    "line": cit["line"]
                },
                content=cit["text"],
                source=f"derived://{doc_obj.id}/citation/{cit['key']}"
            )
            storage.save_object(cit_obj)
            created_citation_ids.append(cit_obj.id)

            # Link doc -> cites -> citation object
            storage.save_relationship(Relationship(
                source=doc_obj.id,
                target=cit_obj.id,
                relation_type=RelationType.CITES.value,
                confidence=1.0
            ))

        return {
            "document_id": doc_obj.id,
            "filename": filename,
            "tables_extracted_count": len(created_table_ids),
            "citations_extracted_count": len(created_citation_ids),
            "table_object_ids": created_table_ids,
            "citation_object_ids": created_citation_ids
        }
