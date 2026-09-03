# WoodCraft — a Fusion add-in for cabinetmaking.
# Copyright (C) 2026 Abdelrahman Youssry
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.

"""Deciding what a component IS from its name — carcass part, front, or neither.

Extracted from the Set Finish command once a second command needed the same answer:
Skirting works out which way a cabinet faces by finding its door, and "which of
these components is a door" is exactly this question. Two copies of a rule this
fiddly — suffix stripping, exact names, keyword phrases, precedence — would have
drifted apart the first time a name was added to only one of them.

Pure Python, no Fusion API: it takes a name (or anything with a `.name`), so it can
be unit-tested and reasoned about on its own. The lists themselves live in
config.py, where the user's vocabulary belongs.
"""

import re

from .. import config


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------
# Fusion decorates a component name in three ways the user never typed: a copy
# suffix "Left Panel (2)", an occurrence suffix "Left Panel:1", and a trailing
# serial "Shelf 2". Strip all three and casefold, so one entry in the config lists
# covers every instance of that part. None of the configured names ends in a digit,
# so dropping a trailing number can't collapse two distinct parts into one.
_COPY_SUFFIX = re.compile(r'\s*\(\s*\d+\s*\)\s*$')
_OCC_SUFFIX = re.compile(r':\s*\d+\s*$')
_SERIAL_SUFFIX = re.compile(r'\s+\d+\s*$')


def fold(text) -> str:
    """Case- and whitespace-insensitive form. No suffix stripping: used for the
    keyword phrases, which are fragments and must survive verbatim."""
    return re.sub(r'\s+', ' ', str(text or '').strip()).casefold()


def normalize(name) -> str:
    """Canonical form of a component NAME for matching against the config lists."""
    text = str(name or '').strip()
    for _ in range(3):          # suffixes can stack, e.g. "Shelf 2 (3):1"
        stripped = _OCC_SUFFIX.sub('', text)
        stripped = _COPY_SUFFIX.sub('', stripped)
        stripped = _SERIAL_SUFFIX.sub('', stripped)
        stripped = stripped.strip()
        if stripped == text or not stripped:
            break
        text = stripped
    return fold(text)


CARCASS_NAMES = frozenset(normalize(n) for n in config.WC_CARCASS_PART_NAMES)
DOOR_NAMES = frozenset(normalize(n) for n in config.WC_DOOR_PART_NAMES)

# Substring rules. Empty phrases are dropped rather than matching every component —
# a stray '' in the config would otherwise silently repaint the whole kitchen.
CARCASS_KEYWORDS = tuple(k for k in (fold(p) for p in config.WC_CARCASS_PART_KEYWORDS) if k)
DOOR_KEYWORDS = tuple(k for k in (fold(p) for p in config.WC_DOOR_PART_KEYWORDS) if k)


def group_for(component):
    """'carcass' | 'door' | None — which material/appearance (if any) this component
    takes.

    Two kinds of rule, resolved in a fixed order so the answer never depends on
    which happens to be checked first:

      1. Exact name — the component's whole name, once Fusion's copy/occurrence
         suffixes are stripped, is one of the configured names. Carcass, then door.
      2. Keyword — the name CONTAINS a configured phrase anywhere. Carcass, then
         door.

    Exact beats keyword, so adding a broad phrase can never hijack a part that a
    listed name already claims. Anything matching neither is left alone."""
    key = normalize(getattr(component, 'name', ''))
    if not key:
        return None
    if key in CARCASS_NAMES:
        return 'carcass'
    if key in DOOR_NAMES:
        return 'door'
    if any(phrase in key for phrase in CARCASS_KEYWORDS):
        return 'carcass'
    if any(phrase in key for phrase in DOOR_KEYWORDS):
        return 'door'
    return None
