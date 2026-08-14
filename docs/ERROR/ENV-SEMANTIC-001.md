# ENV-SEMANTIC-001

## Meaning

Canonical records violate document identity, uniqueness or inert-value rules.

## Cause

Examples include missing or misordered headers, a duplicate name, unknown
reserved metadata, an invalid environment identity, interpolation, command
substitution, quotes or a host-language constructor.

## Resolution

Restore the required header order, keep each name unique and replace executable
or host-specific expressions with their literal data value. Perform conversion
only in a consumer adapter.
