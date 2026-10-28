from datetime import datetime, time, timedelta
import unittest

from tests.support import add_section, app_tables, load_server, state


inv = load_server()


def card(key, label, rows="Ice", cols="Qty"):
  return {"table_key": key, "label": label, "row_labels_text": rows, "column_labels_text": cols}


def version():
  return inv.get_inventory_grid()["setup_version"]


def save(cards):
  return inv.save_inventory_configuration(cards, version())


def sections():
  return [(t["table_key"], t["label"]) for t in inv.get_inventory_grid()["tables"]]


def cells_for(key):
  return [c for c in app_tables.inventory_cells.rows if c["row_key"].startswith(key + "-")]


class ServerTest(unittest.TestCase):
  def setUp(self):
    state.reset()


class DefaultGridTest(ServerTest):
  def test_first_load_makes_one_default_section(self):
    grid = inv.get_inventory_grid()
    self.assertEqual([t["label"] for t in grid["tables"]], [inv.DEFAULT_TABLE])
    self.assertEqual(grid["tables"][0]["row_labels"], inv.DEFAULT_ROWS)
    self.assertEqual(grid["tables"][0]["column_labels"], inv.DEFAULT_COLUMNS)
    inv.get_inventory_grid()
    self.assertEqual(len(app_tables.inventory_tables.rows), 1)

  def test_uncounted_cells_show_zero_and_write_nothing(self):
    cell = inv.get_inventory_grid()["tables"][0]["rows"][0]["cells"][0]
    self.assertEqual((cell["entry_quantity"], cell["latest_display"]), ("0", "Not entered"))
    self.assertEqual(app_tables.inventory_cells.rows, [])

  def test_rows_and_columns_from_before_sections_join_the_first_section(self):
    for i, label in enumerate(["Rice", "Flour"], 1):
      app_tables.inventory_rows.add_row(row_key=f"r{i}", label=label, sort_order=i, active=True)
    for i, label in enumerate(["Cases", "Loose"], 1):
      app_tables.inventory_columns.add_row(column_key=f"c{i}", label=label, sort_order=i, active=True)
    app_tables.inventory_cells.add_row(row_key="r1", column_key="c1", quantity=3)
    table = inv.get_inventory_grid()["tables"][0]
    self.assertEqual(table["row_labels"], ["Rice", "Flour"])
    self.assertEqual(table["column_labels"], ["Cases", "Loose"])
    self.assertEqual(table["rows"][0]["cells"][0]["entry_quantity"], "3")

  def test_snapshot_carries_limits_and_initials(self):
    grid = inv.get_inventory_grid()
    self.assertEqual(grid["initials"], "BM")
    self.assertEqual(grid["limits"], {
      "sections": inv.MAX_SECTIONS, "rows": inv.MAX_ROWS,
      "columns": inv.MAX_COLUMNS, "label_length": inv.MAX_LABEL_LENGTH,
    })

  def test_sections_rows_and_columns_come_back_in_sort_order(self):
    add_section("B", "Fridge", order=2)
    add_section("A", "Freezer", rows=("Peas", "Ice"), order=1)
    app_tables.inventory_rows.get(row_key="A-r0")["sort_order"] = 3
    grid = inv.get_inventory_grid()
    self.assertEqual([t["label"] for t in grid["tables"]], ["Freezer", "Fridge"])
    self.assertEqual(grid["tables"][0]["row_labels"], ["Ice", "Peas"])


class SetupVersionTest(unittest.TestCase):
  tables = [
    {"table_key": "B", "label": "Fridge", "sort_order": 2},
    {"table_key": "A", "label": "Freezer", "sort_order": 1},
  ]
  rows = [
    {"row_key": "r2", "table_key": "A", "label": "Ice", "sort_order": 1},
    {"row_key": "r1", "table_key": "B", "label": None, "sort_order": 1},
  ]
  columns = [{"column_key": "c1", "table_key": "A", "label": "Qty", "sort_order": 1}]

  def test_ignores_search_order(self):
    self.assertEqual(
      inv._setup_version(self.tables, self.rows, self.columns),
      inv._setup_version(self.tables[::-1], self.rows[::-1], self.columns),
    )

  def test_changes_with_order_and_with_new_items(self):
    before = inv._setup_version(self.tables, self.rows, self.columns)
    moved = [dict(t) for t in self.tables]
    moved[0]["sort_order"] = 3
    self.assertNotEqual(before, inv._setup_version(moved, self.rows, self.columns))
    added = self.columns + [{"column_key": "c2", "table_key": "B", "label": "Cases", "sort_order": 1}]
    self.assertNotEqual(before, inv._setup_version(self.tables, self.rows, added))


