import os
import unittest

from tests.support import CLIENT_DIR, Component, Event, add_section, app_tables, load_form, load_server, state


inv = load_server()


class Cell:
  # Stands in for a GridCell raising x-save-cell.
  def __init__(self, row_key, column_key):
    self.item = {"row_key": row_key, "column_key": column_key}
    self.reverted = False
    self.saved = None

  def revert(self):
    self.reverted = True

  def show_saved(self, result):
    self.saved = (result["entry_quantity"], result["latest_display"])


class SnapshotCell(Cell):
  # A GridCell whose item is the snapshot's own cell dict, as in the app.
  def __init__(self, item):
    super().__init__(item["row_key"], item["column_key"])
    self.item = item

  def show_saved(self, result):
    super().show_saved(result)
    self.item.update(result)


def boom(*args, **kwargs):
  raise RuntimeError("TransactionConflict")


class FormTest(unittest.TestCase):
  def setUp(self):
    state.reset()
    self.mf = load_form("MainForm")
    add_section("A", "Freezer", order=1)
    add_section("B", "Fridge", rows=("Milk", "Eggs"), cols=("Qty", "Cases"), order=2)
    self.form = self.mf.MainForm()

  def type_into(self, box_name, text):
    # Set a box and fire its change event, as typing then leaving it would.
    getattr(self.form, box_name).text = text
    getattr(self.form, box_name + "_change")()

  def labels(self):
    return [card["label"] for card in self.form._section_cards]

  def edited(self):
    form = self.form
    self.assertEqual(form.edited_status_button.enabled, form.cancel_setup_button.visible)
    return form.edited_status_button.enabled

  def opened(self):
    return [t["table_key"] for t in self.form._snapshot["tables"] if t["expanded"]]


class GridTest(FormTest):
  def test_first_load_opens_only_the_first_section(self):
    self.assertEqual(self.opened(), ["A"])
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(self.form.user_initials_label.text, "BM")
    self.assertEqual(self.form.dom_nodes["columns_label_text"].textContent, "Columns (up to 5)")

  def test_reloads_keep_the_readers_open_sections(self):
    self.form._snapshot["tables"][1]["expanded"] = True
    self.form._set_active_tab("analytics")
    self.form._set_active_tab("grid")
    self.form.refresh_button_click()
    self.assertEqual(self.opened(), ["A", "B"])
    for table in self.form._snapshot["tables"]:
      table["expanded"] = False
    self.form.refresh_button_click()
    self.assertEqual(self.opened(), [])

  def test_first_section_opens_when_every_open_one_is_gone(self):
    add_section("C", "Bar", order=3)
    self.form.refresh_button_click()
    for table in self.form._snapshot["tables"]:
      table["expanded"] = table["table_key"] == "C"
    app_tables.inventory_tables.get(table_key="C").delete()
    self.form.refresh_button_click()
    self.assertEqual(self.opened(), ["A"])

  def test_a_lone_section_has_no_toggle(self):
    app_tables.inventory_tables.get(table_key="B").delete()
    self.form.refresh_button_click()
    table = self.form.tables_panel.items[0]
    self.assertEqual((table["show_toggle"], table["expanded"]), (False, True))

  def test_without_initials_counts_are_view_only(self):
    state.user["initials"] = None
    self.form.refresh_button_click()
    cells = [c for t in self.form.tables_panel.items for r in t["rows"] for c in r["cells"]]
    self.assertFalse(any(c["editable"] for c in cells))
    self.assertEqual(self.form.user_initials_label.text, "—")
    self.assertEqual(state.notifications[-1], self.mf.NO_INITIALS_MESSAGE)
    self.form.guided_tab_button_click()
    self.assertEqual(self.form._active_tab, "grid")

  def test_saved_cell_shows_the_new_count(self):
    cell = Cell("A-r0", "A-c0")
    self.form.tables_panel.raise_event("x-save-cell", cell=cell, quantity="3")
    self.assertEqual(cell.saved[0], "3")
    self.assertFalse(cell.reverted)

  def test_refused_or_failed_cell_save_reverts_and_warns(self):
    cell = Cell("A-r0", "A-c0")
    self.form._save_grid_cell(cell, "-1")
    self.assertTrue(cell.reverted)
    self.assertIn("zero or greater", state.notifications[-1])

    state.routes["save_grid_cell"] = boom
    cell = Cell("A-r0", "A-c0")
    self.form._save_grid_cell(cell, "3")
    self.assertTrue(cell.reverted)
    self.assertEqual(state.notifications[-1], self.mf.SAVE_FAILED["message"])
    self.assertEqual(self.form._saves_in_flight, 0)

  def test_one_warning_at_a_time(self):
    self.form._show_error("first")
    first = self.form._error_notification
    self.form._show_error("second")
    self.assertFalse(first.visible)
    self.assertTrue(self.form._error_notification.visible)


