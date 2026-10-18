"""Colour themes for the popup; the viewer's CSS defines the same two themes."""

from dataclasses import dataclass
from typing import Literal

Theme = Literal["dark", "light"]


@dataclass(frozen=True)
class Palette:
    background: str  # the window and its bars
    field: str  # the query box and the lists
    text: str
    muted: str  # secondary text: other modes, hints, earlier days in notes
    border: str
    selection: str
    selection_text: str
    accent: str  # the splash title underline and its keys
    label: str  # a label already in use (`idea: `), as in the viewer
    warning: str  # a label not used before, which may be a typo
    thumb: str  # scrollbar thumb
    thumb_active: str


PALETTES: dict[Theme, Palette] = {
    "dark": Palette(
        background="#202020",
        field="#2b2b2b",
        text="#e8e8e8",
        muted="#9a9a9a",
        border="#3c3c3c",
        selection="#0b5cad",
        selection_text="#ffffff",
        accent="#4ea1ff",
        label="#5fd38d",
        warning="#e0a84f",
        thumb="#5a5a5a",
        thumb_active="#7a7a7a",
    ),
    "light": Palette(
        background="#f0f0f0",
        field="#ffffff",
        text="#1d1d1f",
        muted="#767676",
        border="#c8c8c8",
        selection="#0078d7",
        selection_text="#ffffff",
        accent="#0067c0",
        label="#1a7f37",
        warning="#9a6700",
        thumb="#b0b0b0",
        thumb_active="#8a8a8a",
    ),
}
