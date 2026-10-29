"""Just enough of Anvil to run this app's Python under plain CPython.

The server module runs against in-memory tables built from anvil.yaml, and
forms get stand-in components read from their form_template.html, so a test
can drive the real MainForm against the real server code.

None of this is Skulpt, the browser's Python: client code that passes here can
still fail in the browser. test_static.py catches the known gaps.
"""
import copy
import importlib
import os
import re
import sys
import types

# Keep __pycache__ out of client_code and server_code.
sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_DIR = os.path.join(ROOT, "client_code")
SERVER_DIR = os.path.join(ROOT, "server_code")
PACKAGE = "TBL_Inventory"


# Data tables

def read_schema():
  # {table name: set of column names}, from the db_schema block of anvil.yaml.
  with open(os.path.join(ROOT, "anvil.yaml")) as f:
    text = f.read()
  block = re.search(r"^db_schema:\n((?:[ -].*\n)+)", text, re.M).group(1)
  schema = {}
  for name, body in re.findall(r"^  (\w+):\n((?:   .*\n|  -.*\n)*)", block, re.M):
    schema[name] = set(re.findall(r"\bname: (\w+)", body))
  return schema


class Row(dict):
  # Like a real row: a column nobody set reads as None, an unknown one raises.
  def __init__(self, table, values):
    super().__init__()
    self._table = table
    self.update(**values)

  def __getitem__(self, key):
    self._table.check(key)
    return self.get(key)

  def __setitem__(self, key, value):
    self._table.check(key)
    super().__setitem__(key, value)

  def update(self, **values):
    for key, value in values.items():
      self[key] = value

  def delete(self):
    self._table.rows = [row for row in self._table.rows if row is not self]


class Matcher:
  # What anvil.tables.query's any_of() and the like stand for in a search.
  def __init__(self, test):
    self.test = test


def _matches(value, wanted):
  return wanted.test(value) if isinstance(wanted, Matcher) else value == wanted


class FetchOnly:
  def __init__(self, *columns):
    self.columns = columns


class Table:
  def __init__(self, name, columns):
    self.name = name
    self.columns = columns
    self.rows = []
    # Searches and gets since the last reset: each is a slow trip in Anvil.
    self.reads = 0

  def check(self, column):
    if column not in self.columns:
      raise KeyError(f"{self.name} has no column {column!r}")

  def search(self, *options, **filters):
    self.reads += 1
    for option in options:
      if not isinstance(option, FetchOnly):
        raise TypeError(f"unsupported search option {option!r}")
      for column in option.columns:
        self.check(column)
    for column in filters:
      self.check(column)
    return [row for row in self.rows if all(_matches(row.get(k), v) for k, v in filters.items())]

  def get(self, **filters):
    found = self.search(**filters)
    if len(found) > 1:
      raise ValueError(f"more than one {self.name} row matches {filters}")
    return found[0] if found else None

  def add_row(self, **values):
    row = Row(self, values)
    self.rows.append(row)
    return row


class AppTables:
  def __init__(self, schema):
    self._tables = {name: Table(name, columns) for name, columns in schema.items()}

  def __getattr__(self, name):
    try:
      return self._tables[name]
    except KeyError:
      raise AttributeError(f"anvil.yaml has no table {name!r}") from None

  def clear(self):
    for table in self._tables.values():
      table.rows = []
    self.reset_reads()

  def reset_reads(self):
    for table in self._tables.values():
      table.reads = 0

  def reads(self):
    # {table name: reads} for the tables read since reset_reads().
    return {name: table.reads for name, table in self._tables.items() if table.reads}

  def dump(self):
    # Everything stored, for checking a refused save wrote nothing.
    return {name: [dict(row) for row in table.rows] for name, table in self._tables.items()}


app_tables = AppTables(read_schema())


def add_section(key, label, rows=("Ice",), cols=("Qty",), active=True, order=1):
  # A saved section whose every cell holds 7.
  app_tables.inventory_tables.add_row(table_key=key, label=label, sort_order=order, active=active)
  for i, row_label in enumerate(rows):
    app_tables.inventory_rows.add_row(
      row_key=f"{key}-r{i}", table_key=key, label=row_label, sort_order=i + 1, active=active
    )
    for j, _ in enumerate(cols):
      app_tables.inventory_cells.add_row(row_key=f"{key}-r{i}", column_key=f"{key}-c{j}", quantity=7)
  for j, column_label in enumerate(cols):
    app_tables.inventory_columns.add_row(
      column_key=f"{key}-c{j}", table_key=key, label=column_label, sort_order=j + 1, active=active
    )


# Browser stand-ins

class Style:
  def __init__(self):
    self.display = ""
    self.properties = {}

  def setProperty(self, name, value):
    self.properties[name] = value


class ClassList:
  def __init__(self):
    self.names = set()

  def toggle(self, name, force):
    (self.names.add if force else self.names.discard)(name)


class DomNode:
  def __init__(self):
    self.style = Style()
    self.classList = ClassList()
    self.textContent = ""


class Event:
  def __init__(self):
    self.prevented = False
    self.returnValue = None

  def preventDefault(self):
    self.prevented = True


class Window:
  def __init__(self):
    self.scrollX = 0
    self.scrollY = 0
    self.listeners = {}
    self.reloaded = False
    self.location = types.SimpleNamespace(reload=self._reload)

  def _reload(self):
    self.reloaded = True

  def scrollTo(self, x, y):
    self.scrollX, self.scrollY = x, y

  def addEventListener(self, name, handler):
    self.listeners[name] = handler


