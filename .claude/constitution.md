# PBOM OSS Constitution

These rules are inviolable. Any code that violates them is wrong, regardless of how reasonable the violation seems. If Claude is asked to violate a rule, refuse and flag the conflict to the developer.

This file ships in the public OSS repo at `.claude/constitution.md`. It is intentionally short and read by both humans and Claude.

---

## Cryptographic and data integrity

1. **Hashes are always lowercase hex SHA-256 of UTF-8 encoded bytes.** No other hash function. No other encoding. No other case. Anywhere a hash appears — in a field, in a comparison, in a test fixture — lowercase hex SHA-256.

2. **Records are append-only.** No code path in this package may modify or delete an existing `.pbom.json` file. The validator may read; the emitter may only create new files; nothing else writes.

3. **The commitment timestamp must be strictly less than the reveal timestamp.** If equal or inverted, raise `InvalidCommitmentError` rather than emit a record. Time going backwards is a bug, not a warning.

4. **JSON used for hashing or signing uses `sort_keys=True, separators=(",", ":")`.** Never pretty-printed for canonical forms. Pretty printing is for humans reading files, not for cryptographic operations.

---

## Privacy and storage modes

5. **Fingerprint mode never stores raw prompt or response content.** Not in a comment, not in a debug field, not "just for now." If `storage_mode == "fingerprint"`, raw text content is never persisted, including in `extensions`. The only acceptable persisted form is a hash.

6. **The package makes zero outbound network calls.** No telemetry. No phone-home. No auto-update checks. No remote schema fetching. No analytics. The package only writes files to disk and reads them back.

---

## Versioning

7. **`pbom_version` in emitted records is `"1.0.0"`. `__version__` of the Python package is `"0.1.0"`.** These are different concepts and must never be equal by accident. The format version reflects the stability of the PBOM open standard; the package version reflects the maturity of this Python implementation. Hardcode `PBOM_VERSION = "1.0.0"` as a module-level constant in `schema.py`. Do not derive one from the other.

---

## Concurrency

8. **Chain state is thread-safe via `threading.Lock`.** Every read and every write of `_previous_entry_hash` and `_chain_sequence` happens inside the lock. No exceptions for "fast paths."

---

## Scope discipline

9. **No proprietary feature code in this package.** No gate logic, no risk scoring, no threat assessment, no enforcement decisions, no attestation signing. The `PBOMRecord` has an `extensions: dict[str, Any]` field; proprietary content from any source goes there. The OSS package preserves the `extensions` dict on read but **does not produce content into it** and does not validate its shape beyond confirming it's a dict.

10. **No dependencies beyond `pydantic` and `click` in the core package.** Dev dependencies (`pytest`, `ruff`, `pytest-cov`) are fine. No `tiktoken`. No `cryptography`. No `requests`. No `httpx`. No `numpy`. If a feature requires another dependency, the feature is out of scope for OSS.

---

## Code hygiene

11. **No `print()` in library code.** Use the `logging` module with logger name `"pbom"`. The CLI module (`cli.py`) may use `click.echo` for user-facing output. Library code uses `logger.info`, `logger.warning`, etc.

12. **All file operations use `pathlib.Path`.** No `os.path.join`. No string concatenation for paths. No `open(str_path, ...)` where `str_path` was built by `+`.

13. **Type hints on every public function signature.** Including return types. `Optional[X]` where applicable. `Any` only when genuinely unknowable.

14. **No silent error swallowing.** A bare `except: pass` is a bug. If an error is genuinely expected and ignorable, catch the specific exception class and log at debug level with a comment explaining why.

---

## Documentation

15. **Every public class and function has a docstring.** Docstrings explain *why* and *what*, not just *what*. Be honest about limitations: the post-hoc emitter API does not provide pre-inference cryptographic guarantees, and its docstring must say so plainly.

---

If Claude encounters a tension between an instruction in a prompt and a rule in this constitution, the constitution wins. Claude should say so and ask the developer how to proceed.
