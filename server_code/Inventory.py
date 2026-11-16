import anvil
import anvil.users
from datetime import datetime, time, timedelta
import hashlib
import json
import math
import uuid

import anvil.server
from anvil.tables import app_tables, in_transaction
import anvil.tables.query as q


DEFAULT_TABLE = "Inventory"
DEFAULT_ROWS = ["Item 1", "Item 2", "Item 3"]
DEFAULT_COLUMNS = ["Quantity", "Small containers", "Large containers"]
# The one place these limits live: get_inventory_grid sends them to the
# browser, so its checks, messages and labels follow any change here.
MAX_SECTIONS = 10
# Per section. Five columns is as many as fit beside the row labels on a phone.
MAX_ROWS = 50
MAX_COLUMNS = 5
# For section, row and column names alike.
MAX_LABEL_LENGTH = 60
MAX_PAR_DAYS = 365
# The Analytics chart's ranges. History is only ever read inside one of these.
TOTALS_RANGES = (30, 90, 365)
STALE_GRID_MESSAGE = "Refresh the table and try again."
STALE_SETUP_MESSAGE = (
  "Someone else changed the sections since you opened Customize. "
  "Press Cancel, then open Customize again to see their changes."
)
NO_INITIALS_MESSAGE = (
  "Your account needs initials (1–5 letters) before you can enter counts. "
  "Ask an admin to add them, then reload this page."
)


def _live(table, **filters):
  # Before deletes were real, a removed section, row or column was only marked
  # active=False. The next setup save deletes those; until then, skip them.
  return [item for item in table.search(**filters) if item["active"] is not False]


def _get_live(table, **filters):
  return next(iter(_live(table, **filters)), None)


@in_transaction
def _create_default_grid():
  # Check again inside the transaction: two first loads at once would otherwise
  # each make an "Inventory" section. The loser retries and finds the winner's.
  if _live(app_tables.inventory_tables):
    return
  table_key = uuid.uuid4().hex
  app_tables.inventory_tables.add_row(table_key=table_key, label=DEFAULT_TABLE, sort_order=1)

  # Rows and columns from before sections existed join the first section.
  for item in app_tables.inventory_rows.search(table_key=None):
    item["table_key"] = table_key
  for item in app_tables.inventory_columns.search(table_key=None):
    item["table_key"] = table_key

  if not list(app_tables.inventory_rows.search(table_key=table_key)):
    for order, label in enumerate(DEFAULT_ROWS, start=1):
      app_tables.inventory_rows.add_row(
        row_key=uuid.uuid4().hex, table_key=table_key, label=label, sort_order=order
      )
  if not list(app_tables.inventory_columns.search(table_key=table_key)):
    for order, label in enumerate(DEFAULT_COLUMNS, start=1):
      app_tables.inventory_columns.add_row(
        column_key=uuid.uuid4().hex, table_key=table_key, label=label, sort_order=order
      )


def _format_quantity(quantity):
  if quantity is None:
    return ""
  return f"{quantity:g}"


def _format_latest(cell):
  if cell is None or not cell["entered_at"]:
    return "Not entered"
  # Short enough to fit under a number in a phone-width grid cell; the year
  # only shows once it isn't this year's.
  entered_at = cell["entered_at"]
  date_format = "%m/%d" if entered_at.year == datetime.now().year else "%m/%d/%y"
  date_text = entered_at.strftime(date_format)
  return f"{cell['entered_by']} · {date_text}"


def _is_blank(raw):
  return raw is None or (isinstance(raw, str) and not raw.strip())


def _parse_days(raw_days):
  # Whole days between counts, for an on-par level.
  if isinstance(raw_days, bool):
    return None
  try:
    days = float(raw_days)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(days) or days != int(days) or not 1 <= days <= MAX_PAR_DAYS:
    return None
  return int(days)


def _local(moment):
  # Anvil hands stored datetimes back with a time zone, and datetime.now() has
  # none; bring both to the server's clock before comparing them.
  return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def _days_since(moment):
  # Calendar days, as people say it: a count saved last night was 1 day ago
  # this morning, not 0.
  return (datetime.now().date() - _local(moment).date()).days


