# ENV-EXPRESSION-001

## Meaning

A suffix-typed Env DSL equation cannot be parsed or deterministically
evaluated under the portable operator model.

## Cause

The equation may contain an invalid token, missing operand, unresolved
`@SNAKE_CASE` reference, dependency cycle, operand type mismatch, non-boolean
condition result or division by zero.

## Resolution

Use only the documented operands and operators, make every reference available
after explicit layering, remove cycles, and preserve the required scalar types.
Keep host-language functions and effectful decisions outside Env DSL.