class SaveConfigurationTest(ServerTest):
  def test_rename_and_reorder_keep_counts(self):
    add_section("A", "Freezer")
    self.assertEqual(save([card(None, "Fridge"), card("A", "Deep freeze")]), {"ok": True})
    self.assertEqual([label for _, label in sections()], ["Fridge", "Deep freeze"])
    self.assertEqual(len(cells_for("A")), 1)

  def test_same_row_name_in_another_section_is_a_new_row(self):
    add_section("A", "Freezer")
    save([card("A", "Freezer"), card(None, "Fridge")])
    fridge = inv.get_inventory_grid()["tables"][1]
    self.assertNotEqual(fridge["rows"][0]["row_key"], "A-r0")
    self.assertEqual(fridge["rows"][0]["cells"][0]["entry_quantity"], "0")

  def test_deleting_a_section_drops_its_rows_columns_and_counts_but_not_history(self):
    add_section("A", "Freezer")
    add_section("B", "Fridge")
    app_tables.inventory_history.add_row(entry_id="h1", table_key="B", table_label="Fridge")
    self.assertEqual(save([card("A", "Freezer")]), {"ok": True})
    self.assertEqual(sections(), [("A", "Freezer")])
    self.assertEqual(cells_for("B"), [])
    self.assertEqual(app_tables.inventory_rows.search(table_key="B"), [])
    self.assertEqual(app_tables.inventory_columns.search(table_key="B"), [])
    self.assertEqual(len(app_tables.inventory_history.rows), 1)

  def test_re_adding_a_deleted_section_starts_fresh(self):
    add_section("A", "Freezer")
    add_section("B", "Fridge")
    save([card("A", "Freezer")])
    save([card("A", "Freezer"), card(None, "Fridge")])
    new_key = dict((label, key) for key, label in sections())["Fridge"]
    self.assertNotEqual(new_key, "B")
    self.assertEqual(cells_for(new_key), [])

  def test_removed_row_goes_with_its_counts(self):
    add_section("A", "Freezer", rows=("Ice", "Peas"))
    self.assertEqual(save([card("A", "Freezer", rows="Peas\nCorn")]), {"ok": True})
    self.assertEqual(sorted(r["label"] for r in app_tables.inventory_rows.rows), ["Corn", "Peas"])
    self.assertEqual([c["row_key"] for c in app_tables.inventory_cells.rows], ["A-r1"])

  def test_labels_match_ignoring_case_and_spacing(self):
    add_section("A", "Freezer", rows=("Ice",))
    save([card("A", "Freezer", rows="  ICE \n\n")])
    self.assertEqual([r["row_key"] for r in app_tables.inventory_rows.rows], ["A-r0"])
    self.assertEqual(app_tables.inventory_rows.rows[0]["label"], "ICE")

  def test_hidden_items_from_before_real_deletes_are_skipped_then_cleared(self):
    add_section("A", "Freezer")
    add_section("H", "Old", active=False)
    app_tables.inventory_rows.add_row(row_key="A-old", table_key="A", label="Gone", sort_order=9, active=False)
    app_tables.inventory_cells.add_row(row_key="A-old", column_key="A-c0", quantity=3)
    self.assertEqual(sections(), [("A", "Freezer")])
    self.assertEqual(inv.get_inventory_grid()["tables"][0]["row_labels"], ["Ice"])
    self.assertEqual(save([card("A", "Freezer")]), {"ok": True})
    self.assertEqual([t["table_key"] for t in app_tables.inventory_tables.rows], ["A"])
    self.assertIsNone(app_tables.inventory_rows.get(row_key="A-old"))
    self.assertEqual([c for c in app_tables.inventory_cells.rows if c["row_key"] in ("A-old", "H-r0")], [])

  def test_stale_version_is_refused(self):
    add_section("A", "Freezer")
    result = inv.save_inventory_configuration([card("A", "Freezer")], "old")
    self.assertEqual(result, {"ok": False, "message": inv.STALE_SETUP_MESSAGE})

  def test_bad_setups_are_refused_without_writing(self):
    add_section("A", "Freezer")
    long_name = "x" * (inv.MAX_LABEL_LENGTH + 1)
    cases = {
      "no sections": ([], "Keep between 1"),
      "too many sections": ([card(None, f"S{i}") for i in range(inv.MAX_SECTIONS + 1)], "Keep between 1"),
      "blank name": ([card("A", "  ")], "Give every section a name."),
      "long name": ([card("A", long_name)], "under 60 characters"),
      "same name twice": ([card("A", "Freezer"), card(None, "FREEZER ")], "Two sections are called FREEZER"),
      "no rows": ([card("A", "Freezer", rows="\n ")], "Freezer: enter 1–50 unique row labels"),
      "duplicate rows": ([card("A", "Freezer", rows="Ice\nice")], "Freezer: enter 1–50 unique row labels"),
      "too many columns": ([card("A", "Freezer", cols="a\nb\nc\nd\ne\nf")], "Freezer: enter 1–5 unique"),
      "long row label": ([card("A", "Freezer", rows=long_name)], "keep each row and column label"),
      "unknown section": ([card("nope", "Freezer")], inv.STALE_SETUP_MESSAGE),
      "section twice": ([card("A", "Freezer"), card("A", "Fridge")], inv.STALE_SETUP_MESSAGE),
      "not a card": (["Freezer"], inv.STALE_SETUP_MESSAGE),
    }
    before = app_tables.dump()
    for name, (cards, message) in cases.items():
      with self.subTest(name):
        result = save(cards)
        self.assertFalse(result["ok"])
        self.assertIn(message, result["message"])
        self.assertEqual(app_tables.dump(), before)


