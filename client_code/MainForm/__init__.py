from ._anvil_designer import MainFormTemplate
from anvil import *
import anvil.users
import anvil.server
from anvil.js import window
import time
from datetime import datetime

NO_INITIALS_MESSAGE = (
  "Your account has no initials yet, so counts are view-only. "
  "Ask an admin to add 1–5 letters to your account, then reload this page."
)
# A save that errors (busy server, dropped connection) is shown like a refused
# one, so the box reverts instead of keeping a value that never saved.
SAVE_FAILED = {"ok": False, "message": "That didn't save. Check your connection and try again."}
TOTALS_FAILED = {"ok": False, "message": "The chart didn't load. Check your connection and press Refresh."}
TOTALS_NOT_LOADED = "The chart didn't load. Press Refresh to try again."
# What a saved par level sends back about its cell.
PAR_FIELDS = ("par_text", "days_text", "below_par", "overdue", "alert_text")
TOTALS_RANGES = [("Last 30 days", 30), ("Last 90 days", 90), ("Last year", 365)]
# The chart draws one column at a time, so one line colour does.
TOTALS_COLOR = "#2a78d6"
# Checked items each get a line; these repeat if more are ticked than there are.
ITEM_COLORS = ["#2a78d6", "#d9622b", "#2f9e6f", "#8a5cc2", "#c9a227", "#d6457a", "#3a9cae", "#6b655b"]


PLOT_HINT = "Each ticked item's count in the column above, as it stood at the end of each day."
PLOT_INSTRUCTIONS = "Tick the Plot box beside one or more items in the table above to chart their history here."
ITEM_HINT = PLOT_HINT


def _totals_layout():
  # A fresh dict each draw: Plotly may write ranges back into the layout it's
  # given, and those mustn't carry over to the next column or range.
  return {
    "margin": {"l": 44, "r": 12, "t": 8, "b": 36},
    "hovermode": "x unified",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "showlegend": False,
    "font": {"color": "#6b655b", "size": 12},
    "xaxis": {"type": "date", "showgrid": False, "linecolor": "#dcd6ca", "fixedrange": True},
    "yaxis": {"rangemode": "tozero", "gridcolor": "#efece5", "zeroline": False, "fixedrange": True},
  }


def _clean_lines(text):
  return [line.strip() for line in (text or "").split("\n") if line.strip()]


