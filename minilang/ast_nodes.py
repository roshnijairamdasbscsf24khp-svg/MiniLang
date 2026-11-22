"""Syntax tree nodes, data types and helpers to print / describe a tree."""
import json
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class DataType(Enum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"

    def __str__(self):
        return self.value

    @property
    def is_numeric(self):
        return self in (DataType.INT, DataType.FLOAT)


class Node:
    pass


@dataclass(eq=False)
class Program(Node):
    statements: List[Node]
    line: int = 1
    column: int = 1


@dataclass(eq=False)
class Block(Node):
    statements: List[Node]
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class VarDecl(Node):
    dtype: DataType
    name: str
    init: Optional[Node] = None
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class Assign(Node):
    name: str
    value: Node
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class Print(Node):
    expr: Node
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class If(Node):
    cond: Node
    then: Node
    otherwise: Optional[Node] = None
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class While(Node):
    cond: Node
    body: Node
    line: int = 0
    column: int = 0


@dataclass(eq=False)
class Binary(Node):
    op: str
    left: Node
    right: Node
    line: int = 0
    column: int = 0
    dtype: Optional[DataType] = None        # filled in by the semantic analyzer


@dataclass(eq=False)
class Unary(Node):
    op: str
    operand: Node
    line: int = 0
    column: int = 0
    dtype: Optional[DataType] = None


@dataclass(eq=False)
class Variable(Node):
    name: str
    line: int = 0
    column: int = 0
    dtype: Optional[DataType] = None


@dataclass(eq=False)
class Literal(Node):
    value: object
    dtype: DataType
    line: int = 0
    column: int = 0


def _literal_text(n: Literal) -> str:
    if n.dtype == DataType.STRING:
        return json.dumps(n.value, ensure_ascii=False)
    if n.dtype == DataType.BOOL:
        return "true" if n.value else "false"
    return str(n.value)


def describe(node):
    """Returns (label, detail, [(role, child), ...]) - used by print_ast and the GUI tree."""
    name = type(node).__name__
    typed = lambda: f"  : {node.dtype}" if getattr(node, "dtype", None) else ""
    if isinstance(node, (Program, Block)):
        return name, "", [("", s) for s in node.statements]
    if isinstance(node, VarDecl):
        return name, f"{node.dtype} {node.name}", [("init", node.init)] if node.init else []
    if isinstance(node, Assign):
        return name, node.name, [("value", node.value)]
    if isinstance(node, Print):
        return name, "", [("expr", node.expr)]
    if isinstance(node, If):
        kids = [("cond", node.cond), ("then", node.then)]
        if node.otherwise is not None:
            kids.append(("else", node.otherwise))
        return name, "", kids
    if isinstance(node, While):
        return name, "", [("cond", node.cond), ("body", node.body)]
    if isinstance(node, Binary):
        return name, node.op + typed(), [("left", node.left), ("right", node.right)]
    if isinstance(node, Unary):
        return name, node.op + typed(), [("operand", node.operand)]
    if isinstance(node, Variable):
        return name, node.name + typed(), []
    if isinstance(node, Literal):
        return name, f"{_literal_text(node)}  : {node.dtype}", []
    return name, "", []


def count_nodes(node) -> int:
    return 1 + sum(count_nodes(c) for _, c in describe(node)[2])


def count_statements(node) -> int:
    own = 1 if isinstance(node, (VarDecl, Assign, Print, If, While, Block)) else 0
    return own + sum(count_statements(c) for _, c in describe(node)[2])


def print_ast(node, depth: int = 0, role: str = "") -> str:
    label, detail, kids = describe(node)
    text = "  " * depth + (f"{role}: " if role else "") + label + (f" {detail}" if detail else "") + "\n"
    for r, child in kids:
        text += print_ast(child, depth + 1, r)
    return text
