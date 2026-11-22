"""Token types and the Token record."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    # keywords
    INT_KW = auto(); FLOAT_KW = auto(); STRING_KW = auto(); BOOL_KW = auto()
    PRINT = auto(); IF = auto(); ELSE = auto(); WHILE = auto(); TRUE = auto(); FALSE = auto()
    # literals and names
    INT_LIT = auto(); FLOAT_LIT = auto(); STRING_LIT = auto(); IDENT = auto()
    # operators
    PLUS = auto(); MINUS = auto(); STAR = auto(); SLASH = auto(); PERCENT = auto()
    EQ = auto(); EQEQ = auto(); NEQ = auto(); LT = auto(); GT = auto(); LE = auto(); GE = auto()
    AND = auto(); OR = auto(); NOT = auto()
    # punctuation
    LPAREN = auto(); RPAREN = auto(); LBRACE = auto(); RBRACE = auto(); SEMI = auto()
    EOF = auto()


KEYWORDS = {
    "int": TokenType.INT_KW, "float": TokenType.FLOAT_KW, "string": TokenType.STRING_KW,
    "bool": TokenType.BOOL_KW, "print": TokenType.PRINT, "if": TokenType.IF,
    "else": TokenType.ELSE, "while": TokenType.WHILE, "true": TokenType.TRUE,
    "false": TokenType.FALSE,
}
TYPE_KEYWORDS = {TokenType.INT_KW, TokenType.FLOAT_KW, TokenType.STRING_KW, TokenType.BOOL_KW}

OPERATORS = {
    "+": TokenType.PLUS, "-": TokenType.MINUS, "*": TokenType.STAR, "/": TokenType.SLASH,
    "%": TokenType.PERCENT, "=": TokenType.EQ, "==": TokenType.EQEQ, "!=": TokenType.NEQ,
    "<": TokenType.LT, ">": TokenType.GT, "<=": TokenType.LE, ">=": TokenType.GE,
    "&&": TokenType.AND, "||": TokenType.OR, "!": TokenType.NOT,
    "(": TokenType.LPAREN, ")": TokenType.RPAREN, "{": TokenType.LBRACE, "}": TokenType.RBRACE,
    ";": TokenType.SEMI,
}


@dataclass
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int
    value: Any = None


def token_category(tt: TokenType) -> str:
    """keyword / literal / identifier / punct / operator / eof - used for coloring."""
    if tt == TokenType.EOF:
        return "eof"
    if tt in KEYWORDS.values():
        return "keyword"
    if tt.name.endswith("_LIT"):
        return "literal"
    if tt == TokenType.IDENT:
        return "identifier"
    if tt in (TokenType.LPAREN, TokenType.RPAREN, TokenType.LBRACE, TokenType.RBRACE, TokenType.SEMI):
        return "punct"
    return "operator"
