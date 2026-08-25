"""Read the first worksheet of an .xlsx file using only the standard library.

An .xlsx file is a ZIP archive of XML, and both `zipfile` and
`xml.etree.ElementTree` are in the standard library, so supporting the format
costs no dependency. That matters here: `openpyxl` would be the bundle's first
third-party requirement, and the whole distribution argument rests on there not
being one.

Deliberately partial. This reads a rectangular sheet of values and nothing else
— no formulas, styles, dates, merged cells or multiple sheets. It exists to
ingest the tabular exports that prediction services produce, where the file
happens to be .xlsx rather than .csv, and it should not grow beyond that.
"""

import zipfile
from xml.etree import ElementTree

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
FIRST_SHEET = "xl/worksheets/sheet1.xml"
SHARED_STRINGS = "xl/sharedStrings.xml"


def _column_index(reference: str) -> int:
    """`C7` -> 2. Needed because empty cells are simply absent from the XML."""
    letters = "".join(character for character in reference if character.isalpha())
    index = 0
    for character in letters:
        index = index * 26 + (ord(character.upper()) - ord("A") + 1)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if SHARED_STRINGS not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(SHARED_STRINGS))
    return [
        "".join(node.text or "" for node in item.iter(NS + "t"))
        for item in root.findall(NS + "si")
    ]


def read_rows(path) -> list[list[str]]:
    """Every row of the first worksheet, as lists of strings.

    Rows are padded so that column *n* is always at index *n*: a spreadsheet
    omits empty cells entirely, and without padding a blank cell would silently
    shift every later value one column left.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            if FIRST_SHEET not in archive.namelist():
                raise ValueError(
                    f"{path} has no first worksheet at {FIRST_SHEET}; it may not be "
                    "an .xlsx workbook"
                )
            shared = _shared_strings(archive)
            root = ElementTree.fromstring(archive.read(FIRST_SHEET))
    except zipfile.BadZipFile as error:
        raise ValueError(f"{path} is not a readable .xlsx file: {error}") from error
    except ElementTree.ParseError as error:
        raise ValueError(f"{path} contains malformed worksheet XML: {error}") from error

    rows = []
    for row in root.iter(NS + "row"):
        values: list[str] = []
        for cell in row.iter(NS + "c"):
            reference = cell.get("r") or ""
            if reference:
                target = _column_index(reference)
                while len(values) < target:
                    values.append("")
            node = cell.find(NS + "v")
            text = "" if node is None else (node.text or "")
            if cell.get("t") == "s" and text.isdigit():
                # Shared-string table index rather than a literal value.
                index = int(text)
                text = shared[index] if index < len(shared) else ""
            elif cell.get("t") == "inlineStr":
                inline = cell.find(NS + "is")
                text = (
                    "".join(node.text or "" for node in inline.iter(NS + "t"))
                    if inline is not None
                    else ""
                )
            values.append(text)
        rows.append(values)
    return rows


def read_records(path) -> tuple[list[str], list[dict[str, str]]]:
    """(header, rows-as-dicts) from the first worksheet."""
    rows = read_rows(path)
    if not rows:
        raise ValueError(f"{path} contains no rows")
    header = [name.strip() for name in rows[0]]
    records = []
    for values in rows[1:]:
        if not any(value.strip() for value in values):
            continue  # trailing blank row
        padded = list(values) + [""] * (len(header) - len(values))
        records.append(dict(zip(header, padded, strict=False)))
    return header, records
