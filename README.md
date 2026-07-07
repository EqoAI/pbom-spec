# PBOM

PBOM is the open standard for tamper-evident LLM audit trails. This package is the reference implementation.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
[![CI](https://github.com/eqo/pbom-spec/actions/workflows/ci.yml/badge.svg)](https://github.com/eqo/pbom-spec/actions/workflows/ci.yml)

## What is PBOM?

PBOM (Prompt Bill of Materials) is an open JSON-LD format for recording LLM interactions as tamper-evident records. Each record captures identity, prompt fingerprints, model metadata, response fingerprints, telemetry, and hash links to prior records.

**Security model.** PBOM provides tamper-evidence *relative to an external anchor*. Chain linking makes in-place modification and mid-chain deletion detectable on their own; detecting deliberate rewriting or truncation of the chain requires holding one record hash outside the `.pbom/` directory. Records are unsigned in v1.0.0 — the chain proves linkage, not authorship. See [Security model](docs/spec.md#12-security-model) in the specification for the full treatment.

The goal is: make LLM interactions auditable without locking teams into one provider or one runtime. PBOM gives you verifiable evidence about what was sent and what came back, while keeping storage mode flexible (`fingerprint` vs `forensic`) and extension-friendly.

## Why PBOM?

Software supply chains have the SBOM. Machine-learning systems have the ML-BOM. Both inventory *static* artifacts — code dependencies, model weights, datasets — and neither captures the thing that actually shaped a given LLM output: the prompt, the model version, and the parameters at inference time.

That layer usually lives only in application logs, if it's recorded at all — raw text, often PII-heavy, with no integrity guarantee and no link from one call to the next. When you later need to answer "what exactly did we send, which model answered, and has this record been altered since," logs can't prove it.

PBOM fills that gap at the inference boundary: a per-call record that fingerprints the prompt and response, pins the model, and hash-links to the record before it — so the audit trail is verifiable, not just present.

## Quick Start

```bash
pip install pbom
pbom init
```

```python
from pbom import PBOMEmitter
emitter = PBOMEmitter(application_id="demo-app", storage_mode="fingerprint")
with emitter.commit(system_prompt="You are concise.", user_prompt="Summarize PBOM.") as commit:
    response_text = call_your_llm()  # your LLM client call
    record = commit.complete(response_text=response_text, model_id="gpt-4.1")
print(record.identity.entry_id)
print(record.commitment.commitment_verified)
```

```bash
pbom validate .pbom/
```

## The Two APIs

- **API 1: `PBOMEmitter.commit(...)` (context manager)**  
  Pre-inference commitment flow. You commit prompt material before model execution, then complete the record after receiving the response.
- **API 2: `PBOMEmitter.record(...)` (single call)**  
  Post-hoc record creation. Useful for existing pipelines, but it does **not** provide pre-inference guarantees.

See the specification and examples for full semantics and edge cases.

## CLI Commands

| Command | Purpose |
| --- | --- |
| `pbom init` | Create and initialize a local PBOM chain directory. |
| `pbom validate <dir>` | Validate chain integrity and commitment status for a PBOM directory. |
| `pbom status <dir>` | Show chain status summary (record count, head info). |
| `pbom export-schema <path>` | Export the PBOM JSON Schema to a file. |

## What's Captured

| Section | What it captures | Presence |
| --- | --- | --- |
| `identity` | Record ID, chain sequence, timestamps, previous hash pointer | Always present |
| `principal` | Emitting application and SDK identity/version | Always present |
| `commitment` | Commitment mode, nonce, commitment hash, verification timing | Always present |
| `prompt` | Prompt hashes, token counts, optional raw prompt text | Always present |
| `inference` | Model ID and optional runtime inference settings | Always present |
| `response` | Response hash, token counts, stop reason, optional raw text | Always present |
| `telemetry` | Optional end-to-end and inference latency measurements | Always present |
| `context_management` | Optional history/cache metadata | Optional (nullable) |
| `provider_metadata` | Optional provider request metadata | Optional (nullable) |
| `structural_analysis` | Optional machine-readable output analysis | Optional (nullable) |
| `action_primitives` | Canonical action detections with confidence/evidence | Optional (empty list default) |
| `extensions` | Implementation-specific metadata outside core PBOM fields | Always present |
| `storage_mode` | Whether raw content is omitted (`fingerprint`) or retained (`forensic`) | Always present |

## What This Package Is NOT

- **Not an LLM client wrapper**  
  You call your model/provider SDK directly, then call PBOM to commit/record results.
- **Not a policy engine**  
  No gating or risk-scoring decisions are performed here. If you want that layer, build it separately and store outputs in `extensions`.
- **Not a hosted service**  
  PBOM records are local JSON files. You own storage, transport, and retention.

If you want all-in-one model routing, enforcement, and hosted analytics today, this is not that.

## Documentation

- [PBOM specification (`docs/spec.md`)](docs/spec.md)
- [Field-by-field guide (`docs/fields.md`)](docs/fields.md)
- [Examples (`examples/`)](examples/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0. See [LICENSE](LICENSE).

---

Built and maintained by Eqo. PBOM is an open standard; anyone may implement it.
