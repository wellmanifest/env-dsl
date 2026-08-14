# Env DSL logic flow

Validation completes before layering, and portable equation evaluation
completes before a consumer-specific conversion. No stage invokes a host
expression engine or evaluates source as code.

```mermaid
sequenceDiagram
    participant C as Consumer
    participant P as Env DSL parser
    participant L as Layer merger
    participant E as Equation evaluator
    participant A as Host adapter
    C->>P: Exact ordered document bytes
    P->>P: Check UTF-8, LF, records and inert values
    alt any diagnostic
        P-->>C: Stable ENV-* error and help path
    else all documents valid
        P->>L: Typed document records
        L->>L: Check BASE, namespace and parent chain
        alt invalid chain
            L-->>C: ENV-LAYER-001
        else valid chain
            L->>E: Final constants and equation map
            E->>E: Check references, DAG, types and precedence
            alt invalid equation
                E-->>C: ENV-EXPRESSION-001
            else valid equations
                E->>A: Constants and computed scalars
                A->>A: Escape, convert or compile for host
                A-->>C: Host-owned representation
            end
        end
    end
```

## Determinism

For one ordered byte sequence, validation and merge output are deterministic.
The merger and equation evaluator read no process environment, clock, network,
secret provider or unnamed file. Later explicit layers replace earlier values
with the same name. References resolve only in the final layered namespace.

## Failure behavior

All errors fail closed. A consumer must not merge a document with syntax,
semantic, expression or security diagnostics. It must not coerce a broken
chain, type mismatch or dependency cycle into a plausible result. Diagnostic
messages may add context, while each stable code links to its normative help
page.
