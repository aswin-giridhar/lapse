"""Loading the document set Lapse reads.

`inbox` is what arrived. `reference` is the filing cabinet -- the instruments
that govern what arrived: plans, leases, contracts, policy bulletins. The
split matters because an incoming document almost never states the window
that governs it; the window lives in the instrument.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CORPUS_ROOT = Path(__file__).resolve().parent.parent / "corpus"


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    kind: str  # "inbox" | "reference"


def _load(directory: Path, kind: str) -> list[Document]:
    if not directory.is_dir():
        return []
    return [
        Document(doc_id=p.name, text=p.read_text(encoding="utf-8"), kind=kind)
        for p in sorted(directory.iterdir())
        if p.is_file() and p.suffix in {".txt", ".md"}
    ]


def load_inbox(root: Path | None = None) -> list[Document]:
    return _load((root or CORPUS_ROOT), "inbox")


def load_reference(root: Path | None = None) -> list[Document]:
    return _load((root or CORPUS_ROOT) / "reference", "reference")


def reference_index(root: Path | None = None) -> dict[str, Document]:
    return {d.doc_id: d for d in load_reference(root)}
