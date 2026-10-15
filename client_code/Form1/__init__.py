from ._anvil_designer import Form1Template
from anvil import *
import anvil.server


class Form1(Form1Template):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._wizard_cells = []
    self._wizard_index = 0
    self.table_editor_panel.visible = False
    self.guided_panel.visible = False
    self._load_latest_counts()

  def _load_latest_counts(self):
    snapshot = anvil.server.call("get_inventory_grid")
    self._snapshot = snapshot
    self.title_label.text = snapshot["settings"]["title"]
    self.latest_stocktake_label.text = snapshot["latest_update_display"]
    self.matrix_row_heading.text = snapshot["settings"]["row_heading"]
    self.column_headers_panel.items = snapshot["columns"]
    self.rows_panel.items = snapshot["rows"]

  def _open_table_editor(self):
    settings = self._snapshot["settings"]
    self.table_title_box.text = settings["title"]
    self.row_heading_box.text = settings["row_heading"]
    self.row_labels_area.text = "\n".join(self._snapshot["row_labels"])
    self.column_labels_area.text = "\n".join(self._snapshot["column_labels"])
    self.table_editor_panel.visible = True
    self.guided_panel.visible = False

  def _show_wizard_step(self):
    total_steps = len(self._wizard_cells)
    if self._wizard_index >= total_steps:
      self.wizard_step_label.text = "Guided entry complete"
      self.wizard_target_label.text = "All cells have been reviewed."
      self.wizard_quantity_box.visible = False
      self.wizard_save_button.visible = False
      self.wizard_skip_button.visible = False
      return

    row, cell = self._wizard_cells[self._wizard_index]
    self.wizard_step_label.text = f"Cell {self._wizard_index + 1} of {total_steps}"
    self.wizard_target_label.text = f"{row['label']}  ·  {cell['column_label']}"
    self.wizard_quantity_box.text = cell["entry_quantity"]
    self.wizard_quantity_box.visible = True
    self.wizard_save_button.visible = True
    self.wizard_skip_button.visible = True
    self.wizard_save_button.text = (
      "Save & Finish" if self._wizard_index == total_steps - 1 else "Save & Next"
    )

  @handle("save_grid_button", "click")
  def save_grid_button_click(self, **event_args):
    initials = (self.initials_box.text or "").strip().upper()
    if not initials.isalpha() or not 1 <= len(initials) <= 5:
      self.status_label.text = "Enter 1–5 letters for your initials."
      return

    cell_values = []
    for row in self.rows_panel.items:
      for cell in row["cells"]:
        cell_values.append({
          "row_key": row["row_key"],
          "column_key": cell["column_key"],
          "quantity": cell["entry_quantity"],
        })

    self.save_grid_button.enabled = False
    try:
      result = anvil.server.call("save_grid_counts", initials, cell_values)
    finally:
      self.save_grid_button.enabled = True

    if not result["ok"]:
      self.status_label.text = result["message"]
      return

    self._load_latest_counts()
    self.status_label.text = "Grid counts saved and shared."

  @handle("refresh_button", "click")
  def refresh_button_click(self, **event_args):
    self._load_latest_counts()
    self.status_label.text = "Latest shared values refreshed."

  @handle("customize_button", "click")
  def customize_button_click(self, **event_args):
    if self.table_editor_panel.visible:
      self.table_editor_panel.visible = False
    else:
      self._open_table_editor()

  @handle("cancel_setup_button", "click")
  def cancel_setup_button_click(self, **event_args):
    self.table_editor_panel.visible = False

  @handle("save_setup_button", "click")
  def save_setup_button_click(self, **event_args):
    self.save_setup_button.enabled = False
    try:
      result = anvil.server.call(
        "save_inventory_configuration",
        self.table_title_box.text,
        self.row_heading_box.text,
        self.row_labels_area.text,
        self.column_labels_area.text,
      )
    finally:
      self.save_setup_button.enabled = True

    if not result["ok"]:
      self.status_label.text = result["message"]
      return

    self.table_editor_panel.visible = False
    self._load_latest_counts()
    self.status_label.text = "Table setup saved. Existing history is retained."

  @handle("guided_button", "click")
  def guided_button_click(self, **event_args):
    if self.guided_panel.visible:
      self.guided_panel.visible = False
      return

    self._wizard_cells = [
      (row, cell)
      for row in self.rows_panel.items
      for cell in row["cells"]
    ]
    self._wizard_index = 0
    self.table_editor_panel.visible = False
    self.guided_panel.visible = True
    self._show_wizard_step()

  @handle("wizard_save_button", "click")
  def wizard_save_button_click(self, **event_args):
    initials = (self.initials_box.text or "").strip().upper()
    if not initials.isalpha() or not 1 <= len(initials) <= 5:
      self.status_label.text = "Enter 1–5 letters for your initials."
      return

    row, cell = self._wizard_cells[self._wizard_index]
    self.wizard_save_button.enabled = False
    try:
      result = anvil.server.call(
        "save_grid_cell",
        initials,
        row["row_key"],
        cell["column_key"],
        self.wizard_quantity_box.text,
      )
    finally:
      self.wizard_save_button.enabled = True

    if not result["ok"]:
      self.status_label.text = result["message"]
      return

    self._load_latest_counts()
    self.status_label.text = "Cell saved."
    self._wizard_index += 1
    self._show_wizard_step()

  @handle("wizard_skip_button", "click")
  def wizard_skip_button_click(self, **event_args):
    self._wizard_index += 1
    self._show_wizard_step()

  @handle("wizard_close_button", "click")
  def wizard_close_button_click(self, **event_args):
    self.guided_panel.visible = False
