import unittest

from tests.support import Component, load_form, state


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
    item = {"entry_quantity": "3", "latest_display": "BM · 03/04", "editable": True}
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
    self.cell.show_saved("4", "BM · 03/05")
    self.assertEqual(self.cell.item["latest_display"], "BM · 03/05")
    self.leave_with("4")
    self.assertEqual(self.raised, [])
    self.cell.revert()
    self.assertEqual(self.cell.item["entry_quantity"], "4")

  def test_view_only_cells_are_disabled(self):
    module = load_form("MainForm", "GridCell")
    cell = module.GridCell(item={"entry_quantity": "3", "latest_display": "", "editable": False})
    self.assertFalse(cell.quantity_box.enabled)


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


if __name__ == "__main__":
  unittest.main()