def _par_flags(cell):
  # (below par, overdue). An uncounted cell holds 0, just as the grid shows it.
  if cell is None:
    return False, False
  quantity = cell["quantity"] if cell["quantity"] is not None else 0
  below_par = cell["par_quantity"] is not None and quantity < cell["par_quantity"]
  overdue = bool(cell["max_days"]) and (
    not cell["entered_at"] or _days_since(cell["entered_at"]) > cell["max_days"]
  )
  return below_par, overdue


def _plural(count, word):
  return f"{count} {word}{'' if count == 1 else 's'}"


def _alert_text(cell, below_par, overdue):
  # The Needs attention line. It names the problem in words, not just a colour.
  parts = []
  if below_par:
    quantity = cell["quantity"] if cell["quantity"] is not None else 0
    parts.append(
      f"Low: {_format_quantity(quantity)} on hand, par {_format_quantity(cell['par_quantity'])}"
    )
  if overdue:
    interval = _plural(int(cell["max_days"]), "day")
    if cell["entered_at"]:
      days_ago = _days_since(cell["entered_at"])
      parts.append(f"Due: last counted {_plural(days_ago, 'day')} ago, every {interval}")
    else:
      parts.append(f"Due: never counted, every {interval}")
  return " · ".join(parts)


def _par_fields(cell):
  # What the grid and Analytics need to show and edit a cell's on-par level.
  below_par, overdue = _par_flags(cell)
  return {
    "par_text": _format_quantity(cell["par_quantity"] if cell else None),
    "days_text": _format_quantity(cell["max_days"] if cell else None),
    "below_par": below_par,
    "overdue": overdue,
    "alert_text": _alert_text(cell, below_par, overdue) if cell else "",
  }


def _parse_quantity(raw_quantity):
  if raw_quantity is None or isinstance(raw_quantity, bool):
    return None
  if isinstance(raw_quantity, str) and not raw_quantity.strip():
    return None

  try:
    quantity = float(raw_quantity)
  except (TypeError, ValueError):
    return None

  if not math.isfinite(quantity) or quantity < 0:
    return None
  return quantity


def _user_initials(user):
  # Admins type these into the users table, so hold them to the old 1–5 letter rule.
  initials = user["initials"]
  if not isinstance(initials, str):
    return None
  initials = initials.strip().upper()
  if not initials.isalpha() or not 1 <= len(initials) <= 5:
    return None
  return initials


@anvil.server.callable
def activate_account(email):
  # Built-in sign-up is off, and with it off Anvil ignores its own
  # email-confirmation links. A password-reset link still works, and using it
  # both sets the first password and marks the email confirmed, so activation
  # sends one to any email an admin has added, enabled and given initials.
  not_invited = {
    "ok": False,
    "message": "That email hasn't been set up yet. Ask an admin to add it, then try again.",
  }
  if not isinstance(email, str):
    return not_invited
  email = email.strip()
  invited = next(
    (
      user for user in app_tables.users.search()
      if (user["email"] or "").strip().casefold() == email.casefold()
    ),
    None,
  )
  if invited is None or not invited["enabled"] or _user_initials(invited) is None:
    return not_invited
  anvil.users.send_password_reset_email(invited["email"])
  return {"ok": True}


def _ordered(table, **filters):
  items = _live(table, **filters)
  items.sort(key=lambda item: item["sort_order"] or 0)
  return items


def _cell_rank(cell):
  return _local(cell["entered_at"]) if cell["entered_at"] else datetime.min


def _newest_cells(cells):
  # {(row_key, column_key): cell}. Saves from before they ran in a
  # transaction could leave two rows for one cell; every reader and writer
  # uses the most recently counted, so a par level never lands on a row the
  # grid doesn't show. Saving a count keeps that row the newest.
  chosen = {}
  for cell in cells:
    key = (cell["row_key"], cell["column_key"])
    if key not in chosen or _cell_rank(cell) > _cell_rank(chosen[key]):
      chosen[key] = cell
  return chosen


def _setup_version(tables, rows, columns):
  # A fingerprint of the current setup. Customize sends back the one it loaded,
  # so a save built on out-of-date data is refused rather than quietly undoing
  # what someone else saved in the meantime.
  parts = [
    sorted(
      (item[key_name], item["table_key"], item["label"], item["sort_order"])
      for item in items
    )
    for items, key_name in ((tables, "table_key"), (rows, "row_key"), (columns, "column_key"))
  ]
  return hashlib.sha1(repr(parts).encode()).hexdigest()


def _group_by_table(items):
  grouped = {}
  for item in items:
    grouped.setdefault(item["table_key"], []).append(item)
  return grouped


