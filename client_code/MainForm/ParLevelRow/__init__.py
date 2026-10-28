from ._anvil_designer import ParLevelRowTemplate
from anvil import *
import anvil.users


class ParLevelRow(ParLevelRowTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._saved = (self.item["par_text"], self.item["days_text"])
    self._saving = False
    self._show_flags()

  def _show_flags(self):
    self.dom_nodes["row"].classList.toggle("is-below-par", self.item["below_par"])
    self.dom_nodes["row"].classList.toggle("is-overdue", self.item["overdue"])

  def show_saved(self, result):
    self._saved = (result["par_text"], result["days_text"])
    for name in ("par_text", "days_text", "below_par", "overdue"):
      self.item[name] = result[name]
    self.refresh_data_bindings()
    self._show_flags()

  def revert(self):
    self.item["par_text"], self.item["days_text"] = self._saved
    self.refresh_data_bindings()

  def _save_if_changed(self):
    # Both boxes go together, so leaving either one saves the pair.
    entered = ((self.par_box.text or "").strip(), (self.days_box.text or "").strip())
    if self._saving or entered == self._saved:
      return

    self._saving = True
    try:
      self.parent.raise_event("x-save-par", row=self, par=entered[0], days=entered[1])
    finally:
      self._saving = False

  @handle("par_box", "lost_focus")
  def par_box_lost_focus(self, **event_args):
    self._save_if_changed()

  @handle("par_box", "pressed_enter")
  def par_box_pressed_enter(self, **event_args):
    self._save_if_changed()

  @handle("days_box", "lost_focus")
  def days_box_lost_focus(self, **event_args):
    self._save_if_changed()

  @handle("days_box", "pressed_enter")
  def days_box_pressed_enter(self, **event_args):
    self._save_if_changed()
