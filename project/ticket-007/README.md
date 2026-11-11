# Ticket 007: Modularize env_dsl_check under 500 lines and harden recursion, integer bounds, and file I/O

- **ID**: ticket-007
- **Owner**: unresolved:human
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-11-11

## Goal and scope

Split `tests/env_dsl_check.py` (813 lines) into cohesive modules strictly under 500 lines (`tests/env_dsl_expr.py` + `tests/env_dsl_check.py`) and harden expression evaluation and file I/O:
- Extract the expression lexer, parser, iterative cycle/topological analyzer, and bounded integer/scalar evaluator into `tests/env_dsl_expr.py` while re-exporting public symbols from `tests/env_dsl_check.py`.
- Eliminate `RecursionError` on deep equation reference chains (`> 1000` equations) and wide binary operator chains (`MAX_EXPRESSION_OPERATORS = 512`) via iterative reference/cycle/topological evaluation.
- Bound integer literals (`<= 64` digits) and arithmetic results (`<= 256` bits) so `> 4300`-digit payloads fail closed with `ENV-EXPRESSION-001` instead of raising Python's `int_max_str_digits` `ValueError`.
- Harden `parse_file()` with `O_NOFOLLOW | O_NONBLOCK`, `stat.S_ISREG`, and a 4 MiB byte budget; synchronize `parser-contract` digests in `dsl-manifest.json`; and add regression coverage in `tests/test_env_dsl.py`.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner (continuous hardening/modularity session).
- [x] AC-02: `tests/env_dsl_check.py`, `tests/env_dsl_expr.py`, and `tests/test_env_dsl.py` stay strictly under 500 lines and fail closed without `RecursionError` or uncaught `ValueError`.
- [x] AC-03: `unittest`, `env_dsl_check.py self-test`, `dsl_check.py validate dsl-manifest.json`, `./project/governance-check.sh --actor ci`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
