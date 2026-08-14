from pathlib import Path
import unittest

from env_dsl_check import (
    LAYER,
    SECURITY,
    SEMANTIC,
    SYNTAX,
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
        self.assertNotIn("re." + "compile(", VALID.read_text(encoding="utf-8"))

    def test_invalid_fixture_covers_required_boundaries(self) -> None:
        _, diagnostics = parse_file(INVALID)
        codes = {item.code for item in diagnostics}
        self.assertEqual({SYNTAX, SEMANTIC, SECURITY}, codes)
        messages = "\n".join(item.message for item in diagnostics)
        self.assertIn("duplicate", messages)
        self.assertIn("interpolation", messages)
        self.assertIn("constructors", messages)

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
