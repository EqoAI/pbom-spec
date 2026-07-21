# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.1.1] - 2026-07-21

### Added

- `extensions` keyword-only parameter on `PBOMEmitter.record()` and
  `CommitmentContext.complete()` to pass non-standard, namespaced metadata
  through into the record's existing `extensions` field. Defaults to `{}` when
  omitted, so existing callers are unaffected.
- `PBOMEmitter.record_blocked()` for emitting a record when no response
  occurred (e.g. blocked before inference). Its response section is an explicit
  no-response marker (`response_hash=None`, `response_text=None`,
  `response_token_count=0`, `stop_reason=None`, `thinking_token_count=None`),
  distinguishable from an empty-string response. No response hash is computed.

### Note

- The PBOM format version (`pbom_version`) remains `1.0.0`; these are
  backward-compatible additions to the Python implementation only.
- `record_blocked()` uses `commitment_type="post_hoc"` as an interim value:
  the required enum (`pre_inference`/`post_hoc`) has no no-inference option.
  A dedicated value is deferred to the next `PBOM_VERSION` release.


## [0.1.0-alpha] - 2026-07-11

### Added

- Initial reference implementation of PBOM v1.0.0
- Pydantic v2 schema models for the complete PBOM record format
- PBOMEmitter with context-manager (pre-inference) and post-hoc APIs
- Cryptographic commitment scheme (nonce + SHA-256)
- Merkle chain linking with thread-safe state and resume support
- Chain validator and commitment verifier
- CLI: init, validate, status, export-schema
- Fingerprint and forensic storage modes
- Example scripts (basic_usage.py, verify_chain.py)
- Formal specification (docs/spec.md) and field guide (docs/fields.md)
