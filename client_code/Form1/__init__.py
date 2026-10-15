from ._anvil_designer import Form1Template
from anvil import *
import anvil.server


class Form1(Form1Template):
  def __init__(self, **properties):
    super().__init__(**properties)
    self.inventory_panel.items = anvil.server.call("get_inventory_snapshot")
    self.status_label.text = "Latest counts are shared with everyone who opens this app."

  @handle("save_button", "click")
  def save_button_click(self, **event_args):
    initials = (self.initials_box.text or "").strip().upper()
    if not initials.isalpha() or not 1 <= len(initials) <= 5:
      self.status_label.text = "Enter 1–5 letters for your initials."
      return

    entry_values = [
      {
        "item_key": item["item_key"],
        "quantity": item["entry_quantity"],
      }
      for item in self.inventory_panel.items
    ]

    self.save_button.enabled = False
    try:
      result = anvil.server.call("save_inventory", initials, entry_values)
    finally:
      self.save_button.enabled = True

    if not result["ok"]:
      self.status_label.text = result["message"]
      return

    self.inventory_panel.items = anvil.server.call("get_inventory_snapshot")
    self.status_label.text = "Inventory saved. The latest counts are now visible to everyone."