def _count_lines(text):
  return len(_clean_lines(text))


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
    self._saved_setup = []
    self._active_card = None
    self.section_list_panel.add_event_handler("x-select-section", self._on_select_section)
    self._wizard_cells = []
    self._wizard_index = 0
    self._wizard_confirmed = set()
    self.tables_panel.add_event_handler("x-save-cell", self._save_grid_cell)
    self.par_levels_panel.add_event_handler("x-save-par", self._save_par_level)
    self.par_levels_panel.add_event_handler("x-plot-row", self._on_plot_row)
    # Items ticked Plot in the on-par table, by row key, for the open section.
    self._plot_rows = set()
    # Charts already fetched, by (section, days). Any new count empties it,
    # and bumps the generation so a fetch already out can't refill it with
    # totals from before that count.
    self._totals_cache = {}
    self._totals_generation = 0
    self._analytics_table_key = None
    # The column the par levels and chart show, within the Analytics section.
    self._column_key = None
    # Set when a par change has to show in the grid; it's rebuilt on return.
    self._grid_needs_rebuild = False
    self.range_dropdown.items = TOTALS_RANGES
    self.range_dropdown.selected_value = 30
    # Closing or reloading the page would drop unsaved Customize edits too.
    window.addEventListener("beforeunload", self._on_before_unload)
    self._active_tab = None
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

  def _has_unsaved_setup(self):
    return self._active_tab == "customize" and self._setup_signature() != self._saved_setup

  def _confirm_discard(self):
    if not self._has_unsaved_setup():
      return True
    if not confirm("Discard your unsaved section changes?", title="Unsaved changes"):
      return False
    self._forget_setup_edits()
    return True

  def _forget_setup_edits(self):
    # Treat what's on screen as settled (saved, or knowingly thrown away), so
    # nothing asks about it again. The next visit to Customize starts fresh.
    self._saved_setup = self._setup_signature()

  def _on_before_unload(self, event):
    if self._has_unsaved_setup():
      event.preventDefault()
      event.returnValue = ""

  def _set_active_tab(self, active_tab):
    # Returns False when the reader chose to stay with unsaved Customize edits.
    if active_tab != "customize" and not self._confirm_discard():
      return False
    self._active_tab = active_tab
    panels = {
      "grid": self.grid_entry_panel,
      "guided": self.guided_panel,
      "customize": self.table_editor_panel,
      "analytics": self.analytics_panel,
      "email": self.email_panel,
    }
    buttons = {
      "grid": self.grid_tab_button,
      "guided": self.guided_tab_button,
      "customize": self.customize_tab_button,
      "analytics": self.analytics_tab_button,
      "email": self.email_tab_button,
    }

    for tab_name, panel in panels.items():
      panel.visible = tab_name == active_tab
      buttons[tab_name].enabled = tab_name != active_tab
    if active_tab == "grid" and self._grid_needs_rebuild:
      self._show_grid()
    return True

  def _load_latest_counts(self):
    snapshot = anvil.server.call("get_inventory_grid")
    # Only a load decides which sections are open; switching tabs leaves them be.
    open_keys = None if self._snapshot is None else {
      table["table_key"] for table in self._snapshot["tables"] if table["expanded"]
    }
    self._snapshot = snapshot
    self._clear_totals()
    # The server vets the account's initials; without them every save would be refused.
    self._can_enter = snapshot["initials"] is not None
    self.user_initials_label.text = snapshot["initials"] or "—"
    # The server owns the limits; the client only reads them.
    self._limits = snapshot["limits"]
    self.dom_nodes["columns_label_text"].textContent = (
      f"Columns (up to {self._limits['columns']})"
    )
    tables = snapshot["tables"]
    # The first section starts open. After that the reader's choice stands,
    # unless every section they had open is gone (deleted in Customize).
    keys = {table["table_key"] for table in tables}
    if open_keys is None or (open_keys and not open_keys & keys):
      open_keys = {tables[0]["table_key"]} if tables else set()
    for table in tables:
      table["show_toggle"] = len(tables) > 1
      table["expanded"] = not table["show_toggle"] or table["table_key"] in open_keys
      for row in table["rows"]:
        for cell in row["cells"]:
          cell["editable"] = self._can_enter
    self._show_grid()
    if not self._can_enter:
      self._show_error(NO_INITIALS_MESSAGE)

  def _show_grid(self):
    # Rebuilding the rows briefly collapses the page, so keep the reader's place.
    scroll_y = window.scrollY
    self.tables_panel.items = self._snapshot["tables"]
    window.scrollTo(window.scrollX, scroll_y)
    self._grid_needs_rebuild = False

  def _analytics_table(self):
    return next(
      table for table in self._snapshot["tables"]
      if table["table_key"] == self._analytics_table_key
    )

  def _render_analytics(self):
    # Everything here but the chart comes from the snapshot already loaded,
    # so opening the tab reads nothing more from the database.
    tables = self._snapshot["tables"]
    keys = [table["table_key"] for table in tables]
    if self._analytics_table_key not in keys:
      # Start on the section the grid has open, as Customize does.
      self._analytics_table_key = next(
        (table["table_key"] for table in tables if table["expanded"]), keys[0]
      )
    self.section_dropdown.items = [(table["label"], table["table_key"]) for table in tables]
    self.section_dropdown.selected_value = self._analytics_table_key
    self._render_alerts()
    self._render_section_analytics()

  def _render_alerts(self):
    tables = self._snapshot["tables"]
    alerts = []
    for table in tables:
      for row in table["rows"]:
        for cell in row["cells"]:
          if not (cell["below_par"] or cell["overdue"]):
            continue
          label = f"{row['label']}  ·  {cell['column_label']}"
          if len(tables) > 1:
            label = f"{table['label']}  ·  {label}"
          alerts.append({
            "label": label,
            "detail": cell["alert_text"],
            "below_par": cell["below_par"],
            "overdue": cell["overdue"],
          })
    self.alerts_panel.items = alerts
    self.alerts_empty_label.visible = not alerts

  def _render_section_analytics(self):
    columns = self._analytics_table()["columns"]
    keys = [column["column_key"] for column in columns]
    if self._column_key not in keys:
      self._column_key = keys[0] if keys else None
    self.column_dropdown.items = [(column["label"], column["column_key"]) for column in columns]
    self.column_dropdown.selected_value = self._column_key
    self._render_column()

  def _render_column(self):
    # One column at a time keeps this to one box pair per item, and the chart
    # to one line.
    self.par_levels_panel.items = [
      {
        "row_key": row["row_key"],
        "column_key": cell["column_key"],
        "label": row["label"],
        "plot": row["row_key"] in self._plot_rows,
        "entry_quantity": cell["entry_quantity"],
        "par_text": cell["par_text"],
        "days_text": cell["days_text"],
        "below_par": cell["below_par"],
        "overdue": cell["overdue"],
      }
      for row in self._analytics_table()["rows"]
      for cell in row["cells"]
      if cell["column_key"] == self._column_key
    ]
    self._show_totals()

  def _snapshot_cell(self, row_key, column_key):
    # None when a reload while the save was out dropped the cell.
    return next(
      (
        cell
        for table in self._snapshot["tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["row_key"] == row_key and cell["column_key"] == column_key
      ),
      None,
    )

  def _forget_failed_totals(self):
    # A failed load stays failed while only the column changes; picking a
    # section or range, opening the tab, or Refresh tries again.
    for key in [key for key, totals in self._totals_cache.items() if not totals["ok"]]:
      del self._totals_cache[key]

  def _show_totals(self):
    if not self._plot_rows:
      # Nothing to draw yet, so there's no need for the slow history read.
      self.totals_title_label.text = "History over time"
      self.totals_hint_label.text = PLOT_HINT
      self._show_totals_empty(PLOT_INSTRUCTIONS)
      return
    # The chart's history read is the one slow call here, so it runs once per
    # section and range until a count changes. It brings every column, so
    # picking another column redraws from the cache.
    key = (self._analytics_table_key, self.range_dropdown.selected_value)
    totals = self._totals_cache.get(key)
    if totals is None:
      generation = self._totals_generation
      try:
        totals = anvil.server.call("get_section_totals", key[0], key[1])
      except Exception:
        totals = TOTALS_FAILED
      if generation != self._totals_generation:
        # A count saved while this was out may be missing from it; fetch
        # again (or use what a redraw meanwhile already fetched).
        return self._show_totals()
      self._totals_cache[key] = totals
      if not totals["ok"]:
        self._show_error(totals["message"])
    if not totals["ok"]:
      self._show_totals_empty(TOTALS_NOT_LOADED)
      return

    # The grid's own name for the column, the same one the picker shows.
    label = next(
      column["label"] for column in self._analytics_table()["columns"]
      if column["column_key"] == self._column_key
    )
    self._show_item_lines(totals, label)

  def _show_item_lines(self, totals, label):
    # One line per ticked item, for the column the picker shows.
    self.totals_title_label.text = f"{label} over time"
    self.totals_hint_label.text = ITEM_HINT
    history = {
      cell["row_key"]: cell["quantities"]
      for cell in totals.get("cells", [])
      if cell["column_key"] == self._column_key
    }
    data = []
    latest = []
    for row in self._analytics_table()["rows"]:
      quantities = history.get(row["row_key"])
      if row["row_key"] not in self._plot_rows or quantities is None:
        continue
      counted = [value for value in quantities if value is not None]
      if not counted:
        continue
      data.append({
        "type": "scatter",
        "mode": "lines",
        "name": row["label"],
        "x": totals["dates"],
        "y": quantities,
        "connectgaps": False,
        "hovertemplate": "%{y:g}<extra>" + row["label"] + "</extra>",
        "line": {"color": ITEM_COLORS[len(data) % len(ITEM_COLORS)], "width": 2},
      })
      latest.append(f"{row['label']} {counted[-1]:g}")
    if not data:
      self._show_totals_empty(f"No {label} counts saved in this range yet for the ticked items.")
      return
    layout = _totals_layout()
    layout["showlegend"] = len(data) > 1
    self.totals_plot.layout = layout
    self.totals_plot.data = data
    self.totals_plot.visible = True
    self.totals_summary_label.text = "Latest: " + ", ".join(latest)
    self.totals_summary_label.visible = True
    self.totals_empty_label.visible = False

  def _show_totals_empty(self, message):
    self.totals_plot.visible = False
    self.totals_summary_label.visible = False
    self.totals_empty_label.text = message
    self.totals_empty_label.visible = True

  def _show_error(self, message):
    # Keep one warning on screen; a run of failed saves would otherwise stack them.
    if self._error_notification is not None:
      self._error_notification.hide()
    self._error_notification = Notification(message, style="warning", timeout=None)
    self._error_notification.show()

  def _open_table_editor(self):
    # Start from the latest setup, not the grid as it was last loaded: edits
    # built on an old copy would only be refused as stale on save.
    self._load_latest_counts()
    tables = self._snapshot["tables"]
    # Each card keeps its section's key for the whole edit, so moving or
    # renaming it never loses the rows, columns and counts behind it.
    self._section_cards = [
      {
        "table_key": table["table_key"],
        "label": table["label"],
        "row_labels_text": "\n".join(table["row_labels"]),
        "column_labels_text": "\n".join(table["column_labels"]),
      }
      for table in tables
    ]
    # What Customize opened with, so any later difference shows as "Edited".
    self._saved_setup = self._setup_signature()
    # Taken now, not at save time: a Refresh mid-edit mustn't make old edits
    # look current to the server.
    self._editing_version = self._snapshot["setup_version"]
    self.new_section_box.text = ""
    # Start on the section the grid has open, so Customize edits what was in view.
    open_index = next((index for index, table in enumerate(tables) if table["expanded"]), 0)
    self._select_section(self._section_cards[open_index])
    self._set_active_tab("customize")

  def _active_index(self):
    return next(
      index for index, card in enumerate(self._section_cards) if card is self._active_card
    )

  def _select_section(self, card):
    # The list picks the section; the boxes below edit only that one.
    self._active_card = card
    self.section_name_box.text = card["label"]
    self.row_labels_area.text = card["row_labels_text"]
    self.column_labels_area.text = card["column_labels_text"]
    self._render_section_list()

  def _render_section_list(self):
    cards = self._section_cards
    active_index = self._active_index()
    self.section_list_panel.items = [
      {
        "index": index,
        # Flags a naming problem in any section, not just the one open below.
        "label": ("⚠ " if self._name_problem(card) else "") + (card["label"] or "(no name)"),
        "row_count": _count_lines(card["row_labels_text"]),
        "column_count": _count_lines(card["column_labels_text"]),
        "selected": index == active_index,
      }
      for index, card in enumerate(cards)
    ]
    full = len(cards) >= self._limits["sections"]
    self.move_up_button.enabled = active_index > 0
    self.move_down_button.enabled = active_index < len(cards) - 1
    self.clone_section_button.enabled = not full
    self.delete_section_button.enabled = len(cards) > 1
    self.add_section_button.enabled = not full
    self.new_section_box.enabled = not full
    problem = self._name_problem(self._active_card)
    self.section_name_error.text = problem or ""
    self.section_name_error.visible = problem is not None
    self._show_edited_state()

  def _setup_signature(self):
    # Spacing and blank lines don't change what gets saved, so they don't count.
    return [
      (
        card["table_key"],
        card["label"].strip(),
        _clean_lines(card["row_labels_text"]),
        _clean_lines(card["column_labels_text"]),
      )
      for card in self._section_cards
    ]

  def _show_edited_state(self):
    edited = self._setup_signature() != self._saved_setup
    self.edited_status_button.text = "Edited · Save now" if edited else "No unsaved changes"
    self.edited_status_button.enabled = edited
    # With nothing to throw away, the tabs already lead out of Customize.
    self.cancel_setup_button.visible = edited

  def _name_taken(self, name, ignore=None):
    # Matches the server's _section_key, so a clash shows here before saving.
    key = name.strip().lower()
    return any(
      card is not ignore and card["label"].strip().lower() == key
      for card in self._section_cards
    )

  def _name_problem(self, card):
    # The same rules the server applies, caught while typing instead of on save.
    name = card["label"].strip()
    if not name:
      return "Give this section a name."
    if len(name) > self._limits["label_length"]:
      return f"Keep section names under {self._limits['label_length']} characters."
    if self._name_taken(name, ignore=card):
      return f"Another section is already called {name}."
    return None

  def _on_select_section(self, index, **event_args):
    self._select_section(self._section_cards[index])

  def _add_section(self):
    name = (self.new_section_box.text or "").strip()
    if not name:
      return
    card = {"table_key": None, "label": name, "row_labels_text": "", "column_labels_text": ""}
    problem = self._name_problem(card)
    if problem:
      self._show_error(problem)
      return
    self._section_cards.append(card)
    self.new_section_box.text = ""
    self._select_section(card)
    # A new section can't be saved until it has rows and columns.
    self.row_labels_area.focus()

  def _move_active_section(self, step):
    index = self._active_index()
    cards = self._section_cards
    cards[index], cards[index + step] = cards[index + step], cards[index]
    self._render_section_list()

  def _clone_name(self, label):
    base = label.strip() or "Section"
    copy_number = 1
    while True:
      suffix = " copy" if copy_number == 1 else f" copy {copy_number}"
      name = base[:self._limits["label_length"] - len(suffix)] + suffix
      if not self._name_taken(name):
        return name
      copy_number += 1

  def _start_guided_entry(self):
    self._wizard_cells = [
      (table, row, cell)
      for table in self._snapshot["tables"]
      for row in table["rows"]
      for cell in row["cells"]
    ]
    self._wizard_index = 0
    self._wizard_confirmed = set()
    self._show_wizard_step()

  def _wizard_cell(self):
    # Read the latest counts, not this pass's starting copy: a count saved from
    # the grid meanwhile mustn't be shown stale and then saved back over.
    table, row, cell = self._wizard_cells[self._wizard_index]
    for latest_table in self._snapshot["tables"]:
      for latest_row in latest_table["rows"]:
        if latest_row["row_key"] != row["row_key"]:
          continue
        for latest_cell in latest_row["cells"]:
          if latest_cell["column_key"] == cell["column_key"]:
            return latest_table, latest_row, latest_cell
    return table, row, cell

  def _show_wizard_step(self):
    total_steps = len(self._wizard_cells)
    complete = self._wizard_index >= total_steps
    self.dom_nodes["wizard_quantity_field"].style.display = "none" if complete else ""
    self.dom_nodes["wizard_quick_quantities"].style.display = "none" if complete else ""
    self.wizard_zero_button.visible = not complete
    self.wizard_next_button.visible = not complete
    self.wizard_exit_button.visible = not complete
    self.wizard_close_button.visible = complete
    # Back also leaves the done screen, so a last-cell slip can be fixed.
    self.wizard_back_button.visible = self._wizard_index > 0
    if complete:
      self.wizard_step_label.text = "Guided entry complete"
      self.wizard_target_label.text = "All cells have been reviewed."
      return

    table, row, cell = self._wizard_cell()
    self.wizard_step_label.text = f"Cell {self._wizard_index + 1} of {total_steps}"
    target = f"{row['label']}  ·  {cell['column_label']}"
    if len(self._snapshot["tables"]) > 1:
      target = f"{table['label']}  ·  {target}"
    self.wizard_target_label.text = target
    self.wizard_quantity_box.text = cell["entry_quantity"]
    self.wizard_next_button.text = (
      "Finish" if self._wizard_index == total_steps - 1 else "Next"
    )

  def _move_wizard(self, quantity, step):
    # Next confirms an unchanged count, so it's logged once per pass; after
    # that, and for Back and Exit, only an edit is saved. Re-saving an
    # untouched value would log a duplicate entry under this user's initials.
    if self._wizard_index < len(self._wizard_cells):
      _, row, cell = self._wizard_cell()
      unchanged = (quantity or "") == (cell["entry_quantity"] or "")
      confirmed = (row["row_key"], cell["column_key"]) in self._wizard_confirmed
      if not unchanged or (step == 1 and not confirmed):
        return self._save_wizard_step(quantity, step)
    if step:
      self._wizard_index += step
      self._show_wizard_step()
    return True

  def _save_wizard_step(self, quantity, step):
    _, row, cell = self._wizard_cell()
    wizard_buttons = (
      self.wizard_back_button, self.wizard_next_button, self.wizard_zero_button, self.wizard_exit_button,
    )
    for button in wizard_buttons:
      button.enabled = False
    try:
      result = anvil.server.call(
        "save_grid_cell",
        row["row_key"],
        cell["column_key"],
        quantity,
      )
    except Exception:
      result = SAVE_FAILED
    finally:
      for button in wizard_buttons:
        button.enabled = True

    if not result["ok"]:
      self.wizard_quantity_box.text = cell["entry_quantity"]
      self._show_error(result["message"])
      return False

    self._wizard_confirmed.add((row["row_key"], cell["column_key"]))
    # Holds the new count until the reload brings it in.
    cell["entry_quantity"] = result["entry_quantity"]
    # Move before reloading: the buttons are live again during the call, so a
    # second tap must start from the new step, and the old step's buttons
    # mustn't linger.
    if step:
      self._wizard_index += step
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
    if self._set_active_tab("guided"):
      self._start_guided_entry()

  @handle("customize_tab_button", "click")
  def customize_tab_button_click(self, **event_args):
    self._open_table_editor()

  @handle("analytics_tab_button", "click")
  def analytics_tab_button_click(self, **event_args):
    if self._set_active_tab("analytics"):
      self._forget_failed_totals()
      self._render_analytics()

  @handle("section_dropdown", "change")
  def section_dropdown_change(self, **event_args):
    self._analytics_table_key = self.section_dropdown.selected_value
    self._plot_rows = set()
    self._forget_failed_totals()
    self._render_section_analytics()

  @handle("range_dropdown", "change")
  def range_dropdown_change(self, **event_args):
    self._forget_failed_totals()
    self._show_totals()

  @handle("column_dropdown", "change")
  def column_dropdown_change(self, **event_args):
    self._column_key = self.column_dropdown.selected_value
    self._render_column()

  @handle("email_tab_button", "click")
  def email_tab_button_click(self, **event_args):
    self._set_active_tab("email")

  @handle("logout_button", "click")
  def logout_button_click(self, **event_args):
    if not self._confirm_discard():
      return
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
    if self._active_tab == "analytics":
      self._render_analytics()

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
    except Exception:
      result = SAVE_FAILED
    finally:
      self._saves_in_flight -= 1
    if not result["ok"]:
      cell.revert()
      self._show_error(result["message"])
      return

    cell.show_saved(result)
    # The chart's totals include this count now.
    self._clear_totals()
    # Leaving the box for the Analytics tab starts this save, and the tab can
    # draw before it lands; draw it again with the new count.
    if self._active_tab == "analytics":
      self._render_analytics()

  def _clear_totals(self):
    self._totals_cache = {}
    self._totals_generation += 1

  def _on_plot_row(self, row, checked, **event_args):
    row_key = row.item["row_key"]
    if checked:
      self._plot_rows.add(row_key)
    else:
      self._plot_rows.discard(row_key)
    self._show_totals()

  def _save_par_level(self, row, par, days, **event_args):
    row_key = row.item["row_key"]
    column_key = row.item["column_key"]
    self._saves_in_flight += 1
    try:
      result = anvil.server.call_s("save_par_level", row_key, column_key, par, days)
    except Exception:
      result = SAVE_FAILED
    finally:
      self._saves_in_flight -= 1
    if not result["ok"]:
      row.revert()
      self._show_error(result["message"])
      return

    row.show_saved(result)
    cell = self._snapshot_cell(row_key, column_key)
    if cell is None:
      return
    for name in PAR_FIELDS:
      cell[name] = result[name]
    self._render_alerts()
    if self._active_tab == "grid":
      # Leaving the par box for the Grid tab starts this save, so the grid
      # can already be showing; redraw it now rather than on the next visit.
      self._show_grid()
    else:
      self._grid_needs_rebuild = True

  @handle("add_section_button", "click")
  def add_section_button_click(self, **event_args):
    self._add_section()

  @handle("new_section_box", "pressed_enter")
  def new_section_box_pressed_enter(self, **event_args):
    self._add_section()

  @handle("move_up_button", "click")
  def move_up_button_click(self, **event_args):
    self._move_active_section(-1)

  @handle("move_down_button", "click")
  def move_down_button_click(self, **event_args):
    self._move_active_section(1)

  @handle("clone_section_button", "click")
  def clone_section_button_click(self, **event_args):
    source = self._active_card
    # No key, so the server makes new rows and columns and the copy starts
    # with no counts of its own.
    card = {
      "table_key": None,
      "label": self._clone_name(source["label"]),
      "row_labels_text": source["row_labels_text"],
      "column_labels_text": source["column_labels_text"],
    }
    self._section_cards.insert(self._active_index() + 1, card)
    self._select_section(card)

  @handle("delete_section_button", "click")
  def delete_section_button_click(self, **event_args):
    card = self._active_card
    if card["table_key"] is not None and not confirm(
      f"Delete {card['label']}? Saving removes it with its rows, columns and current "
      "counts for good; past entries stay in the history.",
      title="Delete section",
    ):
      return
    index = self._active_index()
    self._section_cards.pop(index)
    self._select_section(self._section_cards[min(index, len(self._section_cards) - 1)])

  @handle("section_name_box", "change")
  def section_name_box_change(self, **event_args):
    self._active_card["label"] = (self.section_name_box.text or "").strip()
    self._render_section_list()

  @handle("row_labels_area", "change")
  def row_labels_area_change(self, **event_args):
    self._active_card["row_labels_text"] = self.row_labels_area.text
    self._render_section_list()

  @handle("column_labels_area", "change")
  def column_labels_area_change(self, **event_args):
    self._active_card["column_labels_text"] = self.column_labels_area.text
    self._render_section_list()

  @handle("edited_status_button", "click")
  def edited_status_button_click(self, **event_args):
    self._save_setup()

  def _save_setup(self):
    # Naming problems are already flagged; open the first one rather than
    # making a server call that can only refuse.
    for card in self._section_cards:
      problem = self._name_problem(card)
      if problem:
        self._select_section(card)
        self._show_error(problem)
        return
    self.edited_status_button.enabled = False
    self.cancel_setup_button.enabled = False
    try:
      result = anvil.server.call(
        "save_inventory_configuration",
        self._section_cards,
        self._editing_version,
      )
    except Exception:
      result = SAVE_FAILED
    finally:
      self.cancel_setup_button.enabled = True
      self._show_edited_state()

    if not result["ok"]:
      self._show_error(result["message"])
      return

    self._forget_setup_edits()
    self._wizard_cells = []
    self._load_latest_counts()
    self._set_active_tab("grid")

  @handle("cancel_setup_button", "click")
  def cancel_setup_button_click(self, **event_args):
    # Cancel is the explicit discard, so it doesn't ask.
    self._forget_setup_edits()
    self._set_active_tab("grid")

  @handle("wizard_next_button", "click")
  def wizard_next_button_click(self, **event_args):
    self._move_wizard(self.wizard_quantity_box.text, 1)

  @handle("wizard_zero_button", "click")
  def wizard_zero_button_click(self, **event_args):
    self.wizard_quantity_box.text = "0"
    self._move_wizard("0", 1)

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

  @handle("wizard_back_button", "click")
  def wizard_back_button_click(self, **event_args):
    if self._wizard_index > 0:
      self._move_wizard(self.wizard_quantity_box.text, -1)

  @handle("wizard_exit_button", "click")
  def wizard_exit_button_click(self, **event_args):
    if self._move_wizard(self.wizard_quantity_box.text, 0):
      self._set_active_tab("grid")

  @handle("wizard_close_button", "click")
  def wizard_close_button_click(self, **event_args):
    self._set_active_tab("grid")
