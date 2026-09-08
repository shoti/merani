#!/usr/bin/env python3
"""Enforce Merani's internal dependency direction without dependencies."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
from typing import Iterable


PACKAGE_ROOT = Path(__file__).with_name("merani_core")
LAYER_RULES = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "application", "adapters", "settings"},
    "presentation": {"domain", "application", "presentation"},
}
PROHIBITED_DOMAIN_IMPORTS = {
    "asyncio", "fcntl", "http", "os", "shutil", "socket",
    "sqlite3", "subprocess", "tempfile", "urllib",
}
PROHIBITED_DOMAIN_CALLS = {
    "open", "Popen", "run", "system", "unlink", "write_bytes", "write_text",
    "read_bytes", "read_text",
}


def module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(parts)


def internal_imports(
    tree: ast.AST, current: str, *, current_is_package: bool = False
) -> set[str]:
    result: set[str] = set()
    current_parts = current.split(".")
    package_parts = current_parts if current_is_package else current_parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names if alias.name.startswith("merani_core"))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                ascend = node.level - 1
                base = (
                    package_parts[: len(package_parts) - ascend]
                    if ascend
                    else package_parts
                )
                target = ".".join((*base, *(node.module or "").split(".")))
            else:
                target = node.module or ""
            if target.startswith("merani_core"):
                result.add(target.rstrip("."))
                result.update(
                    f"{target.rstrip('.')}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return result


def absolute_imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def graph_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visiting: list[str] = []
    complete: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            start = visiting.index(node)
            cycles.append([*visiting[start:], node])
            return
        if node in complete:
            return
        visiting.append(node)
        for target in sorted(graph.get(node, set())):
            if target in graph:
                visit(target)
        visiting.pop()
        complete.add(node)

    for node in sorted(graph):
        visit(node)
    return cycles


def check(package_root: Path = PACKAGE_ROOT) -> tuple[list[str], list[str]]:
    global PACKAGE_ROOT
    original = PACKAGE_ROOT
    PACKAGE_ROOT = package_root
    try:
        errors: list[str] = []
        signals: list[str] = []
        graph: dict[str, set[str]] = {}
        for path in sorted(package_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            module = module_name(path)
            imports = internal_imports(
                tree, module, current_is_package=path.name == "__init__.py"
            )
            graph[module] = imports
            if any(
                target == "merani" or target.startswith("merani.")
                for target in absolute_imports(tree)
            ):
                errors.append(f"{path}: internal module imports compatibility launcher")
            parts = path.relative_to(package_root).parts
            layer = parts[0] if len(parts) > 1 else None
            allowed = LAYER_RULES.get(layer or "")
            if allowed is not None:
                for target in imports:
                    target_parts = target.split(".")
                    target_layer = target_parts[1] if len(target_parts) > 1 else None
                    if target_layer and target_layer not in allowed:
                        errors.append(f"{path}: {layer} may not import {target_layer}: {target}")
            if layer == "domain":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = {alias.name.split(".")[0] for alias in node.names}
                    elif isinstance(node, ast.ImportFrom):
                        names = {(node.module or "").split(".")[0]} if node.level == 0 else set()
                    else:
                        names = set()
                    for name in sorted(names & PROHIBITED_DOMAIN_IMPORTS):
                        errors.append(f"{path}:{node.lineno}: pure domain imports {name}")
                    if isinstance(node, ast.Call):
                        called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                        if called in PROHIBITED_DOMAIN_CALLS:
                            errors.append(f"{path}:{node.lineno}: pure domain calls {called}")
            functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for function in functions:
                lines = function.end_lineno - function.lineno + 1
                if lines >= 200:
                    signals.append(f"large function: {path}:{function.lineno} {function.name} ({lines} lines)")
            line_count = len(source.splitlines())
            if line_count >= 1000:
                signals.append(f"large module: {path} ({line_count} lines)")
        for cycle in graph_cycles(graph):
            errors.append("circular internal dependency: " + " -> ".join(cycle))
        return sorted(set(errors)), sorted(set(signals))
    finally:
        PACKAGE_ROOT = original


def main() -> int:
    errors, signals = check()
    for signal in signals:
        print(f"SIGNAL: {signal}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"Architecture checks passed ({len(signals)} review signals).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