class SaveGridCellTest(ServerTest):
  def setUp(self):
    super().setUp()
    add_section("A", "Freezer", rows=("Ice",), cols=("Qty", "Cases"))
    add_section("B", "Fridge", order=2)

  def test_saves_the_count_and_logs_history(self):
    result = inv.save_grid_cell("A-r0", "A-c1", " 2.5 ")
    self.assertTrue(result["ok"])
    self.assertEqual(result["entry_quantity"], "2.5")
    self.assertTrue(result["latest_display"].startswith("BM · "))
    cell = app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c1")
    self.assertEqual((cell["quantity"], cell["entered_by"]), (2.5, "BM"))
    entry = app_tables.inventory_history.rows[-1]
    self.assertEqual(
      (entry["table_label"], entry["row_label"], entry["column_label"], entry["quantity"]),
      ("Freezer", "Ice", "Cases", 2.5),
    )

  def test_saving_again_updates_the_same_cell(self):
    inv.save_grid_cell("A-r0", "A-c0", "1")
    inv.save_grid_cell("A-r0", "A-c0", 4)
    self.assertEqual(len(app_tables.inventory_cells.search(row_key="A-r0", column_key="A-c0")), 1)
    self.assertEqual(len(app_tables.inventory_history.rows), 2)
    grid = inv.get_inventory_grid()
    self.assertEqual(grid["tables"][0]["rows"][0]["cells"][0]["entry_quantity"], "4")

  def test_bad_quantities_are_refused(self):
    for raw in ["", "  ", "abc", "-1", "nan", "inf", None, True, [1]]:
      with self.subTest(raw=raw):
        result = inv.save_grid_cell("A-r0", "A-c0", raw)
        self.assertEqual(result, {"ok": False, "message": "Enter a zero or greater number for Ice · Qty."})
    self.assertEqual(app_tables.inventory_history.rows, [])

  def test_stale_or_mismatched_keys_are_refused(self):
    for row_key, column_key in [("A-r0", "B-c0"), ("gone", "A-c0"), ("A-r0", None), (1, "A-c0")]:
      with self.subTest(row_key=row_key, column_key=column_key):
        result = inv.save_grid_cell(row_key, column_key, "1")
        self.assertEqual(result, {"ok": False, "message": inv.STALE_GRID_MESSAGE})

  def test_users_without_valid_initials_cannot_save(self):
    for initials in [None, "", "B1", "TOOLONG", 5]:
      with self.subTest(initials=initials):
        state.user["initials"] = initials
        result = inv.save_grid_cell("A-r0", "A-c0", "1")
        self.assertEqual(result, {"ok": False, "message": inv.NO_INITIALS_MESSAGE})
        self.assertIsNone(inv.get_inventory_grid()["initials"])

  def test_initials_are_tidied(self):
    state.user["initials"] = " bm "
    self.assertEqual(inv.get_inventory_grid()["initials"], "BM")


