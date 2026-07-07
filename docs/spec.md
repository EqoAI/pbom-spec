# PBOM Specification v1.0.0

## Status

This document defines the PBOM (Prompt Bill of Materials) open format version `1.0.0`.

## 1. Abstract

PBOM is a JSON-LD record format for tamper-evident logging of LLM interactions.
Each record captures prompt metadata, commitment metadata, model metadata, response metadata,
and cryptographic chain linkage to the previous record in the same directory-level chain.

PBOM defines:

- A canonical record structure.
- A commitment model for pre-inference and post-hoc usage.
- A deterministic chain-linking model.
- Storage modes for privacy-preserving versus forensic persistence.
- Validation rules for chain integrity and, where possible, commitment verification.

PBOM does not define implementation-specific policy, risk scoring, enforcement decisions,
or product-specific verdict semantics. Such content belongs in `extensions`.

## 2. Introduction

### 2.1 Problem statement

LLM systems require audit records that preserve:

- What interaction occurred.
- Which model produced output.
- Whether records were modified.
- Whether prompt content can be proven fixed before inference.

Traditional application logs are often mutable, implementation-specific, and difficult
to validate across tools.

### 2.2 PBOM goals

PBOM provides:

- **Tamper evidence** using deterministic per-record hashing and previous-record linkage.
- **Commitment metadata** that can represent both pre-inference and post-hoc workflows.
- **Interoperable structure** via an open JSON-LD schema.
- **Privacy flexibility** through storage modes (`fingerprint`, `forensic`).

### 2.3 Non-goals

PBOM does not define:

- Product gating or approval logic.
- Risk or threat scoring semantics.
- Any commercial or hosted-product-specific feature set.
- Any mandatory remote service dependency.

## 3. Conventions

### 3.1 RFC 2119 keywords

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**,
**SHOULD NOT**, **RECOMMENDED**, **NOT RECOMMENDED**, **MAY**, and **OPTIONAL**
in this document are to be interpreted as described in RFC 2119.

### 3.2 Data encoding conventions

- All records are UTF-8 JSON text.
- All hashes in PBOM are SHA-256 lowercase hexadecimal strings.
- Canonical JSON for cryptographic operations uses:
  - `sort_keys=True`
  - `separators=(",", ":")`
- Pretty-printed JSON MAY be used for human-readable files, but canonical serialization
  MUST be used when computing hashes and validating links.

## 4. Version

### 4.1 Format version

The PBOM format version defined by this document is:

- `pbom_version = "1.0.0"`

### 4.2 SemVer policy

PBOM follows semantic versioning at the format layer:

- Patch version increments for editorial clarifications and non-structural fixes.
- Minor version increments for backward-compatible additive changes.
- Major version increments for backward-incompatible changes.

### 4.3 Forward compatibility expectations

Implementations SHOULD:

- Reject unknown top-level fields when strict validation is enabled.
- Preserve `extensions` data through read/write round-trips.

## 5. Format

### 5.1 JSON-LD envelope

A PBOM record MUST include:

- `@context`
- `@type`
- `@id`

Default values for core PBOM records:

- `@context = "https://pbom.org/context/v1"`
- `@type = "PBOMRecord"`
- `@id = "urn:uuid:{entry_id}"`

### 5.2 Encoding requirements

- Record files MUST be valid UTF-8 JSON.
- Cryptographic validation MUST use canonical JSON serialization.
- Implementations MUST NOT rely on raw file bytes for chain-hash recomputation.

## 6. Record structure

A PBOM record contains:

- JSON-LD envelope fields (`@context`, `@type`, `@id`)
- Standard sections:
  - `identity`
  - `principal`
  - `commitment`
  - `prompt`
  - `inference`
  - `response`
  - `telemetry`
  - `context_management`
  - `provider_metadata`
  - `structural_analysis`
  - `action_primitives`
  - `extensions`
- Top-level field:
  - `storage_mode`

---

## 6.1 Identity

Section field: `identity`  
Type: `EntryIdentity`  
Required: **REQUIRED**

### 6.1.1 `identity.pbom_version`

- Type: `str`
- Required: **REQUIRED**
- Description: Format version of this record.
- Constraints: MUST equal `"1.0.0"` for this specification.

### 6.1.2 `identity.entry_id`

