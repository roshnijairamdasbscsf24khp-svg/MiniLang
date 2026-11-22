"""Semantic analysis: scopes, symbol table, type checking, definite assignment."""
import difflib
from dataclasses import dataclass
from typing import Optional

from . import ast_nodes as A
from .ast_nodes import DataType as D
from .errors import ErrorReporter


@dataclass(eq=False)
class Symbol:
    name: str
    type: D
    declared_line: int
    declared_col: int = 0
    initialized: bool = False        # true once any value is stored (for the table)
    uses: int = 0
    scope: int = 0                   # nesting depth, 0 = global


class SymbolTable:
    def __init__(self):
        self._scopes = [{}]
        self._all = []

    @property
    def depth(self) -> int:
        return len(self._scopes) - 1

    def enter(self):
        self._scopes.append({})

    def exit(self):
        self._scopes.pop()

    def declare(self, sym: Symbol) -> bool:
        if sym.name in self._scopes[-1]:
            return False
        self._scopes[-1][sym.name] = sym
        self._all.append(sym)
        return True

    def lookup(self, name: str) -> Optional[Symbol]:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def lookup_current(self, name: str) -> Optional[Symbol]:
        return self._scopes[-1].get(name)

    def all(self):
        return list(self._all)

    def visible_names(self):
        return [name for scope in self._scopes for name in scope]


def assignable(target: D, value: D) -> bool:
    return target == value or (target == D.FLOAT and value == D.INT)


def binary_type(op: str, l: D, r: D) -> Optional[D]:
    num = l.is_numeric and r.is_numeric
    wide = D.FLOAT if D.FLOAT in (l, r) else D.INT
    if op == "+":
        if l == D.STRING and r == D.STRING:
            return D.STRING
        return wide if num else None
    if op in ("-", "*", "/"):
        return wide if num else None
    if op == "%":
        return D.INT if l == r == D.INT else None
    if op in ("<", ">", "<=", ">="):
        return D.BOOL if num else None
    if op in ("==", "!="):
        return D.BOOL if (num or l == r) else None
    if op in ("&&", "||"):
        return D.BOOL if l == r == D.BOOL else None
    return None


class SemanticAnalyzer:
    def __init__(self, reporter: ErrorReporter):
        self.rep = reporter
        self.symbols = SymbolTable()
        self.definite = set()        # symbols that certainly have a value at this point

    def analyze(self, program: A.Program) -> SymbolTable:
        for s in program.statements:
            self.stmt(s)
        return self.symbols

    def err(self, node, message):
        self.rep.add("Semantic", message, node.line, node.column)

    def undeclared(self, node, name):
        near = difflib.get_close_matches(name, self.symbols.visible_names(), n=1, cutoff=0.7)
        hint = f" - did you mean '{near[0]}'?" if near else ""
        self.err(node, f"undeclared variable '{name}'{hint}")

    # ---- statements
    def stmt(self, n):
        if isinstance(n, A.VarDecl):
            t = self.expr(n.init) if n.init is not None else None
            sym = Symbol(n.name, n.dtype, n.line, n.column, scope=self.symbols.depth)
            if not self.symbols.declare(sym):
                prev = self.symbols.lookup_current(n.name)
                self.err(n, f"variable '{n.name}' is already declared in this scope (line {prev.declared_line})")
                return
            if n.init is not None:
                self._check_store(n.init, sym, t)
                sym.initialized = True
                self.definite.add(sym)
        elif isinstance(n, A.Assign):
            t = self.expr(n.value)
            sym = self.symbols.lookup(n.name)
            if sym is None:
                self.undeclared(n, n.name)
                return
            self._check_store(n.value, sym, t)
            sym.initialized = True
            self.definite.add(sym)
        elif isinstance(n, A.Print):
            self.expr(n.expr)
        elif isinstance(n, A.Block):
            self.symbols.enter()
            for s in n.statements:
                self.stmt(s)
            self.symbols.exit()
        elif isinstance(n, A.If):
            self._condition(n, "if")
            before = set(self.definite)
            self._scoped(n.then)
            after_then = set(self.definite)
            self.definite = set(before)
            if n.otherwise is not None:
                self._scoped(n.otherwise)
            self.definite &= after_then          # only values set on BOTH paths are certain
        elif isinstance(n, A.While):
            self._condition(n, "while")
            before = set(self.definite)
            self._scoped(n.body)
            self.definite = before               # the body may run zero times

    def _scoped(self, n):
        self.symbols.enter()
        self.stmt(n)
        self.symbols.exit()

    def _condition(self, n, kw):
        t = self.expr(n.cond)
        if t is not None and t != D.BOOL:
            self.err(n.cond, f"the condition of '{kw}' must be bool, but it is {t}")

    def _check_store(self, value_node, sym, t):
        if t is None or assignable(sym.type, t):
            return
        if sym.type == D.INT and t == D.FLOAT:
            self.err(value_node, f"cannot store a float in the int variable '{sym.name}' (declare it as float?)")
        else:
            self.err(value_node, f"type mismatch: cannot assign {t} to '{sym.name}' of type {sym.type}")

    # ---- expressions: return the type, or None after an error (stops cascades)
    def expr(self, n):
        if isinstance(n, A.Literal):
            return n.dtype
        if isinstance(n, A.Variable):
            sym = self.symbols.lookup(n.name)
            if sym is None:
                self.undeclared(n, n.name)
                return None
            sym.uses += 1
            if sym not in self.definite:
                self.err(n, f"variable '{n.name}' is used before it has a value")
                self.definite.add(sym)
            n.dtype = sym.type
            return sym.type
        if isinstance(n, A.Unary):
            t = self.expr(n.operand)
            if t is None:
                return None
            ok = t.is_numeric if n.op == "-" else t == D.BOOL
            if not ok:
                self.err(n, f"operator '{n.op}' cannot be applied to {t}")
                return None
            n.dtype = t
            return t
        if isinstance(n, A.Binary):
            lt, rt = self.expr(n.left), self.expr(n.right)
            if lt is None or rt is None:
                return None
            if n.op in ("/", "%") and isinstance(n.right, A.Literal) and n.right.value == 0 \
                    and n.right.dtype.is_numeric:
                self.err(n.right, "division by zero")
            res = binary_type(n.op, lt, rt)
            if res is None:
                self.err(n, f"operator '{n.op}' cannot be applied to {lt} and {rt}")
                return None
            n.dtype = res
            return res
        return None