def _build_table(table, rows, columns, saved_cells):
  grid_rows = []
  for row in rows:
    row_cells = []
    for column in columns:
      key = (row["row_key"], column["column_key"])
      saved = saved_cells.get(key)
      quantity = saved["quantity"] if saved else None
      cell = {
        "row_key": row["row_key"],
        "column_key": column["column_key"],
        "column_label": column["label"],
        # A cell nobody has counted yet starts at 0. Nothing is written until
        # someone saves, so no history entry is invented for it. A cell with
        # only an on-par level set has a row but still no count.
        "entry_quantity": _format_quantity(0 if quantity is None else quantity),
        "latest_display": _format_latest(saved),
      }
      # Par lives on the cell row already read here, so it costs no extra search.
      cell.update(_par_fields(saved))
      row_cells.append(cell)
    grid_rows.append({
      "row_key": row["row_key"],
      "label": row["label"],
      "cells": row_cells,
    })

  return {
    "table_key": table["table_key"],
    "label": table["label"],
    "rows": grid_rows,
    "columns": [
      {"column_key": column["column_key"], "label": column["label"]}
      for column in columns
    ],
    "row_labels": [row["label"] for row in rows],
    "column_labels": [column["label"] for column in columns],
  }


@anvil.server.callable(require_user=True)
def get_inventory_grid():
  # One search per table rather than one per section keeps the load quick.
  tables = _ordered(app_tables.inventory_tables)
  if not tables:
    # Saving the setup always leaves at least one section, so this only runs
    # on a new app or one from before sections existed.
    _create_default_grid()
    tables = _ordered(app_tables.inventory_tables)
  rows = _ordered(app_tables.inventory_rows)
  columns = _ordered(app_tables.inventory_columns)
  rows_by_table = _group_by_table(rows)
  columns_by_table = _group_by_table(columns)
  saved_cells = _newest_cells(app_tables.inventory_cells.search())

  return {
    "initials": _user_initials(anvil.users.get_user()),
    "limits": {
      "sections": MAX_SECTIONS,
      "rows": MAX_ROWS,
      "columns": MAX_COLUMNS,
      "label_length": MAX_LABEL_LENGTH,
    },
    "setup_version": _setup_version(tables, rows, columns),
    "tables": [
      _build_table(
        table,
        rows_by_table.get(table["table_key"], []),
        columns_by_table.get(table["table_key"], []),
        saved_cells,
      )
      for table in tables
    ],
  }


def _split_labels(raw_text):
  if not isinstance(raw_text, str):
    return None
  labels = [line.strip() for line in raw_text.splitlines() if line.strip()]
  if len({label.casefold() for label in labels}) != len(labels):
    return None
  return labels


def _delete_items(items, key_name):
  # Current counts go with their row or column. History keeps its own copy of
  # every name, so past entries still read correctly.
  for item in list(items):
    for cell in list(app_tables.inventory_cells.search(**{key_name: item[key_name]})):
      cell.delete()
    item.delete()


def _delete_section(table):
  _delete_items(app_tables.inventory_rows.search(table_key=table["table_key"]), "row_key")
  _delete_items(app_tables.inventory_columns.search(table_key=table["table_key"]), "column_key")
  table.delete()


def _sync_labels(table, labels, key_name, table_key):
  # Labels match within one section, so the same item name can sit in two. A
  # label that's gone is deleted with its counts, and a new or renamed one
  # starts fresh rather than showing another item's counts.
  by_label = {}
  leftovers = []
  for item in table.search(table_key=table_key):
    if item["active"] is False:
      leftovers.append(item)
    else:
      by_label[(item["label"] or "").strip().casefold()] = item
  for order, label in enumerate(labels, start=1):
    item = by_label.pop(label.casefold(), None)
    if item is None:
      item = table.add_row(**{key_name: uuid.uuid4().hex, "table_key": table_key})
    item.update(label=label, sort_order=order)
  _delete_items(leftovers + list(by_label.values()), key_name)


def _section_key(label):
  # Section names compare with lower(), exactly as Customize checks them in the
  # browser (which has no casefold()), so the two never disagree on a clash.
  return (label or "").strip().lower()


