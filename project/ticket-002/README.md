# Ticket 002: Adopt new-project standard 0.18.6

- **ID**: ticket-002
- **Owner**: agent:gemini under SESSION_EXECUTION_AUTHORIZATION
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-08-23

## Goal and scope

Adopt published `wellmanifest/new-project` 0.18.6 into `wellmanifest/env-dsl` in one atomic transaction through `create_adoption_lock.py`.
Brings the host-agnostic contract (CLAUDE.md, GEMINI.md, Cursor rule, pre-commit hook, agent-hosts.json validator) and `governance / enforce` CI job.

## Acceptance criteria

- [x] AC-01: `python3 .governance/agent_host_check.py --root .` → `GOV-AGENT-HOST-PASS` after `./scripts/install-agent-hosts.sh`.
- [x] AC-02: `./project/governance-check.sh --actor agent` → `GOV-PASS`, all managed digests match lock.
- [x] AC-03: `python3 -m unittest discover -s tests -v` passes; domain contracts unaffected.

## Publication evidence

- Pull request: `wellmanifest/env-dsl#1`
- Frozen and approved head: `d6f584e736090f5c95066233df64aaac33563481`
- Merge commit: `70e6662b04cce0702e20d6e48b86256ebc39c903`

## Participants

- Human participant: authorized via active session.
- Agent participant: [ai-gemini.md](ai-gemini.md)