class ParRow:
  # Stands in for a ParLevelRow raising x-save-par.
  def __init__(self, row_key, column_key):
    self.item = {"row_key": row_key, "column_key": column_key}
    self.reverted = False
    self.saved = None

  def revert(self):
    self.reverted = True

  def show_saved(self, result):
    self.saved = result


class AnalyticsTest(FormTest):
  def setUp(self):
    super().setUp()
    state.calls.clear()
    self.form.analytics_tab_button_click()

  def calls(self):
    return [call for call in state.calls if call[0] != "save_par_level"]

  def tick(self, row_key, column_key="A-c0", checked=True):
    self.form.par_levels_panel.raise_event(
      "x-plot-row", row=ParRow(row_key, column_key), checked=checked
    )

  def test_opens_on_the_grids_section_with_one_call(self):
    form = self.form
    self.assertEqual(form._active_tab, "analytics")
    self.assertEqual(state.calls, [])
    self.assertEqual(form.section_dropdown.items, [("Freezer", "A"), ("Fridge", "B")])
    self.assertEqual(form.section_dropdown.selected_value, "A")
    self.assertEqual([row["label"] for row in form.par_levels_panel.items], ["Ice"])
    self.assertEqual((form.column_dropdown.items, form.column_dropdown.selected_value), ([("Qty", "A-c0")], "A-c0"))
    self.assertEqual(form.alerts_panel.items, [])
    self.assertTrue(form.alerts_empty_label.visible)

  def test_chart_starts_with_instructions_and_reads_nothing(self):
    form = self.form
    self.assertFalse(form.totals_plot.visible)
    self.assertTrue(form.totals_empty_label.visible)
    self.assertIn("Tick the Plot box", form.totals_empty_label.text)

  def test_ticked_items_are_plotted_one_line_each(self):
    form = self.form
    self.tick("A-r0")
    self.assertEqual(state.calls, [("get_section_totals", "A", 30)])
    self.assertEqual(len(form.totals_plot.data), 1)
    trace = form.totals_plot.data[0]
    self.assertEqual((trace["name"], trace["y"][-1], len(trace["x"])), ("Ice", 7, 30))
    self.assertEqual(form.totals_summary_label.text, "Latest: Ice 7")
    self.assertFalse(form.totals_empty_label.visible)
    self.tick("A-r0", checked=False)
    self.assertFalse(form.totals_plot.visible)
    self.assertIn("Tick the Plot box", form.totals_empty_label.text)

  def test_ticks_stay_across_columns_and_clear_on_a_new_section(self):
    form = self.form
    form.section_dropdown.selected_value = "B"
    form.section_dropdown_change()
    self.tick("B-r0", "B-c0")
    self.tick("B-r1", "B-c0")
    self.assertEqual([t["name"] for t in form.totals_plot.data], ["Milk", "Eggs"])
    form.column_dropdown.selected_value = "B-c1"
    form.column_dropdown_change()
    self.assertEqual([r["plot"] for r in form.par_levels_panel.items], [True, True])
    form.section_dropdown.selected_value = "A"
    form.section_dropdown_change()
    self.assertEqual([r["plot"] for r in form.par_levels_panel.items], [False])

  def test_chart_with_no_counts_says_so(self):
    for cell in list(app_tables.inventory_cells.rows):
      cell.delete()
    self.form.refresh_button_click()
    self.tick("A-r0")
    self.assertFalse(self.form.totals_plot.visible)
    self.assertTrue(self.form.totals_empty_label.visible)
    self.assertIn("No Qty counts saved", self.form.totals_empty_label.text)

  def test_an_empty_column_names_itself_not_the_section(self):
    for cell in list(app_tables.inventory_cells.rows):
      if cell["column_key"] == "B-c0":
        cell.delete()
    self.form.refresh_button_click()
    self.form.section_dropdown.selected_value = "B"
    self.form.section_dropdown_change()
    self.tick("B-r0", "B-c0")
    self.assertIn("No Qty counts saved", self.form.totals_empty_label.text)
    self.form.column_dropdown.selected_value = "B-c1"
    self.form.column_dropdown_change()
    self.assertTrue(self.form.totals_plot.visible)
    self.assertFalse(self.form.totals_empty_label.visible)

  def test_each_draw_gets_its_own_layout(self):
    self.tick("A-r0")
    self.form.totals_plot.layout["yaxis"]["range"] = [0, 999]
    self.form.range_dropdown_change()
    self.assertNotIn("range", self.form.totals_plot.layout["yaxis"])

  def test_reopening_uses_the_cached_chart(self):
    self.tick("A-r0")
    self.form.grid_tab_button_click()
    state.calls.clear()
    self.form.analytics_tab_button_click()
    self.assertEqual(state.calls, [])

  def test_section_and_range_each_load_once_and_columns_load_nothing(self):
    form = self.form
    state.calls.clear()
    form.section_dropdown.selected_value = "B"
    form.section_dropdown_change()
    self.tick("B-r0", "B-c0")
    self.assertEqual(state.calls, [("get_section_totals", "B", 30)])
    self.assertEqual(form.column_dropdown.items, [("Qty", "B-c0"), ("Cases", "B-c1")])
    self.assertEqual(form.totals_summary_label.text, "Latest: Milk 7")
    state.calls.clear()
    form.column_dropdown.selected_value = "B-c1"
    form.column_dropdown_change()
    self.assertEqual(state.calls, [])
    self.assertEqual([(r["label"], r["column_key"]) for r in form.par_levels_panel.items], [("Milk", "B-c1"), ("Eggs", "B-c1")])
    self.assertEqual(form.totals_title_label.text, "Cases over time")
    form.range_dropdown.selected_value = 90
    form.range_dropdown_change()
    self.assertEqual(state.calls, [("get_section_totals", "B", 90)])

  def test_a_new_count_or_refresh_drops_the_cached_chart(self):
    self.tick("A-r0")
    state.calls.clear()
    self.form._save_grid_cell(Cell("A-r0", "A-c0"), "3")
    self.assertEqual(state.calls[-1], ("get_section_totals", "A", 30))
    self.assertEqual(self.form.totals_plot.data[0]["y"][-1], 3)
    state.calls.clear()
    self.form.refresh_button_click()
    self.assertEqual(state.calls, [("get_inventory_grid",), ("get_section_totals", "A", 30)])

  def test_a_chart_fetched_across_a_new_count_is_not_kept(self):
    form = self.form
    self.tick("A-r0")
    form.range_dropdown.selected_value = 90

    def count_lands_meanwhile(table_key, days):
      stale = inv.get_section_totals(table_key, days)
      del state.routes["get_section_totals"]
      form._save_grid_cell(Cell("A-r0", "A-c0"), "3")
      return stale

    state.routes["get_section_totals"] = count_lands_meanwhile
    form.range_dropdown_change()
    self.assertEqual(form.totals_plot.data[0]["y"][-1], 3)
    self.assertEqual(form._totals_cache[("A", 90)]["series"][0]["totals"][-1], 3)

  def test_a_count_landing_after_opening_analytics_updates_it(self):
    form = self.form
    form._save_par_level(ParRow("A-r0", "A-c0"), "10", "")
    self.assertEqual(len(form.alerts_panel.items), 1)
    form.grid_tab_button_click()

    def leave_for_analytics(*args):
      # Clicking the tab blurs the box; the tab draws before the save lands.
      del state.routes["save_grid_cell"]
      form.analytics_tab_button_click()
      self.assertEqual(len(form.alerts_panel.items), 1)
      return inv.save_grid_cell(*args)

    state.routes["save_grid_cell"] = leave_for_analytics
    cell = form.tables_panel.items[0]["rows"][0]["cells"][0]
    # The real GridCell writes the reply into the snapshot's cell.
    form._save_grid_cell(SnapshotCell(cell), "12")
    self.assertEqual(form.alerts_panel.items, [])
    self.assertEqual(form.par_levels_panel.items[0]["entry_quantity"], "12")

  def test_a_par_save_landing_on_the_grid_redraws_it(self):
    form = self.form

    def leave_for_grid(*args):
      del state.routes["save_par_level"]
      form.grid_tab_button_click()
      return inv.save_par_level(*args)

    state.routes["save_par_level"] = leave_for_grid
    form._save_par_level(ParRow("A-r0", "A-c0"), "10", "")
    self.assertEqual(form._active_tab, "grid")
    self.assertFalse(form._grid_needs_rebuild)
    self.assertTrue(form.tables_panel.items[0]["rows"][0]["cells"][0]["below_par"])

  def test_saved_par_shows_in_alerts_and_the_grid_without_a_reload(self):
    form = self.form
    row = ParRow("B-r0", "B-c0")
    form.par_levels_panel.raise_event("x-save-par", row=row, par="10", days="")
    self.assertEqual(row.saved["par_text"], "10")
    self.assertEqual(len(form.alerts_panel.items), 1)
    alert = form.alerts_panel.items[0]
    self.assertEqual(alert["label"], "Fridge  ·  Milk  ·  Qty")
    self.assertEqual(alert["detail"], "Low: 7 on hand, par 10")
    self.assertFalse(form.alerts_empty_label.visible)
    state.calls.clear()
    form.grid_tab_button_click()
    self.assertEqual(state.calls, [])
    cell = form.tables_panel.items[1]["rows"][0]["cells"][0]
    self.assertEqual((cell["par_text"], cell["below_par"]), ("10", True))
    self.assertFalse(form._grid_needs_rebuild)

  def test_refused_or_failed_par_save_reverts_and_warns(self):
    row = ParRow("A-r0", "A-c0")
    self.form._save_par_level(row, "lots", "")
    self.assertTrue(row.reverted)
    self.assertIn("Enter a par", state.notifications[-1])
    state.routes["save_par_level"] = boom
    row = ParRow("A-r0", "A-c0")
    self.form._save_par_level(row, "3", "")
    self.assertTrue(row.reverted)
    self.assertEqual(state.notifications[-1], self.mf.SAVE_FAILED["message"])
    self.assertFalse(self.form._grid_needs_rebuild)

  def test_failed_chart_warns_once_and_retries_on_a_new_choice(self):
    form = self.form
    form.section_dropdown.selected_value = "B"
    state.routes["get_section_totals"] = boom
    form.section_dropdown_change()
    self.tick("B-r0", "B-c0")
    self.assertEqual(state.notifications[-1], self.mf.TOTALS_FAILED["message"])
    self.assertEqual(form.totals_empty_label.text, self.mf.TOTALS_NOT_LOADED)
    # Moving through columns for par levels doesn't keep calling and warning.
    state.calls.clear()
    warnings = len(state.notifications)
    form.column_dropdown.selected_value = "B-c1"
    form.column_dropdown_change()
    self.assertEqual(state.calls, [])
    self.assertEqual(len(state.notifications), warnings)
    self.assertTrue(form.totals_empty_label.visible)
    del state.routes["get_section_totals"]
    form.range_dropdown_change()
    self.assertEqual(state.calls, [("get_section_totals", "B", 30)])
    self.assertTrue(form.totals_plot.visible)

  def test_admin_roles_card_lives_on_the_email_tab(self):
    with open(os.path.join(CLIENT_DIR, "MainForm", "form_template.html")) as f:
      html = f.read()
    self.assertLess(html.index('name="email_panel"'), html.index("Admin roles and permissions"))


