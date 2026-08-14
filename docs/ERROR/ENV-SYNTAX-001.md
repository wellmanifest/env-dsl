# ENV-SYNTAX-001

## Meaning

The document bytes or a source line do not match Env DSL 1 canonical syntax.

## Cause

Common causes are non-UTF-8 input, CRLF, a missing final LF, tabs, non-ASCII
characters, whitespace around `=`, a lowercase name or a non-assignment line.

## Resolution

Encode the document as UTF-8 without BOM, use LF, and express every record as
an exact `SNAKE_CASE=value` line. Keep comments on separate lines.
