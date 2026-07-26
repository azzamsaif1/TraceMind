"""First-class ChangeSet / ChangeOperation domain (spec sections 10-11, 13).

A recall is never modelled as only ``old_file`` -> ``new_file``. A change is a
structured :class:`ChangeSet` of typed :class:`ChangeOperation` objects. Each
operation type propagates through a specific subset of dependency edge types
(spec section 13) — that mapping is executable dependency knowledge used by the
:mod:`rusted_recall.propagation` engine, not marketing text.

``propose_changeset`` performs *automatic change understanding* (spec section
11) by diffing two source-of-truth versions and emitting a proposed ChangeSet
with per-operation confidence. Computer vision is never presented as perfect:
inferred operations carry a confidence < 1.0 and are flagged for user
confirmation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field

from rusted_recall import evidence as ev

# --- operation types (spec section 10) -----------------------------------
OP_REPLACE_TEXT = "replace_text"
OP_REMOVE_TEXT = "remove_text"
OP_ADD_TEXT = "add_text"
OP_REPLACE_VISUAL = "replace_visual_reference"
OP_REPLACE_LOGO = "replace_logo"
OP_COLOR_CHANGE = "color_change"
OP_PACKAGE_GEOMETRY = "package_geometry_change"
OP_PRICE_CHANGE = "price_change"
OP_CLAIM_WITHDRAWAL = "claim_withdrawal"
OP_PERSON_REMOVAL = "person_removal"
OP_VOICE_EXPIRY = "voice_expiry"
OP_PRODUCT_RETIREMENT = "product_retirement"
OP_REGION_CHANGE = "region_applicability_change"

ALL_OPERATION_TYPES = frozenset(
    {
        OP_REPLACE_TEXT,
        OP_REMOVE_TEXT,
        OP_ADD_TEXT,
        OP_REPLACE_VISUAL,
        OP_REPLACE_LOGO,
        OP_COLOR_CHANGE,
        OP_PACKAGE_GEOMETRY,
        OP_PRICE_CHANGE,
        OP_CLAIM_WITHDRAWAL,
        OP_PERSON_REMOVAL,
        OP_VOICE_EXPIRY,
        OP_PRODUCT_RETIREMENT,
        OP_REGION_CHANGE,
    }
)

# Operations that touch visible imagery and therefore require generative repair
# rather than a deterministic text overlay.
_VISUAL_OPERATIONS = frozenset(
    {
        OP_REPLACE_VISUAL,
        OP_REPLACE_LOGO,
        OP_COLOR_CHANGE,
        OP_PACKAGE_GEOMETRY,
        OP_PERSON_REMOVAL,
    }
)

# Which dependency edge types each operation type propagates through
# (spec section 13 "dependency semantics"). An empty set means "does not
# propagate structurally" and must rely on direct/explicit dependency only.
PROPAGATION_MAP: dict[str, frozenset[str]] = {
    OP_REPLACE_TEXT: frozenset(
        {ev.EDGE_EXPLICIT, ev.EDGE_OCR_TEXT, ev.EDGE_SEMANTIC, ev.EDGE_PARENT_CHILD}
    ),
    OP_REMOVE_TEXT: frozenset({ev.EDGE_EXPLICIT, ev.EDGE_OCR_TEXT, ev.EDGE_PARENT_CHILD}),
    OP_ADD_TEXT: frozenset({ev.EDGE_EXPLICIT, ev.EDGE_OCR_TEXT, ev.EDGE_PARENT_CHILD}),
    OP_REPLACE_VISUAL: frozenset(
        {
            ev.EDGE_EXPLICIT,
            ev.EDGE_MANIFEST,
            ev.EDGE_PHASH_DERIVATIVE,
            ev.EDGE_VISUAL,
            ev.EDGE_PARENT_CHILD,
            ev.EDGE_SHA256_DUPLICATE,
        }
    ),
    OP_REPLACE_LOGO: frozenset(
        {ev.EDGE_EXPLICIT, ev.EDGE_VISUAL, ev.EDGE_PHASH_DERIVATIVE, ev.EDGE_PARENT_CHILD}
    ),
    OP_COLOR_CHANGE: frozenset({ev.EDGE_EXPLICIT, ev.EDGE_VISUAL, ev.EDGE_PARENT_CHILD}),
    OP_PACKAGE_GEOMETRY: frozenset(
        {ev.EDGE_EXPLICIT, ev.EDGE_VISUAL, ev.EDGE_PHASH_DERIVATIVE, ev.EDGE_PARENT_CHILD}
    ),
    OP_PRICE_CHANGE: frozenset({ev.EDGE_EXPLICIT, ev.EDGE_OCR_TEXT, ev.EDGE_PARENT_CHILD}),
    OP_CLAIM_WITHDRAWAL: frozenset(
        {ev.EDGE_EXPLICIT, ev.EDGE_OCR_TEXT, ev.EDGE_SEMANTIC, ev.EDGE_PARENT_CHILD}
    ),
    OP_PERSON_REMOVAL: frozenset(
        {ev.EDGE_EXPLICIT, ev.EDGE_VISUAL, ev.EDGE_PHASH_DERIVATIVE, ev.EDGE_PARENT_CHILD}
    ),
    OP_VOICE_EXPIRY: frozenset({ev.EDGE_EXPLICIT}),
    OP_PRODUCT_RETIREMENT: frozenset(
        {
            ev.EDGE_EXPLICIT,
            ev.EDGE_MANIFEST,
            ev.EDGE_VISUAL,
            ev.EDGE_OCR_TEXT,
            ev.EDGE_SEMANTIC,
            ev.EDGE_PARENT_CHILD,
            ev.EDGE_PHASH_DERIVATIVE,
            ev.EDGE_SHA256_DUPLICATE,
        }
    ),
    OP_REGION_CHANGE: frozenset({ev.EDGE_EXPLICIT}),
}


@dataclass
class ChangeOperation:
    """A single typed change within a :class:`ChangeSet`."""

    type: str
    field: str = ""
    old: str = ""
    new: str = ""
    confidence: float = 1.0
    inferred: bool = False
    human_confirmed: bool = False
    detail: dict = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in ALL_OPERATION_TYPES:
            raise ValueError(f"unknown change operation type: {self.type!r}")
        self.confidence = max(0.0, min(1.0, self.confidence))

    @property
    def requires_generative_repair(self) -> bool:
        return self.type in _VISUAL_OPERATIONS

    def propagates_through(self, edge_type: str) -> bool:
        return edge_type in PROPAGATION_MAP.get(self.type, frozenset())

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChangeSet:
    """Formal representation of what changed (spec section 10)."""

    entity_type: str
    previous_version: str
    new_version: str
    operations: list[ChangeOperation] = dc_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.operations

    @property
    def requires_generative_repair(self) -> bool:
        return any(op.requires_generative_repair for op in self.operations)

    def propagating_edge_types(self) -> set[str]:
        """Union of edge types any operation propagates through."""
        edges: set[str] = set()
        for op in self.operations:
            edges |= PROPAGATION_MAP.get(op.type, frozenset())
        return edges

    def edge_type_propagates(self, edge_type: str) -> bool:
        return any(op.propagates_through(edge_type) for op in self.operations)

    def summary(self) -> str:
        parts = []
        for op in self.operations:
            if op.type == OP_REPLACE_TEXT and (op.old or op.new):
                parts.append(f"claim '{op.old}' -> '{op.new}'")
            else:
                parts.append(op.type.replace("_", " "))
        return "; ".join(parts) or "no operations"

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "previous_version": self.previous_version,
            "new_version": self.new_version,
            "operations": [op.as_dict() for op in self.operations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChangeSet:
        return cls(
            entity_type=data.get("entity_type", ""),
            previous_version=data.get("previous_version", ""),
            new_version=data.get("new_version", ""),
            operations=[
                ChangeOperation(
                    type=o["type"],
                    field=o.get("field", ""),
                    old=o.get("old", ""),
                    new=o.get("new", ""),
                    confidence=o.get("confidence", 1.0),
                    inferred=o.get("inferred", False),
                    human_confirmed=o.get("human_confirmed", False),
                    detail=o.get("detail", {}),
                )
                for o in data.get("operations", [])
            ],
        )


def propose_changeset(
    *,
    entity_type: str,
    old_version_id: str,
    new_version_id: str,
    old_label: str,
    new_label: str,
    old_claim: str,
    new_claim: str,
    old_phash: str | None = None,
    new_phash: str | None = None,
) -> ChangeSet:
    """Automatic change understanding (spec section 11).

    Diffs two source-of-truth versions and proposes a ChangeSet. Text changes
    are detected with high confidence (exact string comparison); visual changes
    are *inferred* from perceptual-hash distance and flagged for confirmation.
    """
    operations: list[ChangeOperation] = []

    old_text = (old_claim or old_label or "").strip()
    new_text = (new_claim or new_label or "").strip()
    if old_text != new_text:
        if old_text and new_text:
            operations.append(
                ChangeOperation(
                    type=OP_REPLACE_TEXT,
                    field="front_claim",
                    old=old_text,
                    new=new_text,
                    confidence=1.0,
                )
            )
        elif old_text and not new_text:
            operations.append(
                ChangeOperation(
                    type=OP_CLAIM_WITHDRAWAL, field="front_claim", old=old_text, confidence=1.0
                )
            )
        elif new_text and not old_text:
            operations.append(
                ChangeOperation(
                    type=OP_ADD_TEXT, field="front_claim", new=new_text, confidence=1.0
                )
            )

    if old_phash and new_phash:
        from rusted_recall.hashing import phash_similarity

        sim = phash_similarity(old_phash, new_phash)
        distance = round((1.0 - sim) * 64)
        if distance > 4:
            operations.append(
                ChangeOperation(
                    type=OP_REPLACE_VISUAL,
                    field="package_artwork",
                    confidence=round(min(1.0, distance / 32.0), 4),
                    inferred=True,
                    detail={"phash_distance": distance, "similarity": round(sim, 4)},
                )
            )

    return ChangeSet(
        entity_type=entity_type,
        previous_version=old_version_id,
        new_version=new_version_id,
        operations=operations,
    )
