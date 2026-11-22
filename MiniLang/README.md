# MiniLang Compiler Workbench

A small educational compiler with a desktop GUI, written in **Python 3.8+** with **Tkinter** and the `re` module.
No packages to install (Tkinter ships with Python on Windows and macOS; Ubuntu/Debian: `sudo apt install python3-tk`).

**Lexical -> Syntax (AST) -> Semantic (symbol table) -> Three-address code -> Optimizer -> Flow graph -> Run / debug**

## Run it

```powershell
python main.py                                  # opens the workbench
python main.py samples\03_if_else.ml --run      # console: compile + run
python main.py samples\07_optimizer_demo.ml --no-opt
python main.py samples\12_errors_recovery_demo.ml --compare          # compare error-handling strategies
python main.py samples\12_errors_recovery_demo.ml --strategy=panic    # stop | panic | phrase
python -m unittest discover -s tests -v         # 100 tests
```
(On Linux/macOS use `python3`.) In the window: **F5** compile, **Ctrl+O** open, **Ctrl+S** save.

## The workbench - one page per stage

| Page | What it shows |
|------|---------------|
| **Tokens** | every token with line / column, colored by category |
| **Syntax tree** | the AST drawn as an animated tree. Click a node to highlight its source line, double-click to fold a subtree, wheel to zoom, drag to pan, play / scrub the build, export SVG or JSON. Operators, literals and variables show their inferred type |
| **Symbol table** | name, type, declaration line, scope depth, whether it has a value, number of uses |
| **Intermediate code** | original and optimized three-address code side by side, plus what the optimizer did |
| **Flow graph** | basic blocks and edges (green = true, red = false); toggle original / optimized. While you debug, the running block glows and every block shows how many times it ran (`x3`) |
| **Run & debug** | **Run** the program, **Step** one instruction at a time with the current line highlighted, watch variables (the ones the last step changed flash) and output |
| **Recovery** | compares the three error-handling strategies on your program and replays what the chosen one did to the tokens (see below) |
| **Errors** | every error with stage, line, column, message and what the parser did about it; click for the source line with a `^`, double-click to jump to it |

The dot next to each stage is **green** (passed), **red** (failed) or **dark** (skipped because an earlier stage failed).
Also: syntax-colored editor with line numbers, red lines for errors, a **Samples** menu (13 programs), **Live compile**.

### Themes and tree animation
* **4 themes** - *Obsidian* (shiny black + gold, default), *Emerald* (black + green), *Ruby* (black + coral red), *Paper* (light). Click **Theme** at the bottom of the sidebar; your choice is remembered (`~/.minilang_theme`). The black themes give every tree node a soft neon glow.
* **Tree build animation** - plays automatically when you press F5 or load a sample. Nodes pop in one by one (parents first), edges grow from their parent with a bright head, and the caption shows what is being added. Use **Play / Pause**, the **speed buttons** (0.5x - 4x) and drag the **slider** to scrub forward and backward through the build.
* Syntax tree: **Fit**, zoom, **Expand / Collapse**, double-click a node to fold it, export as **SVG** or **JSON**.
* Editor: auto-indent after `{`, Tab = 4 spaces, **Ctrl +** / **Ctrl -** to change the font size, live `Ln / Col` display.
* Errors page shows the offending source line with a `^` under the exact column.
* Intermediate code: **Save code...** writes original + optimized code to a text file. **F6** = step the program.

## The language

```
// comment
int a = 10;                 float f = a * 2.5;          // int converts to float automatically
string s = "Mini" + "Lang"; bool ok = a > 5 && !(a == 7);
int b;                      b = (a + 5) * 2 - -1;
if (a >= 18) { print("adult"); } else { print("minor"); }
while (a > 0) { a = a - 3; }
{ int a = 1; }              // blocks have their own scope; inner names may shadow outer ones
print(f);
```
* Types `int float string bool`; operators `+ - * / %`, `< > <= >= == !=`, `&& || !`, unary `-`
* `int / int` truncates toward zero (like C); `&&` and `||` short-circuit
* A `float` can not be stored in an `int`; an `int` can be stored in a `float`
* Conditions of `if` / `while` must be `bool`

### Grammar
```
program    -> statement* EOF
statement  -> declaration | assignment | printStmt | ifStmt | whileStmt | block
declaration-> TYPE IDENT ("=" expression)? ";"
assignment -> IDENT "=" expression ";"
printStmt  -> "print" "(" expression ")" ";"
ifStmt     -> "if" "(" expression ")" statement ("else" statement)?
whileStmt  -> "while" "(" expression ")" statement
block      -> "{" statement* "}"
expression -> or ;  or -> and ("||" and)* ;  and -> equality ("&&" equality)*
equality   -> comparison (("=="|"!=") comparison)*
comparison -> term (("<"|">"|"<="|">=") term)*
term       -> factor (("+"|"-") factor)* ;  factor -> unary (("*"|"/"|"%") unary)*
unary      -> ("-"|"!") unary | primary
primary    -> INT | FLOAT | STRING | "true" | "false" | IDENT | "(" expression ")"
```

## Live website

