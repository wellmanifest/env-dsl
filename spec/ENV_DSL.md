# Env DSL Standard 1

Status: experimental normative specification

Canonical media type: `application/vnd.wellmanifest.env-dsl`

Canonical filename suffix: `.env`

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are
normative when written in uppercase.

## 1. Purpose

Env DSL is a small data language for constants that must cross configuration
boundaries. Its records resemble dotenv assignments:

```env
SNAKE_CASE=value
```

An Env DSL document is data. A consumer MUST parse it and MUST NOT source,
evaluate or execute it. Adapters MAY project parsed records into `.env`,
Docker/Compose, Make, Bash, Go, Elixir, Erlang, Ruby or another environment,
but escaping, type conversion and regular-expression compilation remain the
adapter's responsibility.

## 2. Document encoding and lines

A conforming document MUST:

- be UTF-8 without a byte-order mark;
- contain only printable ASCII (`U+0020` through `U+007E`) plus line feed;
- use LF line endings and end with LF;
- contain only blank lines, full-line comments and assignment records.

A blank line contains zero or more spaces. A comment may be indented with
spaces and begins with `#`. Inline comments do not exist: `#` in an assignment
value is literal data.

Tabs, carriage returns, `export KEY=value`, shell statements and whitespace
around `=` are invalid.

## 3. Names

A name MUST match this language-neutral shape:

```text
[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*
```

Consequently, a name starts with an uppercase ASCII letter, contains only
uppercase ASCII letters, digits and single underscores, and has no leading,
trailing or repeated underscore. Names are case-sensitive.

Names beginning with `ENV_DSL_` are reserved by this standard. Version 1
defines only:

- `ENV_DSL_VERSION`
- `ENV_DSL_NAMESPACE`
- `ENV_DSL_ENVIRONMENT`
- `ENV_DSL_EXTENDS`

Unknown reserved names MUST be rejected. A document MUST NOT repeat a name.

## 4. Header and identity

Ignoring leading blank lines and comments, the first three records MUST occur
in this exact order:

```env
ENV_DSL_VERSION=1
ENV_DSL_NAMESPACE=WELLMANIFEST_DSL_CHECK
ENV_DSL_ENVIRONMENT=BASE
```

`ENV_DSL_NAMESPACE` identifies one independently owned constant set and its
value MUST itself be a valid Env DSL name. `ENV_DSL_ENVIRONMENT` explicitly
selects the environment and MUST also be a valid name.

`BASE` MUST NOT contain `ENV_DSL_EXTENDS`. Every non-`BASE` document MUST put
`ENV_DSL_EXTENDS=<PARENT>` immediately after the three required header records.
`PARENT` MUST be a valid environment name and MUST differ from the selected
environment.

## 5. Literal values

The first `=` separates the name from its value. A value MUST contain one or
more printable, non-space ASCII characters. It is an opaque string: booleans,
numbers, paths, media types and regular expressions have no intrinsic Env DSL
type.

Quotes are forbidden because dotenv, shell and Make interpret them
differently. Backslash is ordinary data and is not an escape character. The
characters `#`, `=`, `(`, `)`, `[`, `]`, `{`, `}`, `+`, `*`, `?`, `^` and `$`
are permitted when they do not create one of the forbidden forms below.

A value MUST NOT contain:

- variable interpolation such as `$NAME` or `${NAME}`;
- command substitution such as `$(command)` or backticks;
- language constructors or evaluators such as Python regular-expression
  compilation, Ruby `Regexp.new`, Java `Pattern.compile`, Elixir
  `Regex.compile`, `eval`, `exec` or `system` calls;
- a quoted representation whose meaning depends on a host parser.

For example, a regex constant stores `^sha256:([a-f0-9]{64})$` directly. A Go,
Ruby or Python adapter decides whether and how to compile that text.

## 6. Secrets

Env DSL is for non-secret constants. It MUST NOT contain credentials, private
keys, passwords, access tokens or secret material. A conforming checker MUST
reject secret-signalling names, including names ending in `_PASSWORD`,
`_TOKEN`, `_SECRET`, `_PRIVATE_KEY`, `_ACCESS_KEY`, `_API_KEY` or
`_CREDENTIAL`, and recognizable private-key or common token material.

Secret references also belong to deployment-specific secret transport, not to
this language. A project needing secrets MUST use a separately governed secret
provider and join the result only at runtime.

## 7. Layering

Layering is an explicit ordered operation over already validated documents:

1. The first document MUST select `BASE`.
2. All documents MUST have the same version and namespace.
3. Each later document's `ENV_DSL_EXTENDS` MUST name the immediately preceding
   document's environment.
4. Environment names MUST be unique in the chain.
5. Header fields never enter the constant map.
6. For each later document, a constant with an existing name replaces the
   earlier value; a new name is added.

This ordered last-layer-wins rule is the only override rule. A consumer MUST
NOT read ambient process variables, files not named in the chain or implicit
profiles while computing the result. The selected environment is the final
document's `ENV_DSL_ENVIRONMENT`.

## 8. Consumer boundary

A conforming consumer performs these stages in order:

1. read bytes without execution;
2. validate encoding, grammar and semantics;
3. validate and merge an explicit environment chain;
4. pass inert strings to a host adapter;
5. let the host adapter escape, convert or compile values.

Direct inclusion is safe only when a target format preserves every accepted
record byte-for-byte. Otherwise an adapter MUST generate target syntax from the
parsed map. Env DSL never standardizes `source`, `include`, `eval` or a host
language constructor.

## 9. Diagnostics

Conformance tools use stable codes with direct help pages:

- `ENV-SYNTAX-001`: bytes or a line do not match canonical syntax;
- `ENV-SEMANTIC-001`: document metadata, uniqueness or inert-value rules fail;
- `ENV-LAYER-001`: the explicit environment chain is inconsistent;
- `ENV-SECURITY-001`: a name or value appears to carry secret material.

Tools MAY add detail to a message, but MUST NOT change the meaning of a code
within Env DSL major version 1.

## 10. Compatibility

Removing a record form, changing merge results, widening evaluation authority
or accepting previously ambiguous executable syntax is breaking. Adding a new
reserved metadata field is additive only when version-1 readers can safely
reject it and a new minor conformance profile defines its behavior.