def _plan_section(section):
  # Returns (table or None, label, row_labels, column_labels), or an error message.
  if not isinstance(section, dict) or not isinstance(section.get("label"), str):
    return STALE_SETUP_MESSAGE
  label = section["label"].strip()
  if not label:
    return "Give every section a name."
  if len(label) > MAX_LABEL_LENGTH:
    return f"Keep each section name under {MAX_LABEL_LENGTH} characters."

  table = None
  if section.get("table_key") is not None:
    if not isinstance(section["table_key"], str):
      return STALE_SETUP_MESSAGE
    table = _get_live(app_tables.inventory_tables, table_key=section["table_key"])
    if table is None:
      return STALE_SETUP_MESSAGE

  row_labels = _split_labels(section.get("row_labels_text"))
  column_labels = _split_labels(section.get("column_labels_text"))
  if row_labels is None or not 1 <= len(row_labels) <= MAX_ROWS:
    return f"{label}: enter 1–{MAX_ROWS} unique row labels, one per line."
  if column_labels is None or not 1 <= len(column_labels) <= MAX_COLUMNS:
    return f"{label}: enter 1–{MAX_COLUMNS} unique quantity columns, one per line."
  if any(len(item_label) > MAX_LABEL_LENGTH for item_label in row_labels + column_labels):
    return f"{label}: keep each row and column label under {MAX_LABEL_LENGTH} characters."
  return table, label, row_labels, column_labels


@anvil.server.callable(require_user=True)
@in_transaction
def save_inventory_configuration(sections, setup_version=None):
  current_version = _setup_version(
    _live(app_tables.inventory_tables),
    _live(app_tables.inventory_rows),
    _live(app_tables.inventory_columns),
  )
  if setup_version != current_version:
    return {"ok": False, "message": STALE_SETUP_MESSAGE}
  if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
    return {"ok": False, "message": f"Keep between 1 and {MAX_SECTIONS} sections."}

  # Check every section before writing any. The transaction makes the writes
  # all-or-nothing, and the version check above stops a save from an
  # out-of-date Customize undoing another admin's changes.
  plans = []
  for section in sections:
    plan = _plan_section(section)
    if isinstance(plan, str):
      return {"ok": False, "message": plan}
    plans.append(plan)
  seen_labels = set()
  for _, label, _, _ in plans:
    if _section_key(label) in seen_labels:
      return {"ok": False, "message": f"Two sections are called {label}. Give each a different name."}
    seen_labels.add(_section_key(label))
  kept_keys = [table["table_key"] for table, _, _, _ in plans if table is not None]
  if len(set(kept_keys)) != len(kept_keys):
    return {"ok": False, "message": STALE_SETUP_MESSAGE}

  # Deleting is final: a section left out goes with its rows, columns and
  # current counts. This also clears sections hidden before deletes were real.
  for table in list(app_tables.inventory_tables.search()):
    if table["table_key"] not in kept_keys:
      _delete_section(table)

  for order, (table, label, row_labels, column_labels) in enumerate(plans, start=1):
    if table is None:
      table = app_tables.inventory_tables.add_row(table_key=uuid.uuid4().hex)
    table.update(label=label, sort_order=order)
    _sync_labels(app_tables.inventory_rows, row_labels, "row_key", table["table_key"])
    _sync_labels(app_tables.inventory_columns, column_labels, "column_key", table["table_key"])
  return {"ok": True}


def _cell_target(row_key, column_key):
  # (section, row, column) for a live cell, or None when the grid is out of date.
  if not isinstance(row_key, str) or not isinstance(column_key, str):
    return None
  row = _get_live(app_tables.inventory_rows, row_key=row_key)
  column = _get_live(app_tables.inventory_columns, column_key=column_key)
  if row is None or column is None or row["table_key"] != column["table_key"]:
    return None
  table = _get_live(app_tables.inventory_tables, table_key=row["table_key"])
  if table is None:
    return None
  return table, row, column


def _find_cell(row_key, column_key):
  # search() rather than get() still copes with duplicates saved before
  # saves ran in a transaction.
  found = app_tables.inventory_cells.search(row_key=row_key, column_key=column_key)
  return _newest_cells(found).get((row_key, column_key))


