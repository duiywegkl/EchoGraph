"""Catch function-local imports that shadow a module-level module import."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "api_server.py", ROOT / "run_ui.py", *sorted((ROOT / "src").rglob("*.py"))]


def imported_names(node):
    for alias in node.names:
        yield alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)


class FunctionNames(ast.NodeVisitor):
    def __init__(self):
        self.bindings = []
        self.loads = []
        self.global_names = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bindings.append((node.id, node.lineno, "binding"))
        elif isinstance(node.ctx, ast.Load):
            self.loads.append((node.id, node.lineno))

    def visit_Import(self, node):
        self.bindings.extend((name, node.lineno, "import") for name in imported_names(node))

    def visit_ImportFrom(self, node):
        self.bindings.extend((name, node.lineno, "import-from") for name in imported_names(node))

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bindings.append((node.name, node.lineno, "except-as"))
        self.generic_visit(node)

    def visit_Global(self, node):
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node):
        self.global_names.update(node.names)

    def visit_FunctionDef(self, node):
        self.bindings.append((node.name, node.lineno, "definition"))
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        if node.returns is not None:
            self.visit(node.returns)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.bindings.append((node.name, node.lineno, "definition"))
        for expression in (*node.decorator_list, *node.bases, *(item.value for item in node.keywords)):
            self.visit(expression)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self.loads.append((node.target.id, node.lineno))
        self.generic_visit(node)

    def visit_Lambda(self, node):
        pass


def scan_file(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_names = set()
    module_modules = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = set(imported_names(node))
            module_names.update(names)
            if isinstance(node, ast.Import):
                module_modules.update(names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)

    hits = []

    class Functions(ast.NodeVisitor):
        def inspect(self, node):
            scope = FunctionNames()
            for statement in node.body:
                scope.visit(statement)
            loaded = {name for name, _ in scope.loads}
            for name, line, kind in scope.bindings:
                if name in module_names & loaded and name not in scope.global_names:
                    hits.append((path.relative_to(ROOT).as_posix(), line, node.name, name, kind,
                                 [load_line for load_name, load_line in scope.loads if load_name == name]))
            self.generic_visit(node)

        visit_FunctionDef = inspect
        visit_AsyncFunctionDef = inspect

    Functions().visit(tree)
    return hits, module_modules


def scan_all():
    hits = []
    module_imports = {}
    for path in SOURCES:
        file_hits, names = scan_file(path)
        hits.extend(file_hits)
        module_imports[path.relative_to(ROOT).as_posix()] = names
    return hits, module_imports


def test_no_function_local_module_reimports():
    hits, module_imports = scan_all()
    reimports = [hit for hit in hits if hit[4] == "import" and hit[3] in module_imports[hit[0]]]
    assert not reimports, reimports