def days_ago(days):
  # Noon, so a test never lands on a day boundary.
  return datetime.combine(datetime.now().date() - timedelta(days=days), time(12))


def log(row_key, column_key, quantity, previous, days, table_key="A"):
  app_tables.inventory_history.add_row(
    entry_id=f"{row_key}-{days}", table_key=table_key, row_key=row_key, column_key=column_key,
    quantity=quantity, previous_quantity=previous, entered_at=days_ago(days),
  )


class SaveParLevelTest(ServerTest):
  def setUp(self):
    super().setUp()
    add_section("A", "Freezer", rows=("Ice", "Peas"))

  def snapshot_cell(self, row=0):
    return inv.get_inventory_grid()["tables"][0]["rows"][row]["cells"][0]

  def test_par_shows_in_the_snapshot_with_its_flags(self):
    result = inv.save_par_level("A-r0", "A-c0", " 10 ", "7")
    self.assertEqual(result, {
      "ok": True, "par_text": "10", "days_text": "7", "below_par": True, "overdue": True,
      "alert_text": "Low: 7 on hand, par 10 · Due: never counted, every 7 days",
    })
    cell = self.snapshot_cell()
    self.assertEqual((cell["par_text"], cell["days_text"], cell["below_par"]), ("10", "7", True))
    other = self.snapshot_cell(row=1)
    self.assertEqual((other["par_text"], other["below_par"], other["overdue"], other["alert_text"]), ("", False, False, ""))

  def test_at_par_and_recently_counted_is_fine(self):
    app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")["entered_at"] = days_ago(3)
    result = inv.save_par_level("A-r0", "A-c0", "7", "7")
    self.assertEqual((result["below_par"], result["overdue"], result["alert_text"]), (False, False, ""))

  def test_overdue_says_how_long_it_has_been(self):
    app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")["entered_at"] = days_ago(10)
    result = inv.save_par_level("A-r0", "A-c0", "", "1")
    self.assertEqual(result["alert_text"], "Due: last counted 10 days ago, every 1 day")

  def test_uncounted_cell_keeps_par_then_tidies_up(self):
    app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0").delete()
    inv.save_par_level("A-r0", "A-c0", "2", "")
    cell = self.snapshot_cell()
    self.assertEqual((cell["entry_quantity"], cell["latest_display"], cell["below_par"]), ("0", "Not entered", True))
    inv.save_par_level("A-r0", "A-c0", " ", "")
    self.assertIsNone(app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0"))

  def test_clearing_a_counted_cell_keeps_its_count(self):
    inv.save_par_level("A-r0", "A-c0", "2", "3")
    inv.save_par_level("A-r0", "A-c0", "", "")
    cell = app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")
    self.assertEqual((cell["quantity"], cell["par_quantity"], cell["max_days"]), (7, None, None))

  def test_bad_levels_are_refused_without_writing(self):
    cases = [
      ("-1", "", "Enter a par of zero or more for Ice · Qty"),
      ("lots", "", "Enter a par of zero or more"),
      ("", "0", "Enter 1–365 whole days between counts for Ice · Qty"),
      ("", "1.5", "whole days"),
      ("", "366", "whole days"),
      ("", "soon", "whole days"),
      ("", True, "whole days"),
    ]
    before = app_tables.dump()
    for par, days, message in cases:
      with self.subTest(par=par, days=days):
        result = inv.save_par_level("A-r0", "A-c0", par, days)
        self.assertFalse(result["ok"])
        self.assertIn(message, result["message"])
    for row_key, column_key in [("gone", "A-c0"), ("A-r0", None)]:
      self.assertEqual(inv.save_par_level(row_key, column_key, "1", ""), {"ok": False, "message": inv.STALE_GRID_MESSAGE})
    self.assertEqual(app_tables.dump(), before)

  def test_a_count_keeps_par_and_updates_the_flags(self):
    inv.save_par_level("A-r0", "A-c0", "10", "7")
    result = inv.save_grid_cell("A-r0", "A-c0", "12")
    self.assertEqual((result["below_par"], result["overdue"], result["par_text"]), (False, False, "10"))
    cell = app_tables.inventory_cells.get(row_key="A-r0", column_key="A-c0")
    self.assertEqual((cell["quantity"], cell["par_quantity"], cell["max_days"]), (12, 10, 7))
    self.assertEqual(app_tables.inventory_history.rows[-1]["previous_quantity"], 7)

  def test_removing_a_row_in_customize_takes_its_par(self):
    inv.save_par_level("A-r0", "A-c0", "10", "")
    save([card("A", "Freezer", rows="Peas")])
    self.assertEqual([c for c in app_tables.inventory_cells.rows if c["par_quantity"] is not None], [])


class SectionTotalsTest(ServerTest):
  def setUp(self):
    super().setUp()
    add_section("A", "Freezer", rows=("Ice", "Peas"), cols=("Qty", "Cases"))

  def test_steps_back_from_todays_counts(self):
    # Ice: 3 ten days ago, 7 two days ago. Peas: 7 five days ago. Cases has
    # no history, so today's counts held all month.
    log("A-r0", "A-c0", 3, None, 10)
    log("A-r0", "A-c0", 7, 3, 2)
    log("A-r1", "A-c0", 7, None, 5)
    # Outside the window, and a row that's since been deleted: neither counts.
    log("A-r0", "A-c0", 99, 50, 40)
    log("gone", "A-c0", 99, 50, 1)
    result = inv.get_section_totals("A", 30)
    self.assertTrue(result["ok"])
    self.assertEqual(len(result["dates"]), 30)
    self.assertEqual(result["dates"][-1], datetime.now().date().strftime("%Y-%m-%d"))
    qty, cases = result["series"]
    self.assertEqual((qty["label"], cases["label"]), ("Qty", "Cases"))
    self.assertEqual(qty["totals"], [None] * 19 + [3] * 5 + [10] * 3 + [14] * 3)
    self.assertEqual(cases["totals"], [14] * 30)

  def test_reads_five_times_and_only_the_window(self):
    log("A-r0", "A-c0", 3, None, 40)
    app_tables.reset_reads()
    result = inv.get_section_totals("A", 30)
    self.assertEqual(sum(app_tables.reads().values()), 5)
    self.assertEqual(result["series"][0]["totals"], [14] * 30)

  def test_bad_requests_are_refused(self):
    for table_key, days in [("A", 7), ("A", "30"), ("gone", 30), (None, 30)]:
      with self.subTest(table_key=table_key, days=days):
        self.assertEqual(inv.get_section_totals(table_key, days), {"ok": False, "message": inv.STALE_GRID_MESSAGE})


class LoadBudgetTest(ServerTest):
  def test_grid_load_still_reads_four_times(self):
    add_section("A", "Freezer")
    inv.save_par_level("A-r0", "A-c0", "10", "7")
    app_tables.reset_reads()
    inv.get_inventory_grid()
    self.assertEqual(app_tables.reads(), {
      "inventory_tables": 1, "inventory_rows": 1, "inventory_columns": 1, "inventory_cells": 1,
    })


class FormatTest(unittest.TestCase):
  def test_quantities_drop_trailing_zeros(self):
    self.assertEqual([inv._format_quantity(q) for q in (None, 0, 3.0, 2.5)], ["", "0", "3", "2.5"])

  def test_latest_shows_the_year_only_when_it_is_not_this_one(self):
    now = datetime.now()
    this_year = {"entered_by": "BM", "entered_at": datetime(now.year, 3, 4)}
    last_year = {"entered_by": "BM", "entered_at": datetime(now.year - 1, 3, 4)}
    self.assertEqual(inv._format_latest(this_year), "BM · 03/04")
    self.assertEqual(inv._format_latest(last_year), f"BM · 03/04/{(now.year - 1) % 100:02d}")
    self.assertEqual(inv._format_latest(None), "Not entered")


class ActivateAccountTest(ServerTest):
  def test_sends_a_reset_link_to_an_invited_email(self):
    self.assertEqual(inv.activate_account("  BM@Example.com "), {"ok": True})
    self.assertEqual(state.reset_emails, ["bm@example.com"])

  def test_refuses_anyone_not_ready(self):
    app_tables.users.add_row(email="off@example.com", enabled=False, initials="OF")
    app_tables.users.add_row(email="new@example.com", enabled=True)
    for email in ["off@example.com", "new@example.com", "who@example.com", None]:
      with self.subTest(email=email):
        self.assertFalse(inv.activate_account(email)["ok"])
    self.assertEqual(state.reset_emails, [])


if __name__ == "__main__":
  unittest.main()
