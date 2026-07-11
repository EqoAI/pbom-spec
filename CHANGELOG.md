# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


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