class Component:
  def __init__(self, name=None, **properties):
    self.name = name
    self.text = ""
    self.enabled = True
    self.visible = True
    self.items = None
    self.parent = None
    self.focused = False
    self.handlers = {}
    for key, value in properties.items():
      setattr(self, key, value)

  def focus(self):
    self.focused = True

  def add_component(self, component):
    pass

  def add_event_handler(self, event, handler):
    self.handlers[event] = handler

  def raise_event(self, event, **event_args):
    self.handlers[event](**event_args)


def template_names(form_dir):
  # The components and DOM nodes a form's template declares.
  with open(os.path.join(form_dir, "form_template.html")) as f:
    html = f.read()
  components = re.findall(r"<anvil-component\b[^>]*\bname=\"([^\"]+)\"", html)
  dom_nodes = re.findall(r"anvil:dom-node=\"([^\"]+)\"", html)
  return components, dom_nodes


def _template_class(form_dir, class_name):
  components, dom_nodes = template_names(form_dir)

  class Template:
    def __init__(self, **properties):
      self.item = properties.get("item")
      self.parent = None
      self.refreshes = 0
      self.dom_nodes = {name: DomNode() for name in dom_nodes}
      for name in components:
        setattr(self, name, Component(name))

    def refresh_data_bindings(self):
      self.refreshes += 1

  Template.__name__ = class_name
  return Template


# The anvil modules

class State:
  # What the stand-ins record and answer, reset before each test.
  def __init__(self):
    self.reset()

  def reset(self):
    app_tables.clear()
    self.user = app_tables.users.add_row(email="bm@example.com", enabled=True, initials="BM")
    self.reset_emails = []
    self.logouts = 0
    # Queue answers for confirm(); each dialog shown is recorded.
    self.confirm_answers = []
    self.confirms = []
    self.alerts = []
    self.notifications = []
    # Client calls by name; anything not here goes to the server module.
    self.routes = {}
    self.calls = []
    self.window = Window()


state = State()


class Notification:
  def __init__(self, message, **kwargs):
    self.message = message
    self.visible = False

  def show(self):
    self.visible = True
    state.notifications.append(self.message)

  def hide(self):
    self.visible = False


def _confirm(message, **kwargs):
  state.confirms.append(message)
  if not state.confirm_answers:
    raise AssertionError(f"unexpected confirm: {message}")
  return state.confirm_answers.pop(0)


def _alert(message, **kwargs):
  state.alerts.append(message)
  return None


def _handle(component_name, event_name):
  return lambda method: method


def _callable(*args, **kwargs):
  # Both @anvil.server.callable and @anvil.server.callable(require_user=True).
  if args and callable(args[0]):
    return args[0]
  return lambda function: function


def _call(name, *args, **kwargs):
  # Copies stand in for the trip over the wire, so neither side can change
  # what the other holds.
  state.calls.append((name,) + args)
  if name in state.routes:
    return state.routes[name](*args, **kwargs)
  if name == "anvil.private.users.get_current_user":
    return state.user
  function = getattr(load_server(), name)
  return copy.deepcopy(function(*copy.deepcopy(args), **copy.deepcopy(kwargs)))


class PasswordResetRequested(Exception):
  pass


def _get_user(allow_remembered=True):
  return state.user


def _logout():
  state.logouts += 1


def _send_password_reset_email(email):
  state.reset_emails.append(email)


def _install():
  if "anvil" in sys.modules and getattr(sys.modules["anvil"], "_is_stub", False):
    return
  anvil = types.ModuleType("anvil")
  anvil._is_stub = True
  anvil.handle = _handle
  anvil.confirm = _confirm
  anvil.alert = _alert
  anvil.Notification = Notification
  anvil.TextBox = anvil.Label = anvil.ColumnPanel = Component

  server = types.ModuleType("anvil.server")
  server.callable = _callable
  server.background_task = lambda function: function
  server.call = server.call_s = _call

  users = types.ModuleType("anvil.users")
  users.get_user = _get_user
  users.logout = _logout
  users.send_password_reset_email = _send_password_reset_email
  users.PasswordResetRequested = PasswordResetRequested

  tables = types.ModuleType("anvil.tables")
  tables.app_tables = app_tables
  tables.in_transaction = lambda function: function

  query = types.ModuleType("anvil.tables.query")
  query.any_of = lambda *values: Matcher(lambda value: value in values)
  query.greater_than_or_equal_to = lambda bound: Matcher(
    lambda value: value is not None and value >= bound
  )
  query.fetch_only = FetchOnly
  tables.query = query

  js = types.ModuleType("anvil.js")
  # load_form points each form at the current test's window.
  js.window = None

  anvil.server, anvil.users, anvil.tables, anvil.js = server, users, tables, js
  for module in (anvil, server, users, tables, query, js):
    sys.modules[module.__name__] = module

  # The app package, laid out as the repo's own __init__.py lays it out.
  package = types.ModuleType(PACKAGE)
  package.__path__ = [SERVER_DIR, CLIENT_DIR]
  sys.modules[PACKAGE] = package

  # Every form's _anvil_designer, generated from its template.
  for folder, _, files in os.walk(CLIENT_DIR):
    if "form_template.html" not in files:
      continue
    parts = os.path.relpath(folder, CLIENT_DIR).split(os.sep)
    designer = types.ModuleType(".".join([PACKAGE] + parts + ["_anvil_designer"]))
    template_name = parts[-1] + "Template"
    setattr(designer, template_name, _template_class(folder, template_name))
    sys.modules[designer.__name__] = designer


def load_server():
  _install()
  return importlib.import_module(f"{PACKAGE}.Inventory")


def load_form(*parts):
  # load_form("MainForm") or load_form("MainForm", "GridCell"): the form's module.
  _install()
  module = importlib.import_module(".".join((PACKAGE,) + parts))
  # Forms bind window at import, so point it at this test's window.
  module.window = state.window
  return module
