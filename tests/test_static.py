"""Checks read straight from the source, for what running it under CPython can't show."""
import ast
import os
import unittest

from tests.support import CLIENT_DIR, SERVER_DIR, template_names


# Fine in CPython, missing in Skulpt, so they only break in the browser.
SKULPT_MISSING_METHODS = {"casefold", "removeprefix", "removesuffix"}
SKULPT_MISSING_SYNTAX = {ast.NamedExpr: "walrus (:=)", ast.Match: "match"}
# Server callables anyone can reach before logging in.
PUBLIC_CALLABLES = {"activate_account"}


def python_files(folder):
  for path, _, files in os.walk(folder):
    for name in sorted(files):
      if name.endswith(".py"):
        yield os.path.join(path, name)


def parse(path):
  with open(path) as f:
    return ast.parse(f.read(), path)


def server_callables():
  # {name: whether it requires a user}
  found = {}
  for path in python_files(SERVER_DIR):
    for node in ast.walk(parse(path)):
      if not isinstance(node, ast.FunctionDef):
        continue
      for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if ast.unparse(target) == "anvil.server.callable":
          found[node.name] = isinstance(decorator, ast.Call) and any(
            k.arg == "require_user" and ast.literal_eval(k.value) for k in decorator.keywords
          )
  return found


class ClientCodeTest(unittest.TestCase):
  def test_no_python_skulpt_lacks(self):
    for path in python_files(CLIENT_DIR):
      for node in ast.walk(parse(path)):
        where = f"{os.path.relpath(path, CLIENT_DIR)}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Attribute) and node.attr in SKULPT_MISSING_METHODS:
          self.fail(f"{where} uses .{node.attr}(), which Skulpt doesn't have")
        for kind, name in SKULPT_MISSING_SYNTAX.items():
          if isinstance(node, kind):
            self.fail(f"{where} uses {name}, which Skulpt can't parse")

  def test_handlers_name_components_in_the_template(self):
    for path in python_files(CLIENT_DIR):
      form_dir = os.path.dirname(path)
      if not os.path.exists(os.path.join(form_dir, "form_template.html")):
        continue
      components, _ = template_names(form_dir)
      for node in ast.walk(parse(path)):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "handle":
          component = ast.literal_eval(node.args[0])
          with self.subTest(form=os.path.basename(form_dir), component=component):
            self.assertIn(component, components)

  def test_server_calls_name_real_callables(self):
    callables = server_callables()
    for path in python_files(CLIENT_DIR):
      for node in ast.walk(parse(path)):
        if isinstance(node, ast.Call) and ast.unparse(node.func) in ("anvil.server.call", "anvil.server.call_s"):
          name = ast.literal_eval(node.args[0])
          if not name.startswith("anvil.private."):
            with self.subTest(name=name):
              self.assertIn(name, callables)


class ServerCodeTest(unittest.TestCase):
  def test_callables_require_a_user(self):
    for name, requires_user in server_callables().items():
      with self.subTest(name=name):
        self.assertEqual(requires_user, name not in PUBLIC_CALLABLES)


if __name__ == "__main__":
  unittest.main()
