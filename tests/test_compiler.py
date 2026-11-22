import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minilang import ast_nodes as A
from minilang.cfg import build_cfg
from minilang.compiler import compare_strategies, compile_source
from minilang.errors import ErrorReporter
from minilang.parser import COMPARE_OPS, RepairOptions
from minilang.interpreter import Machine, run_program
from minilang.runtime import eval_binary
from minilang.samples import SAMPLES


def msgs(r):
    return [e.message for e in r.errors]


def output(src, optimize=True):
    r = compile_source(src, optimize)
    assert r.success, r.errors
    return run_program(r.optimized).output


class LexerTests(unittest.TestCase):
    def test_tokens_have_positions(self):
        r = compile_source("int a = 10;\n  a = 2;")
        a2 = [t for t in r.tokens if t.lexeme == "a"][1]
        self.assertEqual((a2.line, a2.column), (2, 3))

    def test_comments_ignored(self):
        self.assertTrue(compile_source("// hi\nint a = 1; // x\n").success)

    def test_invalid_character(self):
        r = compile_source("int a = 1 # 2;")
        self.assertIn("invalid character '#'", msgs(r))
        self.assertEqual(r.stages["lexical"], "fail")
        self.assertEqual(r.stages["syntax"], "skipped")

    def test_unterminated_string(self):
        self.assertIn("unterminated string literal", msgs(compile_source('string s = "abc;')))

    def test_malformed_numbers(self):
        self.assertIn("malformed number '9abc'", msgs(compile_source("int a = 9abc;")))
        self.assertIn("malformed number '1.2.3'", msgs(compile_source("float a = 1.2.3;")))

    def test_integer_too_large(self):
        self.assertTrue(any("too large" in m for m in msgs(compile_source("int a = 99999999999;"))))

    def test_bad_escape(self):
        self.assertTrue(any("escape" in m for m in msgs(compile_source(r'string s = "a\qb";'))))

    def test_string_escapes_decoded(self):
        self.assertEqual(output(r'print("a\tb\n");'), ["a\tb\n"])


class ParserTests(unittest.TestCase):
    def test_precedence(self):
        r = compile_source("int a = 1 + 2 * 3;")
        init = r.ast.statements[0].init
        self.assertEqual(init.op, "+")
        self.assertEqual(init.right.op, "*")

    def test_left_associative(self):
        init = compile_source("int a = 10 - 3 - 2;").ast.statements[0].init
        self.assertEqual(init.left.op, "-")

    def test_structure(self):
        r = compile_source("int a = 1; if (a > 0) { print(a); } else print(0); while (a < 3) a = a + 1;")
        kinds = [type(s).__name__ for s in r.ast.statements]
        self.assertEqual(kinds, ["VarDecl", "If", "While"])
        self.assertIsNotNone(r.ast.statements[1].otherwise)

    def test_missing_semicolon(self):
        r = compile_source("int a = 5\nint b = 6;")
        self.assertEqual(msgs(r)[0], "expected ';' but found 'int'")
        self.assertEqual((r.errors[0].line, r.errors[0].column), (1, 10))

    def test_print_without_brackets(self):
        self.assertTrue(any("'(' after 'print'" in m for m in msgs(compile_source("int a=1; print a;"))))

    def test_missing_value(self):
        self.assertTrue(any("expected an expression" in m for m in msgs(compile_source("int a = ;"))))

    def test_keyword_as_name(self):
        self.assertTrue(any("keyword" in m for m in msgs(compile_source("int print = 3;"))))

    def test_unclosed_block(self):
        self.assertTrue(any("'}'" in m for m in msgs(compile_source("{ int a = 1;"))))

    def test_stray_closing_brace_does_not_hang(self):
        self.assertFalse(compile_source("}").success)

    def test_recovery_reports_several_errors(self):
        r = compile_source("int a = ;\nint b = ;\nint c = 3;")
        self.assertEqual(len(r.errors), 2)
        self.assertEqual(len(r.ast.statements), 1)           # the valid statement survives

    def test_partial_tree_kept_on_syntax_error(self):
        r = compile_source("int a = 1;\nint b = ;")
        self.assertIsNotNone(r.ast)
        self.assertEqual(r.stages["syntax"], "fail")
        self.assertEqual(r.stages["semantic"], "skipped")

    def test_else_without_if(self):
        self.assertFalse(compile_source("else print(1);").success)


