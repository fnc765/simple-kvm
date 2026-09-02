"""Host-side Amical transcript to ASCII HID conversion helpers."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from pykakasi import kakasi

from core.hid_typing import (
    DEFAULT_HID_REPORT_DELAY_MS,
    ascii_char_to_hid,
    build_ascii_typing_sequence,
)


AMICAL_F9_SCANCODE = 0x43
AMICAL_F9_VK = 0x78
INJECTED_CONTROL_VK = 0x11
INJECTED_V_VK = 0x56

DEFAULT_PASTE_TIMEOUT_SECONDS = 15.0
MAX_ROMAJI_CHARACTERS = 1_000

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_TRANSLITERATOR = None


@dataclass(frozen=True)
class RomajiResult:
    """Result of Japanese transliteration and ASCII filtering."""

    text: str
    source_length: int
    dropped_symbols: int
    truncated: bool


class AmicalPasteGate:
    """Accept one injected paste shortly after a physical F9 gesture."""

    def __init__(
        self,
        timeout_seconds: float = DEFAULT_PASTE_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("paste timeout must be positive")
        self.timeout_seconds = timeout_seconds
        self._f9_down = False
        self._deadline: float | None = None

    def on_f9_down(self, now: float | None = None) -> bool:
        """Start a gesture; return True only for the first key-down."""
        del now
        if self._f9_down:
            return False
        self._f9_down = True
        self._deadline = None
        return True

    def on_f9_up(self, now: float | None = None) -> bool:
        """Arm the one-shot paste window after the matching key-up."""
        if not self._f9_down:
            return False
        self._f9_down = False
        current = time.monotonic() if now is None else now
        self._deadline = current + self.timeout_seconds
        return True

    def is_waiting(self, now: float | None = None) -> bool:
        """Return whether the paste window is still open."""
        if self._deadline is None:
            return False
        current = time.monotonic() if now is None else now
        if current > self._deadline:
            self._deadline = None
            return False
        return True

    def consume(self, now: float | None = None) -> bool:
        """Consume the single allowed paste if the window is open."""
        if not self.is_waiting(now):
            return False
        self._deadline = None
        return True

    def reset(self) -> None:
        self._f9_down = False
        self._deadline = None


def _get_transliterator():
    global _TRANSLITERATOR
    if _TRANSLITERATOR is None:
        _TRANSLITERATOR = kakasi()
    return _TRANSLITERATOR


def romanize_for_hid(
    source: str,
    max_characters: int = MAX_ROMAJI_CHARACTERS,
) -> RomajiResult:
    """Convert Japanese text to spaced Hepburn ASCII words.

    Only ``A-Z``, ``a-z`` and ``0-9`` survive.  Punctuation and every other
    symbol are discarded, and all word/token boundaries become one space.
    """
    if max_characters <= 0:
        raise ValueError("max characters must be positive")

    chunks: list[str] = []
    dropped_symbols = 0
    for item in _get_transliterator().convert(source):
        romaji = str(item.get("hepburn", item.get("orig", "")))
        chunks.extend(_ASCII_WORD_RE.findall(romaji))
        dropped_symbols += sum(
            1
            for char in romaji
            if not char.isascii() or (not char.isalnum() and not char.isspace())
        )

    full_text = " ".join(chunks)
    truncated = len(full_text) > max_characters
    text = full_text[:max_characters].rstrip() if truncated else full_text
    return RomajiResult(
        text=text,
        source_length=len(source),
        dropped_symbols=dropped_symbols,
        truncated=truncated,
    )
