"""Basic blocks and the control-flow graph."""
from dataclasses import dataclass, field
from typing import List, Tuple

from .codegen import Instr


@dataclass
class Block:
    id: int
    instrs: List[Instr]
    succ: List[Tuple[int, str]] = field(default_factory=list)   # (block id, "" | "true" | "false")


def build_cfg(code: List[Instr]) -> List[Block]:
    if not code:
        return []
    leaders = {0}
    for i, ins in enumerate(code):
        if ins.op == "label":
            leaders.add(i)
        if ins.op in ("jump", "ifFalse", "ifTrue") and i + 1 < len(code):
            leaders.add(i + 1)
    starts = sorted(leaders)
    blocks, by_label = [], {}
    for n, s in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(code)
        b = Block(n, code[s:end])
        blocks.append(b)
        if code[s].op == "label":
            by_label[code[s].dst] = n
    for n, b in enumerate(blocks):
        last = b.instrs[-1]
        nxt = n + 1 if n + 1 < len(blocks) else None
        if last.op == "jump":
            b.succ.append((by_label[last.dst], ""))
        elif last.op == "ifFalse":
            b.succ.append((by_label[last.dst], "false"))
            if nxt is not None:
                b.succ.append((nxt, "true"))
        elif last.op == "ifTrue":
            b.succ.append((by_label[last.dst], "true"))
            if nxt is not None:
                b.succ.append((nxt, "false"))
        elif nxt is not None:
            b.succ.append((nxt, ""))
    return blocks