class SemanticTests(unittest.TestCase):
    def test_valid_program(self):
        r = compile_source("int a = 1; float f = a * 2.5; print(f);")
        self.assertTrue(r.success)
        self.assertEqual(len(r.symbols.all()), 2)
        self.assertEqual(r.symbols.all()[0].uses, 1)

    def test_undeclared(self):
        self.assertIn("undeclared variable 'x'", msgs(compile_source("print(x);")))

    def test_redeclaration(self):
        self.assertTrue(any("already declared" in m for m in msgs(compile_source("int a; int a;"))))

    def test_float_into_int(self):
        self.assertTrue(any("float in the int" in m for m in msgs(compile_source("int a = 2.5;"))))

    def test_int_into_float_is_fine(self):
        self.assertTrue(compile_source("float a = 2;").success)

    def test_string_minus_string(self):
        self.assertTrue(any("cannot be applied" in m for m in msgs(compile_source('string s = "a" - "b";'))))

    def test_use_before_value(self):
        self.assertTrue(any("before it has a value" in m for m in msgs(compile_source("int a; print(a);"))))

    def test_division_by_zero_constant(self):
        self.assertIn("division by zero", msgs(compile_source("int a = 1 / 0;")))

    def test_condition_must_be_bool(self):
        self.assertTrue(any("must be bool" in m for m in msgs(compile_source("int a = 1; if (a) print(a);"))))

    def test_value_set_in_only_one_branch_is_not_certain(self):
        r = compile_source("int a; bool c = true; if (c) { a = 1; } print(a);")
        self.assertTrue(any("before it has a value" in m for m in msgs(r)))

    def test_value_set_in_both_branches_is_certain(self):
        self.assertTrue(compile_source("int a; bool c = true; if (c) { a = 1; } else { a = 2; } print(a);").success)

    def test_scope_ends_with_block(self):
        self.assertIn("undeclared variable 'x'", msgs(compile_source("{ int x = 1; } print(x);")))

    def test_shadowing_allowed(self):
        self.assertTrue(compile_source("int x = 1; { int x = 2; print(x); } print(x);").success)

    def test_types_annotated_on_tree(self):
        r = compile_source("float f = 1 + 2.5;")
        self.assertEqual(r.ast.statements[0].init.dtype, A.DataType.FLOAT)

    def test_errors_in_one_run(self):
        r = compile_source("int a = 2.5; print(zzz); int a;")
        self.assertGreaterEqual(len(r.errors), 3)


class CodegenAndRunTests(unittest.TestCase):
    def test_three_address_code(self):
        r = compile_source("int a = 10; int b = 20; int sum = a + b; print(sum);", False)
        self.assertEqual(r.intermediate_code, ["a = 10", "b = 20", "t1 = a + b", "sum = t1", "print sum"])

    def test_arithmetic(self):
        self.assertEqual(output("int b = (10 + 5) * 2 - -1; print(b);"), ["31"])

    def test_int_division_truncates_like_c(self):
        self.assertEqual(output("print(7 / 2); print(-7 / 2); print(-7 % 3);"), ["3", "-3", "-1"])

    def test_float_conversion(self):
        self.assertEqual(output("float f = 5; print(f); float g = 10 * 2.5; print(g / 4);"), ["5.0", "6.25"])

    def test_string_concat(self):
        self.assertEqual(output('print("Mini" + "Lang");'), ["MiniLang"])

    def test_bool_and_comparison(self):
        self.assertEqual(output("print(1 < 2 && 3 >= 3); print(!(1 == 2));"), ["true", "true"])

    def test_short_circuit(self):
        # the right side would divide by zero if it were evaluated
        src = "int z = 0; bool ok = false && 1 / z == 1; print(ok);"
        self.assertEqual(output(src, optimize=False), ["false"])

    def test_if_else(self):
        self.assertEqual(output("int a = 3; if (a > 5) print(1); else print(2);"), ["2"])

    def test_while_loop(self):
        self.assertEqual(output("int i = 0; int s = 0; while (i < 5) { i = i + 1; s = s + i; } print(s);"), ["15"])

    def test_scopes_run_correctly(self):
        self.assertEqual(output("int x = 1; { int x = 2; print(x); } print(x);"), ["2", "1"])

    def test_runtime_division_by_zero(self):
        r = compile_source("int a = 0; int b = 5 / a; print(b);", False)
        self.assertTrue(r.success)
        self.assertIn("division by zero", run_program(r.instructions).error)

    def test_infinite_loop_is_stopped(self):
        r = compile_source("while (true) { }", False)
        res = run_program(r.instructions, max_steps=500)
        self.assertIn("infinite loop", res.error)

    def test_stepping(self):
        r = compile_source("int a = 1; a = a + 1; print(a);", False)
        m = Machine(r.instructions)
        while m.step():
            pass
        self.assertEqual(m.output, ["2"])
        m.reset()
        self.assertEqual((m.pc, m.output), (0, []))


