from ._anvil_designer import ParAlertItemTemplate
from anvil import *
import anvil.users


class ParAlertItem(ParAlertItemTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    # The detail text names the problem; the class only adds its colour.
    self.dom_nodes["item"].classList.toggle("is-below-par", self.item["below_par"])
    self.dom_nodes["item"].classList.toggle("is-overdue", self.item["overdue"])
