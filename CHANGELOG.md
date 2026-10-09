# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-10-09

### Added

- `pbom records` CLI command for reading chain contents from the terminal.
  Lists the most recent records (`--last/-n`, default 10), shows a single
  record in detail (`--record/-r SEQ`), and supports `--format table|json`.
  Table and detail views show hashes only, never raw prompt or response
  text, in every storage mode. JSON output is the full record via
  `to_json_dict()`. Unreadable-file warnings go to stderr so JSON output
  stays pipeable.
- `ValidationResult.noncanonical_files`.

### Changed

- `pbom validate` output is clearer: chain links are shown as
  `valid/expected` with a note that the first record has no predecessor;
  the Commitments line is colored by outcome (green/yellow/red); and a note
  explains that unverifiable commitments are expected in fingerprint mode
  and do not affect the Validation result. Exit codes and `is_valid` are
  unchanged.
- Packaged `SKILL.md` now documents `pbom records`, matches current
  `validate` output, and no longer hardcodes a stale package version.

### Security

All issues below affect 0.1.2 and earlier and were found in an internal
review against the threat model in spec §12 (an attacker who can modify
files in `.pbom/`).

- `pbom validate` now fails records whose file content differs from what
  was hashed: unknown nested fields, duplicate JSON keys, or type-coerced
  values. Previously these edits could be made to any record without
  breaking the chain.
- CLI output (`validate`, `status`, `records`) now escapes non-printable
  characters taken from record contents. Previously a tampered record could
  embed terminal escape sequences (e.g. in `entry_id`) and make
  `pbom validate` display a fake "Validation: PASS" for a broken chain
  (the exit code was still 1).
- Record files are now opened without following symlinks and must be
  regular files. Previously a named pipe or a symlink to a device in
  `.pbom/` could hang or exhaust memory in `validate`, `records`, `status`,
  and in `PBOMEmitter` when resuming the chain at startup. Such files are
  now treated as unreadable: validation fails and chain resume raises
  `ChainCorruptedError` instead of hanging.
- A record file with deeply nested JSON no longer crashes `records`,
  `status`, or `validate` (and `validate_chain()` no longer raises
  `RecursionError`); it is reported as unreadable, which fails validation.
- Parse-failure warnings no longer echo record contents (which could
  include forensic-mode prompt text, e.g. in CI logs), and file names in
  warnings are escaped.
- `pbom init` and `pbom install-skill` no longer write through symlinks.
  Previously, running them in an untrusted repository could append to or
  overwrite files outside the project (e.g. a symlinked `CLAUDE.md`,
  `.gitignore`, skill file, or `.pbom/config.json`). `install-skill` now
  refuses and writes nothing; `init` skips the unsafe step with a warning.

## [0.1.2] - 2026-09-30

### Fixed

- Race condition in `chain.py` when multiple emitters wrote records concurrently.
  Sequence-number claiming is now atomic via `os.O_CREAT | os.O_EXCL`, and an
  `RLock` guards in-process state. Previously, concurrent writers could claim
  the same sequence number, producing duplicate-sequence validation failures.
  All 15 concurrency tests pass, including a new concurrent-emitter regression.


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
