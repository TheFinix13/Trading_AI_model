"""Quick & dirty .docx → structured-text dump used while we read your weekly trading log.

Outputs a single Markdown-ish file with:
  - all paragraphs (preserving order),
  - every embedded image extracted to a folder so we can eyeball the charts,
  - tables flattened to TSV,
  - a JSON sidecar of {paragraph_index, text, style} for later ingestion.

Usage:
    python scripts/extract_docx.py --input "/abs/path/file.docx" --out-dir tmp/weekly_log
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from docx import Document
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


def iter_block_items(parent):
    """Yield paragraphs and tables in document order (python-docx doesn't expose this directly)."""
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError("unsupported parent")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def extract(input_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    doc = Document(str(input_path))

    md_lines: list[str] = []
    para_records: list[dict] = []
    table_records: list[list[list[str]]] = []

    md_lines.append(f"# Source: {input_path.name}\n")

    block_idx = 0
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            style = block.style.name if block.style else "Normal"
            para_records.append({"index": block_idx, "style": style, "text": text})
            if not text:
                md_lines.append("")
            elif style.startswith("Heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                md_lines.append(f"{'#' * (int(level) + 1)} {text}")
            else:
                md_lines.append(text)
            block_idx += 1
        elif isinstance(block, Table):
            rows = []
            for row in block.rows:
                rows.append([cell.text.strip() for cell in row.cells])
            table_records.append(rows)
            md_lines.append("")
            md_lines.append(f"_[table {len(table_records)}]_")
            for r in rows:
                md_lines.append(" | ".join(r))
            md_lines.append("")
            block_idx += 1

    # Extract images from the package's relationships.
    image_records = []
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            target = rel.target_ref
            blob = rel.target_part.blob
            ext = Path(target).suffix or ".png"
            name = f"image_{len(image_records) + 1:03d}{ext}"
            (images_dir / name).write_bytes(blob)
            image_records.append({"name": name, "size_bytes": len(blob), "rel_target": target})

    md_lines.append("")
    md_lines.append("---")
    md_lines.append(f"## Embedded images ({len(image_records)})")
    for img in image_records:
        md_lines.append(f"- {img['name']} ({img['size_bytes']} bytes)")

    (out_dir / "doc.md").write_text("\n".join(md_lines), encoding="utf-8")
    (out_dir / "paragraphs.json").write_text(
        json.dumps(para_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "tables.json").write_text(
        json.dumps(table_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "images.json").write_text(
        json.dumps(image_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "paragraphs": len(para_records),
        "tables": len(table_records),
        "images": len(image_records),
        "out_dir": str(out_dir),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    summary = extract(Path(args.input), Path(args.out_dir))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
