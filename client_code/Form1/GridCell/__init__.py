from ._anvil_designer import GridCellTemplate
from anvil import *
import anvil.users


class GridCell(GridCellTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._saved_text = self.item["entry_quantity"]
    self._saving = False

  def show_saved(self, entry_quantity, latest_display):
    self._saved_text = entry_quantity
    self.item["entry_quantity"] = entry_quantity
    self.item["latest_display"] = latest_display
    self.refresh_data_bindings()

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
