from ._anvil_designer import MainFormTemplate
from anvil import *
import anvil.users
import anvil.server
from anvil.js import window
import time

NO_INITIALS_MESSAGE = (
  "Your account has no initials yet, so counts are view-only. "
  "Ask an admin to add 1–5 letters to your account, then reload this page."
)


class MainForm(MainFormTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self.user = anvil.users.get_user() or self._log_in_or_activate()
    self.user_email_label.text = self.user["email"]
    self._error_notification = None
    self._saves_in_flight = 0
    self._wizard_cells = []
    self._wizard_index = 0
    self.rows_panel.add_event_handler("x-save-cell", self._save_grid_cell)
    self._set_active_tab("grid")
    self._load_latest_counts()

  def _log_in_or_activate(self):
    # Anvil's own sign-up tab is off so strangers can't make accounts; an
    # admin-added email activates here instead.
    while True:
      choice = alert(
        "Log in, or activate the account an admin set up for you.",
        title="TBL Inventory",
        buttons=[("Log in", "login"), ("Activate account", "activate")],
        dismissible=False,
      )
      if choice == "login":
        user = anvil.users.login_with_form(allow_cancel=True)
        if user:
          return user
      else:
        self._activate_account()

  def _activate_account(self):
    email_box = TextBox(placeholder="Email", type="email")
    password_box = TextBox(placeholder="Password", hide_text=True)
    repeat_box = TextBox(placeholder="Repeat password", hide_text=True)
    panel = ColumnPanel()
    for box in (email_box, password_box, repeat_box):
      panel.add_component(box)

    while alert(panel, title="Activate account", buttons=[("Activate", True), ("Back", False)]):
      if password_box.text != repeat_box.text:
        Notification("Passwords don't match.", style="warning").show()
        continue
      result = anvil.server.call("activate_account", email_box.text, password_box.text)
      if result["ok"]:
        alert(
          "Check your email for a confirmation link, then log in with your new password.",
          title="Almost done",
        )
        return
      Notification(result["message"], style="warning").show()

  def _set_active_tab(self, active_tab):
    panels = {
      "grid": self.grid_entry_panel,
      "guided": self.guided_panel,
      "customize": self.table_editor_panel,
      "charts": self.charts_panel,
      "digest": self.digest_panel,
    }
    buttons = {
      "grid": self.grid_tab_button,
      "guided": self.guided_tab_button,
      "customize": self.customize_tab_button,
      "charts": self.charts_tab_button,
      "digest": self.digest_tab_button,
    }

    for tab_name, panel in panels.items():
      panel.visible = tab_name == active_tab
      buttons[tab_name].enabled = tab_name != active_tab

  def _load_latest_counts(self):
    snapshot = anvil.server.call("get_inventory_grid")
    self._snapshot = snapshot
    # The server vets the account's initials; without them every save would be refused.
    self._can_enter = snapshot["initials"] is not None
    self.user_initials_label.text = snapshot["initials"] or "—"
    for row in snapshot["rows"]:
      for cell in row["cells"]:
        cell["editable"] = self._can_enter
    # Rebuilding the rows briefly collapses the page, so keep the reader's place.
    scroll_y = window.scrollY
    self.column_headers_panel.items = snapshot["columns"]
    self.rows_panel.items = snapshot["rows"]
    window.scrollTo(window.scrollX, scroll_y)
    if not self._can_enter:
      self._show_error(NO_INITIALS_MESSAGE)

  def _show_error(self, message):
    # Keep one warning on screen; a run of failed saves would otherwise stack them.
    if self._error_notification is not None:
      self._error_notification.hide()
    self._error_notification = Notification(message, style="warning", timeout=None)
    self._error_notification.show()

  def _open_table_editor(self):
    self.row_labels_area.text = "\n".join(self._snapshot["row_labels"])
    self.column_labels_area.text = "\n".join(self._snapshot["column_labels"])
    self._set_active_tab("customize")

  def _start_guided_entry(self):
    self._wizard_cells = [
      (row, cell)
      for row in self.rows_panel.items
      for cell in row["cells"]
    ]
    self._wizard_index = 0
    self._show_wizard_step()

  def _show_wizard_step(self):
    total_steps = len(self._wizard_cells)
    complete = self._wizard_index >= total_steps
    self.dom_nodes["wizard_quantity_field"].style.display = "none" if complete else ""
    self.dom_nodes["wizard_quick_quantities"].style.display = "none" if complete else ""
    self.wizard_zero_button.visible = not complete
    self.wizard_next_button.visible = not complete
    self.wizard_close_button.visible = complete
    if complete:
      self.wizard_step_label.text = "Guided entry complete"
      self.wizard_target_label.text = "All cells have been reviewed."
      return

    row, cell = self._wizard_cells[self._wizard_index]
    self.wizard_step_label.text = f"Cell {self._wizard_index + 1} of {total_steps}"
    self.wizard_target_label.text = f"{row['label']}  ·  {cell['column_label']}"
    self.wizard_quantity_box.text = cell["entry_quantity"]
    self.wizard_next_button.text = (
      "Finish" if self._wizard_index == total_steps - 1 else "Next"
    )

  def _save_wizard_step(self, quantity):
    row, cell = self._wizard_cells[self._wizard_index]
    self.wizard_next_button.enabled = False
    self.wizard_zero_button.enabled = False
    try:
      result = anvil.server.call(
        "save_grid_cell",
        row["row_key"],
        cell["column_key"],
        quantity,
      )
    finally:
      self.wizard_next_button.enabled = True
      self.wizard_zero_button.enabled = True

    if not result["ok"]:
      self.wizard_quantity_box.text = cell["entry_quantity"]
      self._show_error(result["message"])
      return

    # Advance before reloading so the old step's buttons don't linger during the call.
    self._wizard_index += 1
    self._show_wizard_step()
    self._load_latest_counts()

  @handle("grid_tab_button", "click")
  def grid_tab_button_click(self, **event_args):
    self._set_active_tab("grid")

  @handle("guided_tab_button", "click")
  def guided_tab_button_click(self, **event_args):
    if not self._can_enter:
      self._show_error(NO_INITIALS_MESSAGE)
      return
    self._start_guided_entry()
    self._set_active_tab("guided")

  @handle("customize_tab_button", "click")
  def customize_tab_button_click(self, **event_args):
    self._open_table_editor()

  @handle("charts_tab_button", "click")
  def charts_tab_button_click(self, **event_args):
    self._set_active_tab("charts")

  @handle("digest_tab_button", "click")
  def digest_tab_button_click(self, **event_args):
    self._set_active_tab("digest")

  @handle("logout_button", "click")
  def logout_button_click(self, **event_args):
    # Pressing this button blurs a focused grid cell, which starts its save;
    # let that land while the session is still logged in.
    deadline = time.time() + 5
    while self._saves_in_flight and time.time() < deadline:
      time.sleep(0.05)
    anvil.users.logout()
    # Reload rather than open_form so this user's grid and email don't sit
    # behind the next person's login dialog.
    window.location.reload()

  @handle("refresh_button", "click")
  def refresh_button_click(self, **event_args):
    self._load_latest_counts()

  def _save_grid_cell(self, cell, quantity, **event_args):
    # Silent call: no loading overlay while the user moves between cells.
    self._saves_in_flight += 1
    try:
      result = anvil.server.call_s(
        "save_grid_cell",
        cell.item["row_key"],
        cell.item["column_key"],
        quantity,
      )
    finally:
      self._saves_in_flight -= 1
    if not result["ok"]:
      cell.revert()
      self._show_error(result["message"])
      return

    cell.show_saved(result["entry_quantity"], result["latest_display"])

  @handle("save_setup_button", "click")
  def save_setup_button_click(self, **event_args):
    self.save_setup_button.enabled = False
    try:
      result = anvil.server.call(
        "save_inventory_configuration",
        self.row_labels_area.text,
        self.column_labels_area.text,
      )
    finally:
      self.save_setup_button.enabled = True

    if not result["ok"]:
      self._show_error(result["message"])
      return

    self._wizard_cells = []
    self._set_active_tab("grid")
    self._load_latest_counts()

  @handle("cancel_setup_button", "click")
  def cancel_setup_button_click(self, **event_args):
    self._set_active_tab("grid")

  @handle("wizard_next_button", "click")
  def wizard_next_button_click(self, **event_args):
    self._save_wizard_step(self.wizard_quantity_box.text)

  @handle("wizard_zero_button", "click")
  def wizard_zero_button_click(self, **event_args):
    self.wizard_quantity_box.text = "0"
    self._save_wizard_step("0")

  def _wizard_quantity_value(self):
    try:
      return max(float((self.wizard_quantity_box.text or "").strip() or 0), 0)
    except ValueError:
      return 0

  def _set_wizard_quantity(self, quantity):
    self.wizard_quantity_box.text = f"{quantity:g}"

  @handle("wizard_quarter_button", "click")
  def wizard_quarter_button_click(self, **event_args):
    self._set_wizard_quantity(0.25)

  @handle("wizard_half_button", "click")
  def wizard_half_button_click(self, **event_args):
    self._set_wizard_quantity(0.5)

  @handle("wizard_three_quarters_button", "click")
  def wizard_three_quarters_button_click(self, **event_args):
    self._set_wizard_quantity(0.75)

  @handle("wizard_plus_one_button", "click")
  def wizard_plus_one_button_click(self, **event_args):
    self._set_wizard_quantity(self._wizard_quantity_value() + 1)

  @handle("wizard_close_button", "click")
  def wizard_close_button_click(self, **event_args):
    self._set_active_tab("grid")
