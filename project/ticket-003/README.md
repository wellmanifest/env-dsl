# Ticket 003: Declare DSL manifest decision protocol for wellmanifest/dsl gate

- **ID**: ticket-003
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Session execution authorization**: user requested correcting wellmanifest standards that fail their own DSL conformance gate (2026-09-13)
- **Created**: 2026-09-13

## Goal and scope

`dsl-manifest.json` on `b851fdc` fails the `wellmanifest/dsl` gate
(`src/dsl_check.py validate`, revision `5f40ad5d228d6301bdbf4bb78e1646ebd3c2b95b`):

```text
DSL-MANIFEST-001 ERROR: llm misses fields: decisionProtocol
DSL-LLM-001 ERROR: llm.decisionProtocol is invalid
```

`wellmanifest/dsl` commit `869e47f` (2026-08-26) made the field mandatory and
requires `decisionProtocol=none` when `llm.mode=none`. This ticket declares
that value and changes nothing else.

## Acceptance criteria

- [x] AC-01: the wellmanifest/dsl gate reports `DSL-PASS: passed (0 errors)`.
- [ ] AC-02: `./project/governance-check.sh` passes on the published head.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-claude.md](ai-claude.md)
