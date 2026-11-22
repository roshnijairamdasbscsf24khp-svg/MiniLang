"""A small virtual machine that executes three-address code (supports single stepping)."""
from dataclasses import dataclass, field
from typing import List, Optional

from .codegen import Instr
from .runtime import eval_binary, eval_unary, format_value, parse_const


@dataclass
class RunResult:
    output: List[str] = field(default_factory=list)
    error: Optional[str] = None
    steps: int = 0


class Machine:
    def __init__(self, instrs: List[Instr], max_steps: int = 200_000):
        self.code = list(instrs)
        self.max_steps = max_steps
        self.labels = {i.dst: k for k, i in enumerate(self.code) if i.op == "label"}
        self.reset()

    def reset(self):
        self.pc = 0
        self.env = {}
        self.output: List[str] = []
        self.error: Optional[str] = None
        self.steps = 0
        self._skip_labels()

    @property
    def finished(self) -> bool:
        return self.error is not None or self.pc >= len(self.code)

    def _skip_labels(self):
        while self.pc < len(self.code) and self.code[self.pc].op == "label":
            self.pc += 1

    def _get(self, tok):
        ok, v = parse_const(tok)
        if ok:
            return v
        if tok in self.env:
            return self.env[tok]
        raise RuntimeError(f"'{tok}' has no value")

    def step(self) -> bool:
        """Executes one instruction. Returns False when there is nothing left to run."""
        if self.finished:
            return False
        if self.steps >= self.max_steps:
            self.error = f"stopped after {self.max_steps} instructions (infinite loop?)"
            return False
        ins = self.code[self.pc]
        self.steps += 1
        nxt = self.pc + 1
        try:
            if ins.op == "assign":
                self.env[ins.dst] = self._get(ins.a)
            elif ins.op == "bin":
                self.env[ins.dst] = eval_binary(ins.sym, self._get(ins.a), self._get(ins.b))
            elif ins.op == "un":
                self.env[ins.dst] = eval_unary(ins.sym, self._get(ins.a))
            elif ins.op == "cast":
                self.env[ins.dst] = float(self._get(ins.a))
            elif ins.op == "print":
                self.output.append(format_value(self._get(ins.a)))
            elif ins.op == "jump":
                nxt = self.labels[ins.dst]
            elif ins.op == "ifFalse":
                if not self._get(ins.a):
                    nxt = self.labels[ins.dst]
            elif ins.op == "ifTrue":
                if self._get(ins.a):
                    nxt = self.labels[ins.dst]
        except ZeroDivisionError:
            self.error = f"runtime error: division by zero in '{ins}'"
        except RuntimeError as exc:
            self.error = f"runtime error: {exc}"
        self.pc = nxt
        self._skip_labels()
        return not self.finished


def run_program(instrs: List[Instr], max_steps: int = 200_000) -> RunResult:
    m = Machine(instrs, max_steps)
    while m.step():
        pass
    return RunResult(m.output, m.error, m.steps)