- Type: `str`
- Required: **REQUIRED**
- Description: Unique identifier for this record.
- Constraints: SHOULD be UUID-formatted text when using reference implementations.

### 6.1.3 `identity.chain_sequence_number`

- Type: `int`
- Required: **REQUIRED**
- Description: Monotonic sequence within the chain directory.
- Constraints: MUST begin at `1` and increase by `1` per record in-chain.

### 6.1.4 `identity.previous_entry_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of previous canonical record.
- Constraints:
  - MUST be `null` for first record (`chain_sequence_number == 1`).
  - MUST be lowercase hex SHA-256 for subsequent records.

### 6.1.5 `identity.created_at_iso`

- Type: `str`
- Required: **REQUIRED**
- Description: UTC timestamp in ISO-8601 format.
- Constraints: SHOULD include millisecond precision when available.

### 6.1.6 `identity.created_at_epoch_ms`

- Type: `int`
- Required: **REQUIRED**
- Description: UTC timestamp in epoch milliseconds.
- Constraints: MUST represent the same instant as `created_at_iso`.

### 6.1.7 `identity.entry_signature`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Reserved for future signing support.
- Constraints: MAY be `null` in v1.0.0.

---

## 6.2 Principal

Section field: `principal`  
Type: `Principal`  
Required: **REQUIRED**

### 6.2.1 `principal.application_id`

- Type: `str`
- Required: **REQUIRED**
- Description: Identifier of the application emitting records.

### 6.2.2 `principal.sdk_name`

- Type: `str`
- Required: **REQUIRED**
- Description: SDK identity string.

### 6.2.3 `principal.sdk_version`

- Type: `str`
- Required: **REQUIRED**
- Description: SDK version string used for record emission.

---

## 6.3 Commitment

Section field: `commitment`  
Type: `CryptographicCommitment`  
Required: **REQUIRED**

### 6.3.1 `commitment.commitment_type`

- Type: `Literal["pre_inference", "post_hoc"]`
- Required: **REQUIRED**
- Description: Commitment mode.
- Constraints:
  - `"pre_inference"` indicates commitment constructed before inference.
  - `"post_hoc"` indicates commitment constructed after inference.

### 6.3.2 `commitment.nonce`

- Type: `str`
- Required: **REQUIRED**
- Description: Nonce used in commitment hash input.
- Constraints:
  - SHOULD be 16 random bytes hex-encoded (32 lowercase hex chars).

### 6.3.3 `commitment.commitment_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of canonical prompt text concatenated with nonce.
- Constraints:
  - If non-null, MUST be lowercase hex SHA-256.

### 6.3.4 `commitment.commitment_ts`

- Type: `int`
- Required: **REQUIRED**
- Description: Commitment timestamp (epoch ms).

### 6.3.5 `commitment.nonce_revealed_ts`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Reveal timestamp (epoch ms).
- Constraints:
  - If non-null, MUST satisfy `commitment_ts < nonce_revealed_ts`.

### 6.3.6 `commitment.commitment_verified`

- Type: `bool`
- Required: **REQUIRED**
- Description: Whether commitment hash verification succeeded.
- Constraints:
  - For post-hoc records produced by reference emitter APIs, SHOULD be `false`.

---

## 6.4 Prompt

Section field: `prompt`  
Type: `PromptRecord`  
Required: **REQUIRED**

### 6.4.1 `prompt.raw_content`

- Type: `RawContent`
- Required: **REQUIRED**
- Description: Prompt hashes, token counts, and optional raw text.

#### 6.4.1.1 `prompt.raw_content.system_prompt_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of system prompt text.
- Constraints: If non-null, MUST be lowercase hex SHA-256.

#### 6.4.1.2 `prompt.raw_content.user_prompt_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of user prompt text.
- Constraints: If non-null, MUST be lowercase hex SHA-256.

#### 6.4.1.3 `prompt.raw_content.full_prompt_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of canonical two-message prompt JSON.
- Constraints:
  - Canonical prompt JSON MUST use `sort_keys=True, separators=(",", ":")`.
  - If non-null, MUST be lowercase hex SHA-256.

#### 6.4.1.4 `prompt.raw_content.system_prompt_token_count`

- Type: `int`
- Required: **REQUIRED**
- Description: Token count estimate for system prompt.

