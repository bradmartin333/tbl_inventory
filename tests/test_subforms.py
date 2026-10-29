import unittest

from tests.support import Component, load_form, state


def saved_count(entry_quantity, latest_display, below_par=False, overdue=False):
  # What save_grid_cell sends back.
  return {
    "entry_quantity": entry_quantity, "latest_display": latest_display, "par_text": "2",
    "days_text": "", "below_par": below_par, "overdue": overdue, "alert_text": "",
  }


def parent_recording(event):
  # A parent panel that records what its child raises.
  parent = Component()
  raised = []
  parent.add_event_handler(event, lambda **event_args: raised.append(event_args))
  return parent, raised


class GridCellTest(unittest.TestCase):
  def setUp(self):
    state.reset()
    module = load_form("MainForm", "GridCell")
    item = {
      "entry_quantity": "3", "latest_display": "BM · 03/04", "editable": True,
      "below_par": False, "overdue": True,
    }
    self.cell = module.GridCell(item=item)
    self.cell.parent, self.raised = parent_recording("x-save-cell")

  def leave_with(self, text):
    self.cell.quantity_box.text = text
    self.cell.quantity_box_lost_focus()

  def test_unchanged_box_saves_nothing(self):
    self.leave_with(" 3 ")
    self.assertEqual(self.raised, [])

  def test_cleared_box_reverts(self):
    self.cell.item["entry_quantity"] = ""
    self.leave_with("  ")
    self.assertEqual(self.raised, [])
    self.assertEqual(self.cell.item["entry_quantity"], "3")

  def test_changed_box_asks_to_save(self):
    self.cell.quantity_box.text = " 4 "
    self.cell.quantity_box_pressed_enter()
    self.assertEqual(self.raised, [{"cell": self.cell, "quantity": "4"}])

  def test_saved_value_becomes_the_new_baseline(self):
    self.cell.show_saved(saved_count("4", "BM · 03/05"))
    self.assertEqual(self.cell.item["latest_display"], "BM · 03/05")
    self.leave_with("4")
    self.assertEqual(self.raised, [])
    self.cell.revert()
    self.assertEqual(self.cell.item["entry_quantity"], "4")

  def test_view_only_cells_are_disabled(self):
    module = load_form("MainForm", "GridCell")
    cell = module.GridCell(item={
      "entry_quantity": "3", "latest_display": "", "editable": False, "below_par": False, "overdue": False,
    })
    self.assertFalse(cell.quantity_box.enabled)

  def test_par_flags_mark_the_cell_and_follow_a_save(self):
    classes = self.cell.dom_nodes["cell"].classList.names
    self.assertEqual(classes, {"is-overdue"})
    self.cell.show_saved(saved_count("1", "BM · 03/05", below_par=True))
    self.assertEqual(classes, {"is-below-par"})


class GridSectionTest(unittest.TestCase):
  def make(self, expanded, rows=1):
    module = load_form("MainForm", "GridSection")
    return module.GridSection(item={
      "label": "Freezer",
      "show_toggle": True,
      "expanded": expanded,
      "columns": [{"column_key": "c1", "label": "Qty"}, {"column_key": "c2", "label": "Cases"}],
      "rows": [{"row_key": f"r{i}", "label": f"Item {i}", "cells": []} for i in range(rows)],
    })

  def test_open_section_shows_its_rows(self):
    section = self.make(expanded=True)
    self.assertEqual(section.toggle_button.text, "▾  Freezer  ·  1 item")
    self.assertEqual(len(section.rows_panel.items), 1)
    self.assertIn("is-expanded", section.dom_nodes["section"].classList.names)
    self.assertEqual(section.dom_nodes["matrix"].style.properties["--matrix-columns"], "2")

  def test_closed_section_builds_no_rows(self):
    section = self.make(expanded=False, rows=2)
    self.assertEqual(section.toggle_button.text, "▸  Freezer  ·  2 items")
    self.assertEqual(section.rows_panel.items, [])
    self.assertEqual(section.dom_nodes["matrix_scroll"].style.display, "none")

  def test_toggle_flips_and_remembers(self):
    section = self.make(expanded=False)
    section.toggle_button_click()
    self.assertTrue(section.item["expanded"])
    self.assertEqual(len(section.rows_panel.items), 1)

  def test_forwards_cell_saves(self):
    section = self.make(expanded=True)
    section.parent, raised = parent_recording("x-save-cell")
    section.rows_panel.raise_event("x-save-cell", cell="cell", quantity="2")
    self.assertEqual(raised, [{"cell": "cell", "quantity": "2"}])


