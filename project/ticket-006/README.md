# Ticket 006: Enforce ABNF string-atom charset, expression depth bound, and pytest integration

- **ID**: ticket-006
- **Owner**: agent:antigravity
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-11-11

## Session authorization

- `SESSION_EXECUTION_AUTHORIZATION`: Autonomous execution, testing, and protected publication requested by the repository owner.

## Goal and scope

Harden `tests/env_dsl_check.py`, `tests/test_env_dsl.py`, `pyproject.toml`, and `dsl-manifest.json`:

1. Align `tokenize_expression()` `:string-atom` scanning with the normative `atom-char` production in `spec/env-dsl.abnf` (`%x23-24 / %x2C / %x2E / %x30-3B / %x3F-5F / %x61-7B / %x7D-7E`) so spaces, quotes, backticks, control characters, and non-ASCII fail closed in direct `parse_expression()` and `evaluate_constants()` calls.
2. Bound expression recursion (`MAX_EXPRESSION_DEPTH = 64`) in `ExpressionParser` so deeply nested parentheses or unary chains emit `ENV-EXPRESSION-001` instead of crashing with `RecursionError`.
3. Reject POSIX positional/special shell parameter interpolation (`$0`-`$9`, `$$`, `$@`) in `has_interpolation()` and extend `secret_value()` to detect PEM headers, AWS STS `ASIA` keys, GitLab `glpat-`, Slack `xoxb-`/`xoxp-`, and `npm_` tokens.
4. Configure standalone `pytest` (`pythonpath = [".", "tests"]`, `testpaths = ["tests"]`) in `pyproject.toml` and synchronize `dsl-manifest.json` artifact digests.

## Acceptance criteria

- [x] AC-01: Non-ABNF characters in `:string-atom`, deep nesting (`>64`), `$1`/`$$`/`$@` shell interpolation, and additional credential token prefixes fail closed without unhandled exceptions.
- [x] AC-02: `dsl-manifest.json` digests, `self-test`, `unittest`, `pytest -q`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass cleanly.
