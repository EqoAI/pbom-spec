# PBOM Fields Guide (Plain-English Companion)

This is the developer-friendly companion to `docs/spec.md`.  
Think of it as "what each field means in practice" instead of "formal rules language."

Two mental models help:

- The **commitment** is like a **sealed envelope at a notary**: you lock in what you claim before (or after) generation, and later prove whether it matches.
- The **chain** is like a **blockchain for LLM calls** (without consensus/mining): each record points to the previous one by hash, so in-place edits and mid-chain deletions become detectable. Detecting deliberate rewriting or removal from the *end* of the chain requires an external reference — see the [Security model](spec.md#12-security-model) section of the spec for how that works.

## 6.1 Identity (`identity`)

This section captures **who this record is in the chain, and when it was created**.

**Presence rule:** Always present

- `identity.pbom_version`: The PBOM format version this record follows (for this spec, `1.0.0`).
- `identity.entry_id`: A unique ID for this single record (typically UUID text).
- `identity.chain_sequence_number`: The position in the chain (`1`, `2`, `3`, ...).
- `identity.previous_entry_hash`: The hash pointer to the previous record; `null` only on the first record.
- `identity.created_at_iso`: Human-readable UTC timestamp (ISO-8601).
- `identity.created_at_epoch_ms`: Same creation time as epoch milliseconds (machine-friendly).
- `identity.entry_signature`: Reserved for future signatures; usually `null` in v1.0.0.

## 6.2 Principal (`principal`)

This section captures **which app and SDK emitted the record**.

**Presence rule:** Always present

- `principal.application_id`: Your app/service identifier that is generating PBOM records.
- `principal.sdk_name`: The name of the PBOM-emitting SDK or component.
- `principal.sdk_version`: The version of that SDK/component.

## 6.3 Commitment (`commitment`)

This section captures **cryptographic proof metadata for the prompt you used**.

**Presence rule:** Always present

- `commitment.commitment_type`: Either:
  - `pre_inference`: committed before model execution (stronger timing guarantee), or
  - `post_hoc`: committed after execution (audit trail, but weaker pre-execution proof).
- `commitment.nonce`: Random salt used in the commitment hash, so identical prompts do not always produce identical commitment hashes.
- `commitment.commitment_hash`: SHA-256 hash of `(canonical prompt JSON + nonce)` when available.
- `commitment.commitment_ts`: Epoch ms time when commitment was created.
- `commitment.nonce_revealed_ts`: Epoch ms time when reveal happened; for pre-inference, should be later than `commitment_ts`.
- `commitment.commitment_verified`: Whether recomputation succeeded for this record.

## 6.4 Prompt (`prompt`)

This section captures **what was asked (as hashes, counts, and optionally raw text)**.

**Presence rule:** Always present

### `prompt.raw_content`

Core prompt fingerprint and optional raw prompt content.

- `prompt.raw_content.system_prompt_hash`: SHA-256 of system prompt text (if present).
- `prompt.raw_content.user_prompt_hash`: SHA-256 of user prompt text (if present).
- `prompt.raw_content.full_prompt_hash`: SHA-256 of canonical two-message prompt JSON.
- `prompt.raw_content.system_prompt_token_count`: Token estimate for system prompt.
- `prompt.raw_content.total_input_token_count`: Token estimate for total input prompt.
- `prompt.raw_content.system_prompt_text`: Raw system prompt text. Must be `null` in `fingerprint` mode; may be present in `forensic`.
- `prompt.raw_content.user_prompt_text`: Raw user prompt text. Must be `null` in `fingerprint` mode; may be present in `forensic`.

### `prompt.template`

Template metadata, if your application builds prompts from templates.

- `prompt.template.template_id`: Template identifier.
- `prompt.template.template_hash`: Optional hash of template representation.
- `prompt.template.prompt_construction_method`: Description of how the final prompt was constructed.

If no template is used, `prompt.template` is `null`.

### `prompt.structural_fingerprint`

Optional intent-style fingerprint of the prompt.

- `prompt.structural_fingerprint.prompt_intent_classification`: Label such as "classification", "summarization", "code_generation", etc., depending on your classifier.

If no classifier output is available, `prompt.structural_fingerprint` is `null`.

## 6.5 Inference (`inference`)

This section captures **how the model was configured and what context limits were relevant**.

**Presence rule:** Always present

- `inference.model_id`: Exact model identifier used.
- `inference.model_family`: Optional family label (for example, model family grouping).
- `inference.model_provider`: Optional provider label.
- `inference.temperature`: Optional temperature value used for sampling.
- `inference.max_tokens`: Optional output token limit.
- `inference.streaming`: Optional flag indicating whether streaming mode was used.
- `inference.context_window_max`: Optional maximum context window size.
- `inference.context_utilization_pct`: Optional utilization ratio of context window.

## 6.6 Response (`response`)

This section captures **what the model returned (as hashes/counts, and optionally raw text)**.

**Presence rule:** Always present

- `response.response_hash`: SHA-256 of response text (if available).
- `response.response_token_count`: Token estimate/count for output.
- `response.stop_reason`: Optional provider-reported reason generation stopped.
- `response.thinking_token_count`: Optional internal reasoning token count (provider-dependent).
- `response.response_text`: Raw response text. Must be `null` in `fingerprint` mode; may be present in `forensic`.

## 6.7 Telemetry (`telemetry`)

This section captures **timing measurements for the interaction**.

**Presence rule:** Always present

- `telemetry.total_latency_ms`: Optional end-to-end latency.
- `telemetry.inference_latency_ms`: Optional model-inference-only latency.

## 6.8 Context Management (`context_management`)

This section captures **conversation-history and cache facts when available**.

**Presence rule:** Optional (nullable)

- `context_management.conversation_turn_count`: Turn number/count in the conversation.
- `context_management.history_token_count`: How many tokens came from prior conversation history.
- `context_management.history_message_count`: How many prior messages contributed.
- `context_management.prompt_cache_hit`: Whether a prompt-cache hit occurred.

If this data is unavailable, the section is `null`.

## 6.9 Provider Metadata (`provider_metadata`)

This section captures **provider-level request metadata when available**.

**Presence rule:** Optional (nullable)

- `provider_metadata.provider_name`: Provider identifier/name.
- `provider_metadata.api_version`: Provider API version used.
- `provider_metadata.request_id`: Provider request ID for trace/debug correlation.

If this data is unavailable, the section is `null`.

## 6.10 Structural Analysis (`structural_analysis`)

This section captures **machine-readable analysis of response structure/content when available**.

**Presence rule:** Optional (nullable)

- `structural_analysis.output_type`: Output type classification (for example, text/code).
- `structural_analysis.language`: Primary language label.
- `structural_analysis.raw_hash`: Optional SHA-256 hash of analysis input/source.
- `structural_analysis.imports`: Detected imports.
- `structural_analysis.function_calls`: Detected function calls.
- `structural_analysis.file_operations`: Detected file operations.
- `structural_analysis.network_calls`: Detected network operations.
- `structural_analysis.system_commands`: Detected command execution patterns.
- `structural_analysis.env_access`: Detected environment-variable access patterns.
- `structural_analysis.parse_errors`: Parse/analysis errors captured by the analyzer.

If this data is unavailable, the section is `null`.

## 6.11 Action Primitives (`action_primitives`)

This section captures **normalized "what kind of action happened" detections**.

**Presence rule:** Optional (empty list default)

`action_primitives` is always present as a field, but it may be `[]` when no primitives were detected.

Each item has:

- `primitive`: One of the 19 canonical action labels:
  - `DATA_READ`
  - `DATA_WRITE`
  - `DATA_DELETE`
  - `DATA_EXFILTRATION`
  - `NETWORK_OUTBOUND`
  - `NETWORK_INBOUND`
  - `FILE_SYSTEM_READ`
  - `FILE_SYSTEM_WRITE`
  - `FILE_SYSTEM_DELETE`
  - `AUTH_ESCALATION`
  - `AUTH_DELEGATION`
  - `TOOL_INVOCATION`
  - `STATE_MUTATION`
  - `PII_ACCESS`
  - `PII_EXPOSURE`
  - `SECRET_ACCESS`
  - `FINANCIAL_TXN`
  - `CONFIG_CHANGE`
  - `HUMAN_COMMUNICATION`
- `confidence`: A score from `0.0` to `1.0` for how confident the detector is.
- `evidence`: Human-readable supporting text for why this primitive was assigned.
- `location`: Optional pointer/hint to where the evidence came from.
- `risk_level`: One of `low`, `medium`, `high`, `critical`.
- `category`: One canonical category:
  - `DATA_OPERATIONS`
  - `NETWORK`
  - `FILE_SYSTEM`
  - `AUTHENTICATION`
  - `EXECUTION`
  - `SENSITIVE_DATA`
  - `EXTERNAL`

## 6.12 Extensions (`extensions`)

This section captures **extra metadata that is not part of PBOM core fields**.

**Presence rule:** Always present

- `extensions`: Free-form object (`dict`) for implementation-specific metadata.

Important behavior:

- Core PBOM validators treat this object as opaque.
- Unknown keys are expected and should survive round-trips.
- This is for additional metadata, while core PBOM sections remain first-class schema fields.

## 6.13 Top-Level Field (`storage_mode`)

This field captures **how much raw content is stored in the record**.

**Presence rule:** Always present

- `storage_mode`: Either:
  - `fingerprint`: keep hashes/metadata, do not store raw prompt/response text.
  - `forensic`: may include raw prompt/response text in addition to hashes.

Also note: non-standard legacy fields such as `origin`, `verdict`, `timestamp`, and `pbom_signature` are not part of the PBOM open standard top-level schema.

---

## Hash Reference Table

| Hash field | Input (what it fingerprints) | What it proves |
| --- | --- | --- |
| `system_prompt_hash` | SHA-256 of the system prompt text (UTF-8) | System prompt wasn't changed after the fact |
| `user_prompt_hash` | SHA-256 of the user prompt text (UTF-8) | User prompt wasn't changed after the fact |
| `full_prompt_hash` | SHA-256 of canonical JSON: `[{"role":"system","content":...},{"role":"user","content":...}]` with `sort_keys=True, separators=(",",":")` | The complete prompt bundle is intact |
| `response_hash` | SHA-256 of the response text (UTF-8) | The LLM response wasn't modified |
| `commitment_hash` | SHA-256 of (canonical prompt JSON + nonce) | The prompt was fixed before the LLM saw it (API 1) or was recorded after the fact (API 2) |
| `previous_entry_hash` | SHA-256 of the canonical JSON of the previous record | No record in the chain was inserted, removed, or modified |
