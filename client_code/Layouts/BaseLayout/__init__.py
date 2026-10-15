from ._anvil_designer import BaseLayoutTemplate
from anvil import *
import anvil.users


class BaseLayout(BaseLayoutTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
