"""Conservative changed-code signals, not a complete vulnerability scanner."""

import ast
import re

SENSITIVE = re.compile(
    r"auth(?:entication|orization)?|payment|billing|secret|migration|terraform|policy", re.I
)
SECRET = re.compile(
    r"(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|-----BEGIN .*PRIVATE KEY-----)"
)


def check_candidate(base: dict[str, str], candidate: dict[str, str]) -> None:
    for path in base.keys() | candidate.keys():
        if base.get(path) == candidate.get(path):
            continue
        if SENSITIVE.search(path):
            raise ValueError("Changed path requires risk escalation")
        content = candidate.get(path, "")
        if SECRET.search(content):
            raise ValueError("Candidate contains a probable credential")
        if not path.endswith(".py"):
            continue
        tree = ast.parse(content, filename=path)
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) and SENSITIVE.search(node.name):
                raise ValueError("Changed code contains a sensitive capability")
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                )
                if name in {"eval", "exec", "__import__", "system", "popen"}:
                    raise ValueError("Dynamic execution is outside the low-risk scope")