class OptimizerTests(unittest.TestCase):
    def test_constant_folding_and_propagation(self):
        r = compile_source("int a = 2 * 3 + 4; print(a);")
        self.assertEqual(r.optimized_code, ["print 10"])

    def test_dead_branch_removed(self):
        r = compile_source('if (true) { print(1); } else { print("never"); }')
        self.assertEqual(r.optimized_code, ["print 1"])

    def test_algebraic_identities(self):
        r = compile_source("int x = 7; int y = x * 1 + 0; print(y);")
        self.assertEqual(run_program(r.optimized).output, ["7"])

    def test_loop_not_folded_wrongly(self):
        r = compile_source("int i = 0; while (i < 3) { i = i + 1; } print(i);")
        self.assertEqual(run_program(r.optimized).output, ["3"])
        self.assertTrue(any(c.endswith(":") for c in r.optimized_code))

    def test_same_output_before_and_after_for_all_valid_samples(self):
        for name, src in SAMPLES:
            r = compile_source(src)
            if r.success:
                self.assertEqual(run_program(r.instructions).output, run_program(r.optimized).output, name)
                self.assertLessEqual(len(r.optimized), len(r.instructions), name)

    def test_folding_division_by_zero_is_left_for_runtime(self):
        self.assertEqual(eval_binary("+", 1, 2), 3)
        with self.assertRaises(ZeroDivisionError):
            eval_binary("/", 1, 0)

    def test_stats(self):
        r = compile_source("int a = 1 + 2; print(a);")
        self.assertGreater(r.opt_stats["folded"], 0)


class CfgTests(unittest.TestCase):
    def test_if_else_graph(self):
        r = compile_source("int a = 1; bool c = a > 0; if (c) print(1); else print(2); print(3);", False)
        blocks = build_cfg(r.instructions)
        self.assertGreaterEqual(len(blocks), 4)
        first = blocks[0]
        self.assertEqual({k for _, k in first.succ}, {"true", "false"})

    def test_loop_has_back_edge(self):
        r = compile_source("int i = 0; while (i < 3) { i = i + 1; }", False)
        blocks = build_cfg(r.instructions)
        self.assertTrue(any(t < b.id for b in blocks for t, _ in b.succ))

    def test_empty_program(self):
        self.assertEqual(compile_source("").cfg, [])


class SampleTests(unittest.TestCase):
    def test_valid_samples_compile_and_run(self):
        for name, src in SAMPLES:
            if "Errors" in name:
                continue
            r = compile_source(src)
            self.assertTrue(r.success, f"{name}: {r.errors}")
            self.assertIsNone(run_program(r.optimized).error, name)

    def test_error_samples_fail_at_the_expected_stage(self):
        expected = {"09": "Lexical", "10": "Syntax", "11": "Semantic", "12": "Syntax", "13": "Semantic"}
        for name, src in SAMPLES:
            if name[:2] in expected:
                r = compile_source(src)
                self.assertFalse(r.success)
                self.assertEqual({e.stage for e in r.errors}, {expected[name[:2]]}, name)
                self.assertGreaterEqual(len(r.errors), 3, name)

    def test_known_outputs(self):
        outs = {n[:2]: run_program(compile_source(s).optimized).output for n, s in SAMPLES if "Errors" not in n}
        self.assertEqual(outs["04"], ["720"])
        self.assertEqual(outs["05"], ["0", "1", "1", "2", "3", "5", "8", "13", "21", "34"])
        self.assertEqual(outs["08"], ["111"])
        self.assertEqual(outs["06"], ["2", "1"])




