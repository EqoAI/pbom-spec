---
name: pbom
description: Correct usage of the installed 'pbom' Python package (Prompt Bill of Materials) — tamper-evident, hash-chained JSON audit records for LLM calls via PBOMEmitter. Load this when instrumenting or adding audit logging to LLM calls, wrapping an LLM call to record what was asked/answered, or running 'pbom validate'/'pbom status'/'pbom records'. This skill is the authority on the pbom API; do not web-search it. Not needed for unrelated tasks.
---

# Using PBOM (Prompt Bill of Materials)

PBOM produces tamper-evident, hash-chained JSON audit records for LLM interactions. Each record captures what was asked, what was answered, and cryptographic proof the record was not altered, linked to the previous record in a Merkle chain. This skill tells you how to use the package correctly. The package records and verifies; it does not call LLMs and does not make policy decisions.

## What PBOM is NOT

- **NOT an LLM client.** You call your own LLM. PBOM records the call. It never makes a network request of any kind.
- **NOT a policy engine.** No gating, risk scoring, or threat assessment. If a tool needs to attach such data, it goes in the record's `extensions` dict — PBOM preserves it but never produces it.
- **NOT a hosted service.** Records are local JSON files under `.pbom/`. Ship them wherever you want.

## Core usage: prefer the context-manager API

There are two ways to emit a record. They have **different security guarantees**, and the choice is not stylistic.

**Decision rule — read before choosing:**
- If you are writing new code, OR you can see and reach the LLM call site, you **MUST** use API 1 (`commit()`). This is the default and the overwhelming majority of cases.
- API 2 (`record()`) is **only** for a call you genuinely cannot wrap in the context manager — e.g. the LLM call already ran in code you don't control and only its persisted output remains. "The call site is nested," "wrapping it is a refactor," or "a `with` block is inconvenient" do **NOT** qualify as "cannot." Inconvenience is not impossibility.
- If you find yourself reaching for API 2 to avoid restructuring, stop — that is the case the rule exists to prevent. Restructure and use API 1.

### API 1 — `commit()` context manager (PREFERRED)

This creates a cryptographic commitment to the prompt **before** the LLM call, giving genuine pre-inference proof the prompt was fixed before the model saw it.

```python
from pbom import PBOMEmitter

emitter = PBOMEmitter(application_id="my-agent")

with emitter.commit(system_prompt, user_prompt) as c:
    response = your_llm_client.chat.completions.create(...)   # YOUR call, not PBOM's
    record = c.complete(
        model_id="openai/gpt-4o",
        response_text=response.choices[0].message.content,
        response_token_count=response.usage.completion_tokens,   # a REAL measured value
        inference_latency_ms=measured_latency_ms,                # timed around YOUR call
    )
```

- `commit()` takes `system_prompt` and `user_prompt` positionally, in that order.
- `complete()` is **keyword-only** — every argument must be named, including `model_id`. `c.complete("openai/gpt-4o", ...)` raises `TypeError`. Always write `c.complete(model_id="openai/gpt-4o", response_text=...)`.
- The commitment is made on `__enter__`, revealed in `complete()`.
- If `complete()` is never called, **no record is written** (an incomplete record is worse than none). The emitter logs a warning and emits nothing.
- `commitment_type` is `"pre_inference"`, `commitment_verified` is `true`.

### API 2 — `record()` post-hoc (WEAKER — say so to the user)

```python
record = emitter.record(
    system_prompt=system_prompt,
    user_prompt=user_prompt,
    model_id="openai/gpt-4o",
    response_text=response_text,
)
```

- `record()` is **keyword-only** — every argument must be named, including `system_prompt` and `user_prompt`. There are no positional arguments.
- Constructs the commitment **after the fact**. `commitment_type` is `"post_hoc"`, `commitment_verified` is `false`.
- This is a **logging convenience, not a security guarantee.** It proves nothing about prompt-fixing order.
- **ALWAYS tell the user this when you use it.** Do not present a post-hoc record as if it carried pre-inference proof. If the user's code can be restructured to use `commit()`, recommend that instead.

## Pass model identifiers as three separate fields

`model_id`, `model_family`, and `model_provider` are **three distinct caller-supplied fields**. NEVER parse `model_id` to derive the other two. If the user only has `model_id`, pass only `model_id` and leave the others unset.

## NEVER fabricate any field — parameters OR measurements

Two classes of field must never be invented:

- **Inference parameters** — `temperature`, `max_tokens`, `streaming`, etc. default to `None`. NEVER fill in a plausible default (e.g. `temperature=0.0`, `max_tokens=512`).
- **Measured values** — `response_token_count`, `inference_latency_ms`, and any other measurement must come from a **real source**: the response object, an actual timer, a real token count. NEVER type in a representative-looking number.

If you do not have a real value for a field, **omit it** — leave it `None`. This is not laziness; it is correctness. A fabricated value in an audit record — whether a parameter or a measurement — is a **falsified audit record**, which defeats the entire purpose of the tool. An absent field is honest; an invented one is a lie with a number on it.

## Constitution hard rules — NEVER violate these

These are inviolable properties of the format. Violating them produces invalid or unsafe records. (These are a renumbered subset of the full constitution in `.claude/constitution.md`; the numbers below are local to this list and do **not** match constitution rule numbers. Cite the constitution by its own numbering when referencing it.)

