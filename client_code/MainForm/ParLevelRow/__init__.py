from ._anvil_designer import ParLevelRowTemplate
from anvil import *
import anvil.users


class ParLevelRow(ParLevelRowTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._saved = (self.item["par_text"], self.item["days_text"])
    self._saving = False
    self._sent = self._saved
    self._show_flags()

  def _show_flags(self):
    self.dom_nodes["row"].classList.toggle("is-below-par", self.item["below_par"])
    self.dom_nodes["row"].classList.toggle("is-overdue", self.item["overdue"])

  def _boxes(self):
    return ((self.par_box, "par_text"), (self.days_box, "days_text"))

  def _entered(self):
    return tuple((box.text or "").strip() for box, _ in self._boxes())

  def _settle(self, values):
    # Anvil runs other events while a save is out, so a box may have been
    # edited since it was sent. Only a box still holding what was sent takes
    # the settled value; an edited one keeps the edit for the next save.
    for (box, name), sent, value in zip(self._boxes(), self._sent, values):
      if (box.text or "").strip() == sent:
        box.text = value
        self.item[name] = value

  def show_saved(self, result):
    self._saved = (result["par_text"], result["days_text"])
    self._settle(self._saved)
    self.item["below_par"] = result["below_par"]
    self.item["overdue"] = result["overdue"]
    self._show_flags()

  def revert(self):
    self._settle(self._saved)

  def _save_if_changed(self):
    # Both boxes go together, so leaving either one saves the pair. A box
    # left while a save is out is picked up when that save lands.
    if self._saving:
      return
    self._saving = True
    try:
      # Send again only for an edit made since the last send, so a save that
      # was refused (or never answered) isn't retried over and over.
      last_sent = None
      while self._entered() not in (self._saved, last_sent):
        self._sent = last_sent = self._entered()
        self.parent.raise_event("x-save-par", row=self, par=self._sent[0], days=self._sent[1])
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
