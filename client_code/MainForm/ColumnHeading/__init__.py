from ._anvil_designer import ColumnHeadingTemplate
from anvil import *
import anvil.users


class ColumnHeading(ColumnHeadingTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
