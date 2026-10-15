from ._anvil_designer import GridCellTemplate
from anvil import *


class GridCell(GridCellTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)

  @handle("quantity_box", "change")
  def quantity_box_change(self, **event_args):
    self.item["entry_quantity"] = self.quantity_box.text
