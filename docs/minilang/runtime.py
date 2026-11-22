"""Value helpers shared by the optimizer and the interpreter, so both agree on the semantics."""
import json
import re

_INT = re.compile(r"-?\d+$")
_FLT = re.compile(r"-?\d+\.\d+$|-?\d+(?:\.\d+)?e[+-]?\d+$")


def parse_const(tok):
    """Operand text -> (True, python value) if it is a literal, else (False, None)."""
    if tok is None:
        return False, None
    if tok == "true":
        return True, True
    if tok == "false":
        return True, False
    if tok.startswith('"'):
        try:
            return True, json.loads(tok)
        except ValueError:
            return False, None
    if _INT.match(tok):
        return True, int(tok)
    if _FLT.match(tok):
        return True, float(tok)
    return False, None


def fmt_const(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float):
        return repr(v)
    return str(v)


def format_value(v) -> str:
    """How print shows a value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _trunc_div(a: int, b: int) -> int:           # C-style: rounds toward zero
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def eval_binary(op, a, b):
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op in ("/", "%"):
        if b == 0:
            raise ZeroDivisionError("division by zero")
        both_int = type(a) is int and type(b) is int
        if op == "/":
            return _trunc_div(a, b) if both_int else a / b
        return a - b * _trunc_div(a, b) if both_int else a % b
    if op == "<": return a < b
    if op == ">": return a > b
    if op == "<=": return a <= b
    if op == ">=": return a >= b
    if op == "==": return a == b
    if op == "!=": return a != b
    raise ValueError(f"unknown operator {op}")


def eval_unary(op, a):
    return -a if op == "-" else (not a)
