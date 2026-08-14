# wellmanifest/env-dsl

Normative Wellmanifest domain pack for language-neutral environment constants.

`env-dsl` defines a small, deterministic `SNAKE_CASE=value` contract that can
carry constants between `.env` files and adapters for Docker, Make, shell, Go,
Elixir, Erlang, Ruby, Python and other runtimes. Values are data: the DSL never
embeds constructors or calls such as Python's `re.compile(...)`.

## Repository boundary

This repository owns:

- the normative Env DSL syntax and semantics;
- a language-neutral ABNF grammar;
- valid and invalid portability examples;
- deterministic conformance fixtures;
- architecture and projection guidance.

It does not own application secrets, environment deployment, a daemon, or
language-specific loading libraries. Consumers parse the same constants and
perform type conversion or regular-expression compilation in their own adapter.

## Planned entry points

- `spec/ENV_DSL.md` — normative requirements;
- `spec/env-dsl.abnf` — language-neutral grammar;
- `examples/valid/dsl-check.env` — constants derived from `dsl_check.py`
  without Python calls;
- `tests/env_dsl_check.py` and `tests/fixtures/invalid/` — deterministic
  checker and rejected portability cases;
- `docs/ARCHITECTURE.md` and `docs/LOGIC_FLOW.md` — adapter guidance.

Status: `0.1.0-dev`, governed implementation in `project/ticket-001`.
