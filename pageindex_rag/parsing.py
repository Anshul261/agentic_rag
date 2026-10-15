"""Docling-based parsing: any supported file -> DocTree (no LLM involved).

Docling gives us headings, body text, tables and figure crops, but on PDFs it
reports every heading as level 1. We rebuild the hierarchy from section
numbering ("3.2.1." -> depth 3) and nest unnumbered sub-headings under the
last numbered one. Formats with real heading levels (DOCX, HTML, MD) keep them.
"""

from __future__ import annotations

import hashlib
import logging
import multiprocessing as mp
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument, PictureItem, TableItem
from docling_core.types.doc.labels import DocItemLabel

from .models import DocTree, Node

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".png", ".jpg", ".jpeg", ".tiff"}

BODY_LABELS = {
    DocItemLabel.TEXT, DocItemLabel.PARAGRAPH, DocItemLabel.LIST_ITEM, DocItemLabel.FORMULA,
    DocItemLabel.CODE, DocItemLabel.FOOTNOTE, DocItemLabel.REFERENCE,
}
HEADING_LABELS = {DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE}

# "3", "3.2", "3.2.1." followed by a title
_ARABIC = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+\S")
# "IV. METHOD" (IEEE top level) / "B. Dataset" (IEEE second level)
_ROMAN = re.compile(r"^(?=[IVX])(X{0,3})(IX|IV|V?I{0,3})\.\s+\S")
_ALPHA = re.compile(r"^[A-H]\.\s+[A-Z]")
# Appendix numbering: "A Experimental protocol", "A.1 Datasets", "B.2.3 ..."
_APPENDIX = re.compile(r"^[A-H]((?:\.\d{1,2})*)\s+[A-Z]")
# Things Docling sometimes tags as headings that are really captions/labels
_NOT_A_HEADING = re.compile(r"^(table|fig\.?|figure|algorithm)\s*[A-Z]?\d+|\(continued\s*\)", re.I)
_TOP_LEVEL = re.compile(
    r"^(abstract|introduction|conclusions?|references|bibliography|acknowledge?ments?|appendix|"
    r"related work|discussion|keywords|article info|declaration.*|data availability|funding|"
    r"credit authorship.*)\b",
    re.I,
)
# Private-use glyphs some PDF fonts emit for the "fi" ligature: classication
_PUA_LIGATURE = re.compile(r"(?<=[A-Za-z])[-]|[-](?=[a-z])")
_SPACED_CAPS = re.compile(r"^(?:[A-Z] ){2,}[A-Z]$")  # "A B S T R A C T"

MIN_FIGURE_PX = 150  # uncaptioned images smaller than this are logos/icons


def clean(text: str) -> str:
    text = _PUA_LIGATURE.sub("fi", text)
    text = text.replace("­", "")  # soft hyphen
    if _SPACED_CAPS.match(text.strip()):
        text = text.replace(" ", "")
    return re.sub(r"\s+", " ", text).strip()


def file_id(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class DoclingParser:
    """Wraps one DocumentConverter (models load once, reuse across files)."""

    def __init__(self, images_scale: float = 2.0, do_ocr: bool = False):
        pdf_opts = PdfPipelineOptions()
        pdf_opts.do_ocr = do_ocr  # born-digital PDFs have a text layer; OCR only for scans
        pdf_opts.do_table_structure = True
        pdf_opts.generate_picture_images = True  # renders figure regions, incl. vector drawings
        pdf_opts.images_scale = images_scale
        self.converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)}
        )

    def parse(self, path: Path, out_dir: Path) -> DocTree:
        """Convert `path`, write figure PNGs + tree.json under out_dir/<doc_id>/."""
        doc_id = file_id(path)
        doc_dir = out_dir / doc_id
        (doc_dir / "figures").mkdir(parents=True, exist_ok=True)

        result = self.converter.convert(path)
        tree = build_tree(result.document, doc_id=doc_id, filename=path.name, doc_dir=doc_dir)
        (doc_dir / "tree.json").write_text(tree.model_dump_json(indent=2))
        return tree


_worker_parser: DoclingParser | None = None


def _parse_in_worker(path: Path, out_dir: Path) -> DocTree:
    global _worker_parser
    if _worker_parser is None:
        _worker_parser = DoclingParser()
    return _worker_parser.parse(path, out_dir)


class ParserCrashed(RuntimeError):
    pass


class IsolatedParser:
    """Runs Docling in a child process so a native crash (segfault in the
    layout model on some pages) fails one file instead of the whole batch.
    The child is reused across files; models load once per child."""

    def __init__(self, timeout_s: float = 600):
        self.timeout_s = timeout_s
        self._pool: ProcessPoolExecutor | None = None

    def _get_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
        return self._pool

    def parse(self, path: Path, out_dir: Path) -> DocTree:
        try:
            return self._get_pool().submit(_parse_in_worker, path, out_dir).result(timeout=self.timeout_s)
        except BrokenProcessPool as e:
            self._pool = None  # child died; next file gets a fresh one
            raise ParserCrashed("docling worker crashed (native error)") from e

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown()


