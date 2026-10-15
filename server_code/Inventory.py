import anvil.users
from datetime import datetime
import math
import uuid

import anvil.server
from anvil.tables import app_tables


DEFAULT_ROWS = ["Item 1", "Item 2", "Item 3"]
DEFAULT_COLUMNS = ["Quantity", "Small containers", "Large containers"]
MAX_ROWS = 50
MAX_COLUMNS = 12
NO_INITIALS_MESSAGE = (
  "Your account needs initials (1–5 letters) before you can enter counts. "
  "Ask an admin to add them, then reload this page."
)


def _ensure_default_grid():
  if not list(app_tables.inventory_rows.search()):
    for order, label in enumerate(DEFAULT_ROWS, start=1):
      app_tables.inventory_rows.add_row(
        row_key=uuid.uuid4().hex,
        label=label,
        sort_order=order,
        active=True,
      )
  if not list(app_tables.inventory_columns.search()):
    for order, label in enumerate(DEFAULT_COLUMNS, start=1):
      app_tables.inventory_columns.add_row(
        column_key=uuid.uuid4().hex,
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
  date_text = cell["entered_at"].strftime("%m/%d/%y")
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


@anvil.server.callable(require_user=True)
def get_inventory_grid():
  _ensure_default_grid()
  rows = _active_ordered(app_tables.inventory_rows)
  columns = _active_ordered(app_tables.inventory_columns)
  saved_cells = {
    (cell["row_key"], cell["column_key"]): cell
    for cell in app_tables.inventory_cells.search()
  }

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
        "entry_quantity": _format_quantity(saved["quantity"] if saved else None),
        "latest_display": _format_latest(saved),
      })
    grid_rows.append({
      "row_key": row["row_key"],
      "label": row["label"],
      "cells": row_cells,
    })

  return {
    "initials": _user_initials(anvil.users.get_user()),
    "rows": grid_rows,
    "columns": [
      {"column_key": column["column_key"], "label": column["label"]}
      for column in columns
    ],
    "row_labels": [row["label"] for row in rows],
    "column_labels": [column["label"] for column in columns],
  }


def _split_labels(raw_text):
  if not isinstance(raw_text, str):
    return None
  labels = [line.strip() for line in raw_text.splitlines() if line.strip()]
  if len({label.casefold() for label in labels}) != len(labels):
    return None
  return labels


def _reconcile_labels(table, labels, key_name):
  existing = list(table.search())
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


@anvil.server.callable(require_user=True)
def save_inventory_configuration(row_labels_text, column_labels_text):
  row_labels = _split_labels(row_labels_text)
  column_labels = _split_labels(column_labels_text)

  if row_labels is None or not 1 <= len(row_labels) <= MAX_ROWS:
    return {"ok": False, "message": f"Enter 1–{MAX_ROWS} unique row labels, one per line."}
  if column_labels is None or not 1 <= len(column_labels) <= MAX_COLUMNS:
    return {"ok": False, "message": f"Enter 1–{MAX_COLUMNS} unique quantity columns, one per line."}
  if any(len(label) > 60 for label in row_labels + column_labels):
    return {"ok": False, "message": "Keep each row and column label under 60 characters."}

  _reconcile_labels(app_tables.inventory_rows, row_labels, "row_key")
  _reconcile_labels(app_tables.inventory_columns, column_labels, "column_key")
  return {"ok": True}


@anvil.server.callable(require_user=True)
def save_grid_cell(row_key, column_key, raw_quantity):
  initials = _user_initials(anvil.users.get_user())
  if initials is None:
    return {"ok": False, "message": NO_INITIALS_MESSAGE}

  if not isinstance(row_key, str) or not isinstance(column_key, str):
    return {"ok": False, "message": "Refresh the table and try again."}
  row = app_tables.inventory_rows.get(row_key=row_key, active=True)
  column = app_tables.inventory_columns.get(column_key=column_key, active=True)
  if row is None or column is None:
    return {"ok": False, "message": "Refresh the table and try again."}

  quantity = _parse_quantity(raw_quantity)
  if quantity is None:
    return {
      "ok": False,
      "message": f"Enter a zero or greater number for {row['label']} · {column['label']}.",
    }

  entered_at = datetime.now()
  # search() rather than get(): a concurrent first save can leave a duplicate.
  latest = next(iter(app_tables.inventory_cells.search(row_key=row_key, column_key=column_key)), None)
  if latest is None:
    latest = app_tables.inventory_cells.add_row(row_key=row_key, column_key=column_key)
  latest.update(quantity=quantity, entered_by=initials, entered_at=entered_at)
  app_tables.inventory_history.add_row(
    entry_id=uuid.uuid4().hex,
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
