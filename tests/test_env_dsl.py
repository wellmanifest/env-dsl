import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from env_dsl_check import (
    EXPRESSION,
    LAYER,
    SECURITY,
    SEMANTIC,
    SYNTAX,
    ExpressionError,
    ExpressionNode,
    evaluate_constants,
    evaluate_node,
    merge_documents,
    parse_file,
    parse_text,
)

ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "examples" / "valid" / "dsl-check.env"
STRATEGIES = ROOT / "examples" / "valid" / "subllm-credential-strategies.env"
INVALID = ROOT / "examples" / "invalid" / "nonportable.env"


class EnvDslTests(unittest.TestCase):
    def test_reference_example_is_valid_inert_data(self) -> None:
        for example_path in (VALID, STRATEGIES):
            document, diagnostics = parse_file(example_path)
            self.assertEqual([], diagnostics, example_path.name)
            self.assertIsNotNone(document)
        document, _ = parse_file(VALID)
        assert document is not None
        self.assertIn("DIGEST_PATTERN", document.constants)
        evaluated, expression_diagnostics = evaluate_constants(
            document.constants,
            {
                "ENV_DSL_VERSION": document.version,
                "ENV_DSL_NAMESPACE": document.namespace,
                "ENV_DSL_ENVIRONMENT": document.environment,
            },
        )
        self.assertEqual([], expression_diagnostics)
        self.assertEqual(2, evaluated["NEXT_MAJOR_EXPRESSION"])
        self.assertIs(True, evaluated["BASE_SCHEMA_CONDITION"])
        self.assertNotIn("re." + "compile(", VALID.read_text(encoding="utf-8"))

    def test_invalid_fixture_covers_required_boundaries(self) -> None:
        _, diagnostics = parse_file(INVALID)
        codes = {item.code for item in diagnostics}
        self.assertEqual({SYNTAX, SEMANTIC, EXPRESSION, SECURITY}, codes)
        messages = "\n".join(item.message for item in diagnostics)
        self.assertIn("duplicate", messages)
        self.assertIn("interpolation", messages)
        self.assertIn("constructors", messages)

    def test_operator_precedence_and_typed_results_are_deterministic(self) -> None:
        values = {
            "BASE_VALUE": "4",
            "RESULT_EXPRESSION": "@BASE_VALUE+2*3",
            "READY_CONDITION": "@RESULT_EXPRESSION==10&&!FALSE",
        }
        evaluated, diagnostics = evaluate_constants(values)
        self.assertEqual([], diagnostics)
        self.assertEqual(10, evaluated["RESULT_EXPRESSION"])
        self.assertIs(True, evaluated["READY_CONDITION"])

    def test_equations_reject_undefined_references_and_cycles(self) -> None:
        undefined, undefined_diagnostics = evaluate_constants(
            {"BROKEN_CONDITION": "FALSE&&@MISSING==1"}
        )
        self.assertEqual({}, undefined)
        self.assertTrue(any(item.code == EXPRESSION for item in undefined_diagnostics))
        cyclic, cycle_diagnostics = evaluate_constants(
            {
                "LEFT_EXPRESSION": "@RIGHT_EXPRESSION+1",
                "RIGHT_EXPRESSION": "@LEFT_EXPRESSION+1",
            }
        )
        self.assertEqual({}, cyclic)
        self.assertTrue(any("cyclic" in item.message for item in cycle_diagnostics))

    def test_condition_must_return_boolean_and_arithmetic_requires_integers(
        self,
    ) -> None:
        _, condition_diagnostics = evaluate_constants({"COUNT_CONDITION": "1+2"})
        self.assertTrue(
            any(
                "must produce boolean" in item.message for item in condition_diagnostics
            )
        )
        _, type_diagnostics = evaluate_constants(
            {"TEXT_VALUE": "TEXT", "BAD_EXPRESSION": "@TEXT_VALUE+1"}
        )
        self.assertTrue(
            any("requires int" in item.message for item in type_diagnostics)
        )

    def test_division_remainder_and_string_order_have_portable_semantics(self) -> None:
        evaluated, diagnostics = evaluate_constants(
            {
                "QUOTIENT_EXPRESSION": "-7/3",
                "REMAINDER_EXPRESSION": "-7%3",
                "ORDER_CONDITION": ":ALPHA<:BETA",
            }
        )
        self.assertEqual([], diagnostics)
        self.assertEqual(-2, evaluated["QUOTIENT_EXPRESSION"])
        self.assertEqual(-1, evaluated["REMAINDER_EXPRESSION"])
        self.assertIs(True, evaluated["ORDER_CONDITION"])

    def test_regex_end_anchor_is_data_not_interpolation(self) -> None:
        text = (
            "ENV_DSL_VERSION=1\n"
            "ENV_DSL_NAMESPACE=REGEX_TEST\n"
            "ENV_DSL_ENVIRONMENT=BASE\n"
            "END_ANCHORED_PATTERN=^[A-Z]+$\n"
        )
        document, diagnostics = parse_text(text)
        assert document is not None
        self.assertEqual([], diagnostics)
        self.assertEqual("^[A-Z]+$", document.constants["END_ANCHORED_PATTERN"])

    def test_non_base_requires_explicit_parent(self) -> None:
        text = (
            "ENV_DSL_VERSION=1\n"
            "ENV_DSL_NAMESPACE=LAYER_TEST\n"
            "ENV_DSL_ENVIRONMENT=DEV\n"
            "VALUE=two\n"
        )
        _, diagnostics = parse_text(text)
        self.assertTrue(any(item.code == SEMANTIC for item in diagnostics))

    def test_layers_are_ordered_and_last_layer_wins(self) -> None:
        base, base_diagnostics = parse_text(
            "ENV_DSL_VERSION=1\n"
            "ENV_DSL_NAMESPACE=LAYER_TEST\n"
            "ENV_DSL_ENVIRONMENT=BASE\n"
            "COLOR=blue\n",
            "base.env",
        )
        dev, dev_diagnostics = parse_text(
            "ENV_DSL_VERSION=1\n"
            "ENV_DSL_NAMESPACE=LAYER_TEST\n"
            "ENV_DSL_ENVIRONMENT=DEV\n"
            "ENV_DSL_EXTENDS=BASE\n"
            "COLOR=green\n"
            "LOG_LEVEL=debug\n",
            "dev.env",
        )
        assert base is not None and dev is not None
        self.assertEqual([], base_diagnostics + dev_diagnostics)
        merged, diagnostics = merge_documents([base, dev])
        self.assertEqual([], diagnostics)
        self.assertEqual({"COLOR": "green", "LOG_LEVEL": "debug"}, merged)

    def test_equations_resolve_only_after_layer_overrides(self) -> None:
        base, _ = parse_text(
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=EQUATION_LAYER\n"
            "ENV_DSL_ENVIRONMENT=BASE\nLIMIT=2\n"
            "DOUBLE_EXPRESSION=@LIMIT*2\n",
            "base.env",
        )
        prod, _ = parse_text(
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=EQUATION_LAYER\n"
            "ENV_DSL_ENVIRONMENT=PROD\nENV_DSL_EXTENDS=BASE\nLIMIT=5\n",
            "prod.env",
        )
        assert base is not None and prod is not None
        merged, layer_diagnostics = merge_documents([base, prod])
        evaluated, expression_diagnostics = evaluate_constants(
            merged,
            {
                "ENV_DSL_VERSION": "1",
                "ENV_DSL_NAMESPACE": "EQUATION_LAYER",
                "ENV_DSL_ENVIRONMENT": "PROD",
                "ENV_DSL_EXTENDS": "BASE",
            },
        )
        self.assertEqual([], layer_diagnostics + expression_diagnostics)
        self.assertEqual(10, evaluated["DOUBLE_EXPRESSION"])

    def test_layer_chain_rejects_implicit_parent(self) -> None:
        base, _ = parse_text(
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=CHAIN\n"
            "ENV_DSL_ENVIRONMENT=BASE\nVALUE=one\n",
            "base.env",
        )
        prod, _ = parse_text(
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=CHAIN\n"
            "ENV_DSL_ENVIRONMENT=PROD\nENV_DSL_EXTENDS=STAGING\nVALUE=two\n",
            "prod.env",
        )
        assert base is not None and prod is not None
        _, diagnostics = merge_documents([base, prod])
        self.assertTrue(any(item.code == LAYER for item in diagnostics))

    def test_quotes_and_missing_final_lf_are_rejected(self) -> None:
        text = (
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=STRICT\n"
            'ENV_DSL_ENVIRONMENT=BASE\nQUOTED="value"'
        )
        _, diagnostics = parse_text(text)
        self.assertTrue(any(item.code == SYNTAX for item in diagnostics))
        self.assertTrue(any(item.code == SEMANTIC for item in diagnostics))

    def test_string_atom_enforces_abnf_charset_and_depth_bound(self) -> None:
        for invalid_atom in (":hello world", ':"quoted"', ":back`tick"):
            _, diagnostics = evaluate_constants(
                {"BAD_CONDITION": f"{invalid_atom}==:ok"}
            )
            self.assertTrue(
                any(item.code == EXPRESSION for item in diagnostics), invalid_atom
            )

        deep = "(" * 80 + "1" + ")" * 80
        _, depth_diagnostics = evaluate_constants({"DEEP_EXPRESSION": deep})
        self.assertTrue(
            any("maximum depth" in item.message for item in depth_diagnostics)
        )

        deep_unary = "!" * 80 + "TRUE"
        _, unary_diagnostics = evaluate_constants({"UNARY_CONDITION": deep_unary})
        self.assertTrue(
            any("maximum depth" in item.message for item in unary_diagnostics)
        )

    def test_positional_shell_interpolation_and_extended_secrets_rejected(self) -> None:
        for shell_val in ("arg=$1", "pid=$$", "all=$@"):
            text = (
                "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SHELL\n"
                f"ENV_DSL_ENVIRONMENT=BASE\nARG_VALUE={shell_val}\n"
            )
            _, diagnostics = parse_text(text)
            self.assertTrue(
                any(item.code == SEMANTIC for item in diagnostics), shell_val
            )

        embedded_secrets = (
            "AS" + "IA1234567890ABCDEF",
            "gl" + "pat-abcdef123456",
            "xox" + "b-12345-abcdef",
            "https://api.example.com?auth=" + "gh" + "o_1234567890abcdef",
            "postgres://svc:s3cr3t@db.internal:5432/app",
            "redis://:s3cr3t@cache.internal:6379/0",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlMTIz",
        )
        for tok in embedded_secrets:
            text = (
                "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SEC\n"
                f"ENV_DSL_ENVIRONMENT=BASE\nPUBLIC_VALUE={tok}\n"
            )
            _, diagnostics = parse_text(text)
            self.assertTrue(any(item.code == SECURITY for item in diagnostics), tok)

        safe_ssh = (
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SEC\n"
            "ENV_DSL_ENVIRONMENT=BASE\nREPO_URI=ssh://git@github.com/wellmanifest/env-dsl\n"
        )
        _, ssh_diags = parse_text(safe_ssh)
        self.assertEqual([], ssh_diags)

    def test_module_line_budgets_symlinks_deep_chains_and_integer_bounds(self) -> None:
        for mod_name in (
            "env_dsl_check.py",
            "env_dsl_expr.py",
            "env_dsl_io.py",
            "test_env_dsl.py",
        ):
            lines = len(
                (ROOT / "tests" / mod_name).read_text(encoding="utf-8").splitlines()
            )
            self.assertLess(lines, 500, f"{mod_name} has {lines} lines")

        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            real_dir = base_dir / "real"
            nested_dir = base_dir / "nested"
            real_dir.mkdir()
            nested_dir.mkdir()
            real_file = real_dir / "base.env"
            real_file.write_bytes(VALID.read_bytes())
            link_file = base_dir / "symlink.env"
            link_file.symlink_to(real_file)
            sym_dir = base_dir / "sym_dir"
            sym_dir.symlink_to(real_dir)
            fifo_path = base_dir / "pipe.env"
            os.mkfifo(fifo_path)

            for bad_path in (
                link_file,
                sym_dir / "base.env",
                Path(os.fspath(sym_dir) + "/../real/base.env"),
                fifo_path,
                Path("bad\x00.env"),
            ):
                doc, diags = parse_file(bad_path)
                self.assertIsNone(doc, str(bad_path))
                self.assertEqual([SYNTAX], [item.code for item in diags], str(bad_path))

            prev_cwd = Path.cwd()
            try:
                os.chdir(nested_dir)
                for rel_bad in (
                    Path("../sym_dir/base.env"),
                    Path("../sym_dir/../real/base.env"),
                ):
                    doc, diags = parse_file(rel_bad)
                    self.assertIsNone(doc, str(rel_bad))
                    self.assertEqual(
                        [SYNTAX], [item.code for item in diags], str(rel_bad)
                    )
            finally:
                os.chdir(prev_cwd)

        chain: dict[str, str] = {"STEP_0": "1"}
        for idx in range(1, 1200):
            chain[f"STEP_{idx}_EXPRESSION"] = (
                "@STEP_0+1" if idx == 1 else f"@STEP_{idx - 1}_EXPRESSION+1"
            )
        evaluated, chain_diags = evaluate_constants(chain)
        self.assertEqual([], chain_diags)
        self.assertEqual(1200, evaluated["STEP_1199_EXPRESSION"])

        many_ops = "1+" * 600 + "1"
        _, op_diags = evaluate_constants({"MANY_EXPRESSION": many_ops})
        self.assertTrue(
            any("maximum operator count" in item.message for item in op_diags)
        )

        huge_int = "1" + "0" * 5000
        _, int_diags = evaluate_constants({"HUGE_EXPRESSION": huge_int})
        self.assertTrue(any(item.code == EXPRESSION for item in int_diags))

        _, const_diags = evaluate_constants(
            {"HUGE_CONST": huge_int, "USE_EXPRESSION": "@HUGE_CONST+1"}
        )
        self.assertTrue(any(item.code == EXPRESSION for item in const_diags))

        big_factor = str(10**40)
        _, overflow_diags = evaluate_constants(
            {"A": big_factor, "OVF_EXPRESSION": "@A*@A*@A"}
        )
        self.assertTrue(any("overflow" in item.message for item in overflow_diags))

    def test_iterative_eval_short_circuit_unicode_digits_and_surrogate_safety(
        self,
    ) -> None:
        max_wide = "1+" * 512 + "1"
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(90)
        try:
            evaluated, diags = evaluate_constants(
                {
                    "WIDE_EXPRESSION": max_wide,
                    "SHORT_AND_CONDITION": "FALSE&&(1/0==0)",
                    "SHORT_OR_CONDITION": "TRUE||(1/0==0)",
                }
            )
        finally:
            sys.setrecursionlimit(old_limit)
        self.assertEqual([], diags)
        self.assertEqual(513, evaluated["WIDE_EXPRESSION"])
        self.assertIs(False, evaluated["SHORT_AND_CONDITION"])
        self.assertIs(True, evaluated["SHORT_OR_CONDITION"])

        ast = ExpressionNode("literal", 1)
        for _ in range(5000):
            ast = ExpressionNode("unary", "-", ast)
        with self.assertRaises(ExpressionError):
            evaluate_node(ast, lambda _: 0)

        for non_ascii_expr in ("\u00b2+1", "\u0661+\u0662"):
            _, u_diags = evaluate_constants({"BAD_EXPRESSION": non_ascii_expr})
            self.assertTrue(
                any(item.code == EXPRESSION for item in u_diags), non_ascii_expr
            )
        _, const_u_diags = evaluate_constants({"X": "\u00b2", "Y_EXPRESSION": "@X+1"})
        self.assertTrue(any(item.code == EXPRESSION for item in const_u_diags))

        _, sur_diags = parse_text(
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=SUR\nENV_DSL_ENVIRONMENT=BASE\n\ud800=1\n",
            "bad\nENV-PASS\udcff.env",
        )
        rendered = "\n".join(item.render() for item in sur_diags)
        self.assertNotIn("\nENV-PASS", rendered)
        self.assertIsInstance(rendered.encode("utf-8"), bytes)

        isolated = subprocess.run(
            [
                sys.executable,
                "-I",
                str(ROOT / "tests" / "env_dsl_check.py"),
                "self-test",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, isolated.returncode, isolated.stderr)
        self.assertEqual("ENV-SELF-TEST-PASS", isolated.stdout.strip())


if __name__ == "__main__":
    unittest.main()
