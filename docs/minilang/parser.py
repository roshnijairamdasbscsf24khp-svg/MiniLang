"""Recursive descent parser with three error-handling strategies.

  stop   - report the first syntax error and stop
  panic  - skip tokens until a safe point (';', '}' or a statement keyword), then carry on
  phrase - repair small mistakes in place (insert ; ) ( =, delete stray tokens, fix misspelt keywords,
           '=' vs '=='); if no local repair fits it falls back to panic mode

All strategies share the same "error productions": friendly messages for typical beginner mistakes.
Every recovery action is written to `events` so the GUI can animate it.
"""
import difflib
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from . import ast_nodes as A
from .errors import ErrorReporter
from .tokens import KEYWORDS, TYPE_KEYWORDS, Token, TokenType as T

STRATEGIES = ("stop", "panic", "phrase")
STRATEGY_NAMES = {"stop": "Stop at first error", "panic": "Panic mode", "phrase": "Phrase-level repair"}
STRATEGY_BLURB = {
    "stop": "Reports the first error and stops. Simple, but you only ever see one problem at a time.",
    "panic": "Skips tokens until a safe point (; or }) and carries on. Finds many errors; the broken statement is dropped.",
    "phrase": "Fixes small mistakes in place (inserts ; ) ( =, removes stray tokens, corrects misspelt keywords) so the statement survives.",
}

COMPARE_OPS = ("==", "!=", "<=", ">=", "<", ">")


@dataclass
class RepairOptions:
    """Which local repairs phrase-level mode may make (each can be switched off) and what '=' becomes in a condition."""
    keywords: bool = True       # misspelt keyword -> keyword   (prnt -> print)
    insert: bool = True         # insert a missing ; ) ( = }
    delete: bool = True         # delete a stray ; ) }
    operators: bool = True      # '=' inside a condition / '==' used as an assignment
    compare_op: str = "=="      # what '=' becomes inside a condition: == != <= >= < >


TYPE_OF = {T.INT_KW: A.DataType.INT, T.FLOAT_KW: A.DataType.FLOAT,
           T.STRING_KW: A.DataType.STRING, T.BOOL_KW: A.DataType.BOOL}
STMT_START = TYPE_KEYWORDS | {T.PRINT, T.IF, T.WHILE, T.LBRACE, T.IDENT}
VALUE_START = {T.INT_LIT, T.FLOAT_LIT, T.STRING_LIT, T.TRUE, T.FALSE}
EXPR_START = VALUE_START | {T.IDENT, T.LPAREN, T.MINUS, T.NOT}
SYMBOL = {T.SEMI: ";", T.RPAREN: ")", T.LPAREN: "(", T.EQ: "="}
MAX_DEPTH = 150          # nested blocks / brackets / unary operators
MAX_CHAIN = 500          # operators in one unbroken chain such as 1 + 1 + 1 + ...
STATEMENT_WORDS = ["int", "float", "string", "bool", "print", "if", "while"]


@dataclass
class Event:
    """One thing that happened while parsing. kind: error | insert | delete | skip | replace | halt."""
    kind: str
    index: int                    # token index it refers to (insert = "before this token")
    text: str = ""
    end: Optional[int] = None     # skip covers tokens [index, end)


class ParseError(Exception):
    pass


def suggest(word: str, candidates, cutoff: float = 0.7) -> Optional[str]:
    near = difflib.get_close_matches(word, list(candidates), n=1, cutoff=cutoff)
    return near[0] if near else None


