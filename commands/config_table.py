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

"""Reading and filling in a configured design's configuration table.

Shared by the two commands that split the job in half, and by Fit Handles, which
needs the same naming rules when it adds a row of its own:

    Create Configurations   works out every combination of the design's theme
                            tables and adds a row for each one missing. Fast, and
                            it changes nothing else.
    Generate Configurations builds the geometry for rows that have none. Slow,
                            and it must not run until the document has been
                            SAVED — see build().

They are separate buttons because doing both in one pass does not work: a row
created moments ago is not ready to be built, and asking anyway gives
"Select failed because Configuration was temporarily unavailable". Saving in
between is what makes the rows real.
"""

import itertools
import re
import time

import adsk.core
import adsk.fusion


# Themes to vary. Empty means every theme the design has, bar the exclusions —
# which is what lets these commands work on a cabinet they have never seen.
VARY = ()

# Themes never varied and never named. Partition is decided by configuration
# rules, and writing it through the API does not make those rules fire, so a row
# inherits whatever its source row had.
EXCLUDE = ('Partition',)

# Row naming. None takes the document's own name as the prefix.
PREFIX = None
PART_NUMBER_FROM_NAME = False

# Where the record of what has been built is kept, on the design itself. There is
# no way to ask a row whether it has geometry, and generate() costs the same ten
# seconds either way, so the commands keep their own note.
BUILT_GROUP = 'WoodCraft'
BUILT_KEY = 'generatedConfigurations'


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------
def digits(value):
    found = re.findall(r'\d+', str(value))
    return found[0] if found else re.sub(r'[^A-Za-z0-9]+', '', str(value))


def name_part(title, value):
    """One piece of a row name. '' leaves the theme out of the name entirely."""
    if title == 'Width':
        return digits(value)
    if title == 'Legs Height':
        return 'L' + digits(value)
    if title == 'Countertop Height':
        return 'C' + digits(value)
    if title == 'Handles':
        return 'Gola' if 'gola' in str(value).lower() else ''
    return re.sub(r'[^A-Za-z0-9]+', '', str(value))


def row_name(prefix, combination, order):
    """The name for a generated row.

    Excluded themes are left out: their value is inherited rather than chosen, so
    naming by it would claim a decision that was never made."""
    parts = [prefix] if prefix else []
    for title in order:
        if title in EXCLUDE:
            continue
        piece = name_part(title, combination.get(title, ''))
        if piece:
            parts.append(piece)
    return '_'.join(parts)


# ---------------------------------------------------------------------------
# Reading a table
# ---------------------------------------------------------------------------
def top_table(design):
    """The configuration table, or None if this is not a configured design.

    Only the design as the ACTIVE document answers: reached through a DataFile or
    a placement, every one of these calls returns "not yet implemented"."""
    try:
        return design.configurationTopTable
    except Exception:
        return None


def theme_columns(table):
    """{title: column} for the theme columns, in table order."""
    out = {}
    for i in range(table.columns.count):
        column = table.columns.item(i)
        if 'ThemeColumn' in column.objectType:
            out[column.title] = column
    return out


def property_columns(table):
    out = {}
    for i in range(table.columns.count):
        column = table.columns.item(i)
        if 'PropertyColumn' in column.objectType:
            out[column.title] = column
    return out


def theme_values(column):
    """The value names a theme column can take, in table order."""
    referenced = column.referencedTable
    return [referenced.rows.item(i).name for i in range(referenced.rows.count)]


def combination_of(columns, row):
    """{theme title: value name} for one row; '' where a cell cannot be read."""
    out = {}
    for title, column in columns.items():
        try:
            referenced = column.getCellByRowId(row.id).referencedTableRow
            out[title] = referenced.name if referenced else ''
        except Exception:
            out[title] = ''
    return out


def row_by_name(table, name):
    """itemByName is unreliable on these tables; walk them instead."""
    for i in range(table.rows.count):
        if table.rows.item(i).name == name:
            return table.rows.item(i)
    return None


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
class Plan:
    """What Create Configurations would do, worked out without doing any of it."""

    __slots__ = ('vary', 'axes', 'total', 'present', 'to_create', 'clashes',
                 'untouched', 'base', 'prefix', 'error')

    def __init__(self, error=None):
        self.vary = ()
        self.axes = []
        self.total = 0
        self.present = 0
        self.to_create = []      # [(name, {theme: value})]
        self.clashes = []
        self.untouched = {}
        self.base = None
        self.prefix = ''
        self.error = error


