from ._anvil_designer import GridCellTemplate
from anvil import *
import anvil.users

# What a saved count sends back about its cell.
SAVED_FIELDS = (
  "entry_quantity", "latest_display", "par_text", "days_text", "below_par", "overdue", "alert_text",
)


class GridCell(GridCellTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._saved_text = self.item["entry_quantity"]
    self._saving = False
    self.quantity_box.enabled = self.item["editable"]
    self._show_flags()

  def _show_flags(self):
    # The stylesheet marks a cell under its par level or past its count interval.
    self.dom_nodes["cell"].classList.toggle("is-below-par", self.item["below_par"])
    self.dom_nodes["cell"].classList.toggle("is-overdue", self.item["overdue"])

  def show_saved(self, result):
    # The item is MainForm's own copy of this cell, so Analytics sees the change too.
    self._saved_text = result["entry_quantity"]
    for name in SAVED_FIELDS:
      self.item[name] = result[name]
    self.refresh_data_bindings()
    self._show_flags()

  def revert(self):
    self.item["entry_quantity"] = self._saved_text
    self.refresh_data_bindings()

  def _save_if_changed(self):
    text = (self.quantity_box.text or "").strip()
    if self._saving or text == self._saved_text:
      return
    if not text:
      # A saved quantity can't be cleared, so restore it.
      self.revert()
      return

    self._saving = True
    try:
      self.parent.raise_event("x-save-cell", cell=self, quantity=text)
    finally:
      self._saving = False

  @handle("quantity_box", "lost_focus")
  def quantity_box_lost_focus(self, **event_args):
    self._save_if_changed()

  @handle("quantity_box", "pressed_enter")
  def quantity_box_pressed_enter(self, **event_args):
    self._save_if_changed()
