from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDES = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "vendor",
    "bin", "obj", "build", "dist", "coverage", ".next", ".nuxt",
}

# Keep this an intentionally small, dependency-free source-file index. Python
# gets AST structure; other languages are indexed as text and can be searched
# without claiming that a regex parser understands their syntax.
SOURCE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".svelte": "svelte",
    ".cs": "csharp",
    ".cshtml": "csharp-template",
    ".razor": "razor",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".scala": "scala",
    ".sc": "scala",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
}
MAX_INDEX_FILE_BYTES = 1_000_000
MAX_TEXT_LINE_LENGTH = 400


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


@dataclass
class SourceFileInfo:
    path: Path
    language: str
    text: str
    module: ModuleInfo | None = None


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


def _parse(path: Path, text: str) -> ModuleInfo | None:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
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
    """Small source index: exact Python structure plus text navigation for other languages."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.files = self._scan()
        self.modules = [item.module for item in self.files if item.module is not None]

    def _scan(self) -> list[SourceFileInfo]:
        files: list[SourceFileInfo] = []
        for current, directories, names in os.walk(self.root):
            directories[:] = sorted(name for name in directories if name not in DEFAULT_EXCLUDES)
            for name in sorted(names):
                path = Path(current) / name
                language = SOURCE_LANGUAGES.get(path.suffix.casefold())
                if language is None:
                    continue
                try:
                    if language != "python" and path.stat().st_size > MAX_INDEX_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if "\x00" in text:
                    continue
                module = _parse(path, text) if language == "python" else None
                files.append(SourceFileInfo(path, language, text, module))
        return files

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _is_test(self, path: Path) -> bool:
        rel = path.relative_to(self.root)
        parts = {part.casefold() for part in rel.parts}
        name = rel.name.casefold()
        return bool(
            parts & {"tests", "test", "__tests__", "spec", "specs"}
            or name.startswith(("test_", "tests_", "spec_"))
            or name.endswith(("_test.py", ".test.js", ".test.jsx", ".test.ts", ".test.tsx",
                             ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx",
                             ".tests.cs", "tests.cs"))
        )

    def _included(self, item: SourceFileInfo, include_tests: bool) -> bool:
        return include_tests or not self._is_test(item.path)

    def map(self, *, include_tests: bool = False) -> list[str]:
        return [self._rel(item.path) for item in self.files if self._included(item, include_tests)]

    def lookup(self, path: str) -> list[dict[str, Any]]:
        query = path.strip().replace("\\", "/").strip("/")
        if query in {"", "."}:
            matches = self.files
        else:
            matches = [item for item in self.files
                       if self._rel(item.path) == query
                       or self._rel(item.path).startswith(query + "/")]
        return [self._file_dict(item) for item in matches]

    def find_symbol(self, query: str, *, include_tests: bool = False) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        if not needle:
            return []
        qualified = "." in needle
        results: list[dict[str, Any]] = []
        for item in self.files:
            if not self._included(item, include_tests):
                continue
            path = self._rel(item.path)
            module = item.module
            if module is not None:
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
                # Parsed Python keeps its precise AST-based result semantics.
                continue

            identifier = needle.rsplit(".", 1)[-1]
            pattern = re.compile(rf"(?<![\w]){re.escape(identifier)}(?![\w])", re.IGNORECASE)
            for line_number, line in enumerate(item.text.splitlines(), start=1):
                if pattern.search(line):
                    results.append({
                        **self._match(path, query.strip(), "text", line_number, line_number),
                        "text": self._snippet(line),
                    })
        return sorted(results, key=lambda result: (result["path"], result["start_line"]))

    def search(self, query: str, *, limit: int = 10,
               include_tests: bool = False) -> list[dict[str, Any]]:
        terms = list(dict.fromkeys(t.casefold() for t in re.findall(r"[A-Za-z0-9_]+", query) if t))
        if not terms:
            return []
        scored: list[tuple[int, str, list[str]]] = []
        for item in self.files:
            if not self._included(item, include_tests):
                continue
            path = self._rel(item.path)
            module = item.module
            categories: list[tuple[str, list[str], int]] = [("path", [path], 10)]
            if module is not None:
                categories.extend([
                    ("class", [c.name for c in module.classes], 8),
                    ("method", [m.name for c in module.classes for m in c.methods], 6),
                    ("function", [f.name for f in module.functions], 6),
                    ("docstring", [module.docstring] if module.docstring else [], 4),
                    ("import", module.imports, 1),
                ])
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

            content_hits: set[str] = set()
            content_reasons: list[str] = []
            for line_number, line in enumerate(item.text.splitlines(), start=1):
                hits = [term for term in terms if term in line.casefold()]
                if hits:
                    content_hits.update(hits)
                    if len(content_reasons) < 3:
                        content_reasons.append(f"content line {line_number}: {self._snippet(line)}")
            score += 2 * len(content_hits)
            reasons.extend(content_reasons)
            if score:
                scored.append((score, path, reasons[:5]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{"path": path, "score": score, "reasons": reasons}
                for score, path, reasons in scored[:max(1, limit)]]

    @staticmethod
    def _snippet(line: str) -> str:
        compact = " ".join(line.strip().split())
        return compact if len(compact) <= MAX_TEXT_LINE_LENGTH else compact[:MAX_TEXT_LINE_LENGTH - 1] + "…"

    @staticmethod
    def _match(path: str, symbol: str, kind: str, line: int, end_line: int) -> dict[str, Any]:
        return {"path": path, "symbol": symbol, "kind": kind,
                "start_line": line, "end_line": end_line}

    def _file_dict(self, item: SourceFileInfo) -> dict[str, Any]:
        if item.module is not None:
            return self._module_dict(item.module)
        return {
            "path": self._rel(item.path),
            "language": item.language,
            "index_type": "text",
            "line_count": len(item.text.splitlines()),
            "docstring": None,
            "imports": [],
            "classes": [],
            "functions": [],
        }

    def _module_dict(self, module: ModuleInfo) -> dict[str, Any]:
        return {
            "path": self._rel(module.path),
            "language": "python",
            "index_type": "ast",
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