class CustomizeTest(FormTest):
  def setUp(self):
    super().setUp()
    self.form._snapshot["tables"][1]["expanded"] = True
    self.form._open_table_editor()

  def test_opens_on_the_section_in_view_with_the_latest_setup(self):
    self.assertEqual(self.form._active_tab, "customize")
    self.assertEqual(self.form._active_card["table_key"], "A")
    self.assertEqual(self.form.section_name_box.text, "Freezer")
    add_section("C", "Bar", order=3)
    self.form.cancel_setup_button_click()
    self.form._open_table_editor()
    self.assertEqual(self.labels(), ["Freezer", "Fridge", "Bar"])

  def test_spacing_and_undone_edits_do_not_count(self):
    self.assertFalse(self.edited())
    self.assertEqual(self.form.edited_status_button.text, "No unsaved changes")
    self.type_into("row_labels_area", "  Ice \n\n")
    self.assertFalse(self.edited())
    self.type_into("section_name_box", "Freezer!")
    self.assertTrue(self.edited())
    self.assertEqual(self.form.edited_status_button.text, "Edited · Save now")
    self.type_into("section_name_box", " Freezer ")
    self.assertFalse(self.edited())
    self.form.move_down_button_click()
    self.assertTrue(self.edited())
    self.form.move_up_button_click()
    self.assertFalse(self.edited())
    self.form.clone_section_button_click()
    self.assertTrue(self.edited())
    self.form.delete_section_button_click()
    self.assertFalse(self.edited())

  def test_moving_follows_the_selected_section(self):
    form = self.form
    self.assertEqual((form.move_up_button.enabled, form.move_down_button.enabled), (False, True))
    form.move_down_button_click()
    self.assertEqual(self.labels(), ["Fridge", "Freezer"])
    self.assertTrue(form.section_list_panel.items[1]["selected"])
    self.assertEqual((form.move_up_button.enabled, form.move_down_button.enabled), (True, False))

  def test_renaming_never_moves_a_sections_key(self):
    for name in ["Fr", "Fridge", "Fridge 2"]:
      self.type_into("section_name_box", name)
    pairs = [(c["table_key"], c["label"]) for c in self.form._section_cards]
    self.assertEqual(pairs, [("A", "Fridge 2"), ("B", "Fridge")])

  def test_list_selection_switches_the_boxes(self):
    self.form.section_list_panel.raise_event("x-select-section", index=1)
    self.assertEqual(self.form.section_name_box.text, "Fridge")
    self.assertEqual(self.form.row_labels_area.text, "Milk\nEggs")
    self.type_into("row_labels_area", "Milk\nEggs\nButter")
    self.assertEqual(self.form.section_list_panel.items[1]["row_count"], 3)

  def test_clones_get_free_names_and_no_key(self):
    form = self.form
    form.clone_section_button_click()
    form.clone_section_button_click()
    self.assertEqual(self.labels(), ["Freezer", "Freezer copy", "Freezer copy copy", "Fridge"])
    form._select_section(form._section_cards[0])
    form.clone_section_button_click()
    self.assertEqual(self.labels()[1], "Freezer copy 2")
    self.assertIsNone(form._section_cards[1]["table_key"])
    self.assertEqual(form._section_cards[1]["row_labels_text"], "Ice")

  def test_clone_names_stay_under_the_limit(self):
    self.type_into("section_name_box", "x" * 60)
    self.form.clone_section_button_click()
    self.assertEqual(self.form._active_card["label"], "x" * 55 + " copy")
    self.form._select_section(self.form._section_cards[0])
    self.type_into("section_name_box", " ")
    self.form.clone_section_button_click()
    self.assertEqual(self.form._active_card["label"], "Section copy")

  def test_adding_a_section(self):
    form = self.form
    form.new_section_box.text = "  freezer "
    form.add_section_button_click()
    self.assertEqual(len(self.labels()), 2)
    self.assertIn("already called", state.notifications[-1])
    form.new_section_box.text = "Bar"
    form.new_section_box_pressed_enter()
    self.assertEqual(self.labels(), ["Freezer", "Fridge", "Bar"])
    self.assertEqual((form.section_name_box.text, form.row_labels_area.text, form.new_section_box.text), ("Bar", "", ""))
    self.assertTrue(form.row_labels_area.focused)

  def test_deleting_a_saved_section_asks_first(self):
    state.confirm_answers.append(False)
    self.form.delete_section_button_click()
    self.assertEqual(self.labels(), ["Freezer", "Fridge"])
    state.confirm_answers.append(True)
    self.form.delete_section_button_click()
    self.assertEqual(self.labels(), ["Fridge"])
    self.assertEqual(self.form._active_card["label"], "Fridge")
    self.assertFalse(self.form.delete_section_button.enabled)

  def test_deleting_an_unsaved_section_does_not_ask(self):
    self.form.clone_section_button_click()
    self.form.delete_section_button_click()
    self.assertEqual(state.confirms, [])

  def test_section_limit_turns_off_add_and_clone(self):
    form = self.form
    while len(form._section_cards) < 10:
      form.new_section_box.text = f"S{len(form._section_cards)}"
      form._add_section()
    self.assertFalse(form.clone_section_button.enabled)
    self.assertFalse(form.add_section_button.enabled)
    self.assertFalse(form.new_section_box.enabled)

  def test_name_problems_show_while_typing(self):
    self.type_into("section_name_box", "FRIDGE")
    self.assertTrue(self.form.section_name_error.visible)
    self.assertIn("already called", self.form.section_name_error.text)
    self.assertTrue(self.form.section_list_panel.items[0]["label"].startswith("⚠ "))
    self.type_into("section_name_box", "freezer")
    self.assertFalse(self.form.section_name_error.visible)
    self.type_into("section_name_box", "   ")
    self.assertEqual(self.form.section_name_error.text, "Give this section a name.")
    self.type_into("section_name_box", "x" * 61)
    self.assertIn("under 60", self.form.section_name_error.text)

  def test_save_with_a_name_problem_opens_it_instead_of_calling(self):
    self.type_into("section_name_box", "Fridge")
    self.form._select_section(self.form._section_cards[1])
    state.calls.clear()
    self.form.edited_status_button_click()
    self.assertEqual(state.calls, [])
    self.assertEqual(self.form._active_card["table_key"], "A")
    self.assertIn("already called", state.notifications[-1])

  def test_save_writes_the_setup_and_returns_to_the_grid(self):
    self.type_into("section_name_box", "Deep freeze")
    self.form.new_section_box.text = "Bar"
    self.form._add_section()
    self.type_into("row_labels_area", "Lime\nLemon")
    self.type_into("column_labels_area", "Each")
    self.form.edited_status_button_click()
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(state.confirms, [])
    self.assertEqual([t["label"] for t in self.form.tables_panel.items], ["Deep freeze", "Fridge", "Bar"])
    self.assertEqual(self.form.tables_panel.items[2]["row_labels"], ["Lime", "Lemon"])

  def test_save_after_someone_else_saved_is_refused(self):
    version = inv.get_inventory_grid()["setup_version"]
    inv.save_inventory_configuration([
      {"table_key": "A", "label": "Theirs", "row_labels_text": "Ice", "column_labels_text": "Qty"},
    ], version)
    self.type_into("section_name_box", "Mine")
    self.form.edited_status_button_click()
    self.assertEqual(state.notifications[-1], inv.STALE_SETUP_MESSAGE)
    self.assertEqual(self.form._active_tab, "customize")
    self.assertEqual(app_tables.inventory_tables.get(table_key="A")["label"], "Theirs")

  def test_failed_save_warns_and_keeps_the_edits(self):
    state.routes["save_inventory_configuration"] = boom
    self.type_into("section_name_box", "Mine")
    self.form.edited_status_button_click()
    self.assertEqual(state.notifications[-1], self.mf.SAVE_FAILED["message"])
    self.assertTrue(self.edited())
    self.assertTrue(self.form.cancel_setup_button.enabled)


