# ENV-SECURITY-001

## Risk

Secret material in a portable constants document can be committed, copied and
projected into multiple environments without an appropriate trust boundary.

## Detection

The checker rejects common secret-signalling names and recognizable private-key
or access-token material. This deterministic detection is a minimum control,
not proof that an otherwise accepted value is non-secret.

## Remediation

Remove the secret and its reference from Env DSL. Store it in a separately
governed secret provider and join it with non-secret configuration only at
runtime.

## Verification

Re-run the checker and repository secret scan, then rotate any credential that
may already have been exposed.
