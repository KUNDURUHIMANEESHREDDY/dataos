"""
Document Intelligence Parser for DataOS (Rule #8, Rule #54).
Parses Markdown, TXT, PDF, DOCX preserving structure, headings,
sections, citations, and hyperlinks.
"""

from __future__ import annotations
import re
import os
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType


class DocumentParser:
    """Extracts hierarchical sections, references, and metadata from documents."""

    @classmethod
    def parse_text_or_markdown(cls, content: str, filename: str, source_path: str = "") -> Dict[str, Any]:
        """Parse plain text or Markdown into sections, headings, links, and citations."""
        lines = content.splitlines()
        headings: List[Dict[str, Any]] = []
        sections: List[Dict[str, Any]] = []
        current_section = {"title": "Introduction", "level": 1, "lines": []}
        
        # Regex patterns
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        citation_pattern = re.compile(r"\[([0-9]+)\]|\(([A-Za-z]+ et al\.,?\s*\d{4})\)")

        links: List[Dict[str, str]] = []
        citations: List[str] = []

        for line_num, line in enumerate(lines, 1):
            h_match = heading_pattern.match(line)
            if h_match:
                # Save previous section
                if current_section["lines"]:
                    current_section["content"] = "\n".join(current_section["lines"])
                    sections.append(current_section)
                level = len(h_match.group(1))
                title = h_match.group(2).strip()
                headings.append({"level": level, "title": title, "line": line_num})
                current_section = {"title": title, "level": level, "lines": [], "start_line": line_num}
            else:
                current_section["lines"].append(line)

            # Match links
            for match in link_pattern.finditer(line):
                links.append({"text": match.group(1), "url": match.group(2), "line": line_num})

            # Match citations
            for match in citation_pattern.finditer(line):
                cit = match.group(1) or match.group(2)
                if cit:
                    citations.append(cit)

        if current_section["lines"]:
            current_section["content"] = "\n".join(current_section["lines"])
            sections.append(current_section)

        # Word count & entities
        words = content.split()
        
        return {
            "format": "markdown" if filename.endswith((".md", ".markdown")) else "text",
            "title": headings[0]["title"] if headings else os.path.splitext(filename)[0],
            "total_lines": len(lines),
            "word_count": len(words),
            "headings": headings,
            "sections": sections,
            "links": links,
            "citations": list(set(citations)),
            "preview": content[:500] if len(content) > 500 else content
        }

    @classmethod
    def parse_pdf_fallback(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Simple text extractor for PDF headers and text content without binary crash."""
        # Extract ASCII strings from PDF stream
        text_chunks = re.findall(rb"[a-zA-Z0-9 .,;:!?'\"\-\(\)\/\n]{4,}", file_bytes)
        decoded_text = "\n".join([chunk.decode("latin-1", errors="ignore") for chunk in text_chunks[:500]])
        
        return {
            "format": "pdf",
            "title": os.path.splitext(filename)[0],
            "total_bytes": len(file_bytes),
            "word_count": len(decoded_text.split()),
            "headings": [{"level": 1, "title": os.path.splitext(filename)[0], "line": 1}],
            "sections": [{"title": "Extracted Content", "level": 1, "content": decoded_text[:2000]}],
            "links": [],
            "citations": [],
            "preview": decoded_text[:500]
        }
