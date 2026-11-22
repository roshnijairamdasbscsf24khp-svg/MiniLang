"""Three-address code generation."""
from dataclasses import dataclass
from typing import List, Optional

from . import ast_nodes as A
from .ast_nodes import DataType as D
from .runtime import fmt_const


@dataclass
class Instr:
    op: str                       # assign bin un cast print label jump ifFalse ifTrue
    dst: Optional[str] = None     # target variable / temp / label name
    a: Optional[str] = None
    b: Optional[str] = None
    sym: Optional[str] = None     # operator or cast type

    def __str__(self) -> str:
        o = self.op
        if o == "assign": return f"{self.dst} = {self.a}"
        if o == "bin": return f"{self.dst} = {self.a} {self.sym} {self.b}"
        if o == "un": return f"{self.dst} = {self.sym}{self.a}"
        if o == "cast": return f"{self.dst} = ({self.sym}) {self.a}"
        if o == "print": return f"print {self.a}"
        if o == "label": return f"{self.dst}:"
        if o == "jump": return f"goto {self.dst}"
        if o == "ifFalse": return f"ifFalse {self.a} goto {self.dst}"
        if o == "ifTrue": return f"ifTrue {self.a} goto {self.dst}"
        return o


class CodeGenerator:
    def __init__(self):
        self.code: List[Instr] = []
        self.temps = 0
        self.labels = 0
        self.scopes = [{}]
        self.counts = {}

    def generate(self, program: A.Program) -> List[Instr]:
        for s in program.statements:
            self.stmt(s)
        return self.code

    # ---- helpers
    def emit(self, op, dst=None, a=None, b=None, sym=None):
        self.code.append(Instr(op, dst, a, b, sym))

    def temp(self):
        self.temps += 1
        return f"t{self.temps}"

    def label(self):
        self.labels += 1
        return f"L{self.labels}"

    def declare(self, name):                        # inner variables that shadow get a unique name
        self.counts[name] = self.counts.get(name, 0) + 1
        unique = name if self.counts[name] == 1 else f"{name}_{self.counts[name]}"
        self.scopes[-1][name] = unique
        return unique

    def resolve(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return name

    def convert(self, operand, src, dst):
        """int -> float is the only implicit conversion MiniLang has."""
        if dst == D.FLOAT and src == D.INT:
            if operand.lstrip("-").isdigit():
                return operand + ".0"
            t = self.temp()
            self.emit("cast", t, operand, sym="float")
            return t
        return operand

    def scoped(self, node):
        self.scopes.append({})
        self.stmt(node)
        self.scopes.pop()

    # ---- statements
    def stmt(self, n):
        if isinstance(n, A.VarDecl):
            value = None
            if n.init is not None:
                value = self.convert(self.expr(n.init), self.type_of(n.init), n.dtype)
            name = self.declare(n.name)
            if value is not None:
                self.emit("assign", name, value)
        elif isinstance(n, A.Assign):
            value = self.expr(n.value)
            name = self.resolve(n.name)
            target = self.type_of_name(n.name)
            self.emit("assign", name, self.convert(value, self.type_of(n.value), target))
        elif isinstance(n, A.Print):
            self.emit("print", a=self.expr(n.expr))
        elif isinstance(n, A.Block):
            self.scopes.append({})
            for s in n.statements:
                self.stmt(s)
            self.scopes.pop()
        elif isinstance(n, A.If):
            cond = self.expr(n.cond)
            l_else = self.label()
            self.emit("ifFalse", l_else, cond)
            self.scoped(n.then)
            if n.otherwise is not None:
                l_end = self.label()
                self.emit("jump", l_end)
                self.emit("label", l_else)
                self.scoped(n.otherwise)
                self.emit("label", l_end)
            else:
                self.emit("label", l_else)
        elif isinstance(n, A.While):
            top, end = self.label(), self.label()
            self.emit("label", top)
            cond = self.expr(n.cond)
            self.emit("ifFalse", end, cond)
            self.scoped(n.body)
            self.emit("jump", top)
            self.emit("label", end)

    # ---- types recorded while generating (the analyzer already validated them)
    def type_of(self, n):
        return n.dtype

    def type_of_name(self, name):
        return self.var_types.get(self.resolve(name))

    var_types = {}

    # ---- expressions
    def expr(self, n) -> str:
        if isinstance(n, A.Literal):
            return fmt_const(n.value)
        if isinstance(n, A.Variable):
            return self.resolve(n.name)
        if isinstance(n, A.Unary):
            a = self.expr(n.operand)
            t = self.temp()
            self.emit("un", t, a, sym=n.op)
            return t
        if isinstance(n, A.Binary):
            if n.op in ("&&", "||"):                     # short-circuit
                res, end = self.temp(), self.label()
                self.emit("assign", res, self.expr(n.left))
                self.emit("ifFalse" if n.op == "&&" else "ifTrue", end, res)
                self.emit("assign", res, self.expr(n.right))
                self.emit("label", end)
                return res
            a, b = self.expr(n.left), self.expr(n.right)
            t = self.temp()
            self.emit("bin", t, a, b, n.op)
            return t
        raise TypeError(n)


def generate_code(program: A.Program) -> List[Instr]:
    gen = CodeGenerator()
    gen.var_types = {}
    _collect_types(program, gen)
    return gen.generate(program)


def _collect_types(program, gen):
    """Pre-pass: unique variable name -> declared type (mirrors CodeGenerator.declare)."""
    counts, scopes = {}, [{}]

    def declare(name, dtype):
        counts[name] = counts.get(name, 0) + 1
        unique = name if counts[name] == 1 else f"{name}_{counts[name]}"
        gen.var_types[unique] = dtype

    def walk(n):
        if isinstance(n, A.VarDecl):
            declare(n.name, n.dtype)
        elif isinstance(n, (A.Program, A.Block)):
            for s in n.statements:
                walk(s)
        elif isinstance(n, A.If):
            walk(n.then)
            if n.otherwise is not None:
                walk(n.otherwise)
        elif isinstance(n, A.While):
            walk(n.body)
    walk(program)
