"""Turns tokens + parser events into display chips (used by the desktop GUI and the web version)."""
from .tokens import token_category


def build_items(tokens, events):
    """Turns tokens + parser events into chips: tokens (ok / skipped / deleted / replaced / unread) and inserted symbols."""
    n = len(tokens)
    skipped, deleted, errs, repl, ins, halt = set(), set(), set(), {}, {}, None
    for e in events:
        i = min(e.index, n - 1)
        if e.kind == "error":
            errs.add(i)
        elif e.kind == "skip":
            skipped.update(range(e.index, min(e.end, n)))
        elif e.kind == "delete":
            deleted.add(i)
        elif e.kind == "replace":
            repl[i] = e.text
        elif e.kind == "insert":
            ins.setdefault(i, []).append(e.text)
        elif e.kind == "halt":
            halt = e.index
    items = []
    for i, t in enumerate(tokens):
        first_on_row = i == 0 or tokens[i - 1].line != t.line
        for text in ins.get(i, []):                                    # a missing ';' belongs to the line before
            items.append({"kind": "ins", "text": text, "row": tokens[i - 1].line if (first_on_row and i) else t.line})
        state = "ok"
        if halt is not None and i > halt:
            state = "unread"
        elif i in skipped:
            state = "skipped"
        elif i in deleted:
            state = "deleted"
        elif i in repl:
            state = "replaced"
        items.append({"kind": "tok", "text": t.lexeme or "EOF", "row": t.line, "state": state, "err": i in errs,
                      "new": repl.get(i), "cat": token_category(t.type)})
    return items
