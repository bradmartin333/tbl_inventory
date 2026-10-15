from datetime import datetime
import math
import uuid

import anvil.server
from anvil.tables import app_tables


DEFAULT_ITEMS = [
  ("espresso_beans", "Espresso beans", "kg"),
  ("decaf_beans", "Decaf beans", "kg"),
  ("whole_milk", "Whole milk", "L"),
  ("oat_milk", "Oat milk", "L"),
  ("almond_milk", "Almond milk", "L"),
  ("vanilla_syrup", "Vanilla syrup", "bottles"),
  ("caramel_syrup", "Caramel syrup", "bottles"),
  ("chocolate_sauce", "Chocolate sauce", "bottles"),
  ("chai_concentrate", "Chai concentrate", "cartons"),
  ("tea_bags", "Tea bags", "boxes"),
  ("cups_8oz", "8 oz hot cups", "sleeves"),
  ("cups_12oz", "12 oz hot cups", "sleeves"),
  ("cups_16oz", "16 oz hot cups", "sleeves"),
  ("cold_cups", "Cold cups", "sleeves"),
  ("hot_lids", "Hot cup lids", "sleeves"),
  ("cold_lids", "Cold cup lids", "sleeves"),
  ("cup_sleeves", "Cup sleeves", "sleeves"),
  ("napkins", "Napkins", "packs"),
  ("cleaning_tablets", "Cleaning tablets", "tubs"),
  ("sanitizer", "Sanitizer", "bottles"),
]


def _ensure_default_items():
  existing_keys = {
    item["item_key"]
    for item in app_tables.inventory_items.search()
  }

  for sort_order, (item_key, name, unit) in enumerate(DEFAULT_ITEMS, start=1):
    if item_key in existing_keys:
      continue
    app_tables.inventory_items.add_row(
      item_key=item_key,
      name=name,
      unit=unit,
      sort_order=sort_order,
      active=True,
      latest_entered_by="",
    )


def _format_quantity(quantity):
  if quantity is None:
    return ""
  return f"{quantity:g}"


@anvil.server.callable
def get_inventory_snapshot():
  _ensure_default_items()
  items = list(app_tables.inventory_items.search(active=True))
  items.sort(key=lambda item: item["sort_order"] or 0)

  return [
    {
      "item_key": item["item_key"],
      "name": item["name"],
      "unit": item["unit"],
      "entry_quantity": _format_quantity(item["latest_quantity"]),
      "latest_date_display": (
        item["latest_entered_at"].strftime("%b %d, %Y")
        if item["latest_entered_at"] else "—"
      ),
      "latest_by_display": item["latest_entered_by"] or "—",
    }
    for item in items
  ]


@anvil.server.callable
def save_inventory(initials, entry_values):
  if not isinstance(initials, str):
    return {"ok": False, "message": "Enter 1–5 letters for your initials."}

  initials = initials.strip().upper()
  if not initials.isalpha() or not 1 <= len(initials) <= 5:
    return {"ok": False, "message": "Enter 1–5 letters for your initials."}

  _ensure_default_items()
  active_items = list(app_tables.inventory_items.search(active=True))
  items_by_key = {item["item_key"]: item for item in active_items}

  if not isinstance(entry_values, list):
    return {"ok": False, "message": "Reload the inventory and try again."}

  quantities = {}
  for entry in entry_values:
    if not isinstance(entry, dict):
      return {"ok": False, "message": "Reload the inventory and try again."}

    item_key = entry.get("item_key")
    if not isinstance(item_key, str):
      return {"ok": False, "message": "Reload the inventory and try again."}
    item = items_by_key.get(item_key)
    if item is None or item_key in quantities:
      return {"ok": False, "message": "Reload the inventory and try again."}

    raw_quantity = entry.get("quantity")
    if raw_quantity is None or (isinstance(raw_quantity, str) and not raw_quantity.strip()):
      return {"ok": False, "message": f"Enter a quantity for {item['name']}."}

    try:
      quantity = float(raw_quantity)
    except (TypeError, ValueError):
      return {"ok": False, "message": f"Enter a valid quantity for {item['name']}."}

    if not math.isfinite(quantity) or quantity < 0:
      return {"ok": False, "message": f"Enter a quantity of zero or more for {item['name']}."}

    quantities[item_key] = quantity

  if set(quantities) != set(items_by_key):
    return {"ok": False, "message": "Reload the inventory and try again."}

  entered_at = datetime.now()
  entry_id = uuid.uuid4().hex
  for item_key, item in items_by_key.items():
    quantity = quantities[item_key]
    app_tables.inventory_entries.add_row(
      entry_id=entry_id,
      item_key=item_key,
      item_name=item["name"],
      quantity=quantity,
      entered_by=initials,
      entered_at=entered_at,
    )
    item["latest_quantity"] = quantity
    item["latest_entered_by"] = initials
    item["latest_entered_at"] = entered_at

  return {"ok": True}
