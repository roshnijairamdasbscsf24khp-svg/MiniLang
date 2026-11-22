"""Lexical analysis with the re module."""
import re
from typing import List

from .errors import ErrorReporter
from .tokens import KEYWORDS, OPERATORS, Token, TokenType

MAX_INT = 2 ** 31 - 1

_SPEC = [
    ("COMMENT", r"//[^\n]*"),
    ("SPACE", r"[ \t\r]+"),
    ("NEWLINE", r"\n"),
    ("STRING", r'"(?:\\.|[^"\\\n])*"'),
    ("BADSTRING", r'"[^\n]*'),
    ("NUMBER", r"\d\w*(?:\.\w+)*"),
    ("IDENT", r"[A-Za-z_]\w*"),
    ("OP2", r"==|!=|<=|>=|&&|\|\|"),
    ("OP1", r"[+\-*/%=<>!(){};]"),
    ("BAD", r"."),
]
_MASTER = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _SPEC))
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
_HINTS = {                                   # wrong character -> what to do instead
    ",": " (MiniLang has no commas: declare each variable in its own statement)",
    "'": " (strings use double quotes)",
    "[": " (arrays are not supported)", "]": " (arrays are not supported)",
    ":": " (use '=' to assign a value)",
    "&": " (did you mean '&&'?)", "|": " (did you mean '||'?)",
}


class Lexer:
    def __init__(self, source: str, reporter: ErrorReporter):
        self.source = source
        self.rep = reporter

    def tokenize(self) -> List[Token]:
        tokens, line, line_start = [], 1, 0
        for m in _MASTER.finditer(self.source):
            kind, text = m.lastgroup, m.group()
            col = m.start() - line_start + 1
            if kind == "NEWLINE":
                line += 1
                line_start = m.end()
            elif kind in ("SPACE", "COMMENT"):
                continue
            elif kind == "STRING":
                value = self._decode(text, line, col)
                tokens.append(Token(TokenType.STRING_LIT, text, line, col, value))
            elif kind == "BADSTRING":
                self.rep.add("Lexical", "unterminated string literal", line, col)
            elif kind == "NUMBER":
                self._number(tokens, text, line, col)
            elif kind == "IDENT":
                tt = KEYWORDS.get(text, TokenType.IDENT)
                value = {"true": True, "false": False}.get(text)
                tokens.append(Token(tt, text, line, col, value))
            elif kind in ("OP1", "OP2"):
                tokens.append(Token(OPERATORS[text], text, line, col))
            else:
                self.rep.add("Lexical", f"invalid character '{text}'" + _HINTS.get(text, ""), line, col)
        end_col = len(self.source) - line_start + 1
        tokens.append(Token(TokenType.EOF, "", line, end_col))
        return tokens

    def _number(self, tokens, text, line, col):
        if re.fullmatch(r"\d+", text):
            value = int(text)
            if value > MAX_INT:
                self.rep.add("Lexical", f"integer '{text}' is too large (max {MAX_INT})", line, col)
            tokens.append(Token(TokenType.INT_LIT, text, line, col, value))
        elif re.fullmatch(r"\d+\.\d+", text):
            tokens.append(Token(TokenType.FLOAT_LIT, text, line, col, float(text)))
        else:
            self.rep.add("Lexical", f"malformed number '{text}'", line, col)

    def _decode(self, text, line, col):
        out, i, inner = [], 0, text[1:-1]
        while i < len(inner):
            ch = inner[i]
            if ch == "\\":
                nxt = inner[i + 1]
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                else:
                    self.rep.add("Lexical", f"invalid escape sequence '\\{nxt}'", line, col + i + 1)
                    out.append(nxt)
                i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)