`docs/` contains a browser version that runs the same compiler through Pyodide (see **DEPLOY.md** for GitHub Pages and
the submission checklist). Try it locally with `cd docs` then `python -m http.server 8000`.

## Error-handling strategies

The parser can react to a syntax error in three different ways. Pick one with the **Recovery** button in the sidebar
(or `--strategy=` on the command line). The **Recovery** page runs all three on your program side by side.

| Strategy | What it does | Good | Bad |
|----------|--------------|------|-----|
| **Stop at first error** | reports the first error and quits | simplest | you only ever see one problem |
| **Panic mode** | skips tokens until a safe point (`;`, `}` or a statement keyword), then continues | finds many errors, always terminates | the broken statement is lost, and skipped tokens can cause follow-up errors |
| **Phrase-level repair** (default, every repair can be switched off) | repairs locally: inserts a missing `;` `)` `(` `=`, deletes stray tokens, corrects misspelt keywords, reads `=` as `==` (and the reverse); falls back to panic mode when no local fix fits | the statement survives, fewer follow-up errors | a wrong guess can hide the real mistake |

**Phrase-level settings** (Recovery page, `--op=` / `--no-fix=` on the command line, and on the website):
tick which local repairs may be made (*fix keywords*, *insert ; ) ( =*, *delete stray ; ) }*, *fix = / ==*), and choose what an
`=` inside a condition becomes: **`==`, `!=`, `<=`, `>=`, `<` or `>`**. The error message lists all the options and the
log shows what was chosen (`read '=' as '<='`). A repair that is switched off falls back to panic mode for that error.

All three share these **error productions** (friendly messages for typical mistakes) and **"did you mean?"** suggestions:
`prnt(x)` -> *did you mean 'print'?*, `itn x` -> *did you mean 'int'?*, `if (a = 5)` -> *use '=='*, `a == 5;` -> *use '='*,
`int a 5;` -> *missing '='*, `print a;` -> *needs brackets*, `else` without `if`, `int a, b;` -> *no commas*,
`'x'` -> *strings use double quotes*, and for variables: `print(countr)` -> *did you mean 'counter'?*.
After 20 errors the compiler stops with a "too many errors" note so one mistake never buries you in messages.

Try **Samples > 12 Errors: recovery demo** and click the three cards on the Recovery page. In the animation:
green chips were read normally, a red ring marks the token where the error was found, struck-through red chips were
skipped by panic mode, dashed gold chips were inserted by phrase-level repair, and `prnt > print` chips were corrected.

## Errors that are detected (always with line and column)

| Stage | Examples |
|-------|----------|
| Lexical | invalid character, unterminated string, `9abc`, `1.2.3`, integer too large, bad escape |
| Syntax | missing `;` `)` `}`, `print a;`, missing value, keyword used as a name, stray `}` / `else` |
| Semantic | undeclared / redeclared variable, type mismatch, `string - string`, use before a value is set (understands `if` / `while` paths), division by constant zero, non-bool condition |

Several errors are reported in one run (the parser recovers after each one, see the strategies above). A later stage only runs if the earlier ones had no errors.

## Size limits and performance

Tested with generated programs: **500 lines compile in about 0.04 s, 10,000 lines in about 1.2 s**, and the window
stays responsive (500 lines load in under half a second; the Syntax tree, Flow graph and Recovery strip switch to a light
drawing mode on big programs and only draw what is on screen). Hard limits that give a clean error instead of a crash:

* nesting deeper than **150** levels (blocks, brackets, repeated `-` / `!`) -> *"nested too deeply"*
* more than **500** operators in one unbroken chain (`1 + 1 + 1 + ...`) -> *"expression too long"*
* a program that runs more than **200,000** instructions is stopped by the virtual machine (infinite-loop guard)

Very large trees (over 250 nodes) are shown at once instead of auto-animating; press **Play** to animate them anyway.

## Optimizer
Constant folding and propagation, algebraic simplification (`x+0`, `x*1`), branch folding (`if (true)`),
unreachable-code removal and dead-assignment removal. Tests check that optimized and original code always give the same output.

## Project layout
```
main.py                 entry point (GUI or console)
minilang/
  tokens.py lexer.py        lexical analysis (re module)
  ast_nodes.py parser.py    syntax analysis, AST, three error-handling strategies
  semantic.py               symbol table, scopes, type checking
  codegen.py optimizer.py   three-address code and optimizations
  cfg.py                    basic blocks / flow graph
  runtime.py interpreter.py shared value rules and the step-able virtual machine
  compiler.py errors.py     pipeline and error collection
  recovery.py               tokens + parser events -> display chips (desktop and web)
  samples.py gui.py         samples menu and the Tkinter workbench
docs/                    the website (index.html + bridge.py + a copy of minilang/), see DEPLOY.md
sync_web.py              copies minilang/ into docs/minilang/
tests/test_compiler.py   100 tests
samples/                 13 example programs (8 valid, 5 with errors)
```

## Make a Windows .exe (optional)
`build_exe.bat` (needs `pip install pyinstaller`) creates `dist\MiniLang.exe`.

## Ideas for later
functions, arrays, `for` loops, a `read()` input statement, register allocation, an x86 / bytecode back end, saving the AST as JSON.
