"""Runs the real MiniLang compiler in the browser (Pyodide) and returns the results as JSON for the web UI."""
import json

from minilang.compiler import compare_strategies, compile_source
from minilang.ast_nodes import describe
from minilang.interpreter import run_program
from minilang.parser import RepairOptions
from minilang.recovery import build_items
from minilang.samples import SAMPLES
from minilang.tokens import TokenType, token_category


def _tree(n, role="", c=None):
    c = c if c is not None else [0]
    label, detail, kids = describe(n)
    node = {"n": label, "d": detail, "r": role, "l": getattr(n, "line", 0), "o": c[0]}
    c[0] += 1
    node["c"] = [_tree(k, r, c) for r, k in kids]
    return node


def samples():
    return json.dumps([[n, s] for n, s in SAMPLES])


def analyze(src, strategy="phrase", opts="{}"):
    rep = RepairOptions(**json.loads(opts))
    r = compile_source(src, True, strategy, rep)
    cmp = compare_strategies(src, rep)
    out = {
        "stages": r.stages,
        "tokens": [[t.type.name, t.lexeme, t.line, t.column, token_category(t.type)]
                   for t in r.tokens if t.type != TokenType.EOF],
        "ast": _tree(r.ast) if r.ast is not None else None,
        "symbols": [[s.name, str(s.type), s.declared_line, s.scope, s.initialized, s.uses]
                    for s in (r.symbols.all() if r.symbols else [])],
        "errors": [[e.stage, e.line, e.column, e.message, r.fixes.get((e.line, e.column, e.message), "")]
                   for e in r.errors],
        "tac": r.intermediate_code, "opt": r.optimized_code, "stats": r.opt_stats,
        "cfg": [{"id": b.id, "code": [str(i) for i in b.instrs], "succ": b.succ} for b in r.cfg],
        "compare": None, "run": None,
    }
    if cmp:
        out["compare"] = [{
            "key": x.key, "name": x.name, "errors": len(x.errors), "stmts": x.statements, "nodes": x.nodes,
            "skipped": x.skipped, "inserted": x.inserted, "replaced": x.replaced,
            "log": [[e.line, e.column, e.message, x.fixes.get((e.line, e.column, e.message), "")] for e in x.errors],
            "chips": build_items(r.tokens, x.events)} for x in cmp]
    if r.success:
        res = run_program(r.optimized)
        out["run"] = {"out": res.output, "err": res.error}
    return json.dumps(out)
