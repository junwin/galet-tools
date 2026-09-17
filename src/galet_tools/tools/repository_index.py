from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDES = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "build", "dist",
}


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    signature: str
    line: int
    end_line: int


@dataclass
class ClassInfo:
    name: str
    line: int
    end_line: int
    bases: list[str] = field(default_factory=list)
    methods: list[SymbolInfo] = field(default_factory=list)


@dataclass
class ModuleInfo:
    path: Path
    docstring: str | None = None
    imports: list[str] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[SymbolInfo] = field(default_factory=list)


def _expr(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _arguments(args: ast.arguments) -> str:
    parts: list[str] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults_offset = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        text = arg.arg
        if arg.annotation:
            text += f": {_expr(arg.annotation)}"
        if index >= defaults_offset:
            text += f" = {_expr(args.defaults[index - defaults_offset])}"
        parts.append(text)
    if args.vararg:
        text = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            text += f": {_expr(args.vararg.annotation)}"
        parts.append(text)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        text = arg.arg
        if arg.annotation:
            text += f": {_expr(arg.annotation)}"
        if default is not None:
            text += f" = {_expr(default)}"
        parts.append(text)
    if args.kwarg:
        text = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            text += f": {_expr(args.kwarg.annotation)}"
        parts.append(text)
    return ", ".join(parts)


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> SymbolInfo:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    signature = f"{prefix}{node.name}({_arguments(node.args)})"
    if node.returns:
        signature += f" -> {_expr(node.returns)}"
    return SymbolInfo(node.name, signature, node.lineno, node.end_lineno or node.lineno)


def _parse(path: Path) -> ModuleInfo | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (UnicodeDecodeError, SyntaxError, OSError):
        return None
    doc = ast.get_docstring(tree, clean=True)
    info = ModuleInfo(path=path, docstring=doc.splitlines()[0].strip() if doc else None)
    for node in tree.body:
        if isinstance(node, ast.Import):
            info.imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            info.imports.append(f"{module}: {', '.join(a.name for a in node.names)}")
        elif isinstance(node, ast.ClassDef):
            cls = ClassInfo(node.name, node.lineno, node.end_lineno or node.lineno,
                            [_expr(base) for base in node.bases])
            cls.methods = [_function(child) for child in node.body
                           if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            info.classes.append(cls)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.functions.append(_function(node))
    info.imports = sorted(set(info.imports))
    return info


class RepositoryIndex:
    """Small, dependency-free structural index for Python repositories."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.modules = self._scan()

    def _scan(self) -> list[ModuleInfo]:
        modules: list[ModuleInfo] = []
        for path in sorted(self.root.rglob("*.py")):
            rel = path.relative_to(self.root)
            if any(part in DEFAULT_EXCLUDES for part in rel.parts):
                continue
            info = _parse(path)
            if info is not None:
                modules.append(info)
        return modules

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _is_test(self, path: Path) -> bool:
        rel = path.relative_to(self.root)
        return "tests" in rel.parts or rel.name.startswith("test_")

    def map(self, *, include_tests: bool = False) -> list[str]:
        return [self._rel(m.path) for m in self.modules
                if include_tests or not self._is_test(m.path)]

    def lookup(self, path: str) -> list[dict[str, Any]]:
        query = path.strip().replace("\\", "/").strip("/")
        matches = [m for m in self.modules
                   if self._rel(m.path) == query or self._rel(m.path).startswith(query + "/")]
        return [self._module_dict(m) for m in matches]

    def find_symbol(self, query: str, *, include_tests: bool = False) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        qualified = "." in needle
        results: list[dict[str, Any]] = []
        for module in self.modules:
            if not include_tests and self._is_test(module.path):
                continue
            path = self._rel(module.path)
            for cls in module.classes:
                if not qualified and needle in cls.name.casefold():
                    results.append(self._match(path, cls.name, "class", cls.line, cls.end_line))
                for method in cls.methods:
                    candidate = f"{cls.name}.{method.name}"
                    haystack = candidate.casefold() if qualified else method.name.casefold()
                    if needle in haystack:
                        results.append(self._match(path, candidate, "method", method.line, method.end_line))
            if not qualified:
                for function in module.functions:
                    if needle in function.name.casefold():
                        results.append(self._match(path, function.name, "function",
                                                   function.line, function.end_line))
        return results

    def search(self, query: str, *, limit: int = 10,
               include_tests: bool = False) -> list[dict[str, Any]]:
        terms = list(dict.fromkeys(t.casefold() for t in re.findall(r"[A-Za-z0-9_]+", query) if t))
        scored: list[tuple[int, str, list[str]]] = []
        for module in self.modules:
            if not include_tests and self._is_test(module.path):
                continue
            path = self._rel(module.path)
            categories = [
                ("path", [path], 10),
                ("class", [c.name for c in module.classes], 8),
                ("method", [m.name for c in module.classes for m in c.methods], 6),
                ("function", [f.name for f in module.functions], 6),
                ("docstring", [module.docstring] if module.docstring else [], 4),
                ("import", module.imports, 1),
            ]
            score = 0
            reasons: list[str] = []
            for label, values, weight in categories:
                matched: set[str] = set()
                category_reasons: list[str] = []
                for value in values:
                    hits = [term for term in terms if term in value.casefold()]
                    if hits:
                        matched.update(hits)
                        category_reasons.append(value)
                score += weight * len(matched)
                reasons.extend(f"{label}: {value}" for value in category_reasons[:3])
            if score:
                scored.append((score, path, reasons[:5]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{"path": path, "score": score, "reasons": reasons}
                for score, path, reasons in scored[:max(1, limit)]]

    @staticmethod
    def _match(path: str, symbol: str, kind: str, line: int, end_line: int) -> dict[str, Any]:
        return {"path": path, "symbol": symbol, "kind": kind,
                "start_line": line, "end_line": end_line}

    def _module_dict(self, module: ModuleInfo) -> dict[str, Any]:
        return {
            "path": self._rel(module.path),
            "docstring": module.docstring,
            "imports": module.imports,
            "classes": [{
                "name": cls.name, "bases": cls.bases,
                "start_line": cls.line, "end_line": cls.end_line,
                "methods": [{"name": m.name, "signature": m.signature,
                             "start_line": m.line, "end_line": m.end_line}
                            for m in cls.methods],
            } for cls in module.classes],
            "functions": [{"name": f.name, "signature": f.signature,
                           "start_line": f.line, "end_line": f.end_line}
                          for f in module.functions],
        }
