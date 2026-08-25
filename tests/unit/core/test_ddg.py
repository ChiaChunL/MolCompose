import pytest

from src.core.ddg import (
    MutationEffect,
    detect_format,
    parse_pythia,
    parse_tabular,
    summarize_by_residue,
)


def test_tabular_csv_is_parsed_with_common_headers():
    text = "chain,position,wt,mut,ddG\nA,59,R,A,1.85\nA,59,R,K,-0.20\n"
    effects = parse_tabular(text, source="foldx")
    assert len(effects) == 2
    assert effects[0] == MutationEffect("A", 59, "R", "A", 1.85, "foldx")
    assert effects[0].label == "RA59A"


def test_tabular_accepts_tsv_and_alternative_spellings():
    text = "chain_id\tresnum\twild_type\tmutant\tprediction\nB\t12\tG\tD\t-1.5\n"
    (effect,) = parse_tabular(text)
    assert (effect.chain, effect.position, effect.ddg) == ("B", 12, -1.5)


def test_tabular_tolerates_malformed_rows():
    text = "chain,position,wt,mut,ddG\nA,59,R,A,1.85\nA,oops,R,K,x\n"
    assert len(parse_tabular(text)) == 1


def test_tabular_reports_missing_columns():
    with pytest.raises(ValueError, match="missing column"):
        parse_tabular("alpha,beta\n1,2\n")


def test_tabular_rejects_a_file_with_no_usable_rows():
    with pytest.raises(ValueError, match="no usable rows"):
        parse_tabular("chain,position,wt,mut,ddG\n")


def test_pythia_lines_are_mapped_through_the_index_map():
    text = "A1G 0.5\nA1V -1.25\nR2K 2.0\n"
    index_map = {1: ("A", 27), 2: ("A", 59)}
    effects = parse_pythia(text, index_map)
    assert len(effects) == 3
    assert effects[0] == MutationEffect("A", 27, "A", "G", 0.5, "pythia")
    assert effects[2].position == 59


def test_pythia_skips_unmapped_positions():
    effects = parse_pythia("A1G 0.5\nR9K 2.0\n", {1: ("A", 27)})
    assert len(effects) == 1


def test_pythia_explains_a_total_mapping_failure():
    with pytest.raises(ValueError, match="sequential indices"):
        parse_pythia("A1G 0.5\n", {5: ("A", 27)})


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("x.csv", "tabular"),
        ("x.tsv", "tabular"),
        ("1pga_pred_mask.txt", "pythia"),
        ("something.txt", "tabular"),
    ],
)
def test_format_detection_follows_name_and_suffix(name, expected):
    assert detect_format(name) == expected


def test_summary_statistics_and_ordering():
    effects = [
        MutationEffect("A", 59, "R", "A", 2.0),
        MutationEffect("A", 59, "R", "K", -1.0),
        MutationEffect("A", 27, "K", "A", -3.0),
    ]
    minimum = summarize_by_residue(effects, "min")
    assert minimum[0][0] == ("A", 27) and minimum[0][2] == pytest.approx(-3.0)
    assert minimum[1][0] == ("A", 59) and minimum[1][2] == pytest.approx(-1.0)
    assert minimum[1][3] == 2  # two scored substitutions at residue 59

    # `max` sorts most positive first: the question it answers is "which
    # residue tolerates substitution least", so the hot spot must lead. This
    # assertion was reversed until 2026-08-15, which put the most *tolerant*
    # residues at the top of what reads as a hot-spot list.
    maximum = summarize_by_residue(effects, "max")
    assert maximum[0][0] == ("A", 59) and maximum[0][2] == pytest.approx(2.0)
    assert maximum[-1][0] == ("A", 27)

    means = {row[0]: row[2] for row in summarize_by_residue(effects, "mean")}
    assert means[("A", 59)] == pytest.approx(0.5)


def test_unknown_statistic_is_rejected():
    with pytest.raises(ValueError, match="min, max or mean"):
        summarize_by_residue([], "median")


# -- PythiaStudio binding ddG -------------------------------------------------

from src.core.ddg import (  # noqa: E402
    classify_ppi,
    parse_pythia_ppi,
)

CSV_ROWS = [
    {"Mutation": "V_A_3_A", "Chain": "A", "Position": "3", "DDG": "0.0715042"},
    {"Mutation": "H_A_102_I", "Chain": "A", "Position": "102", "DDG": "8.598"},
]
WORKBOOK_ROWS = [
    {
        "Mutant Name": "H_A_102_I", "Wildtype": "H", "Chain": "A", "Position": "102",
        "Mutation": "I", "ΔΔG (kcal/mol)": "8.598", "Effect": "Destabilizing",
    },
]
# PythiaStudio's stability export: no chain, and a different unit.
STABILITY_ROWS = [
    {"Wild Type": "D", "Position": "101", "Mutation": "V", "ΔΔG (P.E.U.)": "-11.667"},
]


def test_reads_the_csv_layout():
    effects = parse_pythia_ppi(CSV_ROWS)
    assert [e.label for e in effects] == ["VA3A", "HA102I"]
    assert effects[1].ddg == pytest.approx(8.598)
    assert effects[1].wild_type == "H" and effects[1].mutant == "I"