class UnsavedGuardTest(FormTest):
  def setUp(self):
    super().setUp()
    self.form._open_table_editor()

  def test_leaving_clean_does_not_ask(self):
    self.assertTrue(self.form._set_active_tab("analytics"))
    self.assertEqual(state.confirms, [])

  def test_leaving_with_edits_asks(self):
    self.type_into("section_name_box", "Changed")
    state.confirm_answers.append(False)
    self.form.grid_tab_button_click()
    self.assertEqual(self.form._active_tab, "customize")
    state.confirm_answers.append(True)
    self.form.grid_tab_button_click()
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(len(state.confirms), 2)

  def test_closing_the_page_with_edits_warns(self):
    event = Event()
    self.form._on_before_unload(event)
    self.assertFalse(event.prevented)
    self.type_into("section_name_box", "Changed")
    event = Event()
    state.window.listeners["beforeunload"](event)
    self.assertTrue(event.prevented)

  def test_cancel_discards_without_asking(self):
    self.type_into("section_name_box", "Changed")
    self.form.cancel_setup_button_click()
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(state.confirms, [])
    self.assertEqual(app_tables.inventory_tables.get(table_key="A")["label"], "Freezer")

  def test_logout_asks_then_reloads(self):
    self.type_into("section_name_box", "Changed")
    state.confirm_answers.append(False)
    self.form.logout_button_click()
    self.assertEqual((state.logouts, state.window.reloaded), (0, False))
    state.confirm_answers.append(True)
    self.form.logout_button_click()
    self.assertEqual((state.logouts, state.window.reloaded), (1, True))


