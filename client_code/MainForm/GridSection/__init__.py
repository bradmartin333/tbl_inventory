from ._anvil_designer import GridSectionTemplate
from anvil import *
import anvil.users


class GridSection(GridSectionTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    # A lone section has nothing to open or close, so it keeps today's look.
    self.toggle_button.visible = self.item["show_toggle"]
    self.column_headers_panel.items = self.item["columns"]
    # The stylesheet sizes the grid from this so extra columns scroll, not squash.
    self.dom_nodes["matrix"].style.setProperty("--matrix-columns", str(len(self.item["columns"])))
    self.rows_panel.add_event_handler("x-save-cell", self._forward_save_cell)
    self._show_expanded()

  def set_expanded(self, expanded):
    if expanded != self.item["expanded"]:
      self.item["expanded"] = expanded
      self._show_expanded()

  def _show_expanded(self):
    expanded = self.item["expanded"]
    count = len(self.item["rows"])
    self.toggle_button.text = (
      f"{'▾' if expanded else '▸'}  {self.item['label']}  ·  "
      f"{count} item{'' if count == 1 else 's'}"
    )
    self.dom_nodes["matrix_scroll"].style.display = "" if expanded else "none"
    # Lets the stylesheet rule off the title bar only when the grid is under it.
    self.dom_nodes["section"].classList.toggle("is-expanded", expanded)
    # A closed section builds no cells, which keeps a cheap tablet quick.
    self.rows_panel.items = self.item["rows"] if expanded else []

  def _forward_save_cell(self, cell, quantity, **event_args):
    self.parent.raise_event("x-save-cell", cell=cell, quantity=quantity)

  @handle("toggle_button", "click")
  def toggle_button_click(self, **event_args):
    self.set_expanded(not self.item["expanded"])
