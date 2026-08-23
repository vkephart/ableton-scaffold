#!/usr/bin/env python3
"""
check_py37.py — flag Python 3.8+ syntax in code destined for Ableton's remote scripts.

Live 11 embeds CPython 3.7. Any newer syntax in a MIDI Remote Script makes the whole
control surface fail to load, and Live reports nothing useful: the script simply does
not appear, or appears and answers nothing. There is no 3.7 interpreter on a modern
Mac to test against, which is what makes this worth automating.

The check is a static AST walk, so it runs on whatever Python you have. It reads the
file with the host parser and then looks for constructs 3.7 cannot parse.

Usage:
  python3 bridge/check_py37.py abletonosc-ext/
  python3 bridge/check_py37.py ~/Music/Ableton/User\\ Library/Remote\\ Scripts/AbletonOSC
  python3 bridge/check_py37.py path/to/one_file.py

Exit status is 0 when clean, 1 when something is flagged, 2 on a bad invocation.

What it cannot catch: runtime-only problems. A 3.8+ standard library call
(`math.prod`, `functools.cached_property`, `str.removeprefix`) parses fine under 3.7
and fails only when the line executes. A few of the common ones are listed as
warnings, but the list is not exhaustive - keep to what the stock AbletonOSC modules
already use and you stay inside 3.7.
"""

import argparse
import ast
import os
import re
import sys

# Names that became subscriptable as generics in 3.9 (PEP 585).
BUILTIN_GENERICS = {"list", "dict", "set", "frozenset", "tuple", "type"}

# Attribute calls that exist only in 3.8+. Reported as warnings: an attribute name
# match does not prove the receiver is the standard library type.
LIBRARY_HINTS = {
    "removeprefix": "str.removeprefix() is 3.9+",
    "removesuffix": "str.removesuffix() is 3.9+",
    "cached_property": "functools.cached_property is 3.8+",
    "prod": "math.prod() is 3.8+",
}

# f-string self-documenting form, f"{value=}". 3.8+, and invisible to the AST.
FSTRING_DEBUG = re.compile(r"""f(['"]).*?\{[^{}]+=\}""", re.DOTALL)


class Finding(object):
    def __init__(self, path, line, level, message):
        self.path = path
        self.line = line
        self.level = level      # "error" or "warning"
        self.message = message

    def format(self, root):
        shown = self.path
        try:
            relative = os.path.relpath(self.path, root)
            if not relative.startswith(os.pardir):
                shown = relative
        except ValueError:      # different drive on Windows
            pass
        return "%s:%d: %s: %s" % (shown, self.line, self.level, self.message)


class Py37Visitor(ast.NodeVisitor):
    """Collects 3.8+ constructs. Annotations are tracked separately because the
    PEP 585 and PEP 604 forms are only distinguishable from ordinary indexing and
    bitwise-or by the position they appear in."""

    def __init__(self, path):
        self.path = path
        self.findings = []
        self._annotation_depth = 0

    def _add(self, node, level, message):
        self.findings.append(Finding(self.path, getattr(node, "lineno", 0), level, message))

    # -- 3.8 --------------------------------------------------------------

    def visit_NamedExpr(self, node):
        self._add(node, "error", "walrus operator ':=' is 3.8+")
        self.generic_visit(node)

    # -- 3.10 / 3.11 ------------------------------------------------------

    def visit_Match(self, node):
        self._add(node, "error", "match statement is 3.10+")
        self.generic_visit(node)

    def visit_TryStar(self, node):
        self._add(node, "error", "'except*' is 3.11+")
        self.generic_visit(node)

    # -- annotations ------------------------------------------------------

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def _visit_function(self, node):
        if getattr(node.args, "posonlyargs", None):
            self._add(node.args.posonlyargs[0], "error",
                      "positional-only parameters ('/' in the signature) are 3.8+")
        if node.returns is not None:
            self._visit_annotation(node.returns)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for arg in ast.walk(node.args):
            if isinstance(arg, ast.arg) and arg.annotation is not None:
                self._visit_annotation(arg.annotation)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AnnAssign(self, node):
        self._visit_annotation(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def _visit_annotation(self, node):
        self._annotation_depth += 1
        try:
            self.visit(node)
        finally:
            self._annotation_depth -= 1

    def visit_BinOp(self, node):
        if self._annotation_depth and isinstance(node.op, ast.BitOr):
            self._add(node, "error",
                      "'X | Y' union syntax is 3.10+ - use typing.Optional or typing.Union")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        target = node.value
        if isinstance(target, ast.Name) and target.id in BUILTIN_GENERICS:
            self._add(node, "error",
                      "'%s[...]' as a generic is 3.9+ - use typing.%s"
                      % (target.id, target.id.capitalize()))
        self.generic_visit(node)

    # -- library hints ----------------------------------------------------

    def visit_Attribute(self, node):
        hint = LIBRARY_HINTS.get(node.attr)
        if hint:
            self._add(node, "warning", hint + " (parses under 3.7, fails when it runs)")
        self.generic_visit(node)


def check_source(path, source):
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return [Finding(path, e.lineno or 0, "error",
                        "does not parse even on this Python: %s" % e.msg)]

    visitor = Py37Visitor(path)
    visitor.visit(tree)

    for match in FSTRING_DEBUG.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        visitor.findings.append(
            Finding(path, line, "error", "f-string '{value=}' debug form is 3.8+"))

    return sorted(visitor.findings, key=lambda f: (f.line, f.message))


def check_path(path):
    if not os.path.exists(path):
        print("ERROR: no such path: %s" % path)
        sys.exit(2)
    if os.path.isfile(path):
        return [path]

    files = []
    for dirpath, dirnames, filenames in os.walk(path):
        # pythonosc is vendored into AbletonOSC and is not ours to police; __pycache__
        # holds compiled output, not source.
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "pythonosc", ".git")]
        for name in sorted(filenames):
            if name.endswith(".py"):
                files.append(os.path.join(dirpath, name))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="Flag Python 3.8+ syntax in code that has to run under Live 11's CPython 3.7")
    parser.add_argument("paths", nargs="+", help="Files or directories to check")
    parser.add_argument("--warnings-as-errors", action="store_true",
                        help="Exit non-zero on warnings too, not just errors")
    args = parser.parse_args()

    root = os.getcwd()
    errors = 0
    warnings = 0
    checked = 0

    for target in args.paths:
        for path in check_path(target):
            checked += 1
            with open(path) as f:
                source = f.read()
            for finding in check_source(path, source):
                print(finding.format(root))
                if finding.level == "error":
                    errors += 1
                else:
                    warnings += 1

    print("\nChecked %d file%s: %d error%s, %d warning%s."
          % (checked, "" if checked == 1 else "s",
             errors, "" if errors == 1 else "s",
             warnings, "" if warnings == 1 else "s"))

    if errors or (warnings and args.warnings_as_errors):
        print("Live 11 will not load this. Fix the errors before copying into Remote Scripts.")
        return 1
    print("Nothing here needs a Python newer than 3.7.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