class ErrorStrategyTests(unittest.TestCase):
    MESSY = "int a = 5\nprint a;\nint = 3;\nint c = ;\nif (a > 1 {\n    print(a);\n}\n"

    def test_stop_reports_only_the_first_error(self):
        r = compile_source(self.MESSY, strategy="stop")
        self.assertEqual(len(r.errors), 1)
        self.assertTrue(any(e.kind == "halt" for e in r.recovery))

    def test_panic_finds_more_errors_than_stop(self):
        stop = compile_source(self.MESSY, strategy="stop")
        panic = compile_source(self.MESSY, strategy="panic")
        self.assertGreater(len(panic.errors), len(stop.errors))
        self.assertTrue(any(e.kind == "skip" for e in panic.recovery))

    def test_phrase_repairs_keep_more_of_the_program(self):
        res = {x.key: x for x in compare_strategies(self.MESSY)}
        self.assertGreater(res["phrase"].statements, res["panic"].statements)
        self.assertGreater(res["phrase"].inserted, 0)
        self.assertEqual(res["stop"].inserted + res["stop"].skipped, 0)

    def test_phrase_inserts_missing_semicolon_and_keeps_the_statement(self):
        r = compile_source("int a = 5\nint b = 6;", strategy="phrase")
        self.assertEqual(len(r.errors), 1)
        self.assertEqual(len(r.ast.statements), 2)
        self.assertIn("inserted ';'", r.fixes[(r.errors[0].line, r.errors[0].column, r.errors[0].message)])

    def test_panic_drops_the_broken_statement(self):
        r = compile_source("int a = 5\nint b = 6;", strategy="panic")
        self.assertEqual(len(r.errors), 1)

    def test_phrase_inserts_missing_closing_paren(self):
        r = compile_source("int a = 1; if (a > 0 { print(a); }", strategy="phrase")
        self.assertEqual(len(r.errors), 1)
        self.assertEqual(type(r.ast.statements[1]).__name__, "If")

    def test_phrase_deletes_stray_tokens(self):
        r = compile_source("int a = 1;;\n)\nprint(a);", strategy="phrase")
        self.assertEqual(len(r.errors), 2)
        self.assertEqual(len(r.ast.statements), 2)

    def test_error_production_assignment_in_condition(self):
        r = compile_source("int a = 1; if (a = 2) print(a);")
        self.assertTrue(any("did you mean '=='" in e.message for e in r.errors))
        self.assertEqual(r.ast.statements[1].cond.op, "==")          # repaired in the tree

    def test_error_production_equality_as_assignment(self):
        r = compile_source("int a = 1; a == 2;")
        self.assertTrue(any("did you mean '='" in e.message for e in r.errors))

    def test_error_production_missing_equals_in_declaration(self):
        r = compile_source("int a 5;")
        self.assertTrue(any("is the '=' missing" in e.message for e in r.errors))
        self.assertEqual(r.ast.statements[0].init.value, 5)

    def test_error_production_else_without_if(self):
        self.assertTrue(any("without a matching 'if'" in e.message for e in compile_source("else print(1);").errors))

    def test_misspelt_keyword_suggestion_and_repair(self):
        r = compile_source("prnt(1);\nitn x = 3;")
        msgs_ = [e.message for e in r.errors]
        self.assertIn("unknown word 'prnt' - did you mean 'print'?", msgs_)
        self.assertIn("unknown word 'itn' - did you mean 'int'?", msgs_)
        self.assertEqual([type(s).__name__ for s in r.ast.statements], ["Print", "VarDecl"])
        self.assertTrue(any(e.kind == "replace" for e in r.recovery))
        self.assertIn("read 'prnt' as 'print'", list(r.fixes.values()))

    def test_misspelt_keyword_is_not_repaired_in_panic_mode(self):
        r = compile_source("prnt(1);", strategy="panic")
        self.assertEqual(len(r.ast.statements), 0)

    def test_normal_assignments_are_not_flagged_as_typos(self):
        self.assertTrue(compile_source("int i = 0; i = 1; int count = 2; count = 3;").success)

    def test_semantic_did_you_mean(self):
        r = compile_source("int counter = 1; print(countr);")
        self.assertIn("undeclared variable 'countr' - did you mean 'counter'?", [e.message for e in r.errors])

    def test_lexer_hints(self):
        self.assertTrue(any("own statement" in e.message for e in compile_source("int a, b;").errors))
        self.assertTrue(any("double quotes" in e.message for e in compile_source("string s = 'x';").errors))

    def test_error_limit(self):
        rep = ErrorReporter(limit=3)
        for i in range(10):
            rep.add("Syntax", f"e{i}", i + 1, 1)
        self.assertEqual(len(rep.errors), 4)
        self.assertIn("too many errors", rep.errors[-1].message)
        r = compile_source("int a = ;\n" * 40)
        self.assertEqual(len(r.errors), 21)

    def test_all_strategies_terminate_on_garbage(self):
        junk = "}{ ) ( ; ; = == else while if print int 5 \"x\" + - * / ) ) } {"
        for s in ("stop", "panic", "phrase"):
            compile_source(junk, strategy=s)

    def test_every_error_has_a_recovery_event(self):
        r = compile_source(self.MESSY)
        self.assertEqual(sum(1 for e in r.recovery if e.kind == "error"), len(r.errors))

    def test_comparison_needs_no_lexical_errors(self):
        self.assertIsNone(compare_strategies("int a = 5 # 3;"))
        self.assertEqual(len(compare_strategies("int a = ;")), 3)

    def test_valid_programs_have_no_events(self):
        r = compile_source("int a = 1; print(a);")
        self.assertEqual(r.recovery, [])



