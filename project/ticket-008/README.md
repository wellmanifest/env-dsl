# Ticket 008: Modularize env_dsl_io and harden iterative eval, symlink ancestors, and embedded secrets

- **ID**: ticket-008
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Session authorization

- `SESSION_EXECUTION_AUTHORIZATION`: Autonomous execution, testing, and protected publication requested by the repository owner.

## Goal and scope

Extract `tests/env_dsl_io.py` so every Env DSL checker and test module stays well under 500 lines after formatting, and harden I/O, expression evaluation, Unicode digit handling, diagnostic rendering, and embedded credential detection:

1. Extract `tests/env_dsl_io.py` with symlink-ancestor traversal checks before `..` collapse (`sym_dir/base.env`, `sym_dir/../real/base.env`, `../sym_dir/base.env`), `(st_dev, st_ino)` inode parity between `os.lstat` and `os.fstat`, NUL-byte path rejection, diagnostic text sanitization, and expanded embedded credential detection (inline URI `scheme://user:pass@host` / `scheme://:pass@host`, embedded GitHub/GitLab/Slack/npm/PyPI/OpenAI tokens, AWS `AKIA`/`ASIA` key IDs, and JWTs).
2. Convert `evaluate_node()` in `tests/env_dsl_expr.py` to an explicit iterative frame stack (`O(1)` Python stack frames with `&&`/`||` short-circuiting and `MAX_EVAL_STEPS = 4096`) and restrict `tokenize_expression()` and `coerce_constant()` to ABNF ASCII digits (`%x30-39`) so Unicode digits/superscripts (`\u00b2`, `\u0661`) fail closed with `ENV-EXPRESSION-001` instead of raising `ValueError`.
3. Escape C0/DEL/C1 control characters and lone UTF-16 surrogates in `Diagnostic.render()` and invalid-name diagnostics in `tests/env_dsl_check.py`, preserve `python3 -I` isolated-mode execution, register `tests/env_dsl_io.py` in `dsl-manifest.json`, and mark merged `project/ticket-006/README.md` and `project/ticket-007/README.md` as `DONE`.

## Acceptance criteria

- [x] AC-01: `tests/env_dsl_io.py`, `tests/env_dsl_expr.py`, `tests/env_dsl_check.py`, and `tests/test_env_dsl.py` each remain strictly under 500 lines after `ruff format` and pass `ruff check --no-cache` with zero warnings.
- [x] AC-02: Symlink-ancestor paths, FIFO/NUL paths, 512-operator expressions under tight recursion limits, Unicode digits, embedded URI/JWT/token secrets, and surrogate/newline diagnostics fail closed without unhandled exceptions.
- [x] AC-03: `dsl-manifest.json` digests, `env_dsl_check.py self-test` (including `python3 -I`), `unittest`, `pytest -q`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
