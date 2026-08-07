# PR Review Hardening Design

## Scope

Address the four actionable review findings raised against commit `8ec5e69`:

- DNS pinning must compare normalized IDNA hostnames and restore the real resolver under concurrent use.
- Prometheus scrape authorization must use the schema-supported scrape-job field.
- Vector-store additions must remain consistent when embedding fails.

## Design

### DNS pinning

Add one hostname-normalization helper that lowercases, removes a trailing dot, and converts Unicode DNS names to ASCII IDNA form. Use it for the allowlist and for the hostname comparison inside the pinned resolver. The validated URL and TLS/Host behavior remain unchanged; only resolver matching is normalized.

Acquire `_DNS_PIN_LOCK` before capturing the current `socket.getaddrinfo`. Keep the lock for the complete patch-and-request context so overlapping requests cannot snapshot or restore another request's temporary resolver.

### Prometheus

Move `authorization` directly under the `minimal-agent` scrape job. Keep the bearer token file and Compose read-only mount unchanged.

### Vector store

Compute the new embedding before mutating any in-memory collection. Append the document, metadata, and vector only after embedding succeeds while holding the existing lock. A failed embedding therefore leaves the previous consistent state intact and future saves cannot persist mismatched list lengths.

## Error handling

- Invalid or unresolvable hosts continue to fail through the existing URL validation errors.
- A DNS lookup that does not match the normalized validated host continues to use the original resolver.
- Embedding exceptions propagate unchanged and do not partially mutate the store.
- Prometheus configuration remains bearer-token protected; no unauthenticated scrape path is introduced.

## Verification

Add regression tests for:

1. Unicode validated hostnames matching their IDNA/Punycode connection hostname.
2. Concurrent DNS pinning restoring the original resolver.
3. Prometheus authorization being at the scrape-job level without `http_config`.
4. Failed vector embedding leaving persisted documents, metadata, and vectors unchanged.

Run the focused tests first, then the complete Python suite, compilation, Compose configuration validation, and whitespace checks. Re-run CI after pushing and only then resolve the four corresponding GitHub threads.