def test_reads_the_workbook_layout_identically():
    """The two exports name their columns differently for the same content.

    The CSV's "Mutation" column holds the identifier H_A_102_I; the workbook's
    holds just the substituted residue, I. Reading the identifier first and
    falling back keeps one code path for both.
    """
    (from_book,) = parse_pythia_ppi(WORKBOOK_ROWS)
    from_csv = parse_pythia_ppi(CSV_ROWS)[1]
    assert (from_book.chain, from_book.position) == (from_csv.chain, from_csv.position)
    assert (from_book.wild_type, from_book.mutant) == (from_csv.wild_type, from_csv.mutant)
    assert from_book.ddg == pytest.approx(from_csv.ddg)


def test_a_stability_export_is_refused_not_guessed():
    """Without a chain the predictions cannot be placed on a complex.

    Accepting the file would attribute every prediction to whichever chain came
    first — and it is a different quantity in a different unit besides, so the
    two must never be pooled.
    """
    with pytest.raises(ValueError, match="no Chain column"):
        parse_pythia_ppi(STABILITY_ROWS)


def test_the_refusal_names_the_unit_difference():
    with pytest.raises(ValueError, match="Pythia Energy Units"):
        parse_pythia_ppi(STABILITY_ROWS)


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (8.598, "destabilising"),
        (1.0, "destabilising"),    # threshold is inclusive
        (0.999, "neutral"),
        (0.0715, "neutral"),
        (-0.5, "stabilising"),
        (-2.608, "stabilising"),
    ],
)
def test_effect_labels_follow_the_documented_thresholds(value, label):
    """Positive ddG means reduced binding, per the PythiaStudio documentation.

    Asserted rather than inferred: reading the sign backwards would invert the
    hot-spot ranking while still looking entirely plausible.
    """
    assert classify_ppi(value) == label


def test_detects_the_pythiastudio_csv_by_its_header(tmp_path):
    path = tmp_path / "1BRS.csv"
    path.write_text("Mutation,Chain,Position,DDG\nV_A_3_A,A,3,0.07\n")
    assert detect_format(path) == "pythia-ppi"


def test_a_generic_csv_still_reads_as_tabular(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("chain,position,wt,mut,ddg\nA,3,V,A,0.07\n")
    assert detect_format(path) == "tabular"


def test_malformed_rows_are_skipped_not_fatal():
    rows = [*CSV_ROWS, {"Mutation": "junk", "Chain": "A", "Position": "x", "DDG": "y"}]
    assert len(parse_pythia_ppi(rows)) == 2


def test_restrict_to_keeps_only_the_named_residues():
    """A saturation scan covers every chain; an interface is a handful of them."""
    from src.core.ddg import restrict_to

    effects = [
        MutationEffect("A", 102, "H", "P", 8.6),
        MutationEffect("B", 102, "H", "P", 8.6),   # a second copy in the crystal
        MutationEffect("A", 7, "K", "A", 0.1),     # not at the interface
    ]
    kept = restrict_to(effects, [("A", 102)])
    assert [(e.chain, e.position) for e in kept] == [("A", 102)]


# -- wild-type verification ---------------------------------------------------

from src.core.ddg import (  # noqa: E402
    IDENTITY_THRESHOLD,
    verify_wild_types,
)

BRS_NAMES = {("A", 102): "HIS", ("A", 87): "ARG", ("D", 39): "ASP"}


def test_matching_wild_types_pass():
    effects = [
        MutationEffect("A", 102, "H", "P", 8.6),
        MutationEffect("A", 87, "R", "A", 7.7),
        MutationEffect("D", 39, "D", "A", 7.1),
    ]
    check = verify_wild_types(effects, BRS_NAMES)
    assert (check.matched, check.mismatched) == (3, 0)
    assert check.rate == 1.0


def test_a_file_from_another_structure_is_caught():
    """The failure this exists for, and it is not hypothetical.

    Chain letters coincide across unrelated entries — 1BRS has a chain E and so
    does 1ACB — so a ddG file computed on one complex loaded silently onto the
    other, attributing barstar's predictions to chymotrypsin's catalytic
    residues and reporting them as if they belonged there.
    """
    effects = [
        MutationEffect("A", 102, "E", "P", 8.6),   # structure has HIS
        MutationEffect("A", 87, "K", "A", 7.7),    # structure has ARG
        MutationEffect("D", 39, "G", "A", 7.1),    # structure has ASP
    ]
    check = verify_wild_types(effects, BRS_NAMES)
    assert check.mismatched == 3
    assert check.rate < IDENTITY_THRESHOLD
    assert "file=E structure=HIS" in check.examples[0]


def test_positions_absent_from_the_structure_are_not_mismatches():
    """A saturation scan covers chains the interface does not; that is normal."""
    effects = [MutationEffect("Z", 999, "W", "A", 1.0)]
    check = verify_wild_types(effects, BRS_NAMES)
    assert check.total == 0


def test_non_standard_residues_are_skipped_rather_than_failed():
    effects = [MutationEffect("A", 5, "X", "A", 1.0)]
    check = verify_wild_types(effects, {("A", 5): "MSE"})
    assert check.total == 0


def test_examples_name_distinct_residues():
    """One residue carries ~19 substitutions; the message must not repeat it."""
    effects = [MutationEffect("A", 102, "E", m, 1.0) for m in "ACDFGIKLMN"]
    effects += [MutationEffect("A", 87, "K", m, 1.0) for m in "ACD"]
    check = verify_wild_types(effects, BRS_NAMES)
    assert len(check.examples) == 2
    assert {e.split()[0] for e in check.examples} == {"A:102", "A:87"}