class GuidedEntryTest(FormTest):
  def setUp(self):
    super().setUp()
    self.form.guided_tab_button_click()

  def test_walks_every_cell_of_every_section(self):
    form = self.form
    self.assertEqual(form.wizard_step_label.text, "Cell 1 of 5")
    self.assertEqual(form.wizard_target_label.text, "Freezer  ·  Ice  ·  Qty")
    self.assertEqual(form.wizard_quantity_box.text, "7")
    for _ in range(4):
      form.wizard_next_button_click()
    self.assertEqual(form.wizard_next_button.text, "Finish")
    self.assertEqual(form.wizard_target_label.text, "Fridge  ·  Eggs  ·  Cases")
    form.wizard_next_button_click()
    self.assertEqual(form.wizard_step_label.text, "Guided entry complete")
    self.assertTrue(form.wizard_close_button.visible)
    self.assertEqual(form.dom_nodes["wizard_quantity_field"].style.display, "none")
    self.assertEqual(len(app_tables.inventory_history.rows), 5)

  def test_zero_saves_zero(self):
    self.form.wizard_zero_button_click()
    self.assertEqual(app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")["quantity"], 0)
    self.assertEqual(self.form.wizard_step_label.text, "Cell 2 of 5")

  def test_refused_step_stays_and_restores_the_box(self):
    self.form.wizard_quantity_box.text = "lots"
    self.form.wizard_next_button_click()
    self.assertEqual(self.form.wizard_step_label.text, "Cell 1 of 5")
    self.assertEqual(self.form.wizard_quantity_box.text, "7")
    self.assertTrue(self.form.wizard_next_button.enabled)

  def test_exit_saves_only_an_edit(self):
    self.form.wizard_exit_button_click()
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(app_tables.inventory_history.rows, [])
    self.form.guided_tab_button_click()
    self.form.wizard_quantity_box.text = "2"
    self.form.wizard_exit_button_click()
    self.assertEqual(self.form._active_tab, "grid")
    self.assertEqual(len(app_tables.inventory_history.rows), 1)

  def test_back_returns_to_the_saved_count(self):
    form = self.form
    self.assertFalse(form.wizard_back_button.visible)
    form.wizard_quantity_box.text = "3"
    form.wizard_next_button_click()
    self.assertTrue(form.wizard_back_button.visible)
    form.wizard_back_button_click()
    self.assertEqual(form.wizard_step_label.text, "Cell 1 of 5")
    self.assertEqual(form.wizard_quantity_box.text, "3")
    self.assertEqual(len(app_tables.inventory_history.rows), 1)

  def test_back_saves_only_an_edit(self):
    form = self.form
    form.wizard_next_button_click()
    form.wizard_back_button_click()
    self.assertEqual(len(app_tables.inventory_history.rows), 1)
    form.wizard_next_button_click()
    self.assertEqual(len(app_tables.inventory_history.rows), 1)
    form.wizard_quantity_box.text = "4"
    form.wizard_back_button_click()
    self.assertEqual(form.wizard_step_label.text, "Cell 1 of 5")
    self.assertEqual(len(app_tables.inventory_history.rows), 2)

  def test_back_moves_before_the_reload(self):
    form = self.form
    form.wizard_next_button_click()
    form.wizard_quantity_box.text = "4"
    load = load_server().get_inventory_grid
    def tap_again():
      # A second tap while the reload is out.
      state.routes.pop("get_inventory_grid")
      form.wizard_back_button_click()
      return load()
    state.routes["get_inventory_grid"] = tap_again
    form.wizard_back_button_click()
    self.assertEqual(form._wizard_index, 0)
    self.assertEqual(form.wizard_step_label.text, "Cell 1 of 5")

  def test_back_shows_a_count_saved_from_the_grid(self):
    form = self.form
    form.wizard_next_button_click()
    app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")["quantity"] = 9
    form.wizard_quantity_box.text = "4"
    form.wizard_next_button_click()
    form.wizard_back_button_click()
    form.wizard_back_button_click()
    self.assertEqual(form.wizard_quantity_box.text, "9")

  def test_refused_back_stays(self):
    form = self.form
    form.wizard_next_button_click()
    form.wizard_quantity_box.text = "lots"
    form.wizard_back_button_click()
    self.assertEqual(form.wizard_step_label.text, "Cell 2 of 5")

  def test_back_leaves_the_done_screen(self):
    form = self.form
    for _ in range(5):
      form.wizard_next_button_click()
    self.assertTrue(form.wizard_back_button.visible)
    form.wizard_back_button_click()
    self.assertEqual(form.wizard_step_label.text, "Cell 5 of 5")
    self.assertFalse(form.wizard_close_button.visible)
    self.assertEqual(len(app_tables.inventory_history.rows), 5)

  def test_quick_quantities(self):
    form = self.form
    form.wizard_half_button_click()
    self.assertEqual(form.wizard_quantity_box.text, "0.5")
    form.wizard_plus_one_button_click()
    self.assertEqual(form.wizard_quantity_box.text, "1.5")
    form.wizard_quantity_box.text = "abc"
    form.wizard_plus_one_button_click()
    self.assertEqual(form.wizard_quantity_box.text, "1")


class SignInTest(unittest.TestCase):
  def setUp(self):
    state.reset()
    self.mf = load_form("MainForm")

  def test_shows_the_signed_in_user(self):
    form = self.mf.MainForm()
    self.assertEqual(form.user_email_label.text, "bm@example.com")
    self.assertIn("beforeunload", state.window.listeners)

  def test_password_reset_link_logs_out_the_remembered_user(self):
    def reset_requested(*args, **kwargs):
      raise self.mf.anvil.users.PasswordResetRequested()
    state.routes["anvil.private.users.get_current_user"] = reset_requested
    self.mf.MainForm()
    self.assertEqual(state.logouts, 1)
    self.assertIn("Log in with your new password to continue.", state.alerts)


if __name__ == "__main__":
  unittest.main()