def plan(design, document_name):
    """Work out every missing combination. Reads only; changes nothing."""
    table = top_table(design)
    if table is None:
        return Plan('This document has no configuration table. Open the '
                    'configured design itself, not an assembly that places one.')

    columns = theme_columns(table)
    if VARY:
        vary = tuple(VARY)
        missing = [t for t in vary if t not in columns]
        if missing:
            return Plan('These themes are not columns in this table:\n  ' +
                        '\n  '.join(missing))
    else:
        vary = tuple(t for t in columns if t not in EXCLUDE)
    if not vary:
        return Plan('Nothing to vary — every theme in this table is excluded.')
    if table.rows.count == 0:
        return Plan('This table has no rows to copy from.')

    result = Plan()
    result.vary = vary
    result.axes = [theme_values(columns[t]) for t in vary]
    combinations = [dict(zip(vary, values))
                    for values in itertools.product(*result.axes)]
    result.total = len(combinations)
    result.base = table.rows.item(0)
    result.prefix = PREFIX if PREFIX is not None else document_name

    inherited = combination_of(columns, result.base)
    result.untouched = {t: v for t, v in inherited.items() if t not in vary}

    existing, taken = {}, set()
    for i in range(table.rows.count):
        row = table.rows.item(i)
        taken.add(row.name)
        whole = combination_of(columns, row)
        existing[tuple(whole.get(t, '') for t in vary)] = row.name

    planned = set()
    for combination in combinations:
        key = tuple(combination[t] for t in vary)
        if key in existing:
            continue
        name = row_name(result.prefix, combination, vary)
        if name in taken or name in planned:
            result.clashes.append(name)
        planned.add(name)
        result.to_create.append((name, combination))
    result.present = result.total - len(result.to_create)
    return result


def create(design, result):
    """Add every row the plan calls for. Returns (made, problems).

    Nothing is built here and nothing is saved — creating a row is instant, and
    the geometry is a separate button precisely because it is not."""
    table = top_table(design)
    columns = theme_columns(table)
    parts = property_columns(table)
    made, problems = 0, []

    for name, combination in result.to_create:
        try:
            row = result.base.copy(name)
            if row is None:
                problems.append(f'{name}: copy failed')
                continue
            for title in result.vary:
                column = columns[title]
                target = row_by_name(column.referencedTable, combination[title])
                column.getCellByRowId(row.id).referencedTableRow = target
            if PART_NUMBER_FROM_NAME and 'Part Number' in parts:
                try:
                    parts['Part Number'].getCellByRowId(row.id).value = row.name
                except Exception:
                    pass
            made += 1
        except Exception as exc:
            problems.append(f'{name}: {exc}')
    return made, problems


# ---------------------------------------------------------------------------
# Building the geometry
# ---------------------------------------------------------------------------
def built_record(design):
    try:
        attribute = design.attributes.itemByName(BUILT_GROUP, BUILT_KEY)
        if attribute and attribute.value:
            return set(attribute.value.split('\n'))
    except Exception:
        pass
    return set()


def remember_built(design, ids):
    try:
        design.attributes.add(BUILT_GROUP, BUILT_KEY, '\n'.join(sorted(ids)))
    except Exception:
        pass


def unbuilt(design, regenerate=False):
    """The rows with no geometry yet, in table order."""
    table = top_table(design)
    if table is None:
        return []
    done = set() if regenerate else built_record(design)
    return [table.rows.item(i) for i in range(table.rows.count)
            if table.rows.item(i).id not in done]


def build(design, rows, log, timeout=180.0, regenerate=False):
    """Build each row's geometry in turn. Returns (built, skipped, problems).

    Sequential on purpose: generate() blocks until the work is done and hands
    back a future that has already finished, so there is nothing to overlap.

    The caller must have SAVED the document first. Building a row that was
    created moments ago in an unsaved document fails with "Configuration was
    temporarily unavailable" — the row is not real to Fusion until it is on the
    server."""
    done = set() if regenerate else built_record(design)
    built, skipped, problems = 0, 0, []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        name = row.name
        if row.id in done:
            skipped += 1
            continue
        started = time.perf_counter()
        try:
            future = row.generate()
            if future is None:
                problems.append(f'{name}: generation would not start')
            elif not _settled(future, timeout):
                problems.append(f'{name}: still building after {timeout:.0f} s, '
                                f'moved on')
            else:
                built += 1
                done.add(row.id)
                # Written after every row, so an interrupted run keeps what it did.
                remember_built(design, done)
        except Exception as exc:
            problems.append(f'{name}: {exc}')
        log(f'  [{index}/{total}] {name} — {time.perf_counter() - started:.1f} s')
    return built, skipped, problems


def _settled(future, timeout):
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        try:
            if future.state == 2:
                return True
        except Exception:
            return False
        adsk.doEvents()
    return False