@anvil.server.callable(require_user=True)
@in_transaction
def save_grid_cell(row_key, column_key, raw_quantity):
  initials = _user_initials(anvil.users.get_user())
  if initials is None:
    return {"ok": False, "message": NO_INITIALS_MESSAGE}

  target = _cell_target(row_key, column_key)
  if target is None:
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  table, row, column = target

  quantity = _parse_quantity(raw_quantity)
  if quantity is None:
    return {
      "ok": False,
      "message": f"Enter a zero or greater number for {row['label']} · {column['label']}.",
    }

  entered_at = datetime.now()
  # The transaction stops two first saves both adding a cell.
  latest = _find_cell(row_key, column_key)
  if latest is None:
    latest = app_tables.inventory_cells.add_row(row_key=row_key, column_key=column_key)
  # Kept with the entry so the Analytics chart can step back through a window
  # of history without reading anything older.
  previous_quantity = latest["quantity"]
  latest.update(quantity=quantity, entered_by=initials, entered_at=entered_at)
  app_tables.inventory_history.add_row(
    entry_id=uuid.uuid4().hex,
    table_key=table["table_key"],
    table_label=table["label"],
    row_key=row_key,
    row_label=row["label"],
    column_key=column_key,
    column_label=column["label"],
    quantity=quantity,
    previous_quantity=previous_quantity,
    entered_by=initials,
    entered_at=entered_at,
  )

  # The new count can lift a cell above par or end its overdue spell.
  result = _par_fields(latest)
  result.update(
    ok=True,
    entry_quantity=_format_quantity(quantity),
    latest_display=_format_latest(latest),
  )
  return result


@anvil.server.callable(require_user=True)
@in_transaction
def save_par_level(row_key, column_key, raw_par, raw_days):
  # Blank clears either part. Like Customize, any signed-in user may set these.
  target = _cell_target(row_key, column_key)
  if target is None:
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  _, row, column = target
  name = f"{row['label']} · {column['label']}"

  par_quantity = None if _is_blank(raw_par) else _parse_quantity(raw_par)
  if par_quantity is None and not _is_blank(raw_par):
    return {"ok": False, "message": f"Enter a par of zero or more for {name}, or leave it blank."}
  max_days = None if _is_blank(raw_days) else _parse_days(raw_days)
  if max_days is None and not _is_blank(raw_days):
    return {
      "ok": False,
      "message": f"Enter 1–{MAX_PAR_DAYS} whole days between counts for {name}, or leave it blank.",
    }

  cell = _find_cell(row_key, column_key)
  if cell is None and (par_quantity is not None or max_days is not None):
    cell = app_tables.inventory_cells.add_row(row_key=row_key, column_key=column_key)
  if cell is not None:
    cell.update(par_quantity=par_quantity, max_days=max_days)
    # A row that held only a par level has nothing left to keep.
    if cell["quantity"] is None and par_quantity is None and max_days is None:
      cell.delete()
      cell = None

  result = _par_fields(cell)
  result["ok"] = True
  return result