#### 6.4.1.5 `prompt.raw_content.total_input_token_count`

- Type: `int`
- Required: **REQUIRED**
- Description: Token count estimate for total prompt input.

#### 6.4.1.6 `prompt.raw_content.system_prompt_text`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Raw system prompt.
- Constraints:
  - MUST be `null` in `fingerprint` mode.
  - MAY be non-null in `forensic` mode.

#### 6.4.1.7 `prompt.raw_content.user_prompt_text`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Raw user prompt.
- Constraints:
  - MUST be `null` in `fingerprint` mode.
  - MAY be non-null in `forensic` mode.

### 6.4.2 `prompt.template`

- Type: `Optional[PromptTemplate]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Template metadata when templating is used.

#### 6.4.2.1 `prompt.template.template_id`

- Type: `str`
- Required: **REQUIRED** when template non-null
- Description: Template identifier.

#### 6.4.2.2 `prompt.template.template_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** when template non-null (key present, value nullable)
- Description: Hash of canonical template representation.
- Constraints: If non-null, MUST be lowercase hex SHA-256.

#### 6.4.2.3 `prompt.template.prompt_construction_method`

- Type: `str`
- Required: **REQUIRED** when template non-null
- Description: Method descriptor for prompt construction.

### 6.4.3 `prompt.structural_fingerprint`

- Type: `Optional[StructuralFingerprint]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional prompt intent classification.

#### 6.4.3.1 `prompt.structural_fingerprint.prompt_intent_classification`

- Type: `str`
- Required: **REQUIRED** when structural_fingerprint non-null
- Description: Classifier label for prompt intent.

---

## 6.5 Inference

Section field: `inference`  
Type: `InferenceMetadata`  
Required: **REQUIRED**

### 6.5.1 `inference.model_id`

- Type: `str`
- Required: **REQUIRED**
- Description: Model identifier used for inference.

### 6.5.2 `inference.model_family`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional family label.

### 6.5.3 `inference.model_provider`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional provider label.

### 6.5.4 `inference.temperature`

- Type: `Optional[float]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional sampling temperature.

### 6.5.5 `inference.max_tokens`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional output token cap.

### 6.5.6 `inference.streaming`

- Type: `Optional[bool]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional streaming flag.

### 6.5.7 `inference.context_window_max`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional maximum context window.

### 6.5.8 `inference.context_utilization_pct`

- Type: `Optional[float]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional utilization ratio.

---

## 6.6 Response

Section field: `response`  
Type: `ResponseRecord`  
Required: **REQUIRED**

### 6.6.1 `response.response_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Hash of response text.
- Constraints: If non-null, MUST be lowercase hex SHA-256.

### 6.6.2 `response.response_token_count`

- Type: `int`
- Required: **REQUIRED**
- Description: Response token count estimate.

### 6.6.3 `response.stop_reason`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Provider-defined completion reason.

### 6.6.4 `response.thinking_token_count`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional internal reasoning token count.

### 6.6.5 `response.response_text`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Raw response text.
- Constraints:
  - MUST be `null` in `fingerprint` mode.
  - MAY be non-null in `forensic` mode.

---

## 6.7 Telemetry

Section field: `telemetry`  
Type: `Telemetry`  
Required: **REQUIRED**

### 6.7.1 `telemetry.total_latency_ms`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional end-to-end latency measurement.

### 6.7.2 `telemetry.inference_latency_ms`

