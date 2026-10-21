from ._anvil_designer import SectionEditorTemplate
from anvil import *
import anvil.users


class SectionEditor(SectionEditorTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
