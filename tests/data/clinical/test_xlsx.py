import zipfile

import pytest

from hachi.data.clinical.xlsx import WorkbookError, read_sheet, sheet_names

from .conftest import write_xlsx


def test_reads_cells_by_reference(tmp_path):
    path = write_xlsx(tmp_path / "w.xlsx", {"A": [["x", None, 3], [], [None, "y & z"]]})
    assert sheet_names(path) == ["A"]
    assert read_sheet(path, "A") == [["x", None, "3"], [], [None, "y & z"]]


def test_refuses_document_types_and_unknown_sheets(tmp_path):
    bomb = write_xlsx(tmp_path / "b.xlsx", {"A": [["x"]]}, extra='<!DOCTYPE x [<!ENTITY a "a">]>')
    with pytest.raises(WorkbookError, match="document type"):
        read_sheet(bomb, "A")
    with pytest.raises(WorkbookError, match="no sheet"):
        read_sheet(write_xlsx(tmp_path / "c.xlsx", {"A": [["x"]]}), "B")


def test_refuses_sheet_targets_outside_worksheets(tmp_path):
    path = tmp_path / "d.xlsx"
    write_xlsx(path, {"A": [["x"]]})
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        b"worksheets/sheet1.xml", b"../../etc/passwd"
    )
    with zipfile.ZipFile(path, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    with pytest.raises(WorkbookError, match="outside the worksheets"):
        read_sheet(path, "A")