@anvil.server.callable(require_user=True)
def get_section_totals(table_key, days):
  # Each column's total at the end of each day in the window. Five searches,
  # and none reads history from before the window: the walk starts from
  # today's counts and steps back through the window's entries, each of which
  # remembers the quantity it replaced.
  if days not in TOTALS_RANGES or not isinstance(table_key, str):
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  table = _get_live(app_tables.inventory_tables, table_key=table_key)
  if table is None:
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  rows = _ordered(app_tables.inventory_rows, table_key=table_key)
  columns = _ordered(app_tables.inventory_columns, table_key=table_key)
  row_keys = {row["row_key"] for row in rows}
  column_keys = {column["column_key"] for column in columns}

  values = {}
  if row_keys:
    cells = app_tables.inventory_cells.search(
      q.fetch_only("row_key", "column_key", "quantity", "entered_at"), row_key=q.any_of(*row_keys)
    )
    for key, cell in _newest_cells(cells).items():
      if key[1] in column_keys and cell["quantity"] is not None:
        values[key] = cell["quantity"]

  today = datetime.now().date()
  first_day = today - timedelta(days=days - 1)
  window_start = datetime.combine(first_day, time.min)
  found = app_tables.inventory_history.search(
    q.fetch_only("row_key", "column_key", "quantity", "previous_quantity", "entered_at"),
    table_key=table_key,
    entered_at=q.greater_than_or_equal_to(window_start),
  )
  entries = sorted(
    (
      (_local(entry["entered_at"]), (entry["row_key"], entry["column_key"]), entry)
      for entry in found
      if entry["row_key"] in row_keys and entry["column_key"] in column_keys
    ),
    key=lambda item: item[0],
  )
  # [(entered_at, cell key, quantity before it)], oldest first. Entries saved
  # before previous_quantity was kept (and not yet backfilled) have none, so
  # take it from the cell's next-older entry in the window. Only a cell's
  # oldest such entry is left unknown, and reads as uncounted before it.
  last_quantity = {}
  steps = []
  for entered_at, key, entry in entries:
    previous = entry["previous_quantity"]
    if previous is None:
      previous = last_quantity.get(key)
    steps.append((entered_at, key, previous))
    last_quantity[key] = entry["quantity"]
  steps.reverse()

  dates = [first_day + timedelta(days=offset) for offset in range(days)]
  totals = {key: [None] * days for key in column_keys}
  # The same walk, kept per cell, for plotting single items.
  per_cell = {(row_key, column_key): [None] * days for row_key in row_keys for column_key in column_keys}
  next_entry = 0
  for index in range(days - 1, -1, -1):
    day_end = datetime.combine(dates[index], time.min) + timedelta(days=1)
    # Undo every entry saved after this day ended.
    while next_entry < len(steps) and steps[next_entry][0] >= day_end:
      _, key, previous = steps[next_entry]
      if previous is None:
        values.pop(key, None)
      else:
        values[key] = previous
      next_entry += 1
    for (row_key, column_key), quantity in values.items():
      per_cell[(row_key, column_key)][index] = quantity
      # A column with no counted cell that day stays a gap, not a zero.
      totals[column_key][index] = (totals[column_key][index] or 0) + quantity

  return {
    "ok": True,
    "dates": [day.strftime("%Y-%m-%d") for day in dates],
    "series": [
      {"column_key": column["column_key"], "label": column["label"], "totals": totals[column["column_key"]]}
      for column in columns
    ],
    "cells": [
      {"row_key": row_key, "column_key": column_key, "quantities": quantities}
      for (row_key, column_key), quantities in per_cell.items()
    ],
  }


@anvil.server.background_task
def backfill_previous_quantities():
  # One-off, for history saved before entries kept the quantity they
  # replaced. Fills it in from each cell's previous entry so the Analytics
  # chart is exact for older ranges. Safe to run again: it only fills gaps.
  # Launch from the server console:
  #   anvil.server.launch_background_task("backfill_previous_quantities")
  by_cell = {}
  for entry in app_tables.inventory_history.search():
    if entry["row_key"] and entry["column_key"] and entry["entered_at"]:
      by_cell.setdefault((entry["row_key"], entry["column_key"]), []).append(entry)
  filled = 0
  for entries in by_cell.values():
    entries.sort(key=lambda entry: _local(entry["entered_at"]))
    # A cell's first entry has nothing before it, so it stays empty.
    for older, entry in zip(entries, entries[1:]):
      if entry["previous_quantity"] is None and older["quantity"] is not None:
        entry["previous_quantity"] = older["quantity"]
        filled += 1
  print(f"Filled previous_quantity on {filled} history entries.")
  return filled


# Admin: export and import

EXPORT_FORMAT = "tbl-inventory-export"
EXPORT_VERSION = 1
# Every inventory table and its columns, as anvil.yaml declares them. An
# import replaces these outright.
EXPORT_TABLES = {
  "inventory_tables": {
    "table_key": "string", "label": "string", "sort_order": "number", "active": "bool",
  },
  "inventory_rows": {
    "row_key": "string", "table_key": "string", "label": "string", "sort_order": "number",
    "active": "bool",
  },
  "inventory_columns": {
    "column_key": "string", "table_key": "string", "label": "string", "sort_order": "number",
    "active": "bool",
  },
  "inventory_cells": {
    "row_key": "string", "column_key": "string", "quantity": "number", "entered_by": "string",
    "entered_at": "datetime", "par_quantity": "number", "max_days": "number",
  },
  "inventory_history": {
    "entry_id": "string", "table_key": "string", "table_label": "string", "row_key": "string",
    "row_label": "string", "column_key": "string", "column_label": "string", "quantity": "number",
    "entered_by": "string", "entered_at": "datetime", "previous_quantity": "number",
  },
}
# Within each table, the column no two rows may share.
EXPORT_UNIQUE_KEYS = {
  "inventory_tables": "table_key",
  "inventory_rows": "row_key",
  "inventory_columns": "column_key",
  "inventory_history": "entry_id",
}
# The user columns that travel. Password hashes, login tokens and the like
# stay behind: an added user sets a password with Activate account, which
# needs them enabled and with initials, as these carry over.
EXPORT_USER_COLUMNS = {
  "email": "string", "enabled": "bool", "initials": "string", "signed_up": "datetime",
}
# How many new users' emails the import dialog lists by name.
PREVIEW_USER_NAMES = 10
MAX_IMPORT_BYTES = 50 * 1024 * 1024
IMPORT_CONFIRM_WORD = "REPLACE"
NOT_AN_EXPORT_MESSAGE = (
  "That file isn't an inventory export from this app. Nothing was changed. "
  "Choose a file made with Export all data."
)
IMPORT_NEEDS_INITIALS_MESSAGE = (
  "Your account needs initials (1–5 letters) before it can import data. "
  "Ask an admin to add them, then reload this page."
)


