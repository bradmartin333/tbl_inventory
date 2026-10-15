from ._anvil_designer import GridRowTemplate
from anvil import *
import anvil.users


class GridRow(GridRowTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self.cells_panel.items = self.item["cells"]
    self.cells_panel.add_event_handler("x-save-cell", self._forward_save_cell)

  def _forward_save_cell(self, cell, quantity, **event_args):
    self.parent.raise_event("x-save-cell", cell=cell, quantity=quantity)
