# ENV-LAYER-001

## Meaning

An ordered set of valid documents does not form one explicit environment
inheritance chain.

## Cause

The first layer is not `BASE`, versions or namespaces differ, an environment
is repeated, or `ENV_DSL_EXTENDS` does not name the immediately preceding
environment.

## Resolution

Start with one `BASE` document, list layers in parent-to-child order, preserve
one version and namespace, and declare the exact immediate parent in every
later document.
