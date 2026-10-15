from datetime import datetime
import math
import uuid

import anvil.server
from anvil.tables import app_tables


DEFAULT_ROWS = ["Item 1", "Item 2", "Item 3"]
DEFAULT_COLUMNS = ["Quantity", "Small containers", "Large containers"]
MAX_ROWS = 50
MAX_COLUMNS = 12


def _get_settings():
  rows = list(app_tables.inventory_settings.search(settings_key="main"))
  if rows:
    return rows[0]
  return app_tables.inventory_settings.add_row(
    settings_key="main",
    title="Inventory Tracker",
    row_heading="Item",
  )


def _ensure_default_grid():
  _get_settings()
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
  date_text = cell["entered_at"].strftime("%b %d, %Y")
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


def _active_ordered(table, key_name):
  items = list(table.search(active=True))
  items.sort(key=lambda item: item["sort_order"] or 0)
  return items


def _get_or_create_cell(row_key, column_key):
  matches = list(app_tables.inventory_cells.search(
    row_key=row_key,
    column_key=column_key,
  ))
  if matches:
    return matches[0]
  return app_tables.inventory_cells.add_row(
    row_key=row_key,
    column_key=column_key,
    quantity=0,
    entered_by="",
    entered_at=datetime(1970, 1, 1),
  )