class SectionListItemTest(unittest.TestCase):
  def make(self, rows, columns, selected):
    module = load_form("MainForm", "SectionListItem")
    return module.SectionListItem(item={
      "index": 2, "label": "Freezer", "row_count": rows, "column_count": columns, "selected": selected,
    })

  def test_counts_read_naturally(self):
    self.assertEqual(self.make(1, 1, False).select_button.text, "Freezer  ·  1 row  ·  1 column")
    self.assertEqual(self.make(0, 3, False).select_button.text, "Freezer  ·  0 rows  ·  3 columns")

  def test_selected_item_is_marked(self):
    self.assertIn("is-selected", self.make(1, 1, True).dom_nodes["item"].classList.names)
    self.assertNotIn("is-selected", self.make(1, 1, False).dom_nodes["item"].classList.names)

  def test_click_sends_its_position(self):
    item = self.make(1, 1, False)
    item.parent, raised = parent_recording("x-select-section")
    item.select_button_click()
    self.assertEqual(raised, [{"index": 2}])


class ParLevelRowTest(unittest.TestCase):
  def setUp(self):
    module = load_form("MainForm", "ParLevelRow")
    self.row = module.ParLevelRow(item={
      "row_key": "r", "column_key": "c", "label": "Ice", "entry_quantity": "1",
      "par_text": "4", "days_text": "", "below_par": True, "overdue": False,
    })
    # The boxes as their bindings fill them.
    self.row.par_box.text, self.row.days_box.text = "4", ""
    self.sent = []
    # Answers each save the way MainForm does; a test can type during it.
    self.during_save = None
    self.refuse = False
    self.row.parent = Component()
    self.row.parent.add_event_handler("x-save-par", self.answer)

  def answer(self, row, par, days):
    self.sent.append((par, days))
    if self.during_save:
      during, self.during_save = self.during_save, None
      during()
    if self.refuse:
      row.revert()
    else:
      # The server tidies "7.0" to "7".
      row.show_saved({
        "par_text": par.replace(".0", ""), "days_text": days.replace(".0", ""),
        "below_par": False, "overdue": days != "",
      })

  def enter(self, par, days):
    self.row.par_box.text = par
    self.row.days_box.text = days

  def test_untouched_boxes_save_nothing(self):
    self.enter(" 4 ", "")
    self.row.par_box_lost_focus()
    self.row.days_box_lost_focus()
    self.assertEqual(self.sent, [])

  def test_either_box_saves_the_pair_and_takes_the_tidy_value(self):
    self.enter("4", " 7.0 ")
    self.row.days_box_pressed_enter()
    self.assertEqual(self.sent, [("4", "7.0")])
    self.assertEqual((self.row.days_box.text, self.row.item["days_text"]), ("7", "7"))
    self.assertEqual(self.row.dom_nodes["row"].classList.names, {"is-overdue"})

  def test_an_edit_made_while_saving_is_kept_and_saved_next(self):
    self.enter("5", "")

    def type_days():
      # Tab to Days, type, and leave it before the par save lands.
      self.row.days_box.text = "7"
      self.row.days_box_lost_focus()

    self.during_save = type_days
    self.row.par_box_lost_focus()
    self.assertEqual(self.sent, [("5", ""), ("5", "7")])
    self.assertEqual((self.row.par_box.text, self.row.days_box.text), ("5", "7"))

  def test_refused_save_reverts_only_what_was_sent_and_is_not_retried(self):
    self.refuse = True
    self.enter("lots", "")
    self.row.par_box_lost_focus()
    self.assertEqual(self.sent, [("lots", "")])
    self.assertEqual(self.row.par_box.text, "4")
    self.enter("lots", "")

    def type_days():
      self.row.days_box.text = "7"

    self.during_save = type_days
    self.sent.clear()
    self.row.par_box_lost_focus()
    # Par goes back; the days typed meanwhile stay and are sent once.
    self.assertEqual(self.sent, [("lots", ""), ("4", "7")])
    self.assertEqual((self.row.par_box.text, self.row.days_box.text), ("4", ""))


class ParAlertItemTest(unittest.TestCase):
  def test_marks_the_kind_of_alert(self):
    module = load_form("MainForm", "ParAlertItem")
    item = module.ParAlertItem(item={"label": "Ice", "detail": "Low", "below_par": True, "overdue": True})
    self.assertEqual(item.dom_nodes["item"].classList.names, {"is-below-par", "is-overdue"})


if __name__ == "__main__":
  unittest.main()
