"""A bounded, read-only reader for the cell values of one .xlsx worksheet.

Supplementary workbooks are untrusted downloads. This reads only the workbook, its relationships,
shared strings and the requested sheet; it refuses document type declarations (so no entity
expansion), oversized parts and unexpected compression, and returns raw cell text. Dates stay as
Excel serial numbers for the caller to interpret.
"""

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_PART_BYTES = 256 << 20
MAX_COLUMNS = 16_384


class WorkbookError(ValueError):
    pass


def _part(z: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        info = z.getinfo(name)
    except KeyError as e:
        raise WorkbookError(f"workbook part {name!r} is missing") from e
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise WorkbookError(f"unsupported compression in {name!r}")
    if info.file_size > MAX_PART_BYTES or info.flag_bits & 0x1:
        raise WorkbookError(f"{name!r} is encrypted or too large")
    with z.open(info) as handle:
        raw = handle.read(MAX_PART_BYTES + 1)
    if len(raw) > MAX_PART_BYTES:
        raise WorkbookError(f"{name!r} is larger than its declared size")
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise WorkbookError(f"{name!r} declares a document type")
    return ET.fromstring(raw)


def _column(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    if not 1 <= n <= MAX_COLUMNS:
        raise WorkbookError(f"bad cell reference {ref!r}")
    return n - 1


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        sheets = _part(z, "xl/workbook.xml").find(f"{MAIN}sheets")
        return [s.get("name", "") for s in (sheets if sheets is not None else [])]


def read_sheet(path: Path, sheet: str) -> list[list[str | None]]:
    """Rows of one worksheet as lists of raw cell text (None for an empty cell)."""
    with zipfile.ZipFile(path) as z:
        workbook = _part(z, "xl/workbook.xml")
        rels = _part(z, "xl/_rels/workbook.xml.rels")
        targets = {
            r.get("Id"): r.get("Target", "") for r in rels.iter(f"{PACKAGE_REL}Relationship")
        }
        rid = next(
            (s.get(f"{REL}id") for s in workbook.iter(f"{MAIN}sheet") if s.get("name") == sheet),
            None,
        )
        if rid is None or rid not in targets:
            raise WorkbookError(f"no sheet named {sheet!r}")
        target = targets[rid]
        name = target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        name = posixpath.normpath(name)
        if not name.startswith("xl/worksheets/"):
            raise WorkbookError(f"sheet {sheet!r} points outside the worksheets: {target!r}")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = [
                "".join(t.text or "" for t in si.iter(f"{MAIN}t"))
                for si in _part(z, "xl/sharedStrings.xml").findall(f"{MAIN}si")
            ]
        out: list[list[str | None]] = []
        for row in _part(z, name).iter(f"{MAIN}row"):
            cells: dict[int, str | None] = {}
            for c in row.findall(f"{MAIN}c"):
                kind, v = c.get("t"), c.find(f"{MAIN}v")
                if kind == "inlineStr":
                    value: str | None = "".join(t.text or "" for t in c.iter(f"{MAIN}t"))
                elif v is None or v.text is None:
                    value = None
                elif kind == "s":
                    index = int(v.text)
                    if not 0 <= index < len(shared):
                        raise WorkbookError("shared string index out of range")
                    value = shared[index]
                else:
                    value = v.text
                cells[_column(c.get("r", ""))] = value
            out.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
        return out