@anvil.server.callable
def get_inventory_grid():
  _ensure_default_grid()
  settings = _get_settings()
  rows = _active_ordered(app_tables.inventory_rows, "row_key")
  columns = _active_ordered(app_tables.inventory_columns, "column_key")
  saved_cells = {
    (cell["row_key"], cell["column_key"]): cell
    for cell in app_tables.inventory_cells.search()
  }

  latest_update = None
  grid_rows = []
  for row in rows:
    row_cells = []
    for column in columns:
      key = (row["row_key"], column["column_key"])
      saved = saved_cells.get(key)
      if saved and saved["entered_at"]:
        if latest_update is None or saved["entered_at"] > latest_update["entered_at"]:
          latest_update = saved
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

  latest_update_display = "No values entered yet"
  if latest_update:
    latest_date = latest_update["entered_at"].strftime("%b %d, %Y")
    latest_update_display = f"{latest_update['entered_by']} · {latest_date}"

  return {
    "settings": {
      "title": settings["title"],
      "row_heading": settings["row_heading"],
    },
    "rows": grid_rows,
    "columns": [
      {"column_key": column["column_key"], "label": column["label"]}
      for column in columns
    ],
    "row_labels": [row["label"] for row in rows],
    "column_labels": [column["label"] for column in columns],
    "latest_update_display": latest_update_display,
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
  existing.sort(key=lambda item: item["sort_order"] or 0)
  by_label = {
    item["label"].strip().casefold(): item
    for item in existing
    if item["label"]
  }
  assigned = [by_label.get(label.casefold()) for label in labels]
  used_keys = {
    item[key_name] for item in assigned if item is not None
  }

  for index, label in enumerate(labels):
    item = assigned[index]
    if item is None:
      item = next(
        (candidate for candidate in existing if candidate[key_name] not in used_keys),
        None,
      )
      if item is None:
        item = table.add_row(
          **{
            key_name: uuid.uuid4().hex,
            "label": label,
            "sort_order": index + 1,
            "active": True,
          }
        )
        existing.append(item)
      assigned[index] = item
      used_keys.add(item[key_name])

    item["label"] = label
    item["sort_order"] = index + 1
    item["active"] = True

  for item in existing:
    if item[key_name] not in used_keys:
      item["active"] = False


@anvil.server.callable
def save_inventory_configuration(title, row_heading, row_labels_text, column_labels_text):
  title = title.strip() if isinstance(title, str) else ""
  row_heading = row_heading.strip() if isinstance(row_heading, str) else ""
  row_labels = _split_labels(row_labels_text)
  column_labels = _split_labels(column_labels_text)

  if not title or len(title) > 80:
    return {"ok": False, "message": "Enter a table title up to 80 characters long."}
  if not row_heading or len(row_heading) > 40:
    return {"ok": False, "message": "Enter a first-column heading up to 40 characters long."}
  if row_labels is None or not 1 <= len(row_labels) <= MAX_ROWS:
    return {"ok": False, "message": f"Enter 1–{MAX_ROWS} unique row labels, one per line."}
  if column_labels is None or not 1 <= len(column_labels) <= MAX_COLUMNS:
    return {"ok": False, "message": f"Enter 1–{MAX_COLUMNS} unique quantity columns, one per line."}
  if any(len(label) > 60 for label in row_labels + column_labels):
    return {"ok": False, "message": "Keep each row and column label under 60 characters."}

  _ensure_default_grid()
  settings = _get_settings()
  settings["title"] = title
  settings["row_heading"] = row_heading
  _reconcile_labels(app_tables.inventory_rows, row_labels, "row_key")
  _reconcile_labels(app_tables.inventory_columns, column_labels, "column_key")
  return {"ok": True}


def _save_grid_values(initials, cell_values, skip_blank):
  if not isinstance(initials, str):
    return {"ok": False, "message": "Enter 1–5 letters for your initials."}
  initials = initials.strip().upper()
  if not initials.isalpha() or not 1 <= len(initials) <= 5:
    return {"ok": False, "message": "Enter 1–5 letters for your initials."}

  _ensure_default_grid()
  rows_by_key = {
    row["row_key"]: row
    for row in app_tables.inventory_rows.search(active=True)
  }
  columns_by_key = {
    column["column_key"]: column
    for column in app_tables.inventory_columns.search(active=True)
  }
  if not isinstance(cell_values, list):
    return {"ok": False, "message": "Refresh the table and try again."}

  submitted = set()
  values_to_save = []
  for value in cell_values:
    if not isinstance(value, dict):
      return {"ok": False, "message": "Refresh the table and try again."}
    row_key = value.get("row_key")
    column_key = value.get("column_key")
    if not isinstance(row_key, str) or not isinstance(column_key, str):
      return {"ok": False, "message": "Refresh the table and try again."}
    row = rows_by_key.get(row_key)
    column = columns_by_key.get(column_key)
    cell_key = (row_key, column_key)
    if row is None or column is None or cell_key in submitted:
      return {"ok": False, "message": "Refresh the table and try again."}
    submitted.add(cell_key)

    raw_quantity = value.get("quantity")
    if skip_blank and (raw_quantity is None or (isinstance(raw_quantity, str) and not raw_quantity.strip())):
      continue
    quantity = _parse_quantity(raw_quantity)
    if quantity is None:
      return {
        "ok": False,
        "message": f"Enter a zero or greater number for {row['label']} · {column['label']}.",
      }
    values_to_save.append((row, column, quantity))

  if not values_to_save:
    return {"ok": False, "message": "Enter a quantity in at least one cell."}

  entered_at = datetime.now()
  entry_id = uuid.uuid4().hex
  for row, column, quantity in values_to_save:
    latest = _get_or_create_cell(row["row_key"], column["column_key"])
    latest["quantity"] = quantity
    latest["entered_by"] = initials
    latest["entered_at"] = entered_at
    app_tables.inventory_history.add_row(
      entry_id=entry_id,
      row_key=row["row_key"],
      row_label=row["label"],
      column_key=column["column_key"],
      column_label=column["label"],
      quantity=quantity,
      entered_by=initials,
      entered_at=entered_at,
    )

  return {"ok": True, "saved_count": len(values_to_save)}


@anvil.server.callable
def save_grid_counts(initials, cell_values):
  return _save_grid_values(initials, cell_values, skip_blank=True)


@anvil.server.callable
def save_grid_cell(initials, row_key, column_key, quantity):
  return _save_grid_values(
    initials,
    [{"row_key": row_key, "column_key": column_key, "quantity": quantity}],
    skip_blank=False,
  )