1. **Hashes are ALWAYS lowercase hex SHA-256 of UTF-8 bytes.** No other algorithm, encoding, or case, anywhere.
2. **Records are append-only.** NEVER modify or delete an existing `*.pbom.json` file. The emitter only creates new files; the validator only reads. No code you write around PBOM should edit a record in place.
3. **Fingerprint mode NEVER stores raw prompt or response text** — not in a field, not in a comment, not in `extensions`, not "just for debugging." Only hashes persist. If the user needs raw text stored, they must explicitly choose `storage_mode="forensic"`.
4. **The package makes ZERO outbound network calls.** No telemetry, no phone-home, no update checks. If you find yourself adding a network call "to PBOM," you are doing something wrong.
5. **Two version numbers, never equal.** `pbom_version` in records is the format version (`"1.0.0"`); `__version__` of the Python package is the implementation version (currently 0.1.x, defined in pyproject.toml). They are independent. NEVER derive one from the other or assume they match.
6. **NEVER write into `extensions` and call it standard.** Any namespaced data a tool adds (e.g. `extensions["mytool.verdict"]`) is non-standard by definition. PBOM preserves it on round-trip but does not validate or produce it.

## Adopter setup

### Initialization and chain resume

The chain is **per-directory, not per-application.** All records written to the same `.pbom/` directory form one chain, regardless of `application_id`.

`PBOMEmitter` **automatically resumes the existing chain from disk on initialization.** Across process restarts, a new emitter pointed at an existing `.pbom/` continues the sequence correctly (e.g. existing records `[1, 2, 3]` → next record is `4`) and the chain stays valid. **You do NOT need to call `resume_from()` for the common case.**

The only time to call `resume_from()` explicitly is when a power user constructs and manages their own `ChainState` instance separately from the default emitter flow:

```python
from pbom.chain import ChainState
from pathlib import Path

chain = ChainState()
chain.resume_from(Path(".pbom"))   # only needed for a manually-managed ChainState
```

If the on-disk chain is corrupted (gaps, duplicate sequence numbers, or a broken hash link), resume raises `ChainCorruptedError` rather than silently recovering. Surface that error to the user; do not suppress it.

### Storage modes

- **`fingerprint`** (default): hashes only, no raw content. Privacy-preserving. Commitments **cannot** be re-verified at validation time because the prompt text needed to recompute the hash isn't stored — this is expected, not a failure.
- **`forensic`** (opt-in): stores raw prompt/response text alongside hashes. Only choose this when the user explicitly wants recoverable content and has accepted the privacy implication.

Storage mode is set on the **constructor**, not anywhere else:

```python
emitter = PBOMEmitter(application_id="my-agent", storage_mode="forensic")
```

**Critical — `pbom init` config and the constructor are independent.** `pbom init` writes a `storage_mode` into `.pbom/config.json`, but **the emitter does not read that file.** Storage mode is determined *solely* by the `storage_mode` constructor argument, which defaults to `"fingerprint"`. Editing `config.json` to `"forensic"` does **nothing** to the emitter — you will silently get fingerprint records while believing they are forensic. To store raw content you MUST pass `storage_mode="forensic"` to `PBOMEmitter(...)`. Do not rely on the config file for this.

If PBOM was initialized into a non-default directory, also point the emitter there with `output_dir=`, matching the directory `pbom init` created:

```python
emitter = PBOMEmitter(application_id="my-agent", output_dir="audit/.pbom", storage_mode="forensic")
```

Choose the mode deliberately. Defaulting a user into `forensic` without their say-so leaks prompt content to disk.

## CLI + CI validation workflow

```bash
pbom init                 # create .pbom/ + config + .gitignore entry
pbom validate [dir]       # verify chain integrity; exit 0 if valid, 1 if not. Default: .pbom/
pbom status [dir]         # chain stats: record count, chain health, sequence range
pbom records [dir]        # read records: latest 10 (-n N), one in detail (-r SEQ), or --format json
pbom export-schema [path] # write the PBOMRecord JSON Schema to disk
```

### Interpreting `validate` output

- `is_valid` reflects **chain integrity only** — broken hash links, sequence gaps, duplicate sequence numbers, or unreadable files set it to `false`.
- `is_valid` does **NOT** depend on commitment results. In fingerprint mode every record is `unverifiable` (no stored text to recompute against); this is normal and does NOT make a valid chain report as broken.
- A `failed` commitment count above zero (only possible in forensic mode) means a stored prompt no longer matches its commitment hash — that IS a real tamper signal worth surfacing loudly.

Example `pbom validate` output on a fingerprint-mode chain (captured from a real run):

```text
Validation: PASS
Directory: .pbom
Records: 2
Chain links: 1/1 valid (first record has no predecessor)
Commitments: verified=0 unverifiable=2 failed=0
  note: unverifiable commitments can't be recomputed from stored data (expected when storage_mode is fingerprint, which keeps hashes, not prompt text). Commitment status does not affect the Validation result.
```

### Gating CI on chain validity

```python
from pathlib import Path
from pbom import validate_chain

result = validate_chain(Path(".pbom"))
assert result.is_valid, f"PBOM chain invalid: {result.details}"
```

Or use the CLI exit code directly: `pbom validate` returns `1` on an invalid chain, so `pbom validate || exit 1` fails the build.

## When in doubt

- The format and its guarantees are defined in `docs/spec.md` (formal) and `docs/fields.md` (plain-English). Match those, not assumptions.
- If a user asks PBOM to do something it is not (call an LLM, score risk, host records), explain the scope boundary and point them at the `extensions` dict or their own analysis layer.
- Never weaken a guarantee to make a task easier. If a constraint above makes something hard, that constraint is the point.