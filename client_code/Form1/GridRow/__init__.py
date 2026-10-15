from ._anvil_designer import GridRowTemplate
from anvil import *


class GridRow(GridRowTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self.cells_panel.items = self.item["cells"]