def _infer_level(title: str, docling_level: int, use_docling_levels: bool, last_numbered: int) -> int:
    if use_docling_levels:
        return max(1, docling_level)
    if m := _ARABIC.match(title):
        return m.group(1).count(".") + 1
    if _ROMAN.match(title):
        return 1
    if _ALPHA.match(title):
        return 2
    if m := _APPENDIX.match(title):
        return m.group(1).count(".") + 1
    if _TOP_LEVEL.match(title):
        return 1
    # Unnumbered heading inside a numbered section ("GraphSage" under 4.1.1)
    return last_numbered + 1 if last_numbered else 1


def build_tree(doc: DoclingDocument, doc_id: str, filename: str, doc_dir: Path) -> DocTree:
    items = list(doc.iterate_items())
    headings = [(it, clean(it.text)) for it, _ in items if it.label in HEADING_LABELS]

    # Running headers (author names, journal title) repeat across pages.
    repeats = {t for t, n in Counter(t for _, t in headings).items() if n > 1}
    # Real heading levels exist only if the source reported more than one level.
    use_docling_levels = len({getattr(it, "level", 1) for it, _ in headings}) > 1

    title = next((t for it, t in headings if it.label == DocItemLabel.TITLE), None)
    if not title:
        title = next((t for it, t in headings if it.prov and it.prov[0].page_no == 1), filename)

    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"{counter:04d}"

    roots: list[Node] = []
    stack: list[Node] = []  # current path from root to the open section
    last_numbered = 0
    fig_n = 0

    def current(page: int) -> Node:
        if not stack:  # content before the first heading
            node = Node(node_id=next_id(), title="Front matter", level=1, page_start=page, page_end=page)
            roots.append(node)
            stack.append(node)
        return stack[-1]

    def attach(node: Node, page: int) -> None:
        parent = current(page)
        parent.children.append(node)
        for open_node in stack:
            open_node.page_end = max(open_node.page_end, page)

    for item, _ in items:
        page = item.prov[0].page_no if item.prov else 1
        label = item.label

        if label in HEADING_LABELS:
            text = clean(item.text)
            if text == title or text in repeats or _NOT_A_HEADING.match(text) or len(text) < 2:
                if _NOT_A_HEADING.match(text) and stack:  # keep "Algorithm 3: ..." as body text
                    stack[-1].text += f"\n{text}"
                continue
            level = _infer_level(text, getattr(item, "level", 1), use_docling_levels, last_numbered)
            numbered = bool(_ARABIC.match(text) or _ROMAN.match(text) or _ALPHA.match(text) or _APPENDIX.match(text))
            if page == 1 and not use_docling_levels and not numbered and not _TOP_LEVEL.match(text):
                # Page-1 unnumbered headings in papers are authors, affiliations, journal names
                current(page).text += ("\n" if stack[-1:] and stack[-1].text else "") + text
                continue
            if numbered:
                last_numbered = level
            elif _TOP_LEVEL.match(text):
                last_numbered = 0
            node = Node(node_id=next_id(), title=text, level=level, page_start=page, page_end=page)
            while stack and stack[-1].level >= level:
                stack.pop()
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)

        elif label in BODY_LABELS:
            text = clean(item.text)
            if text:
                node = current(page)
                node.text += ("\n" if node.text else "") + text
                for open_node in stack:
                    open_node.page_end = max(open_node.page_end, page)

        elif isinstance(item, TableItem):
            caption = clean(item.caption_text(doc))
            table_md = item.export_to_markdown(doc=doc)
            prev = stack[-1].children[-1] if stack and stack[-1].children else None
            if not caption and prev is not None and prev.kind == "table":
                # Uncaptioned table right after a table = continuation across pages
                prev.text += f"\n\n{table_md}"
                prev.page_end = page
                for open_node in stack:
                    open_node.page_end = max(open_node.page_end, page)
                continue
            attach(Node(node_id=next_id(), kind="table", title=caption or f"Table (p{page})",
                        level=99, page_start=page, page_end=page,
                        text=f"{caption}\n\n{table_md}".strip()), page)

        elif isinstance(item, PictureItem):
            caption = clean(item.caption_text(doc))
            image = item.get_image(doc)
            if image is None:
                continue
            if not caption and min(image.size) < MIN_FIGURE_PX:
                continue  # publisher logos, icons
            fig_n += 1
            rel = f"figures/fig_{fig_n:03d}_p{page}.png"
            image.save(doc_dir / rel)
            attach(Node(node_id=next_id(), kind="figure", title=caption or f"Figure (p{page}, no caption)",
                        level=99, page_start=page, page_end=page, text=caption, image_path=rel), page)

    return DocTree(doc_id=doc_id, filename=filename, title=title, n_pages=doc.num_pages(), nodes=roots)