class ScaleTests(unittest.TestCase):
    """Big programs and deep nesting must never crash the compiler."""

    def test_500_line_program(self):
        lines = [f"int v{i} = {i} * 2;" for i in range(250)] + [f"print(v{i});" for i in range(250)]
        r = compile_source("\n".join(lines))
        self.assertTrue(r.success)
        out = run_program(r.optimized).output
        self.assertEqual((len(out), out[10]), (250, "20"))

    def test_500_lines_with_loops_and_ifs(self):
        block = "int @ = 0;\nwhile (@ < 3) {\n    if (@ == 1) {\n        print(@);\n    }\n    @ = @ + 1;\n}\n"
        src = "".join(block.replace("@", f"i{k}") for k in range(80))       # 560 lines
        r = compile_source(src)
        self.assertTrue(r.success)
        self.assertEqual(run_program(r.optimized).output, ["1"] * 80)

    def test_big_program_is_fast(self):
        import time
        src = "".join(f"int a{i} = {i} + 1;\nprint(a{i});\n" for i in range(1500))     # 3000 lines
        t = time.time()
        r = compile_source(src)
        self.assertTrue(r.success)
        self.assertLess(time.time() - t, 5.0)

    def test_broken_big_program_terminates_with_few_errors(self):
        lines = [f"int a{i} = {i};" if i % 7 else "int = ;" for i in range(600)]
        for strategy in ("stop", "panic", "phrase"):
            r = compile_source("\n".join(lines), strategy=strategy)
            self.assertFalse(r.success)
            self.assertLessEqual(len(r.errors), 21)                         # 20 + the "too many errors" note

    def test_deep_brackets_give_a_clean_error(self):
        r = compile_source("int a = " + "(" * 200 + "1" + ")" * 200 + ";")
        self.assertFalse(r.success)
        self.assertTrue(any("nested too deeply" in e.message for e in r.errors))

    def test_moderate_nesting_is_fine(self):
        self.assertTrue(compile_source("int a = " + "(" * 40 + "1" + ")" * 40 + ";").success)
        self.assertTrue(compile_source("{" * 100 + "print(1);" + "}" * 100).success)

    def test_deep_blocks_give_a_clean_error(self):
        r = compile_source("{" * 400 + "}" * 400)
        self.assertTrue(any("nested too deeply" in e.message for e in r.errors))

    def test_very_long_expression(self):
        r = compile_source("int a = " + " + ".join(["1"] * 400) + ";\nprint(a);")
        self.assertTrue(r.success)
        self.assertEqual(run_program(r.optimized).output, ["400"])
        r = compile_source("int a = " + " + ".join(["1"] * 1500) + ";")
        self.assertTrue(any("expression too long" in e.message for e in r.errors))

    def test_long_unary_chain(self):
        r = compile_source("int a = " + "-" * 1000 + "1;")
        self.assertTrue(any("nested too deeply" in e.message for e in r.errors))

    def test_empty_and_comment_only_files(self):
        for src in ("", "// nothing\n" * 300, "\n\n\n"):
            r = compile_source(src)
            self.assertTrue(r.success)
            self.assertEqual(run_program(r.optimized).output, [])
            self.assertEqual(compare_strategies(src) is not None, True)

    def test_one_very_long_line(self):
        r = compile_source("int a = 1; " * 3000)
        self.assertFalse(r.success)                                         # redeclaration, but no crash
        self.assertLessEqual(len(r.errors), 21)



