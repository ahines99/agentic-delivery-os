"""Conservative static imports: an incomplete graph never narrows mandatory validation."""

import ast
from collections import defaultdict, deque
from typing import Any


def impact_report(files: dict[str, str], changed: tuple[str, ...]) -> dict[str, Any]:
    modules = {
        path.removesuffix(".py").replace("/", ".").removesuffix(".__init__"): path
        for path in files
        if path.endswith(".py")
    }
    reverse: dict[str, set[str]] = defaultdict(set)
    unknown = []
    for module, path in modules.items():
        try:
            tree = ast.parse(files[path], filename=path)
        except SyntaxError:
            unknown.append({"path": path, "reason": "parse_error"})
            continue
        for node in ast.walk(tree):
            dependencies = []
            if isinstance(node, ast.Import):
                dependencies = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                parent = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
                if node.level:
                    parts = parent.split(".") if parent else []
                    if node.level > len(parts):
                        unknown.append({"path": path, "reason": "unresolved_relative_import"})
                    prefix = ".".join(parts[: len(parts) - node.level + 1])
                    base = ".".join(part for part in (prefix, node.module) if part)
                else:
                    base = node.module or ""
                dependencies = [base, *[f"{base}.{alias.name}".strip(".") for alias in node.names]]
            elif isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                unknown.append({"path": path, "reason": "dynamic_code_or_import"})
            for dependency in dependencies:
                if dependency in modules:
                    reverse[modules[dependency]].add(path)
                elif dependency:
                    unknown.append(
                        {
                            "path": path,
                            "reason": "external_or_unresolved_import",
                            "module": dependency,
                        }
                    )
    seen = set(changed)
    queue = deque(changed)
    while queue:
        for dependent in reverse[queue.popleft()] - seen:
            seen.add(dependent)
            queue.append(dependent)
    return {
        "changed": sorted(changed),
        "impacted": sorted(seen),
        "unknown": unknown,
        "suggested_tests": sorted(path for path in seen if "test" in path),
        "full_suite_required": True,
        "limitation": "Static imports do not establish complete runtime impact coverage",
    }