def _export_value(value):
  return value.isoformat() if isinstance(value, datetime) else value


def _summary(tables):
  # {table name: rows} -> the counts a person would recognise.
  return {
    "sections": len(tables["inventory_tables"]),
    "items": len(tables["inventory_rows"]),
    "columns": len(tables["inventory_columns"]),
    "counts": len([cell for cell in tables["inventory_cells"] if cell["quantity"] is not None]),
    "history": len(tables["inventory_history"]),
  }


def _summary_text(summary):
  return ", ".join([
    _plural(summary["sections"], "section"),
    _plural(summary["items"], "item"),
    _plural(summary["columns"], "column"),
    _plural(summary["counts"], "current count"),
    f"{summary['history']} history {'entry' if summary['history'] == 1 else 'entries'}",
  ])


def _email_key(email):
  return (email or "").strip().casefold()


def _new_users(users):
  # The file's users whose email this app doesn't have yet, in file order.
  existing = {_email_key(user["email"]) for user in app_tables.users.search()}
  return [user for user in users if _email_key(user["email"]) not in existing]


def _users_text(new_users, total):
  if not new_users:
    return f"none of the file's {_plural(total, 'user')} are new; existing accounts are left as they are"
  names = [user["email"] for user in new_users[:PREVIEW_USER_NAMES]]
  more = len(new_users) - len(names)
  listed = ", ".join(names) + (f" and {more} more" if more else "")
  kept = total - len(new_users)
  return (
    f"{_plural(len(new_users), 'new user')} added ({listed})"
    + (f"; {kept} already here {'is' if kept == 1 else 'are'} left as they are" if kept else "")
  )


def _current_tables():
  return {
    name: [
      {column: _export_value(row[column]) for column in columns}
      for row in getattr(app_tables, name).search()
    ]
    for name, columns in EXPORT_TABLES.items()
  }


@anvil.server.callable(require_user=True)
def export_inventory():
  # Everything the inventory tables hold, as one JSON file to download.
  now = datetime.now()
  data = {
    "format": EXPORT_FORMAT,
    "version": EXPORT_VERSION,
    "exported_at": now.isoformat(timespec="seconds"),
    "exported_by": _user_initials(anvil.users.get_user()),
    "tables": _current_tables(),
    "users": [
      {column: _export_value(user[column]) for column in EXPORT_USER_COLUMNS}
      for user in app_tables.users.search()
    ],
  }
  content = json.dumps(data, indent=1, allow_nan=False).encode("utf-8")
  return anvil.BlobMedia(
    "application/json", content, name=f"tbl-inventory-{now.strftime('%Y-%m-%d-%H%M')}.json"
  )


def _import_value(value, kind):
  # The stored value, or raises ValueError for one the column can't hold.
  if value is None:
    return None
  if kind == "string" and isinstance(value, str):
    return value
  if kind == "bool" and isinstance(value, bool):
    return value
  if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
    if math.isfinite(value):
      return value
  if kind == "datetime" and isinstance(value, str):
    return datetime.fromisoformat(value)
  raise ValueError(value)


