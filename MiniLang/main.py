"""Starts MiniLang.

    python main.py                       opens the desktop window
    python main.py program.ml            compiles a file in the console (no window)
    python main.py program.ml --run      ...and runs the optimized code
    python main.py program.ml --no-opt   ...without the optimizer
    python main.py program.ml --strategy=panic     error handling: stop | panic | phrase (default)
    python main.py program.ml --compare            compare the three error-handling strategies
    python main.py program.ml --op=<=              phrase-level: '=' in a condition becomes == != <= >= < >
    python main.py program.ml --no-fix=keywords,insert,delete,operators   switch phrase-level repairs off
"""
import sys

from minilang.ast_nodes import print_ast
from minilang.compiler import compare_strategies, compile_source
from minilang.interpreter import run_program
from minilang.parser import COMPARE_OPS, RepairOptions
from minilang.tokens import TokenType


def run_console(file_name: str, run: bool, optimize: bool, strategy: str = "phrase", compare: bool = False,
                repairs: RepairOptions = None) -> int:
    try:
        with open(file_name, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        print(f"Cannot read '{file_name}': {exc}", file=sys.stderr)
        return 2

    if compare:
        results = compare_strategies(source, repairs)
        if results is None:
            print("Lexical errors stop the parser before any strategy can run - fix them first.")
            return 1
        print(f"{'Strategy':<24}{'Errors':>7}{'Statements':>12}{'Nodes':>7}{'Skipped':>9}{'Inserted':>10}{'Replaced':>10}")
        for x in results:
            print(f"{x.name:<24}{len(x.errors):>7}{x.statements:>12}{x.nodes:>7}{x.skipped:>9}{x.inserted:>10}{x.replaced:>10}")
        return 0

    r = compile_source(source, optimize, strategy, repairs)

    print("=== Tokens ===")
    for t in r.tokens:
        if t.type != TokenType.EOF:
            print(f"{t.type.name:<12} {t.lexeme!r:<14} line {t.line}, col {t.column}")
    if r.ast is not None:
        print("\n=== Syntax tree ===")
        print(print_ast(r.ast), end="")
    if r.symbols is not None:
        print("\n=== Symbol table ===")
        print(f"{'Name':<14} {'Type':<8} {'Line':<6} {'Scope':<6} {'Has value':<10} Uses")
        for s in r.symbols.all():
            print(f"{s.name:<14} {str(s.type):<8} {s.declared_line:<6} {s.scope:<6} "
                  f"{'yes' if s.initialized else 'no':<10} {s.uses}")

    if not r.success:
        print("\n=== Errors ===")
        for e in r.errors:
            fix = r.fixes.get((e.line, e.column, e.message))
            print("  " + str(e) + (f"   -> {fix}" if fix else ""))
        print(f"\nCompilation failed with {len(r.errors)} error(s).")
        return 1

    print("\n=== Three-address code ===")
    for line in r.intermediate_code:
        print(line if line.endswith(":") else "  " + line)
    if optimize:
        print("\n=== Optimized code ===", r.opt_stats)
        for line in r.optimized_code:
            print(line if line.endswith(":") else "  " + line)
    print("\nCompilation successful.")
    if run:
        res = run_program(r.optimized)
        print("\n=== Output ===")
        print("\n".join(res.output))
        if res.error:
            print(res.error, file=sys.stderr)
            return 3
    return 0


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if args:
        strategy = next((f.split("=", 1)[1] for f in flags if f.startswith("--strategy=")), "phrase")
        if strategy not in ("stop", "panic", "phrase"):
            print("Strategy must be stop, panic or phrase.", file=sys.stderr)
            return 2
        repairs = RepairOptions(compare_op=next((f.split("=", 1)[1] for f in flags if f.startswith("--op=")), "=="))
        for f in flags:
            if f.startswith("--no-fix="):
                for name in f.split("=", 1)[1].split(","):
                    if hasattr(repairs, name) and name != "compare_op":
                        setattr(repairs, name, False)
        if repairs.compare_op not in COMPARE_OPS:
            print("--op must be one of: " + " ".join(COMPARE_OPS), file=sys.stderr)
            return 2
        return run_console(args[0], "--run" in flags, "--no-opt" not in flags, strategy, "--compare" in flags, repairs)
    try:
        from minilang.gui import launch
    except ImportError:
        print("Tkinter is not installed. On Ubuntu/Debian run:  sudo apt install python3-tk", file=sys.stderr)
        return 2
    try:
        launch()
    except Exception as exc:        # e.g. tkinter.TclError when there is no display
        print(f"Could not open the window: {exc}\nYou can still compile in the console: "
              "python main.py file.ml", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
