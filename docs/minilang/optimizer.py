"""Optimizer: constant folding, constant propagation, algebraic simplification,
branch folding, unreachable-code and dead-assignment removal."""
import math
import re
from dataclasses import replace
from typing import List, Tuple

from .codegen import Instr
from .runtime import eval_binary, eval_unary, fmt_const, parse_const

TEMP = re.compile(r"t\d+$")


def optimize(instrs: List[Instr]) -> Tuple[List[Instr], dict]:
    stats = {"folded": 0, "propagated": 0, "branches": 0, "removed": 0}
    code = [replace(i) for i in instrs]
    for _ in range(20):
        before = [str(i) for i in code]
        code = _propagate_and_fold(code, stats)
        code = _simplify_flow(code, stats)
        code = _remove_dead(code, stats)
        if [str(i) for i in code] == before:
            break
    return code, stats


def _ok_value(v) -> bool:
    return not (isinstance(v, float) and not math.isfinite(v))


def _propagate_and_fold(code, stats):
    env, out = {}, []                                   # env: name -> constant operand (per basic block)

    def sub(tok):
        if tok in env:
            stats["propagated"] += 1
            return env[tok]
        return tok

    for ins in code:
        op = ins.op
        if op == "label":
            env.clear()
            out.append(ins)
            continue
        if op == "assign":
            a = sub(ins.a)
            ins = replace(ins, a=a)
        elif op == "bin":
            a, b = sub(ins.a), sub(ins.b)
            ins = replace(ins, a=a, b=b)
            (ok1, v1), (ok2, v2) = parse_const(a), parse_const(b)
            if ok1 and ok2:
                try:
                    v = eval_binary(ins.sym, v1, v2)
                except (ZeroDivisionError, TypeError):
                    v = None
                if v is not None and _ok_value(v):
                    ins = Instr("assign", ins.dst, fmt_const(v))
                    stats["folded"] += 1
            else:
                s = ins.sym
                keep = None
                if s in ("+", "-") and b == "0": keep = a
                elif s == "+" and a == "0": keep = b
                elif s in ("*", "/") and b == "1": keep = a
                elif s == "*" and a == "1": keep = b
                if keep is not None:
                    ins = Instr("assign", ins.dst, keep)
                    stats["folded"] += 1
        elif op == "un":
            a = sub(ins.a)
            ins = replace(ins, a=a)
            ok, v = parse_const(a)
            if ok:
                ins = Instr("assign", ins.dst, fmt_const(eval_unary(ins.sym, v)))
                stats["folded"] += 1
        elif op == "cast":
            a = sub(ins.a)
            ins = replace(ins, a=a)
            ok, v = parse_const(a)
            if ok:
                ins = Instr("assign", ins.dst, fmt_const(float(v)))
                stats["folded"] += 1
        elif op == "print":
            ins = replace(ins, a=sub(ins.a))
        elif op in ("ifFalse", "ifTrue"):
            a = sub(ins.a)
            ok, v = parse_const(a)
            if ok:
                stats["branches"] += 1
                jumps = (not v) if op == "ifFalse" else bool(v)
                if jumps:
                    out.append(Instr("jump", ins.dst))
                continue
            ins = replace(ins, a=a)
        # record / forget what this instruction defines
        if ins.op in ("assign", "bin", "un", "cast"):
            ok, _ = parse_const(ins.a) if ins.op == "assign" else (False, None)
            if ok:
                env[ins.dst] = ins.a
            else:
                env.pop(ins.dst, None)
        out.append(ins)
    return out


def _simplify_flow(code, stats):
    # 1. drop everything between an unconditional goto and the next label
    out, dead = [], False
    for ins in code:
        if ins.op == "label":
            dead = False
        if dead:
            stats["removed"] += 1
            continue
        out.append(ins)
        if ins.op == "jump":
            dead = True
    # 2. goto L immediately followed by L:
    res = []
    for i, ins in enumerate(out):
        if ins.op == "jump":
            j = i + 1
            while j < len(out) and out[j].op == "label":
                if out[j].dst == ins.dst:
                    break
                j += 1
            if j < len(out) and out[j].op == "label" and out[j].dst == ins.dst:
                stats["removed"] += 1
                continue
        res.append(ins)
    # 3. labels nobody jumps to
    used = {i.dst for i in res if i.op in ("jump", "ifFalse", "ifTrue")}
    final = []
    for ins in res:
        if ins.op == "label" and ins.dst not in used:
            stats["removed"] += 1
            continue
        final.append(ins)
    return final


def _remove_dead(code, stats):
    reads = set()
    for i in code:
        for x in (i.a, i.b):
            if x is not None:
                reads.add(x)
    out = []
    for i in code:
        pure = i.op in ("assign", "cast", "un") or (i.op == "bin" and i.sym not in ("/", "%"))
        if pure and i.dst not in reads:
            stats["removed"] += 1
            continue
        out.append(i)
    return out
