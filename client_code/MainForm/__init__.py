from ._anvil_designer import MainFormTemplate
from anvil import *
import anvil.users
import anvil.server
from anvil.js import get_dom_node, window
import time
from datetime import datetime

NO_INITIALS_MESSAGE = (
  "Your account has no initials yet, so counts are view-only. "
  "Ask an admin to add 1–5 letters to your account, then reload this page."
)


class MainForm(MainFormTemplate):
  def __init__(self, **properties):
    super().__init__(**properties)
    self._finish_emailed_password_reset()
    self.user = anvil.users.get_user() or self._log_in_or_activate()
    self.user_email_label.text = self.user["email"]
    self._show_current_datetime()
    self._error_notification = None
    self._saves_in_flight = 0
    self._snapshot = None
    self._section_cards = []
    self._active_card = None
    # Anvil has no caret events, so watch the box itself for the line in use.
    self._sections_node = get_dom_node(self.section_labels_area)
    for event_name in ("keyup", "pointerup", "input", "focus"):
      self._sections_node.addEventListener(event_name, self._on_sections_caret)
    self._wizard_cells = []
    self._wizard_index = 0
    self.tables_panel.add_event_handler("x-save-cell", self._save_grid_cell)
    self._set_active_tab("grid")
    self._load_latest_counts()

  def _finish_emailed_password_reset(self):
    # Activation links are password-reset links. Left to get_user(), Anvil sets
    # the new password and then falls back to whoever is remembered in this
    # browser, so the new user could never get in on a shared machine. Spot the
    # pending reset ourselves (the same private call get_user() makes) and
    # forget the remembered user once the password is set.
    try:
      anvil.server.call("anvil.private.users.get_current_user", allow_remembered=False)
      return
    except anvil.users.PasswordResetRequested:
      pass
    anvil.users.get_user(allow_remembered=False)  # shows Anvil's set-password form
    anvil.users.logout()
    alert("Log in with your new password to continue.", title="Password updated")

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
    # Errors live inside the dialog: a Notification would sit behind the
    # alert as soon as the loop reopens it.
    error_label = Label(foreground="#b3261e", visible=False)
    panel = ColumnPanel()
    panel.add_component(email_box)
    panel.add_component(error_label)

    while alert(panel, title="Activate account", buttons=[("Send link", True), ("Back", False)]):
      result = anvil.server.call("activate_account", email_box.text)
      if result["ok"]:
        alert(
          "Check your email for a link to set your password, then log in with it.",
          title="Almost done",
        )
        return
      error_label.text = result["message"]
      error_label.visible = True

  def _show_current_datetime(self):
    now = datetime.now()
    hour = now.hour % 12 or 12
    self.current_datetime_label.text = (
      f"{now.strftime('%a %b')} {now.day}, {hour}:{now.minute:02d} "
      f"{'AM' if now.hour < 12 else 'PM'}"
    )

  @handle("clock_timer", "tick")
  def clock_timer_tick(self, **event_args):
    self._show_current_datetime()

  def _set_active_tab(self, active_tab):
    panels = {
      "grid": self.grid_entry_panel,
      "guided": self.guided_panel,
      "customize": self.table_editor_panel,
      "charts": self.charts_panel,
      "email": self.email_panel,
    }
    buttons = {
      "grid": self.grid_tab_button,
      "guided": self.guided_tab_button,
      "customize": self.customize_tab_button,
      "charts": self.charts_tab_button,
      "email": self.email_tab_button,
    }

    for tab_name, panel in panels.items():
      panel.visible = tab_name == active_tab
      buttons[tab_name].enabled = tab_name != active_tab

    if active_tab == "grid":
      # Coming back to the grid starts with only the first section open.
      for index, section in enumerate(self.tables_panel.get_components()):
        section.set_expanded(index == 0)

  def _load_latest_counts(self):
    snapshot = anvil.server.call("get_inventory_grid")
    # A reload keeps open whichever sections the reader opened.
    open_keys = None if self._snapshot is None else {
      table["table_key"] for table in self._snapshot["tables"] if table["expanded"]
    }
    self._snapshot = snapshot
    # The server vets the account's initials; without them every save would be refused.
    self._can_enter = snapshot["initials"] is not None
    self.user_initials_label.text = snapshot["initials"] or "—"
    tables = snapshot["tables"]
    for index, table in enumerate(tables):
      table["show_toggle"] = len(tables) > 1
      table["expanded"] = (
        not table["show_toggle"]
        or (index == 0 if open_keys is None else table["table_key"] in open_keys)
      )
      for row in table["rows"]:
        for cell in row["cells"]:
          cell["editable"] = self._can_enter
    # Rebuilding the rows briefly collapses the page, so keep the reader's place.
    scroll_y = window.scrollY
    self.tables_panel.items = tables
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
    tables = self._snapshot["tables"]
    self.section_labels_area.text = "\n".join(table["label"] for table in tables)
    self._section_cards = [
      {
        "table_key": table["table_key"],
        "label": table["label"],
        "saved_label": table["label"],
        "row_labels_text": "\n".join(table["row_labels"]),
        "column_labels_text": "\n".join(table["column_labels"]),
      }
      for table in tables
    ]
    # Start on the section the grid has open, so Customize edits what was in view.
    open_index = next((index for index, table in enumerate(tables) if table["expanded"]), 0)
    self._show_section(self._section_cards[open_index])
    self._set_active_tab("customize")

  def _show_section(self, card):
    # The Sections box picks the section; the boxes below edit only that one.
    self._active_card = card
    self.section_label.text = (
      card["label"] if card else "Tap a section above to edit its rows and columns."
    )
    self.row_labels_area.text = card["row_labels_text"] if card else ""
    self.column_labels_area.text = card["column_labels_text"] if card else ""
    self.row_labels_area.enabled = card is not None
    self.column_labels_area.enabled = card is not None

  def _on_sections_caret(self, event=None):
    node = self._sections_node
    text = node.value or ""
    lines = text.split("\n")
    caret_line = text[:node.selectionStart].count("\n")
    if not lines[caret_line].strip():
      # An emptied line may be mid-rename, so its section waits for a new name.
      self._show_section(None)
      return
    self._sync_section_cards()
    position = sum(1 for line in lines[:caret_line] if line.strip())
    self._show_section(self._section_cards[position])

  def _sync_section_cards(self):
    # The Sections box is the list itself: one section per line, in grid order.
    names = [
      line.strip()
      for line in (self.section_labels_area.text or "").splitlines()
      if line.strip()
    ]
    previous = self._section_cards
    # Most caret events only move between lines.
    if names == [card["label"] for card in previous]:
      return
    cards = [None] * len(names)
    claimed = []

    def claim(index, card):
      cards[index] = card
      claimed.append(card)

    def unclaimed(card):
      return not any(card is taken for taken in claimed)

    # Exact names first. The saved name catches a section whose line was
    # briefly merged with one typed in front of it, e.g. "BarFreezer" + Enter.
    for name_key in ("label", "saved_label"):
      for index, name in enumerate(names):
        if cards[index] is None:
          match = next(
            (
              card for card in previous
              if card.get(name_key) and card[name_key].lower() == name.lower() and unclaimed(card)
            ),
            None,
          )
          if match is not None:
            claim(index, match)

    for index, name in enumerate(names):
      if cards[index] is None:
        if index < len(previous) and unclaimed(previous[index]):
          # A new name where a vanished one used to be is a rename, so the
          # section keeps its rows, columns and counts.
          claim(index, previous[index])
        else:
          claim(index, {"table_key": None, "row_labels_text": "", "column_labels_text": ""})
      cards[index]["label"] = name
    self._section_cards = cards

  def _start_guided_entry(self):
    self._wizard_cells = [
      (table, row, cell)
      for table in self._snapshot["tables"]
      for row in table["rows"]
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
    self.wizard_exit_button.visible = not complete
    self.wizard_close_button.visible = complete
    if complete:
      self.wizard_step_label.text = "Guided entry complete"
      self.wizard_target_label.text = "All cells have been reviewed."
      return

    table, row, cell = self._wizard_cells[self._wizard_index]
    self.wizard_step_label.text = f"Cell {self._wizard_index + 1} of {total_steps}"
    target = f"{row['label']}  ·  {cell['column_label']}"
    if len(self._snapshot["tables"]) > 1:
      target = f"{table['label']}  ·  {target}"
    self.wizard_target_label.text = target
    self.wizard_quantity_box.text = cell["entry_quantity"]
    self.wizard_next_button.text = (
      "Finish" if self._wizard_index == total_steps - 1 else "Next"
    )

  def _save_wizard_step(self, quantity, advance=True):
    _, row, cell = self._wizard_cells[self._wizard_index]
    wizard_buttons = (self.wizard_next_button, self.wizard_zero_button, self.wizard_exit_button)
    for button in wizard_buttons:
      button.enabled = False
    try:
      result = anvil.server.call(
        "save_grid_cell",
        row["row_key"],
        cell["column_key"],
        quantity,
      )
    finally:
      for button in wizard_buttons:
        button.enabled = True

    if not result["ok"]:
      self.wizard_quantity_box.text = cell["entry_quantity"]
      self._show_error(result["message"])
      return False

    if not advance:
      self._load_latest_counts()
      return True

    # Advance before reloading so the old step's buttons don't linger during the call.
    self._wizard_index += 1
    self._show_wizard_step()
    self._load_latest_counts()
    return True

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

  @handle("email_tab_button", "click")
  def email_tab_button_click(self, **event_args):
    self._set_active_tab("email")

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

  @handle("section_labels_area", "lost_focus")
  def section_labels_area_lost_focus(self, **event_args):
    # Leaving the box settles any emptied line as a removed section.
    self._sync_section_cards()
    if not any(card is self._active_card for card in self._section_cards):
      self._show_section(None)

  @handle("row_labels_area", "change")
  def row_labels_area_change(self, **event_args):
    if self._active_card is not None:
      self._active_card["row_labels_text"] = self.row_labels_area.text

  @handle("column_labels_area", "change")
  def column_labels_area_change(self, **event_args):
    if self._active_card is not None:
      self._active_card["column_labels_text"] = self.column_labels_area.text

  @handle("save_setup_button", "click")
  def save_setup_button_click(self, **event_args):
    # Catch a Sections edit that never lost focus before Save was pressed.
    self._sync_section_cards()
    self.save_setup_button.enabled = False
    try:
      result = anvil.server.call(
        "save_inventory_configuration",
        self._section_cards,
      )
    finally:
      self.save_setup_button.enabled = True

    if not result["ok"]:
      self._show_error(result["message"])
      return

    self._wizard_cells = []
    # Load first so the grid tab opens the new first section, not the old one.
    self._load_latest_counts()
    self._set_active_tab("grid")

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

  @handle("wizard_exit_button", "click")
  def wizard_exit_button_click(self, **event_args):
    # Only save an edit: re-saving an untouched value would log a duplicate
    # entry under this user's initials.
    _, _, cell = self._wizard_cells[self._wizard_index]
    quantity = self.wizard_quantity_box.text
    if (quantity or "") != (cell["entry_quantity"] or ""):
      if not self._save_wizard_step(quantity, advance=False):
        return
    self._set_active_tab("grid")

  @handle("wizard_close_button", "click")
  def wizard_close_button_click(self, **event_args):
    self._set_active_tab("grid")
