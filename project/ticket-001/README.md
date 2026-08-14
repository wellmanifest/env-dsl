# Ticket 001: Define Env DSL portable environment constants standard

- **ID**: ticket-001
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-08-14

## Goal and scope

Create the first usable Wellmanifest Env DSL standard for portable environment
constants. The canonical text format is a strict `SNAKE_CASE=value` subset
that keeps values as data and can be projected into `.env`, Docker, Make,
shell, Go, Elixir, Erlang, Ruby, Python and other runtimes through adapters.

The reference example extracts constants such as schema identifiers and raw
regular-expression patterns from `wellmanifest/dsl/src/dsl_check.py`. It stores
pattern text only; constructors such as `re.compile(...)` remain outside the
DSL and belong to a consumer adapter.

## Acceptance criteria

- [ ] AC-01: A normative specification defines the document identity,
  `SNAKE_CASE` key grammar, literal value grammar and environment metadata.
- [ ] AC-02: The language forbids evaluation, interpolation, command
  substitution, host-language constructors and secret material.
- [ ] AC-03: Environment layering and duplicate/override semantics are
  deterministic and distinguish the selected environment explicitly.
- [ ] AC-04: A language-neutral ABNF grammar describes every accepted line.
- [ ] AC-05: A valid `.env`-shaped example represents the scalar constants from
  `dsl_check.py`, including raw pattern text and no `re.compile(...)` calls.
- [ ] AC-06: Invalid fixtures cover lowercase keys, duplicate keys,
  interpolation, command substitution, language constructors and secret names.
- [ ] AC-07: A dependency-free checker and tests accept valid documents and
  reject invalid fixtures with stable diagnostic codes.
- [ ] AC-08: A Wellmanifest DSL manifest binds the standard, grammar, examples,
  checker and documentation by SHA-256 and pins `wellmanifest/dsl`.
- [ ] AC-09: Architecture and logic-flow documentation show the neutral DSL
  boundary and consumer-owned compilation/type-conversion boundary.
- [ ] AC-10: Governance, unit, self-test, DSL manifest, link, secret and
  repository-diff checks pass with recorded evidence.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)

## Non-goals

- Editing `wellmanifest/dsl/src/dsl_check.py` from this repository ticket.
- Defining secrets, credentials or deployment-specific secret transport.
- Executing, sourcing or evaluating an Env DSL document.
- Standardizing the public API of every language-specific environment loader.
- Hosting a CLI, daemon or runtime service in Wellmanifest.

## Resolved prerequisite

Published `wellmanifest/new-project` v0.18.0 accepts and validates the required
`intent.json.placement` object. The repository adopted exact release commit
`769183ca27593af1d166acee11bc9e37decf9870`; its lock records
`publicationStatus=published`. Implementation may resume inside the unchanged
ticket scope.

## Authorized delivery boundary

- Seed baseline: `main@d8ffe2c706bd06952311029571ecef8b1787b2a0`.
- Complexity: L; at most 15 implementation files, 5 affected components, 3
  public-interface changes and 0 runtime dependencies.
- Implementation branch: `ticket/001-env-dsl-standard`; remote publication is
  not part of the seed authorization.