- Type: `Optional[int]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional inference-only latency measurement.

---

## 6.8 Context Management

Section field: `context_management`  
Type: `Optional[ContextManagement]`  
Required: **REQUIRED** (key present, value nullable)

### 6.8.1 `context_management.conversation_turn_count`

- Type: `int`
- Required: **REQUIRED** when section non-null
- Description: Conversation turn index/count.

### 6.8.2 `context_management.history_token_count`

- Type: `int`
- Required: **REQUIRED** when section non-null
- Description: Tokens attributable to history.

### 6.8.3 `context_management.history_message_count`

- Type: `int`
- Required: **REQUIRED** when section non-null
- Description: Messages attributable to history.

### 6.8.4 `context_management.prompt_cache_hit`

- Type: `bool`
- Required: **REQUIRED** when section non-null
- Description: Whether prompt cache hit occurred.

---

## 6.9 Provider Metadata

Section field: `provider_metadata`  
Type: `Optional[ProviderMetadata]`  
Required: **REQUIRED** (key present, value nullable)

### 6.9.1 `provider_metadata.provider_name`

- Type: `str`
- Required: **REQUIRED** when section non-null
- Description: Provider identifier.

### 6.9.2 `provider_metadata.api_version`

- Type: `str`
- Required: **REQUIRED** when section non-null
- Description: API version identifier.

### 6.9.3 `provider_metadata.request_id`

- Type: `str`
- Required: **REQUIRED** when section non-null
- Description: Provider request identifier.

---

## 6.10 Structural Analysis

Section field: `structural_analysis`  
Type: `Optional[StructuralAnalysis]`  
Required: **REQUIRED** (key present, value nullable)

### 6.10.1 `structural_analysis.output_type`

- Type: `str`
- Required: **REQUIRED** when section non-null
- Description: Output classification (for example, text/code).

### 6.10.2 `structural_analysis.language`

- Type: `str`
- Required: **REQUIRED** when section non-null
- Description: Primary language label.

### 6.10.3 `structural_analysis.raw_hash`

- Type: `Optional[str]`
- Required: **REQUIRED** when section non-null (key present, value nullable)
- Description: Optional hash for structural-analysis source content.
- Constraints: If non-null, MUST be lowercase hex SHA-256.

### 6.10.4 `structural_analysis.imports`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected imports.

### 6.10.5 `structural_analysis.function_calls`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected function calls.

### 6.10.6 `structural_analysis.file_operations`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected file operations.

### 6.10.7 `structural_analysis.network_calls`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected network calls.

### 6.10.8 `structural_analysis.system_commands`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected system command usage.

### 6.10.9 `structural_analysis.env_access`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Detected environment access.

### 6.10.10 `structural_analysis.parse_errors`

- Type: `list[str]`
- Required: **REQUIRED** when section non-null
- Description: Parsing/analysis errors.

---

## 6.11 Action Primitives

Section field: `action_primitives`  
Type: `list[ActionPrimitiveDetection]`  
Required: **REQUIRED** (empty list allowed)

### 6.11.1 ActionPrimitive enum (19 values)

Allowed primitive values:

1. `DATA_READ`
2. `DATA_WRITE`
3. `DATA_DELETE`
4. `DATA_EXFILTRATION`
5. `NETWORK_OUTBOUND`
6. `NETWORK_INBOUND`
7. `FILE_SYSTEM_READ`
8. `FILE_SYSTEM_WRITE`
9. `FILE_SYSTEM_DELETE`
10. `AUTH_ESCALATION`
11. `AUTH_DELEGATION`
12. `TOOL_INVOCATION`
13. `STATE_MUTATION`
14. `PII_ACCESS`
15. `PII_EXPOSURE`
16. `SECRET_ACCESS`
17. `FINANCIAL_TXN`
18. `CONFIG_CHANGE`
19. `HUMAN_COMMUNICATION`

### 6.11.2 ActionPrimitiveDetection model

#### 6.11.2.1 `primitive`

- Type: `ActionPrimitive`
- Required: **REQUIRED**
- Description: Canonical primitive label.

#### 6.11.2.2 `confidence`

- Type: `float`
- Required: **REQUIRED**
- Description: Detection confidence.
- Constraints: MUST be within `[0.0, 1.0]`.

#### 6.11.2.3 `evidence`

- Type: `str`
- Required: **REQUIRED**
- Description: Supporting evidence text.

#### 6.11.2.4 `location`

- Type: `Optional[str]`
- Required: **REQUIRED** (key present, value nullable)
- Description: Optional source-location hint.

#### 6.11.2.5 `risk_level`

- Type: `Literal["low", "medium", "high", "critical"]`
- Required: **REQUIRED**
- Description: Severity label.

#### 6.11.2.6 `category`

- Type: `Literal["DATA_OPERATIONS", "NETWORK", "FILE_SYSTEM", "AUTHENTICATION", "EXECUTION", "SENSITIVE_DATA", "EXTERNAL"]`
- Required: **REQUIRED**
- Description: Canonical primitive category.

---

## 6.12 Extensions

Section field: `extensions`  
Type: `dict[str, Any]`  
Required: **REQUIRED** (empty object allowed)

### 6.12.1 Purpose

`extensions` is the standard location for non-core, implementation-specific metadata.
This preserves interoperability while allowing additional information where needed.

### 6.12.2 Validation expectations

- Core PBOM validation MUST treat `extensions` as opaque.
- Implementations MAY preserve unknown extension keys and values unchanged.
- PBOM core schema does not define nested `extensions` shape.

### 6.12.3 Emission expectations

The OSS reference implementation:

- Preserves `extensions` through round-trips.
- Does not validate `extensions` shape beyond object/dict typing.
- Does not emit implementation-specific content into `extensions`.

---

## 6.13 Top-level fields

Beyond JSON-LD envelope fields and the standard sections above, the open standard defines exactly:

### 6.13.1 `storage_mode`

- Type: `Literal["fingerprint", "forensic"]`
- Required: **REQUIRED**
- Description: Controls whether raw prompt/response text is stored.

### 6.13.2 Explicit exclusion of non-standard legacy fields

The following are **NOT** part of the PBOM open standard top-level schema:

- `origin`
- `verdict`
- `timestamp`
- `pbom_signature`

Implementations requiring those semantics SHOULD encode them under `extensions`.

## 7. Commitment scheme

### 7.1 Canonical prompt serialization

For commitment construction and verification, prompt text MUST be:

```python
messages = [
  {"role": "system", "content": system_prompt},
  {"role": "user", "content": user_prompt},
]
prompt_text = json.dumps(messages, sort_keys=True, separators=(",", ":"))
```

### 7.2 Hash function

Commitment hash input:

- `prompt_text + nonce`

Commitment hash output:

- `SHA-256` over UTF-8 bytes
- lowercase hex digest

### 7.3 Pre-inference mode (`commitment_type="pre_inference"`)

Required ordering:

1. Create nonce.
2. Compute commitment hash.
3. Record `commitment_ts`.
4. Perform inference.
5. Record `nonce_revealed_ts`.
6. Enforce `commitment_ts < nonce_revealed_ts`.

### 7.4 Post-hoc mode (`commitment_type="post_hoc"`)

Post-hoc records are created after inference.
They provide timestamp anchoring and chain linkage but do not provide proof that prompt
was fixed before model execution.

### 7.5 Verification result semantics

- `True`: recomputed hash matches stored `commitment_hash`.
- `False`: recomputed hash does not match.
- Unverifiable (`None` in validator API): prompt raw text unavailable (fingerprint mode).

## 8. Chain linking

### 8.1 Chain scope

Chain state is directory-scoped.
All records in one target directory are part of the same chain regardless of `application_id`.

### 8.2 Link rule

For each record `n > 1`:

- `record[n].identity.previous_entry_hash` MUST equal canonical hash of record `n-1`.

### 8.3 Canonical hash recomputation rule

Validators MUST NOT hash raw file bytes.
Validators MUST:

1. Parse JSON.
2. Serialize canonical JSON (`sort_keys=True, separators=(",", ":")`).
3. Compute SHA-256 over UTF-8 bytes.

### 8.4 Resume semantics

When resuming chain state from disk:

- Records are sorted by `chain_sequence_number`.
- Duplicate sequence numbers MUST fail validation.
- Sequence gaps MUST fail validation.
- Broken previous-hash links MUST fail validation.
- Highest valid sequence/hash become resumed chain head.

## 9. Storage modes

### 9.1 `fingerprint` mode

- Raw prompt/response text MUST NOT be persisted.
- Hashes and metadata remain available.
- Commitment verification from stored records is generally not possible.

### 9.2 `forensic` mode

- Raw prompt and response text MAY be persisted alongside hashes.
- Commitment verification is possible from record content.

### 9.3 Consistency requirements

In all modes:

- Hash fields SHOULD remain populated.
- `storage_mode` MUST reflect actual record persistence mode.

## 10. Validation rules

### 10.1 Chain integrity checks

A structurally valid chain requires:

- No unreadable `.pbom.json` files.
- No duplicate `chain_sequence_number`.
- No sequence gaps.
- No broken previous-hash links.

### 10.2 Commitment checks

Commitment checks are reported independently from chain integrity.
A chain MAY be structurally valid even when some commitments are unverifiable
because records are in `fingerprint` mode.

### 10.3 Empty and single-record chains

- Empty directory: valid chain (`total_records = 0`).
- Single record: valid chain with `valid_links = 0`.

## 11. Extension namespace conventions

### 11.1 Key naming

Implementations SHOULD use dot-namespaced extension keys, for example:

- `mytool.gate_verdict`
- `acme.risk_score`

### 11.2 Conflict avoidance

Namespace prefixes SHOULD be stable per producing tool to minimize collisions.

### 11.3 Interoperability

Tools processing PBOM records SHOULD preserve unknown extension keys and values
without modification.

### 11.4 OSS reference implementation behavior

The OSS reference implementation:

- Preserves the `extensions` dict through read/write round-trips.
- Does not validate extension payload shape.
- Does not emit implementation-specific extension content.

## 12. Security model

PBOM provides **tamper-evidence relative to an external anchor**. This section
specifies the guarantee PBOM makes, the conditions under which it holds, and the
verifier configuration required to obtain each property.

These properties hold under a threat model in which an adversary MAY read,
modify, reorder, or delete records within a `.pbom/` directory, but cannot alter
a reference value the verifier holds outside that directory. Where a property
requires such an external reference, this section states so explicitly.

### 12.1 Tamper-evidence and the external anchor

Chain linking (§8) makes in-place modification of a record detectable: changing
a record changes its canonical hash (§8.3), which breaks the
`previous_entry_hash` link (§6.1.4) stored by the next record. A verifier that
recomputes the chain observes the break.

To obtain this guarantee against a deliberate adversary, a verifier MUST hold at
least one record hash acquired independently of the `.pbom/` directory. This
independently held value is the **anchor** — for example, the hash of the latest
record committed to an append-only log, an external timestamping service, or a
separate system.

- With an anchor, any modification to the anchored record or to any earlier
  record is detectable.
- Without an anchor, a party holding the complete `.pbom/` directory can modify
  a record and recompute every subsequent hash, yielding a chain that is
  internally consistent. Internal consistency therefore demonstrates that
  records have not been accidentally corrupted; the anchor is what additionally
  demonstrates they have not been deliberately rewritten.

Verifiers that require tamper-evidence against a motivated adversary MUST anchor.

### 12.2 Record authentication

In v1.0.0, `identity.entry_signature` is `null` (§6.1.7): records are not
cryptographically signed. The chain proves **linkage** — that records form an
unbroken, ordered sequence — but not **authorship**; it does not by itself
establish which party produced a record.

Per-record signing is reserved for a future version. A deployment that needs to
constrain who may write records provides that property through its own controls,
for example:

- Filesystem or storage permissions on the `.pbom/` directory.
- Append-only or write-once storage for emitted records.
- Access controls on the process or service that emits records.

PBOM records the interaction; the surrounding deployment establishes trust in
who recorded it.

### 12.3 Truncation detection

Every record that has a successor is fixed by that successor's
`previous_entry_hash`. The final record in a chain has no successor, so removing
one or more records from the *end* of a chain yields a shorter chain that
remains internally consistent.

To detect tail truncation, a verifier MUST compare the chain against an
externally held reference — either the expected `chain_sequence_number` of the
latest record or the anchor of §12.1. A chain whose highest sequence number is
below that reference has been truncated.

Removal of records from the *middle* or *beginning* of a chain requires no
external reference to detect: it produces a sequence gap or a broken link, which
validation reports (§10.1).

## Appendix A. JSON Schema reference

The canonical JSON Schema is generated from the implementation model:

```bash
pbom export-schema docs/schema/pbom-v1.0.0.json
```

Schema file reference:

- `docs/schema/pbom-v1.0.0.json`

This specification references that generated schema file rather than embedding
the full schema inline.

## Appendix B. Example record reference

Reference fixture:

- `docs/examples/example-record.json`

This fixture demonstrates:

- The first record in a chain (`chain_sequence_number = 1`).
- `fingerprint` storage mode.
- `pre_inference` commitment type.
- Real UUID/timestamps/hashes produced by code execution.

The full record is intentionally referenced by file path rather than embedded inline.
