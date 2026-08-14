# Env DSL logic flow

Validation completes before layering, and layering completes before a
consumer-specific conversion. No stage evaluates source text.

```mermaid
sequenceDiagram
    participant C as Consumer
    participant P as Env DSL parser
    participant L as Layer merger
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
            L->>A: Final inert string map
            A->>A: Escape, convert or compile for host
            A-->>C: Host-owned representation
        end
    end
```

## Determinism

For one ordered byte sequence, validation and merge output are deterministic.
The merger reads no process environment, clock, network, secret provider or
unnamed file. Later explicit layers replace earlier values with the same name.

## Failure behavior

All errors fail closed. A consumer must not merge a document with syntax,
semantic or security diagnostics. It must not coerce a broken chain into a
plausible order. Diagnostic messages may add context, while each stable code
links to its normative help page.
