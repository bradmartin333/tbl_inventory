from ._anvil_designer import SectionListItemTemplate
from anvil import *
import anvil.users


class SectionListItem(SectionListItemTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    rows = self.item["row_count"]
    columns = self.item["column_count"]
    self.select_button.text = (
      f"{self.item['label']}  ·  {rows} row{'' if rows == 1 else 's'}"
      f"  ·  {columns} column{'' if columns == 1 else 's'}"
    )
    self.dom_nodes["item"].classList.toggle("is-selected", self.item["selected"])

  @handle("select_button", "click")
  def select_button_click(self, **event_args):
    # Sends the position, not the card: MainForm owns the list and its order.
    self.parent.raise_event("x-select-section", index=self.item["index"])
