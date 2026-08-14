from pathlib import Path
import unittest

from env_dsl_check import (
    EXPRESSION,
    LAYER,
    SECURITY,
    SEMANTIC,
    SYNTAX,
    evaluate_constants,
    merge_documents,
    parse_file,
    parse_text,
)


ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "examples" / "valid" / "dsl-check.env"
INVALID = ROOT / "examples" / "invalid" / "nonportable.env"


class EnvDslTests(unittest.TestCase):
    def test_reference_example_is_valid_inert_data(self) -> None:
        document, diagnostics = parse_file(VALID)
        self.assertEqual([], diagnostics)
        self.assertIsNotNone(document)
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

    def test_condition_must_return_boolean_and_arithmetic_requires_integers(self) -> None:
        _, condition_diagnostics = evaluate_constants(
            {"COUNT_CONDITION": "1+2"}
        )
        self.assertTrue(any("must produce boolean" in item.message for item in condition_diagnostics))
        _, type_diagnostics = evaluate_constants(
            {"TEXT_VALUE": "TEXT", "BAD_EXPRESSION": "@TEXT_VALUE+1"}
        )
        self.assertTrue(any("requires int" in item.message for item in type_diagnostics))

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
        _, diagnostics = merge_documents([base, prod])
        self.assertTrue(any(item.code == LAYER for item in diagnostics))

    def test_quotes_and_missing_final_lf_are_rejected(self) -> None:
        text = (
            "ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=STRICT\n"
            "ENV_DSL_ENVIRONMENT=BASE\nQUOTED=\"value\""
        )
        _, diagnostics = parse_text(text)
        self.assertTrue(any(item.code == SYNTAX for item in diagnostics))
        self.assertTrue(any(item.code == SEMANTIC for item in diagnostics))


if __name__ == "__main__":
    unittest.main()