class Parser:
    def __init__(self, tokens: List[Token], reporter: ErrorReporter, strategy: str = "phrase",
                 repairs: Optional[RepairOptions] = None):
        assert strategy in STRATEGIES, strategy
        self.opts = repairs or RepairOptions()
        self.tokens = [replace(t) for t in tokens]      # private copy: repairs never touch the lexer's tokens
        self.rep, self.pos, self.strategy = reporter, 0, strategy
        self.events: List[Event] = []
        self.fixes: Dict[Tuple[int, int, str], str] = {}  # (line, col, message) -> what the parser did about it
        self._last = None
        self.halted = False
        self.depth = 0

    # ---- helpers
    def peek(self) -> Token:
        return self.tokens[self.pos]

    def peek2(self) -> Token:
        return self.tokens[min(self.pos + 1, len(self.tokens) - 1)]

    def at_end(self) -> bool:
        return self.peek().type == T.EOF

    def check(self, *types) -> bool:
        return self.peek().type in types

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != T.EOF:
            self.pos += 1
        return tok

    def match(self, *types):
        return self.advance() if self.check(*types) else None

    @staticmethod
    def desc(tok: Token) -> str:
        return "end of file" if tok.type == T.EOF else f"'{tok.lexeme}'"

    def _on(self, flag: str) -> bool:
        """Is this kind of local repair allowed right now?"""
        return self.strategy == "phrase" and bool(getattr(self.opts, flag))

    @property
    def stopped(self) -> bool:
        return self.halted or self.rep.full

    def report(self, line: int, col: int, message: str, idx: Optional[int] = None):
        self.rep.add("Syntax", message, line, col)
        self._last = (line, col, message)
        self.events.append(Event("error", self.pos if idx is None else idx, message))
        if self.strategy == "stop":
            self.halted = True

    def fix(self, kind: str, idx: int, text: str, end: Optional[int] = None):
        self.events.append(Event(kind, idx, text, end))
        what = {"insert": f"inserted '{text}'", "delete": f"deleted '{text}'",
                "skip": f"skipped {text} token(s)",
                "replace": f"read '{self.tokens[min(idx, len(self.tokens) - 1)].lexeme}' as {text}"}[kind]
        if self._last is not None:
            old = self.fixes.get(self._last)
            self.fixes[self._last] = f"{old}; {what}" if old else what

    def fail(self, tok: Token, message: str):
        self.report(tok.line, tok.column, message)
        raise ParseError()

    def _can_insert(self, tt, nxt: Token) -> bool:
        """Is a one-token repair believable here?"""
        if tt == T.SEMI:
            return nxt.type in STMT_START | {T.RBRACE, T.EOF, T.ELSE}
        if tt == T.RPAREN:
            return nxt.type in STMT_START | {T.LBRACE, T.SEMI, T.RBRACE, T.EOF}
        if tt == T.LPAREN:
            return nxt.type in EXPR_START
        if tt == T.EQ:
            return nxt.type in EXPR_START
        return False

    def expect(self, tt, what: str, after_prev: bool = False) -> Token:
        if self.check(tt):
            return self.advance()
        tok = self.peek()
        line, col = tok.line, tok.column
        if after_prev and self.pos > 0:                 # "missing ;" points just after the last token
            prev = self.tokens[self.pos - 1]
            line, col = prev.line, prev.column + len(prev.lexeme)
        self.report(line, col, f"expected {what} but found {self.desc(tok)}")
        if self._on("insert") and tt in SYMBOL and self._can_insert(tt, tok):
            self.fix("insert", self.pos, SYMBOL[tt])
            return Token(tt, "", line, col)             # a virtual token: nothing is consumed
        raise ParseError()

    # ---- recovery
    def synchronize(self):
        while not self.at_end():
            if self.pos > 0 and self.tokens[self.pos - 1].type == T.SEMI:
                return
            if self.peek().type in STMT_START or self.peek().type == T.RBRACE:
                return
            self.advance()

    def _recover(self, start: int):
        err_pos = self.pos
        self.synchronize()
        if self.pos == start:                           # always make progress
            self.advance()
        if self.pos > err_pos:
            self.fix("skip", err_pos, str(self.pos - err_pos), end=self.pos)

    def _unexpected(self, t: Token) -> str:
        return (f"unexpected {self.desc(t)}; a statement starts with a type, a name, "
                f"'print', 'if', 'while' or '{{'")

    def _next_statement(self, out: list, top: bool):
        start, t = self.pos, self.peek()
        if self._on("delete") and (t.type in (T.SEMI, T.RPAREN) or (top and t.type == T.RBRACE)):
            self.report(t.line, t.column, self._unexpected(t))
            self.fix("delete", self.pos, t.lexeme)      # a stray token: just drop it
            self.advance()
            return
        try:
            out.append(self.statement())
        except ParseError:
            if not self.halted:
                self._recover(start)

    # ---- statements
    def parse(self) -> A.Program:
        stmts = []
        while not self.at_end() and not self.stopped:
            self._next_statement(stmts, top=True)
        if self.stopped:
            self.events.append(Event("halt", self.pos))
        return A.Program(stmts)

    def _enter(self, tok: Token):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.depth -= 1
            self.fail(tok, f"nested too deeply (more than {MAX_DEPTH} levels) - simplify or split the code")

    def statement(self):
        self._enter(self.peek())
        try:
            return self._statement()
        finally:
            self.depth -= 1

    def _statement(self):
        t = self.peek()
        if t.type in TYPE_KEYWORDS:
            return self.declaration()
        if t.type == T.IDENT:
            return self.ident_statement()
        if t.type == T.PRINT:
            return self.print_stmt()
        if t.type == T.IF:
            return self.if_stmt()
        if t.type == T.WHILE:
            return self.while_stmt()
        if t.type == T.LBRACE:
            return self.block()
        if t.type == T.ELSE:
            self.fail(t, "'else' without a matching 'if'")
        self.fail(t, self._unexpected(t))

    def ident_statement(self):
        t, nxt = self.peek(), self.peek2()
        if nxt.type not in (T.EQ, T.EQEQ) and len(t.lexeme) >= 2:
            word = suggest(t.lexeme, STATEMENT_WORDS, 0.6)                # error production: misspelt keyword
            if word:
                self.report(t.line, t.column, f"unknown word '{t.lexeme}' - did you mean '{word}'?")
                if not self._on("keywords"):
                    raise ParseError()
                self.fix("replace", self.pos, f"'{word}'")
                t.type, t.lexeme = KEYWORDS[word], word
                return self.statement()
        return self.assignment()

    def declaration(self):
        kw = self.advance()
        name = self.peek()
        if name.type != T.IDENT:
            if name.type in KEYWORDS.values():
                self.fail(name, f"'{name.lexeme}' is a keyword and cannot be used as a name")
            self.expect(T.IDENT, "a variable name")
        self.advance()
        init = None
        if self.match(T.EQ):
            init = self.expression()
        elif self.peek().type in VALUE_START:                          # error production: `int a 5;`
            nxt = self.peek()
            self.report(nxt.line, nxt.column,
                        f"expected '=' or ';' after '{name.lexeme}' but found {self.desc(nxt)} "
                        f"(is the '=' missing?)")
            if not self._on("insert"):
                raise ParseError()
            self.fix("insert", self.pos, "=")
            init = self.expression()
        self.expect(T.SEMI, "';'", True)
        return A.VarDecl(TYPE_OF[kw.type], name.lexeme, init, kw.line, kw.column)

    def assignment(self):
        name = self.advance()
        if self.check(T.EQEQ):                                          # error production: `a == 5;`
            eq = self.peek()
            self.report(eq.line, eq.column, "'==' compares two values; to assign use '=' (did you mean '='?)")
            if not self._on("operators"):
                raise ParseError()
            self.fix("replace", self.pos, "'='")
            self.advance()
        else:
            self.expect(T.EQ, f"'=' after '{name.lexeme}'")
        value = self.expression()
        self.expect(T.SEMI, "';'", True)
        return A.Assign(name.lexeme, value, name.line, name.column)

    def print_stmt(self):
        kw = self.advance()
        self.expect(T.LPAREN, "'(' after 'print' (write print(value);)")
        expr = self.expression()
        self.expect(T.RPAREN, "')'", True)
        self.expect(T.SEMI, "';'", True)
        return A.Print(expr, kw.line, kw.column)

    def condition(self, kw: str):
        self.expect(T.LPAREN, f"'(' after '{kw}'")
        cond = self.expression()
        if self.check(T.EQ):                                            # error production: `if (a = 5)`
            eq = self.peek()
            op = self.opts.compare_op if self.opts.compare_op in COMPARE_OPS else "=="
            self.report(eq.line, eq.column,
                        "'=' assigns a value; to compare inside a condition use '==', '!=', '<=', '>=', '<' or '>' "
                        f"(did you mean '{op}'?)")
            if not self._on("operators"):
                raise ParseError()
            self.fix("replace", self.pos, f"'{op}'")
            self.advance()
            cond = A.Binary(op, cond, self.expression(), eq.line, eq.column)
        self.expect(T.RPAREN, "')'", True)
        return cond

    def if_stmt(self):
        kw = self.advance()
        cond = self.condition("if")
        then = self.statement()
        other = self.statement() if self.match(T.ELSE) else None
        return A.If(cond, then, other, kw.line, kw.column)

    def while_stmt(self):
        kw = self.advance()
        cond = self.condition("while")
        return A.While(cond, self.statement(), kw.line, kw.column)

    def block(self):
        lb = self.advance()
        stmts = []
        while not self.check(T.RBRACE) and not self.at_end() and not self.stopped:
            self._next_statement(stmts, top=False)
        if self.check(T.RBRACE):
            self.advance()
        elif not self.stopped:
            eof = self.peek()
            self.report(eof.line, eof.column, f"expected '}}' to close the block opened at line {lb.line}")
            if self._on("insert"):
                self.fix("insert", self.pos, "}")
        return A.Block(stmts, lb.line, lb.column)

    # ---- expressions (lowest precedence first)
    def _binary(self, next_level, *ops):
        left = next_level()
        count = 0
        while self.check(*ops):
            op = self.advance()
            count += 1
            if count > MAX_CHAIN:
                self.fail(op, f"expression too long (more than {MAX_CHAIN} '{op.lexeme}' in a row) - "
                              f"split it into several statements")
            left = A.Binary(op.lexeme, left, next_level(), op.line, op.column)
        return left

    def expression(self):
        return self._binary(self.and_expr, T.OR)

    def and_expr(self):
        return self._binary(self.equality, T.AND)

    def equality(self):
        return self._binary(self.comparison, T.EQEQ, T.NEQ)

    def comparison(self):
        return self._binary(self.term, T.LT, T.GT, T.LE, T.GE)

    def term(self):
        return self._binary(self.factor, T.PLUS, T.MINUS)

    def factor(self):
        return self._binary(self.unary, T.STAR, T.SLASH, T.PERCENT)

    def unary(self):
        if self.check(T.MINUS, T.NOT):
            op = self.advance()
            self._enter(op)
            try:
                return A.Unary(op.lexeme, self.unary(), op.line, op.column)
            finally:
                self.depth -= 1
        return self.primary()

    def primary(self):
        t = self.peek()
        if t.type == T.INT_LIT:
            self.advance(); return A.Literal(t.value, A.DataType.INT, t.line, t.column)
        if t.type == T.FLOAT_LIT:
            self.advance(); return A.Literal(t.value, A.DataType.FLOAT, t.line, t.column)
        if t.type == T.STRING_LIT:
            self.advance(); return A.Literal(t.value, A.DataType.STRING, t.line, t.column)
        if t.type in (T.TRUE, T.FALSE):
            self.advance(); return A.Literal(t.type == T.TRUE, A.DataType.BOOL, t.line, t.column)
        if t.type == T.IDENT:
            self.advance(); return A.Variable(t.lexeme, t.line, t.column)
        if t.type == T.LPAREN:
            self.advance()
            self._enter(t)
            try:
                inner = self.expression()
            finally:
                self.depth -= 1
            self.expect(T.RPAREN, "')'", True)
            return inner
        self.fail(t, f"expected an expression but found {self.desc(t)}")
