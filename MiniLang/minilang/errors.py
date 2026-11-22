"""Compiler errors and the collector that every stage reports into."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CompilerError:
    stage: str          # "Lexical", "Syntax" or "Semantic"
    message: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"[{self.stage}] line {self.line}, col {self.column}: {self.message}"


class ErrorReporter:
    """Collects errors. After `limit` errors it adds one 'too many errors' note and ignores the rest,
    so a single mistake can never bury you in a hundred follow-up messages."""

    def __init__(self, limit: int = 20):
        self.errors = []
        self.limit = limit
        self.full = False

    def add(self, stage: str, message: str, line: int, column: int) -> None:
        if self.full:
            return
        err = CompilerError(stage, message, line, column)
        if err in self.errors:                      # never report the same thing twice
            return
        if len(self.errors) >= self.limit:
            self.errors.append(CompilerError(stage, f"too many errors - stopped after {self.limit}", line, column))
            self.full = True
            return
        self.errors.append(err)

    def count(self, stage: str = None) -> int:
        return sum(1 for e in self.errors if stage is None or e.stage == stage)

    def sorted(self):
        return sorted(self.errors, key=lambda e: (e.line, e.column))
