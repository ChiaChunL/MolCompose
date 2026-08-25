"""The four parts a characterised complex divides into, as named selections.

An interface analysis produces four groups of residues, and every question
asked afterwards is asked of one of them: colour this one, select that one,
report on the other. Until now they existed only as atomspecs rebuilt from
scratch at each call site — long ones, since an interface is a scattered list
of residue numbers.

Naming them in ChimeraX turns each into a word. `color mc1_ifaceA #B72621` is
a command a person can read, retype and reason about, and it is what lands in
the recipe instead of a hundred-character residue list.

Names are qualified by model id because ChimeraX names are session-global
while the things they point at belong to one structure. DockQ needs two
structures open at once, so an unqualified `ifaceA` would silently mean
whichever was characterised last.
"""

from dataclasses import dataclass

PREFIX = "mc"

# Order matters: the panel lists them this way, and it reads as a decomposition
# — first each side entire, then the part of each side that touches the other.
KINDS = ("groupA", "groupB", "ifaceA", "ifaceB")

LABELS = {
    "groupA": "Group A chains",
    "groupB": "Group B chains",
    "ifaceA": "Interface on A",
    "ifaceB": "Interface on B",
}


@dataclass(frozen=True)
class Block:
    """One of the four parts, with the name ChimeraX knows it by."""

    kind: str
    name: str
    spec: str
    residue_count: int

    @property
    def label(self) -> str:
        return LABELS[self.kind]


def block_name(model_id: str, kind: str) -> str:
    """`mc1_ifaceA` for model #1.

    ChimeraX names must be identifiers, so the model's `#` is dropped and its
    number becomes part of the stem. A model id can contain dots for submodels
    (`#1.2`), which become underscores.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown block: {kind}; expected one of {', '.join(KINDS)}")
    stem = model_id.lstrip("#").replace(".", "_")
    return f"{PREFIX}{stem}_{kind}"


def define_commands(model_id: str, specs: dict[str, str]) -> tuple[str, ...]:
    """`name` commands defining whichever of the four have a spec.

    A block with no residues is skipped rather than defined empty: ChimeraX
    would reject the empty spec, and a name that resolves to nothing is worse
    than a name that does not exist.
    """
    commands = []
    for kind in KINDS:
        spec = specs.get(kind)
        if spec:
            commands.append(f"name {block_name(model_id, kind)} {spec}")
    return tuple(commands)


def clear_commands(model_id: str) -> tuple[str, ...]:
    """Remove this model's four names.

    Issued before redefining and when the structure goes away. Without it a
    name outlives the interface it described: re-detect at a different cutoff
    and `mc1_ifaceA` still points at the old residue list, which is the same
    class of staleness as a cached analysis outliving its model.
    """
    return tuple(f"name delete {block_name(model_id, kind)}" for kind in KINDS)
