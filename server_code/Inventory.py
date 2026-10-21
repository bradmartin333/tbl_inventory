import anvil.users
from datetime import datetime
import hashlib
import math
import uuid

import anvil.server
from anvil.tables import app_tables, in_transaction


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
STALE_GRID_MESSAGE = "Refresh the table and try again."
STALE_SETUP_MESSAGE = (
  "Someone else changed the sections since you opened Customize. "
  "Press Cancel, then open Customize again to see their changes."
)
NO_INITIALS_MESSAGE = (
  "Your account needs initials (1–5 letters) before you can enter counts. "
  "Ask an admin to add them, then reload this page."
)


def _ensure_default_grid():
  # Saving the setup always leaves at least one section, so this only runs on
  # a new app or one from before sections existed.
  if list(app_tables.inventory_tables.search(active=True)):
    return
  _create_default_grid()


@in_transaction
def _create_default_grid():
  # Check again inside the transaction: two first loads at once would otherwise
  # each make an "Inventory" section. The loser retries and finds the winner's.
  if list(app_tables.inventory_tables.search(active=True)):
    return
  table_key = uuid.uuid4().hex
  app_tables.inventory_tables.add_row(
    table_key=table_key,
    label=DEFAULT_TABLE,
    sort_order=1,
    active=True,
  )

  # Rows and columns from before sections existed join the first section.
  for item in app_tables.inventory_rows.search(table_key=None):
    item["table_key"] = table_key
  for item in app_tables.inventory_columns.search(table_key=None):
    item["table_key"] = table_key

  if not list(app_tables.inventory_rows.search(table_key=table_key)):
    for order, label in enumerate(DEFAULT_ROWS, start=1):
      app_tables.inventory_rows.add_row(
        row_key=uuid.uuid4().hex,
        table_key=table_key,
        label=label,
        sort_order=order,
        active=True,
      )
  if not list(app_tables.inventory_columns.search(table_key=table_key)):
    for order, label in enumerate(DEFAULT_COLUMNS, start=1):
      app_tables.inventory_columns.add_row(
        column_key=uuid.uuid4().hex,
        table_key=table_key,
        label=label,
        sort_order=order,
        active=True,
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


def _active_ordered(table):
  items = list(table.search(active=True))
  items.sort(key=lambda item: item["sort_order"] or 0)
  return items


def _setup_version(tables, rows, columns):
  # A fingerprint of the active setup. Customize sends back the one it loaded,
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
      row_cells.append({
        "row_key": row["row_key"],
        "column_key": column["column_key"],
        "column_label": column["label"],
        # A cell nobody has counted yet starts at 0. Nothing is written until
        # someone saves, so no history entry is invented for it.
        "entry_quantity": _format_quantity(saved["quantity"] if saved else 0),
        "latest_display": _format_latest(saved),
      })
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
  _ensure_default_grid()
  # One search per table rather than one per section keeps the load quick.
  tables = _active_ordered(app_tables.inventory_tables)
  rows = _active_ordered(app_tables.inventory_rows)
  columns = _active_ordered(app_tables.inventory_columns)
  rows_by_table = _group_by_table(rows)
  columns_by_table = _group_by_table(columns)
  saved_cells = {
    (cell["row_key"], cell["column_key"]): cell
    for cell in app_tables.inventory_cells.search()
  }

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


def _reconcile_labels(table, labels, key_name, table_key):
  # Labels match within one section, so the same item name can sit in two.
  existing = list(table.search(table_key=table_key))
  by_label = {
    item["label"].strip().casefold(): item
    for item in existing
    if item["label"]
  }
  used_keys = set()

  for index, label in enumerate(labels):
    item = by_label.get(label.casefold())
    if item is None:
      # A new label gets a new identity so old values never appear under it.
      item = table.add_row(
        **{
          key_name: uuid.uuid4().hex,
          "table_key": table_key,
          "label": label,
          "sort_order": index + 1,
          "active": True,
        }
      )
      existing.append(item)

    item["label"] = label
    item["sort_order"] = index + 1
    item["active"] = True
    used_keys.add(item[key_name])

  for item in existing:
    if item[key_name] not in used_keys:
      item["active"] = False


def _plan_section(section):
  # Returns (table or None, label, row_labels, column_labels), or an error message.
  if not isinstance(section, dict) or not isinstance(section.get("label"), str):
    return STALE_GRID_MESSAGE
  label = section["label"].strip()
  if not label:
    return "Enter each section name on its own line."
  if len(label) > MAX_LABEL_LENGTH:
    return f"Keep each section name under {MAX_LABEL_LENGTH} characters."

  table = None
  if section.get("table_key") is not None:
    if not isinstance(section["table_key"], str):
      return STALE_GRID_MESSAGE
    table = app_tables.inventory_tables.get(table_key=section["table_key"], active=True)
    if table is None:
      return STALE_GRID_MESSAGE

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
    *(
      list(table.search(active=True))
      for table in (app_tables.inventory_tables, app_tables.inventory_rows, app_tables.inventory_columns)
    )
  )
  if setup_version != current_version:
    return {"ok": False, "message": STALE_SETUP_MESSAGE}
  if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
    return {"ok": False, "message": f"Enter 1–{MAX_SECTIONS} unique sections, one per line."}

  # Check every section before writing any. The transaction makes the writes
  # all-or-nothing, and the version check above stops a save from an
  # out-of-date Customize undoing another admin's changes.
  plans = []
  for section in sections:
    plan = _plan_section(section)
    if isinstance(plan, str):
      return {"ok": False, "message": plan}
    plans.append(plan)
  labels = [label.casefold() for _, label, _, _ in plans]
  if len(set(labels)) != len(labels):
    return {"ok": False, "message": f"Enter 1–{MAX_SECTIONS} unique sections, one per line."}
  existing_keys = [table["table_key"] for table, _, _, _ in plans if table is not None]
  if len(set(existing_keys)) != len(existing_keys):
    return {"ok": False, "message": STALE_GRID_MESSAGE}

  used_keys = set()
  for order, (table, label, row_labels, column_labels) in enumerate(plans, start=1):
    if table is None:
      table = app_tables.inventory_tables.add_row(table_key=uuid.uuid4().hex)
    table.update(label=label, sort_order=order, active=True)
    _reconcile_labels(app_tables.inventory_rows, row_labels, "row_key", table["table_key"])
    _reconcile_labels(app_tables.inventory_columns, column_labels, "column_key", table["table_key"])
    used_keys.add(table["table_key"])

  # A removed section keeps its rows, columns and history, just hidden.
  for table in app_tables.inventory_tables.search(active=True):
    if table["table_key"] not in used_keys:
      table["active"] = False
      _reconcile_labels(app_tables.inventory_rows, [], "row_key", table["table_key"])
      _reconcile_labels(app_tables.inventory_columns, [], "column_key", table["table_key"])
  return {"ok": True}