class RepairOptionTests(unittest.TestCase):
    SRC = "int a = 1;\nif (a = 2) print(a);\nprnt(a);\nint b = 5\n"

    def test_operator_choice_for_equals_in_a_condition(self):
        for op in COMPARE_OPS:
            r = compile_source("int a = 1; if (a = 2) print(a);", repairs=RepairOptions(compare_op=op))
            self.assertEqual(r.ast.statements[1].cond.op, op)
            self.assertIn(f"read '=' as '{op}'", list(r.fixes.values()))
            self.assertTrue(any(f"did you mean '{op}'?" in e.message for e in r.errors))

    def test_message_lists_all_operator_options(self):
        r = compile_source("int a = 1; if (a = 2) print(a);")
        msg = next(e.message for e in r.errors)
        for op in ("'=='", "'!='", "'<='", "'>='", "'<'", "'>'"):
            self.assertIn(op, msg)

    def test_unknown_operator_falls_back_to_equality(self):
        r = compile_source("int a = 1; if (a = 2) print(a);", repairs=RepairOptions(compare_op="??"))
        self.assertEqual(r.ast.statements[1].cond.op, "==")

    def test_each_repair_can_be_switched_off(self):
        full = compile_source(self.SRC)
        self.assertEqual(len(full.ast.statements), 4)
        no_kw = compile_source(self.SRC, repairs=RepairOptions(keywords=False))
        self.assertEqual(len(no_kw.ast.statements), 3)                    # 'prnt(a);' is dropped instead of repaired
        no_ins = compile_source(self.SRC, repairs=RepairOptions(insert=False))
        self.assertEqual(len(no_ins.ast.statements), 3)                   # 'int b = 5' without ';' is dropped
        no_op = compile_source(self.SRC, repairs=RepairOptions(operators=False))
        kinds = lambda r: [type(x).__name__ for x in r.ast.statements]
        self.assertIn("If", kinds(full))
        self.assertNotIn("If", kinds(no_op))                                # the broken 'if' is dropped
        none = compile_source(self.SRC, repairs=RepairOptions(False, False, False, False))
        self.assertEqual(len(none.ast.statements), 2)

    def test_options_only_apply_to_phrase_level(self):
        a = compile_source(self.SRC, strategy="panic", repairs=RepairOptions())
        b = compile_source(self.SRC, strategy="panic", repairs=RepairOptions(False, False, False, False))
        self.assertEqual([e.message for e in a.errors], [e.message for e in b.errors])

    def test_comparison_uses_the_options(self):
        res = {x.key: x for x in compare_strategies(self.SRC, RepairOptions(False, False, False, False))}
        self.assertEqual(res["phrase"].inserted + res["phrase"].replaced, 0)

    def test_stray_tokens_deleted_only_when_allowed(self):
        on = compile_source("int a = 1;;\nprint(a);")
        off = compile_source("int a = 1;;\nprint(a);", repairs=RepairOptions(delete=False))
        self.assertTrue(any(e.kind == "delete" for e in on.recovery))
        self.assertFalse(any(e.kind == "delete" for e in off.recovery))


if __name__ == "__main__":
    unittest.main()
