"""The standard-library .xlsx reader.

Written against a workbook built here rather than a fixture, so the tests state
the format's awkward parts explicitly: absent cells, shared strings, and inline
strings. Real exports use whichever the producing tool happens to emit.
"""

import zipfile

import pytest

from src.core.xlsx import read_records, read_rows

SHEET_HEADER = (
    '<?xml version="1.0"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheetData>"
)
SHEET_FOOTER = "</sheetData></worksheet>"


def write_workbook(path, sheet_xml: str, shared: str | None = None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", SHEET_HEADER + sheet_xml + SHEET_FOOTER)
        if shared is not None:
            archive.writestr("xl/sharedStrings.xml", shared)
    return path


def test_reads_inline_typed_values(tmp_path):
    path = write_workbook(
        tmp_path / "book.xlsx",
        '<row r="1"><c r="A1" t="str"><v>Chain</v></c><c r="B1" t="str"><v>DDG</v></c></row>'
        '<row r="2"><c r="A2" t="str"><v>A</v></c><c r="B2"><v>1.5</v></c></row>',
    )
    assert read_rows(path) == [["Chain", "DDG"], ["A", "1.5"]]


def test_absent_cells_do_not_shift_later_columns(tmp_path):
    """A blank cell is simply missing from the XML.

    Without padding by the cell reference, `C2` would land at index 1 and every
    value after a gap would be attributed to the wrong column — which for a ΔΔG
    table means reading a position as a score.
    """
    path = write_workbook(
        tmp_path / "gap.xlsx",
        '<row r="1"><c r="A1" t="str"><v>a</v></c><c r="B1" t="str"><v>b</v></c>'
        '<c r="C1" t="str"><v>c</v></c></row>'
        '<row r="2"><c r="A2" t="str"><v>1</v></c><c r="C2" t="str"><v>3</v></c></row>',
    )
    assert read_rows(path) == [["a", "b", "c"], ["1", "", "3"]]


def test_shared_strings_are_resolved(tmp_path):
    path = write_workbook(
        tmp_path / "shared.xlsx",
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>',
        shared=(
            '<?xml version="1.0"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>Chain</t></si><si><t>Position</t></si></sst>"
        ),
    )
    assert read_rows(path) == [["Chain", "Position"]]


def test_columns_beyond_z_are_indexed_correctly(tmp_path):
    path = write_workbook(
        tmp_path / "wide.xlsx",
        '<row r="1"><c r="A1" t="str"><v>first</v></c>'
        '<c r="AA1" t="str"><v>twenty-seventh</v></c></row>',
    )
    row = read_rows(path)[0]
    assert row[0] == "first"
    assert row[26] == "twenty-seventh"


def test_records_pair_header_with_values(tmp_path):
    path = write_workbook(
        tmp_path / "rec.xlsx",
        '<row r="1"><c r="A1" t="str"><v>Chain</v></c><c r="B1" t="str"><v>DDG</v></c></row>'
        '<row r="2"><c r="A2" t="str"><v>A</v></c><c r="B2"><v>1.5</v></c></row>'
        '<row r="3"><c r="A3" t="str"><v></v></c></row>',
    )
    header, records = read_records(path)
    assert header == ["Chain", "DDG"]
    assert records == [{"Chain": "A", "DDG": "1.5"}]  # blank trailing row dropped


def test_a_non_workbook_fails_with_a_readable_message(tmp_path):
    path = tmp_path / "not.xlsx"
    path.write_text("Mutation,Chain\nV_A_3_A,A\n")
    with pytest.raises(ValueError, match="not a readable .xlsx file"):
        read_rows(path)


def test_a_zip_without_a_worksheet_is_reported(tmp_path):
    path = tmp_path / "empty.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("docProps/core.xml", "<x/>")
    with pytest.raises(ValueError, match="no first worksheet"):
        read_rows(path)