def _read_import(media):
  # Returns (data, {table name: rows ready to add}, [users]), or an error message.
  # Checks the whole file before anything is written.
  try:
    content = media.get_bytes()
  except Exception:
    return "Choose an export file to import."
  if len(content) > MAX_IMPORT_BYTES:
    return "That file is too large to import. Nothing was changed."
  try:
    data = json.loads(content.decode("utf-8"))
  except (UnicodeDecodeError, ValueError):
    return NOT_AN_EXPORT_MESSAGE
  if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
    return NOT_AN_EXPORT_MESSAGE
  if not isinstance(data.get("version"), int) or data["version"] > EXPORT_VERSION:
    return "That file came from a newer version of this app, so it can't be imported here."
  tables = data.get("tables")
  if not isinstance(tables, dict):
    return NOT_AN_EXPORT_MESSAGE

  clean = {}
  for name, columns in EXPORT_TABLES.items():
    rows = tables.get(name)
    if not isinstance(rows, list):
      return f"That file is missing its {name} table, so it can't be imported. Nothing was changed."
    clean_rows = []
    for number, row in enumerate(rows, start=1):
      problem = f"Row {number} of {name} in that file is damaged, so it can't be imported. Nothing was changed."
      if not isinstance(row, dict) or not set(row) <= set(columns):
        return problem
      try:
        clean_rows.append({column: _import_value(row.get(column), kind) for column, kind in columns.items()})
      except ValueError:
        return problem
    key_name = EXPORT_UNIQUE_KEYS.get(name)
    if key_name:
      keys = [row[key_name] for row in clean_rows]
      if None in keys or len(set(keys)) != len(keys):
        return f"Two rows of {name} in that file share a key, so it can't be imported. Nothing was changed."
    clean[name] = clean_rows

  # Exports from before users travelled have none, which is fine.
  users = data.get("users", [])
  if not isinstance(users, list):
    return NOT_AN_EXPORT_MESSAGE
  clean_users = []
  for number, user in enumerate(users, start=1):
    problem = f"User {number} in that file is damaged, so it can't be imported. Nothing was changed."
    if not isinstance(user, dict) or not set(user) <= set(EXPORT_USER_COLUMNS):
      return problem
    try:
      clean_user = {
        column: _import_value(user.get(column), kind) for column, kind in EXPORT_USER_COLUMNS.items()
      }
    except ValueError:
      return problem
    if not _email_key(clean_user["email"]):
      return problem
    clean_user["email"] = clean_user["email"].strip()
    clean_users.append(clean_user)
  if len({_email_key(user["email"]) for user in clean_users}) != len(clean_users):
    return "Two users in that file share an email, so it can't be imported. Nothing was changed."
  return data, clean, clean_users


def _import_preview(data, tables, users):
  exported_at = data.get("exported_at")
  try:
    exported_text = datetime.fromisoformat(exported_at).strftime("%b %d, %Y at %I:%M %p")
  except (TypeError, ValueError):
    exported_text = "at an unknown time"
  exported_by = data.get("exported_by")
  return {
    "ok": True,
    "current_text": _summary_text(_summary(_current_tables())),
    "incoming_text": _summary_text(_summary(tables)),
    "users_text": _users_text(_new_users(users), len(users)),
    "exported_text": exported_text + (f" by {exported_by}" if isinstance(exported_by, str) else ""),
    "confirm_word": IMPORT_CONFIRM_WORD,
  }


@anvil.server.callable(require_user=True)
def preview_inventory_import(media):
  # Checks a file and says what importing it would replace. Writes nothing.
  if _user_initials(anvil.users.get_user()) is None:
    return {"ok": False, "message": IMPORT_NEEDS_INITIALS_MESSAGE}
  read = _read_import(media)
  if isinstance(read, str):
    return {"ok": False, "message": read}
  return _import_preview(*read)


@anvil.server.callable(require_user=True)
@in_transaction
def import_inventory(media, confirm_word):
  # Replaces every inventory table with the file's contents, all or nothing.
  if _user_initials(anvil.users.get_user()) is None:
    return {"ok": False, "message": IMPORT_NEEDS_INITIALS_MESSAGE}
  if confirm_word != IMPORT_CONFIRM_WORD:
    return {"ok": False, "message": f"Type {IMPORT_CONFIRM_WORD} to confirm the import. Nothing was changed."}
  read = _read_import(media)
  if isinstance(read, str):
    return {"ok": False, "message": read}
  _, tables, users = read
  for name, rows in tables.items():
    table = getattr(app_tables, name)
    table.delete_all_rows()
    if rows:
      table.add_rows(rows)
  # Users are only ever added: anyone already here, the importer included,
  # keeps their password, initials and settings.
  added = _new_users(users)
  if added:
    app_tables.users.add_rows(added)
  return {
    "ok": True,
    "summary_text": _summary_text(_summary(tables)),
    "users_added": len(added),
  }
