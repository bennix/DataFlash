"""AST white-list validator.

This is the only real security boundary of the application (SPEC 5.3 / 7.3):
the system prompt merely biases the model, this module enforces.

The policy is *default-deny*: only syntax nodes in ``ALLOWED_NODES`` are
accepted.  Everything else is rejected with a human-readable reason so the UI
can tell the user exactly what was intercepted.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, asdict
from typing import Iterable

# --- Policy ---------------------------------------------------------------

#: Statements/expressions the generated code may use.  SPEC 5.3 allows
#: expressions, assignments, if/for/while, function definitions and lambdas.
ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Module,
        # statements
        ast.Expr,
        ast.Assign,
        ast.AugAssign,
        ast.AnnAssign,
        ast.If,
        ast.For,
        ast.While,
        ast.Break,
        ast.Continue,
        ast.Pass,
        ast.Return,
        ast.FunctionDef,
        # expressions
        ast.Name,
        ast.Attribute,
        ast.Subscript,
        ast.Call,
        ast.Constant,
        ast.Tuple,
        ast.List,
        ast.Dict,
        ast.Set,
        ast.Starred,
        ast.Slice,
        ast.IfExp,
        ast.Lambda,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.JoinedStr,
        ast.FormattedValue,
        # comprehensions
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.comprehension,
        # helpers / leaf grammar
        ast.keyword,
        ast.arguments,
        ast.arg,
        ast.Load,
        ast.Store,
        ast.expr_context,
        ast.operator,
        ast.boolop,
        ast.unaryop,
        ast.cmpop,
    }
)

#: Names that must never be called, even if somehow bound in the namespace.
FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "input",
        "breakpoint",
        "help",
        "memoryview",
        "__import__",
        "__builtins__",
        "exit",
        "quit",
        "copyright",
        "credits",
        "license",
    }
)

#: Attribute names that are dangerous even though they contain no dunder.
#: These are escape hatches inside otherwise white-listed libraries: pickle
#: readers execute arbitrary code, ``eval``/``query`` compile strings, and the
#: IO helpers reach the filesystem or the network behind pandas' back.
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "read_pickle",
        "to_pickle",
        "read_sql",
        "read_sql_query",
        "read_sql_table",
        "read_gbq",
        "to_gbq",
        "to_sql",
        "eval",
        "exec",
        "system",
        "popen",
        "spawn",
        "spawnl",
        "spawnv",
        "fork",
        "execv",
        "execve",
        "remove",
        "unlink",
        "rmdir",
        "rmtree",
        "chmod",
        "chown",
        "urlopen",
        "urlretrieve",
        "request",
        "connect",
        "socket",
        "load",  # pickle.load / yaml.load / joblib.load
        "loads",  # pickle.loads
        "dump",
        "dumps",
        "save",
        "savez",
        "fromfile",
        "tofile",
        "memmap",
        "genfromtxt",
        "loadtxt",
        "savetxt",
        "ctypes",
        "cdll",
        "windll",
        "check_output",
        "check_call",
        "call",
        "run",
        "Popen",
    }
)

#: Names that may not be rebound; rebinding them would shadow the guard that
#: the executor relies on when it reads the result back out of the namespace.
PROTECTED_NAMES: frozenset[str] = frozenset({"__builtins__"})

_NODE_REASONS: dict[type[ast.AST], str] = {
    ast.Import: "import 语句",
    ast.ImportFrom: "from ... import 语句",
    ast.Try: "try/except 语句",
    ast.Raise: "raise 语句",
    ast.With: "with 语句",
    ast.AsyncWith: "async with 语句",
    ast.ClassDef: "class 定义",
    ast.Global: "global 声明",
    ast.Nonlocal: "nonlocal 声明",
    ast.Delete: "del 语句",
    ast.Assert: "assert 语句",
    ast.Yield: "yield 表达式",
    ast.YieldFrom: "yield from 表达式",
    ast.Await: "await 表达式",
    ast.AsyncFunctionDef: "async def 定义",
    ast.AsyncFor: "async for 语句",
    ast.NamedExpr: "海象运算符 :=",
    ast.Match: "match 语句",
}


# --- Result types ---------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """A single reason why a piece of code was rejected."""

    code: str
    message: str
    lineno: int = 0
    col: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues]}

    @property
    def summary(self) -> str:
        return "；".join(i.message for i in self.issues)


class CodeRejected(Exception):
    """Raised by :func:`ensure_safe` when validation fails."""

    def __init__(self, result: ValidationResult):
        super().__init__(result.summary or "代码未通过安全校验")
        self.result = result


# --- Validator ------------------------------------------------------------


class _Validator(ast.NodeVisitor):
    def __init__(self, allowed_names: Iterable[str]):
        self.allowed_names = set(allowed_names)
        self.issues: list[Issue] = []

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self.issues.append(
            Issue(
                code=code,
                message=message,
                lineno=getattr(node, "lineno", 0),
                col=getattr(node, "col_offset", 0),
            )
        )

    def generic_visit(self, node: ast.AST) -> None:
        node_type = type(node)
        if node_type not in ALLOWED_NODES and not isinstance(
            node, (ast.expr_context, ast.operator, ast.boolop, ast.unaryop, ast.cmpop)
        ):
            reason = _NODE_REASONS.get(node_type, node_type.__name__)
            self._add(node, "forbidden_syntax", f"检测到不允许的语法：{reason}，已拦截")
            # Do not walk into a rejected subtree; one clear reason is enough.
            return
        super().generic_visit(node)

    # -- specific checks --------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            self._add(
                node,
                "dunder_name",
                f"检测到对双下划线名称 {node.id} 的访问，已拦截",
            )
            return
        if isinstance(node.ctx, ast.Store) and node.id in PROTECTED_NAMES:
            self._add(node, "protected_name", f"禁止重新绑定 {node.id}，已拦截")
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self._add(
                node,
                "dunder_attribute",
                f"检测到双下划线属性访问 .{node.attr}，已拦截",
            )
            return
        if node.attr in FORBIDDEN_ATTRIBUTES:
            self._add(
                node,
                "forbidden_attribute",
                f"检测到危险属性 .{node.attr} 的使用，已拦截",
            )
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in FORBIDDEN_CALLS:
                self._add(
                    node,
                    "forbidden_call",
                    f"检测到 {func.id}(...) 调用，已拦截",
                )
                return
        elif isinstance(func, ast.Attribute):
            if func.attr in FORBIDDEN_CALLS or func.attr in FORBIDDEN_ATTRIBUTES:
                owner = _dotted_name(func.value)
                label = f"{owner}.{func.attr}" if owner else func.attr
                self._add(
                    node,
                    "forbidden_call",
                    f"检测到 {label}(...) 调用，已拦截",
                )
                return
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            self._add(node, "forbidden_syntax", "检测到函数装饰器，已拦截")
            return
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if key.value.startswith("__"):
                self._add(
                    node,
                    "dunder_subscript",
                    f"检测到双下划线键 [{key.value!r}] 的访问，已拦截",
                )
                return
        self.generic_visit(node)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


#: Modules already injected into the sandbox namespace (SPEC 5.3).
#: Models often emit these imports habitually; stripping them is safe —
#: any alias (``from pandas import DataFrame``, ``import json as J``) is removed
#: because the sandbox preloads the module roots.
_INJECTED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "pandas",
        "numpy",
        "plotly",
        "json",
        "math",
        "statistics",
        "collections",
        "re",
        "datetime",
        "decimal",
        "functools",
        "itertools",
        "operator",
        "copy",
    }
)


def _is_redundant_injected_import(node: ast.AST) -> bool:
    """True if ``node`` only imports modules the sandbox already provides."""
    if isinstance(node, ast.Import):
        if not node.names:
            return False
        return all(
            alias.name.split(".", 1)[0] in _INJECTED_IMPORT_ROOTS for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        if node.level or not node.module or not node.names:
            return False
        if node.module.split(".", 1)[0] not in _INJECTED_IMPORT_ROOTS:
            return False
        # ``from pandas import *`` is unsafe to strip silently
        return all(alias.name != "*" for alias in node.names)
    return False


def strip_injected_imports(code: str) -> str:
    """Remove redundant imports of sandbox-injected modules; leave others intact.

    Does not weaken security: ``import os`` etc. remain and still fail validation.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return code
    kept: list[ast.stmt] = []
    removed = False
    for stmt in tree.body:
        if _is_redundant_injected_import(stmt):
            removed = True
            continue
        kept.append(stmt)
    if not removed:
        return code
    tree.body = kept
    return ast.unparse(tree)


def validate(code: str, allowed_names: Iterable[str] = ()) -> ValidationResult:
    """Validate ``code`` against the white-list policy.

    ``allowed_names`` is the set of symbols the executor will inject; it is
    accepted for symmetry with the runner but the policy does not currently
    reject unknown free names (a ``NameError`` at runtime is a clearer,
    self-healing-friendly failure than a static rejection).
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return ValidationResult(
            ok=False,
            issues=[
                Issue(
                    code="syntax_error",
                    message=f"代码存在语法错误：{exc.msg}",
                    lineno=exc.lineno or 0,
                    col=exc.offset or 0,
                )
            ],
        )

    validator = _Validator(allowed_names)
    validator.visit(tree)
    return ValidationResult(ok=not validator.issues, issues=validator.issues)


def ensure_safe(code: str, allowed_names: Iterable[str] = ()) -> None:
    """Validate and raise :class:`CodeRejected` on the first failure."""
    result = validate(code, allowed_names)
    if not result.ok:
        raise CodeRejected(result)
