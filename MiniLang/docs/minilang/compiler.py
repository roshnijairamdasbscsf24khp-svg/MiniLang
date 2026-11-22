"""Runs the stages in order: lexical -> syntax -> semantic -> code generation -> optimization."""
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cfg import build_cfg
from .codegen import Instr, generate_code
from .errors import CompilerError, ErrorReporter
from .lexer import Lexer
from .optimizer import optimize
from .parser import STRATEGIES, STRATEGY_NAMES, Event, Parser, RepairOptions
from .ast_nodes import count_nodes, count_statements
from .semantic import SemanticAnalyzer, SymbolTable
from .tokens import Token


if sys.getrecursionlimit() < 10000:        # deep (but legal) nesting needs more than Python's default 1000
    sys.setrecursionlimit(10000)


@dataclass
class CompileResult:
    source: str
    tokens: List[Token] = field(default_factory=list)
    ast: object = None
    symbols: Optional[SymbolTable] = None
    errors: List[CompilerError] = field(default_factory=list)
    instructions: List[Instr] = field(default_factory=list)
    optimized: List[Instr] = field(default_factory=list)
    opt_stats: Dict[str, int] = field(default_factory=dict)
    cfg: list = field(default_factory=list)
    cfg_original: list = field(default_factory=list)
    stages: Dict[str, str] = field(default_factory=dict)   # stage -> "ok" | "fail" | "skipped"
    strategy: str = "phrase"
    recovery: List[Event] = field(default_factory=list)    # what the parser did about each error
    fixes: Dict[tuple, str] = field(default_factory=dict)  # (line, col, message) -> recovery action

    @property
    def success(self) -> bool:
        return not self.errors

    @property
    def intermediate_code(self) -> List[str]:
        return [str(i) for i in self.instructions]

    @property
    def optimized_code(self) -> List[str]:
        return [str(i) for i in self.optimized]


def compile_source(source: str, optimize_code: bool = True, strategy: str = "phrase",
                   repairs: Optional[RepairOptions] = None) -> CompileResult:
    rep = ErrorReporter()
    r = CompileResult(source, strategy=strategy, stages={s: "skipped" for s in ("lexical", "syntax", "semantic", "codegen")})

    try:
        _run_stages(source, optimize_code, strategy, rep, r, repairs)
    except RecursionError:                              # safety net: never crash, report instead
        rep.add("Semantic", "the program is nested too deeply to be analysed", 1, 1)
        for stage in ("semantic", "codegen"):
            if r.stages[stage] != "ok":
                r.stages[stage] = "fail" if stage == "semantic" else "skipped"
    r.errors = rep.sorted()
    return r


def _run_stages(source, optimize_code, strategy, rep, r, repairs=None):
    r.tokens = Lexer(source, rep).tokenize()
    r.stages["lexical"] = "fail" if rep.count("Lexical") else "ok"
    if r.stages["lexical"] == "ok":
        parser = Parser(r.tokens, rep, strategy, repairs)
        r.ast = parser.parse()
        r.recovery, r.fixes = parser.events, parser.fixes
        r.stages["syntax"] = "fail" if rep.count("Syntax") else "ok"
    if r.stages["syntax"] == "ok":
        r.symbols = SemanticAnalyzer(rep).analyze(r.ast)
        r.stages["semantic"] = "fail" if rep.count("Semantic") else "ok"
    if r.stages["semantic"] == "ok":
        r.instructions = generate_code(r.ast)
        if optimize_code:
            r.optimized, r.opt_stats = optimize(r.instructions)
        else:
            r.optimized, r.opt_stats = list(r.instructions), {}
        r.cfg_original = build_cfg(r.instructions)
        r.cfg = build_cfg(r.optimized)
        r.stages["codegen"] = "ok"


@dataclass
class StrategyResult:
    key: str
    name: str
    errors: list
    statements: int          # statements that made it into the tree
    nodes: int
    skipped: int             # tokens thrown away (panic skips + phrase deletions)
    inserted: int
    replaced: int
    events: List[Event]
    halted: bool
    fixes: dict


def compare_strategies(source: str, repairs: Optional[RepairOptions] = None) -> Optional[List[StrategyResult]]:
    """Parses the same source with every strategy. Returns None if lexical errors prevent parsing."""
    rep0 = ErrorReporter()
    tokens = Lexer(source, rep0).tokenize()
    if rep0.count("Lexical"):
        return None
    out = []
    for key in STRATEGIES:
        rep = ErrorReporter()
        parser = Parser(tokens, rep, key, repairs)
        tree = parser.parse()
        ev = parser.events
        out.append(StrategyResult(
            key, STRATEGY_NAMES[key], rep.sorted(), count_statements(tree), count_nodes(tree),
            sum((e.end - e.index) for e in ev if e.kind == "skip") + sum(1 for e in ev if e.kind == "delete"),
            sum(1 for e in ev if e.kind == "insert"), sum(1 for e in ev if e.kind == "replace"),
            ev, any(e.kind == "halt" for e in ev), parser.fixes))
    return out
