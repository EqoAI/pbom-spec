"""Core PBOM schema models using Pydantic v2.

This module defines the reusable sub-models that make up a PBOM record.
The top-level ``PBOMRecord`` model is intentionally added separately in Part 2.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional, Literal, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

PBOM_VERSION = "1.0.0"
logger = logging.getLogger("pbom")


def _coerce_optional_int(value: object) -> Optional[int]:
    """Coerce a non-None numeric value to int, leaving None as None.

    Latency values are frequently computed from float clock
    arithmetic (e.g. time.monotonic() differences). This lets callers
    pass a float while the record still stores an int. None is passed
    through unchanged so optional fields remain optional.
    """
    if value is None:
        return None
    return int(value)


CoercedOptionalInt = Annotated[Optional[int], BeforeValidator(_coerce_optional_int)]


class EntryIdentity(BaseModel):
    """Chain identity and creation metadata for a PBOM record."""

    pbom_version: str = Field(
        default=PBOM_VERSION,
        description="PBOM schema version for this record.",
    )
    entry_id: str = Field(description="Unique record identifier.")
    chain_sequence_number: int = Field(
        description="Monotonic sequence number within the chain directory.",
    )
    previous_entry_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of the previous canonical record; null for first record.",
    )
    created_at_iso: str = Field(
        description="Record creation timestamp in ISO-8601 UTC."
    )
    created_at_epoch_ms: int = Field(
        description="Record creation timestamp as epoch ms."
    )
    entry_signature: Optional[str] = Field(
        default=None,
        description="Optional future cryptographic signature for this entry.",
    )


class Principal(BaseModel):
    """Producer identity metadata for the application and SDK."""

    application_id: str = Field(
        description="Application identifier emitting PBOM records."
    )
    sdk_name: str = Field(description="SDK name, such as pbom-python.")
    sdk_version: str = Field(description="SDK version string.")


class CryptographicCommitment(BaseModel):
    """Commitment metadata proving prompt anchoring semantics."""

    commitment_type: Literal["pre_inference", "post_hoc"] = Field(
        description='Commitment mode, e.g. "pre_inference" or "post_hoc".',
    )
    nonce: str = Field(description="Random nonce used in commitment hash computation.")
    commitment_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 over canonical prompt text concatenated with nonce.",
    )
    commitment_ts: int = Field(description="Commitment creation timestamp in epoch ms.")
    nonce_revealed_ts: Optional[int] = Field(
        default=None,
        description="Nonce reveal timestamp in epoch ms.",
    )
    commitment_verified: bool = Field(
        default=False,
        description="Whether recomputation matches the stored commitment hash.",
    )


class RawContent(BaseModel):
    """Prompt content fingerprints and optional forensic prompt text."""

    system_prompt_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of system prompt text.",
    )
    user_prompt_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of user prompt text.",
    )
    full_prompt_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of canonical combined prompt content.",
    )
    system_prompt_token_count: int = Field(
        description="Token count estimate for the system prompt.",
    )
    total_input_token_count: int = Field(
        description="Token count estimate for full input prompt content.",
    )
    system_prompt_text: Optional[str] = Field(
        default=None,
        description="Optional raw system prompt text in forensic mode.",
    )
    user_prompt_text: Optional[str] = Field(
        default=None,
        description="Optional raw user prompt text in forensic mode.",
    )


class PromptTemplate(BaseModel):
    """Template metadata when a templating system produced prompt content."""

    template_id: str = Field(description="Template identifier from upstream system.")
    template_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of canonical template definition.",
    )
    prompt_construction_method: str = Field(
        description="Description of how template inputs were combined.",
    )


class StructuralFingerprint(BaseModel):
    """High-level classification describing prompt intent."""

    prompt_intent_classification: str = Field(
        description="Classifier label for prompt intent.",
    )


class PromptRecord(BaseModel):
    """Prompt section grouping raw content, template data, and structural intent."""

    raw_content: RawContent = Field(description="Prompt content details.")
    template: Optional[PromptTemplate] = Field(
        default=None,
        description="Optional prompt template metadata.",
    )
    structural_fingerprint: Optional[StructuralFingerprint] = Field(
        default=None,
        description="Optional prompt intent classification metadata.",
    )


class InferenceMetadata(BaseModel):
    """Model and runtime configuration used for inference."""

    model_id: str = Field(description="Full model identifier, e.g. openai/gpt-4o.")
    model_family: Optional[str] = Field(
        default=None,
        description="Model family identifier.",
    )
    model_provider: Optional[str] = Field(
        default=None,
        description="Model provider identifier.",
    )
    temperature: Optional[float] = Field(
        default=None,
        description="Sampling temperature used for generation.",
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Maximum output token target requested.",
    )
    streaming: Optional[bool] = Field(
        default=None,
        description="Whether response streaming was enabled.",
    )
    context_window_max: Optional[int] = Field(
        default=None,
        description="Maximum context window for the model.",
    )
    context_utilization_pct: Optional[float] = Field(
        default=None,
        description="Fraction of context window utilized by request input.",
    )


class ResponseRecord(BaseModel):
    """Response section with output fingerprints and optional forensic text."""

    response_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of model response text.",
    )
    response_token_count: int = Field(
        description="Token count estimate for response text."
    )
    stop_reason: Optional[str] = Field(
        default=None,
        description="Provider stop reason for generation completion.",
    )
    thinking_token_count: Optional[int] = Field(
        default=None,
        description="Reasoning/thinking token count when available.",
    )
    response_text: Optional[str] = Field(
        default=None,
        description="Optional raw model response text in forensic mode.",
    )


class Telemetry(BaseModel):
    """Latency telemetry associated with record emission and inference."""

    total_latency_ms: CoercedOptionalInt = Field(
        default=None,
        description="End-to-end operation latency in ms.",
    )
    inference_latency_ms: CoercedOptionalInt = Field(
        default=None,
        description="Model inference latency in ms.",
    )


class ContextManagement(BaseModel):
    """Conversation context usage metadata for the request."""

    conversation_turn_count: int = Field(
        description="Conversation turn count at emission."
    )
    history_token_count: int = Field(description="Token count contributed by history.")
    history_message_count: int = Field(
        description="Message count contributed by history."
    )
    prompt_cache_hit: bool = Field(
        description="Whether provider-side prompt cache was used."
    )


class ProviderMetadata(BaseModel):
    """Provider-specific request metadata useful for traceability."""

    provider_name: str = Field(description="Inference provider name.")
    api_version: str = Field(description="Provider API version used.")
    request_id: str = Field(description="Provider request identifier.")


class StructuralAnalysis(BaseModel):
    """Structural response analysis output for language/code-aware auditing."""

    output_type: str = Field(description='Output form, e.g. "text" or "code".')
    language: str = Field(description="Primary language detected in output.")
    raw_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash over canonical structural analysis input.",
    )
    imports: list[str] = Field(
        default_factory=list, description="Imported modules or packages."
    )
    function_calls: list[str] = Field(
        default_factory=list,
        description="Detected function calls.",
    )
    file_operations: list[str] = Field(
        default_factory=list,
        description="Detected file operation primitives.",
    )
    network_calls: list[str] = Field(
        default_factory=list,
        description="Detected network call primitives.",
    )
    system_commands: list[str] = Field(
        default_factory=list,
        description="Detected shell/system command primitives.",
    )
    env_access: list[str] = Field(
        default_factory=list,
        description="Detected environment variable access operations.",
    )
    parse_errors: list[str] = Field(
        default_factory=list,
        description="Parser or analyzer errors encountered during structural analysis.",
    )


class ActionPrimitive(str, Enum):
    """Canonical set of action primitives detectable in LLM responses.

    Each value represents a fundamental operation that structural analysis
    can identify in a response -- for example, a generated code snippet that
    reads a file, makes a network call, or accesses a secret.

    This set is fixed within a given PBOM format version. New primitives
    require a format version bump and are added in a backward-compatible way
    (new values appended, existing values never renamed or removed).
    """

    # Data operations
    DATA_READ = "DATA_READ"
    DATA_WRITE = "DATA_WRITE"
    DATA_DELETE = "DATA_DELETE"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"

    # Network operations
    NETWORK_OUTBOUND = "NETWORK_OUTBOUND"
    NETWORK_INBOUND = "NETWORK_INBOUND"

    # File system operations
    FILE_SYSTEM_READ = "FILE_SYSTEM_READ"
    FILE_SYSTEM_WRITE = "FILE_SYSTEM_WRITE"
    FILE_SYSTEM_DELETE = "FILE_SYSTEM_DELETE"

    # Authentication/Authorization
    AUTH_ESCALATION = "AUTH_ESCALATION"
    AUTH_DELEGATION = "AUTH_DELEGATION"

    # Tool and execution
    TOOL_INVOCATION = "TOOL_INVOCATION"
    STATE_MUTATION = "STATE_MUTATION"

    # Sensitive data
    PII_ACCESS = "PII_ACCESS"
    PII_EXPOSURE = "PII_EXPOSURE"
    SECRET_ACCESS = "SECRET_ACCESS"

    # External interactions
    FINANCIAL_TXN = "FINANCIAL_TXN"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    HUMAN_COMMUNICATION = "HUMAN_COMMUNICATION"


class ActionPrimitiveDetection(BaseModel):
    """Detected action primitive with analysis metadata and confidence."""

    primitive: ActionPrimitive = Field(
        description="Detected canonical action primitive."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score in the detection result (0.0 to 1.0).",
    )
    evidence: str = Field(
        description="Short evidence excerpt or rationale supporting the detection.",
    )
    location: Optional[str] = Field(
        default=None,
        description="Optional location hint (line span, node path, or section).",
    )
    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        description='Risk label for the detection: "low", "medium", "high", or "critical".',
    )
    category: Literal[
        "DATA_OPERATIONS",
        "NETWORK",
        "FILE_SYSTEM",
        "AUTHENTICATION",
        "EXECUTION",
        "SENSITIVE_DATA",
        "EXTERNAL",
    ] = Field(
        description=(
            "Category grouping for the detected primitive. One of seven canonical "
            "groups: data operations, network, file system, authentication, "
            "execution, sensitive data, external."
        ),
    )


class _JsonLDAliasConfig(BaseModel):
    """Shared model config and canonical serializer for PBOM models.

    ``to_json_dict()`` is the canonical serialization path for any model
    inheriting this base. Direct calls to ``model_dump()`` will produce
    non-canonical output (attribute names un-aliased — they will appear as context_, type_, id_ instead of @context, @type, @id).
    Always use to_json_dict() when serializing for storage, hashing, or transmission."
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize using aliases. Includes null fields for predictable schema."""
        return self.model_dump(by_alias=True)


class PBOMRecord(_JsonLDAliasConfig):
    """Top-level tamper-evident PBOM record for one LLM interaction.

    The ``extensions`` field is for non-standard or implementation-specific
    content. Any tool that produces PBOM records may write additional data
    there under a namespaced key (e.g., ``mytool.gate_verdict``). The OSS
    reference implementation preserves this dict through round-trips but
    does not validate its shape and does not emit content into it.
    """

    context_: str = Field(
        default="https://pbom.org/context/v1",
        alias="@context",
        description="JSON-LD context URL for PBOM records.",
    )
    type_: str = Field(
        default="PBOMRecord",
        alias="@type",
        description="JSON-LD type identifier.",
    )
    id_: str = Field(alias="@id", description="JSON-LD identifier for this record.")

    identity: EntryIdentity = Field(description="Record identity and chain metadata.")
    principal: Principal = Field(description="Application and SDK producer metadata.")
    commitment: CryptographicCommitment = Field(
        description="Cryptographic commitment metadata.",
    )
    prompt: PromptRecord = Field(description="Prompt metadata and fingerprints.")
    inference: InferenceMetadata = Field(
        description="Model inference configuration metadata."
    )
    response: ResponseRecord = Field(description="Response metadata and fingerprints.")
    telemetry: Telemetry = Field(description="Latency telemetry for this record.")
    context_management: Optional[ContextManagement] = Field(
        default=None,
        description="Optional conversation context accounting metadata.",
    )
    provider_metadata: Optional[ProviderMetadata] = Field(
        default=None,
        description="Optional provider-specific request metadata.",
    )
    structural_analysis: Optional[StructuralAnalysis] = Field(
        default=None,
        description="Optional structural analysis summary for the model output.",
    )
    action_primitives: list[ActionPrimitiveDetection] = Field(
        default_factory=list,
        description="Detected primitives with confidence, evidence, and risk metadata.",
    )
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Implementation-specific metadata that is outside the PBOM core schema. "
            "Use namespaced keys to avoid collisions (for example "
            "'toolname.signal_name'). The OSS reference implementation preserves "
            "this object on read/write but does not emit proprietary content into it."
        ),
    )
    storage_mode: Literal["fingerprint", "forensic"] = Field(
        default="fingerprint",
        description="Storage mode controlling whether raw content is persisted.",
    )


def export_json_schema(output_path: Path) -> None:
    """Export the PBOMRecord JSON Schema to disk."""

    schema = PBOMRecord.model_json_schema(by_alias=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Exported JSON Schema to %s", output_path)