@anvil.server.callable(require_user=True)
@in_transaction
def save_grid_cell(row_key, column_key, raw_quantity):
  initials = _user_initials(anvil.users.get_user())
  if initials is None:
    return {"ok": False, "message": NO_INITIALS_MESSAGE}

  if not isinstance(row_key, str) or not isinstance(column_key, str):
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  row = app_tables.inventory_rows.get(row_key=row_key, active=True)
  column = app_tables.inventory_columns.get(column_key=column_key, active=True)
  if row is None or column is None or row["table_key"] != column["table_key"]:
    return {"ok": False, "message": STALE_GRID_MESSAGE}
  table = app_tables.inventory_tables.get(table_key=row["table_key"], active=True)
  if table is None:
    return {"ok": False, "message": STALE_GRID_MESSAGE}

  quantity = _parse_quantity(raw_quantity)
  if quantity is None:
    return {
      "ok": False,
      "message": f"Enter a zero or greater number for {row['label']} · {column['label']}.",
    }

  entered_at = datetime.now()
  # The transaction stops two first saves both adding a cell; search() rather
  # than get() still copes with duplicates saved before it was added.
  latest = next(iter(app_tables.inventory_cells.search(row_key=row_key, column_key=column_key)), None)
  if latest is None:
    latest = app_tables.inventory_cells.add_row(row_key=row_key, column_key=column_key)
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
    entered_by=initials,
    entered_at=entered_at,
  )

  return {
    "ok": True,
    "entry_quantity": _format_quantity(quantity),
    "latest_display": _format_latest(latest),
  }
