"""Keep the public manuscript case complete and consistent with its manifests."""

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).parents[2]
CASE = ROOT / "examples" / "data" / "derf7-binder2"


def test_case_checksum_inventory_is_complete_and_consistent():
    entries = {}
    for line in (CASE / "SHA256SUMS.txt").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = CASE / relative
        assert path.resolve().is_relative_to(CASE.resolve()), relative
        assert path.is_file(), relative
        assert relative not in entries, relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
        entries[relative] = expected

    assert len(entries) == 104
    actual = {
        path.relative_to(CASE).as_posix()
        for path in CASE.rglob("*")
        if path.is_file()
        and path.relative_to(CASE).parts[0] != "outputs"
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    }
    assert actual == set(entries) | {"SHA256SUMS.txt"}


def test_case_manifest_matches_file_sizes_and_hashes():
    with (CASE / "manifest.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert rows
    for row in rows:
        path = CASE / row["path"]
        assert path.resolve().is_relative_to(CASE.resolve()), row["path"]
        assert path.is_file(), row["path"]
        data = path.read_bytes()
        assert len(data) == int(row["bytes"]), row["path"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]


def test_case_has_structures_numerical_data_and_replay_instructions():
    for relative in (
        "inputs/DerF7_b2.pdb", "inputs/9HAE.cif",
        "inputs/derf7_binder2_template_free_model.cif",
        "inputs/derf7_binder2_template_free_confidences.json",
        "source_data/Table_S1_with_mutations.tsv",
        "source_data/pythia_ppi_all_mutations.csv",
        "source_data/source_energy_R1_GB_PB.tsv",
        "source_data/source_S1A_R1_rmsf.tsv",
        "md/config/mmpbsa.in", "md/README.md",
        "recipes/reproduce_analysis.py", "recipes/render_structure_panels.py",
        "NOTICE.md", "AF3_OUTPUT_TERMS_OF_USE.md", "AF3_LEGALLY_BINDING_TERMS.txt",
    ):
        assert (CASE / relative).is_file(), relative

    guide = (ROOT / "examples/README.md").read_text()
    for name in ("reproduce_analysis.py", "render_structure_panels.py", "SHA256SUMS.txt"):
        assert name in guide
    assert "examples/data/derf7-binder2/README.md" in (ROOT / "README.md").read_text()
    assert "examples/data/derf7-binder2/outputs/" in (ROOT / ".gitignore").read_text()
