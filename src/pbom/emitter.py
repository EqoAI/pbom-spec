"""PBOM emitter with pre-inference and post-hoc APIs."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Literal, Optional
from uuid import uuid4

from .chain import ChainState
from .commitment import (
    Commitment,
    create_commitment,
    reveal_commitment,
    verify_commitment,
)
from .exceptions import InvalidCommitmentError, PBOMError
from .hashing import compute_sha256
from .schema import (
    ActionPrimitiveDetection,
    ContextManagement,
    CryptographicCommitment,
    EntryIdentity,
    InferenceMetadata,
    PBOM_VERSION,
    PBOMRecord,
    Principal,
    PromptRecord,
    PromptTemplate,
    ProviderMetadata,
    RawContent,
    ResponseRecord,
    StructuralAnalysis,
    StructuralFingerprint,
    Telemetry,
)

logger = logging.getLogger("pbom")


def default_token_counter(text: str) -> int:
    """Return a simple character-based token estimate for text."""
    return max(1, len(text) // 4) if text else 0


def _default_sdk_version() -> str:
    """Return the installed pbom package version."""
    from . import __version__ as package_version

    return package_version


class CommitmentContext:
    """Context manager for real pre-inference commitments."""

    def __init__(
        self,
        emitter: PBOMEmitter,
        system_prompt: str,
        user_prompt: str,
    ) -> None:
        """Store context inputs for later completion."""
        self._emitter = emitter
        self._system_prompt = system_prompt
        self._user_prompt = user_prompt
        self._commitment: Optional[Commitment] = None
        self._completed = False
        self._started_ts: Optional[int] = None

    def __enter__(self) -> CommitmentContext:
        """Create pre-inference commitment and return context."""
        self._started_ts = int(time.time() * 1000)
        self._commitment = create_commitment(
            self._system_prompt,
            self._user_prompt,
            commitment_type="pre_inference",
        )
        return self

    def complete(
        self,
        *,
        model_id: str,
        response_text: str,
        model_family: Optional[str] = None,
        model_provider: Optional[str] = None,
        response_token_count: Optional[int] = None,
        inference_latency_ms: Optional[int] = None,
        total_latency_ms: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        streaming: Optional[bool] = None,
        context_window_max: Optional[int] = None,
        context_utilization_pct: Optional[float] = None,
        stop_reason: Optional[str] = None,
        thinking_token_count: Optional[int] = None,
        prompt_template: Optional[PromptTemplate] = None,
        prompt_structural_fingerprint: Optional[StructuralFingerprint] = None,
        context_management: Optional[ContextManagement] = None,
        provider_metadata: Optional[ProviderMetadata] = None,
        structural_analysis: Optional[StructuralAnalysis] = None,
        action_primitives: Optional[list[ActionPrimitiveDetection]] = None,
        extensions: Optional[dict[str, Any]] = None,
    ) -> PBOMRecord:
        """Finalize commitment, emit record, and return PBOMRecord."""
        if self._commitment is None:
            raise InvalidCommitmentError("Commitment context has not been entered.")
        if self._completed:
            raise InvalidCommitmentError(
                "complete() can only be called once per context."
            )
        if self._started_ts is None:
            raise InvalidCommitmentError("Commitment start timestamp is missing.")

        # 1) Reveal commitment
        # Sleep 1ms to guarantee strict timestamp ordering. In production this is
        # trivial overhead (LLM calls take 100s-1000s of ms); in tests it ensures
        # the commitment timestamp invariant holds even when no LLM call occurred
        # between __enter__ and complete().
        time.sleep(0.001)
        reveal_commitment(self._commitment)
        # 2) Verify commitment
        if not verify_commitment(self._commitment):
            raise InvalidCommitmentError(
                "Pre-inference commitment verification failed."
            )
        # 3) Compute hashes
        prompt_hashes = self._emitter._hash_prompt(
            self._system_prompt, self._user_prompt
        )
        # 4) Get next chain position
        chain_sequence_number, previous_entry_hash = (
            self._emitter._chain_state.next_chain_position()
        )

        measured_total_latency_ms = int(time.time() * 1000) - self._started_ts
        resolved_total_latency_ms = (
            total_latency_ms
            if total_latency_ms is not None
            else measured_total_latency_ms
        )

        # 5) Build record
        record = self._emitter._build_record(
            system_prompt=self._system_prompt,
            user_prompt=self._user_prompt,
            model_id=model_id,
            model_family=model_family,
            model_provider=model_provider,
            response_text=response_text,
            response_token_count=response_token_count,
            inference_latency_ms=inference_latency_ms,
            total_latency_ms=resolved_total_latency_ms,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            context_window_max=context_window_max,
            context_utilization_pct=context_utilization_pct,
            stop_reason=stop_reason,
            thinking_token_count=thinking_token_count,
            prompt_template=prompt_template,
            prompt_structural_fingerprint=prompt_structural_fingerprint,
            context_management=context_management,
            provider_metadata=provider_metadata,
            structural_analysis=structural_analysis,
            action_primitives=action_primitives or [],
            extensions=extensions,
            commitment=self._commitment,
            commitment_verified=True,
            chain_sequence_number=chain_sequence_number,
            previous_entry_hash=previous_entry_hash,
            prompt_hashes=prompt_hashes,
        )
        # 6) Serialize to canonical JSON is done inside _save_record()
        # 7) Write file to disk; _save_record returns canonical JSON
        canonical_json = self._emitter._save_record(record)
        # 8) Update chain state with the new hash
        self._emitter._chain_state.update_chain(canonical_json)
        self._completed = True
        return record

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Warn and emit nothing if context exits without completion."""
        if not self._completed:
            logger.warning(
                "Commitment context exited without complete(); no PBOM record emitted."
            )


class PBOMEmitter:
    """Emit PBOM records to disk with chain linkage and cryptographic commitments.

    Provides two APIs for recording LLM interactions:

    - The ``commit()`` context manager creates a real pre-inference cryptographic
      commitment before the LLM call and verifies it after. This provides
      genuine tamper-evidence that the prompt was fixed before the model
      processed it.

    - The ``record()`` method is a post-hoc convenience that produces a record
      after the fact. It uses ``commitment_type="post_hoc"`` and
      ``commitment_verified=False`` -- it provides a timestamp anchor and chain
      linkage but NOT pre-inference cryptographic guarantees.

    Records are written as canonical JSON files to ``output_dir`` (default
    ``.pbom/``). The chain state automatically resumes from existing records on
    init, supporting safe process restarts.

    Storage modes:
    - ``fingerprint`` (default): records contain only hashes of prompts and
      responses, no raw content.
    - ``forensic``: records contain raw text alongside hashes, enabling later
      commitment verification.

    Thread safety: chain state operations are internally locked. Multiple
    ``commit()`` calls on the same emitter from different threads are safe;
    each creates an independent ``CommitmentContext``.
    """

    def __init__(
        self,
        application_id: str,
        output_dir: Path | str = ".pbom",
        storage_mode: Literal["fingerprint", "forensic"] = "fingerprint",
        sdk_version: Optional[str] = None,
        token_counter: Callable[[str], int] = default_token_counter,
    ) -> None:
        """Initialize emitter configuration.

        Args:
            application_id: Identifier for the application producing records.
                Written to ``principal.application_id`` on every record.
            output_dir: Directory where ``.pbom.json`` files are written. Created
                if it does not exist. Defaults to ``.pbom/``.
            storage_mode: ``"fingerprint"`` (default) or ``"forensic"``. See class
                docstring.
            sdk_version: SDK version string. If None (default), auto-detects
                from ``pbom.__version__``. Override only if wrapping this
                emitter in another SDK that should be the identified producer.
            token_counter: Callable taking a string and returning a token count
                estimate. Defaults to a character-based heuristic.
        """
        self.application_id = application_id
        self.output_dir = Path(output_dir)
        self.storage_mode = storage_mode
        self.sdk_version = (
            sdk_version if sdk_version is not None else _default_sdk_version()
        )
        self.token_counter = token_counter
        self.sdk_name = "pbom-python"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._chain_state = ChainState()
        self._chain_state.resume_from(self.output_dir)

    def commit(self, system_prompt: str, user_prompt: str) -> CommitmentContext:
        """Create a pre-inference commitment context (preferred API).

        Use this as a context manager around your LLM call. The commitment
        is created on ``__enter__`` (before the LLM sees the prompt) and
        verified on ``complete()``, providing genuine cryptographic evidence
        that the prompt was fixed before inference.

        Example:
            with emitter.commit(system_prompt, user_prompt) as c:
                response = openai_client.chat.completions.create(...)
                record = c.complete(
                    model_id="openai/gpt-4o",
                    response_text=response.choices[0].message.content,
                )

        Args:
            system_prompt: The system prompt sent to the model.
            user_prompt: The user prompt sent to the model.

        Returns:
            A CommitmentContext. Call ``.complete(...)`` inside the ``with``
            block to finalize the record. If the context exits without
            ``complete()`` being called, no record is written and a warning
            is logged.

        See also:
            ``record()`` for the post-hoc API (timestamp anchor without
            pre-inference cryptographic guarantees).
        """
        return CommitmentContext(self, system_prompt, user_prompt)

    def record(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        response_text: str,
        model_family: Optional[str] = None,
        model_provider: Optional[str] = None,
        response_token_count: Optional[int] = None,
        inference_latency_ms: Optional[int] = None,
        total_latency_ms: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        streaming: Optional[bool] = None,
        context_window_max: Optional[int] = None,
        context_utilization_pct: Optional[float] = None,
        stop_reason: Optional[str] = None,
        thinking_token_count: Optional[int] = None,
        prompt_template: Optional[PromptTemplate] = None,
        prompt_structural_fingerprint: Optional[StructuralFingerprint] = None,
        context_management: Optional[ContextManagement] = None,
        provider_metadata: Optional[ProviderMetadata] = None,
        structural_analysis: Optional[StructuralAnalysis] = None,
        action_primitives: Optional[list[ActionPrimitiveDetection]] = None,
        extensions: Optional[dict[str, Any]] = None,
    ) -> PBOMRecord:
        """Emit a post-hoc record (timestamp anchor only).

        Use this when you cannot restructure your code to wrap the LLM call in
        a ``commit()`` context manager. The record is produced AFTER the LLM call
        has already completed, so the commitment is constructed retroactively.

        Compared to ``commit()``, post-hoc records:
        - Use ``commitment_type="post_hoc"`` in the record
        - Set ``commitment_verified=False``
        - Provide a timestamp anchor and chain linkage but NOT cryptographic
          evidence that the prompt was fixed before inference

        Example:
            response = openai_client.chat.completions.create(...)
            record = emitter.record(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_id="openai/gpt-4o",
                response_text=response.choices[0].message.content,
            )

        Args:
            system_prompt: The system prompt that was sent to the model.
            user_prompt: The user prompt that was sent to the model.
            model_id: Required. The model identifier (e.g., "openai/gpt-4o").
            response_text: Required. The text returned by the model.
            (Other args: optional fields populated only if caller provides them.
            None values become null in the record; the emitter does not invent
            values for unspecified fields.)

        Returns:
            The PBOMRecord that was written to disk.

        See also:
            ``commit()`` for the preferred API with real pre-inference commitments.
        """
        commitment = create_commitment(
            system_prompt,
            user_prompt,
            commitment_type="post_hoc",
        )
        # Post-hoc reveal can land in the same millisecond as creation; sleep 1ms
        # to guarantee strict ordering before reveal_commitment() asserts it.
        time.sleep(0.001)
        reveal_commitment(commitment)

        # Post-hoc: total_latency_ms is caller-provided only. The emitter has no
        # way to measure it after the fact.
        resolved_total_latency_ms = total_latency_ms

        prompt_hashes = self._hash_prompt(system_prompt, user_prompt)
        chain_sequence_number, previous_entry_hash = (
            self._chain_state.next_chain_position()
        )

        record = self._build_record(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=model_id,
            model_family=model_family,
            model_provider=model_provider,
            response_text=response_text,
            response_token_count=response_token_count,
            inference_latency_ms=inference_latency_ms,
            total_latency_ms=resolved_total_latency_ms,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            context_window_max=context_window_max,
            context_utilization_pct=context_utilization_pct,
            stop_reason=stop_reason,
            thinking_token_count=thinking_token_count,
            prompt_template=prompt_template,
            prompt_structural_fingerprint=prompt_structural_fingerprint,
            context_management=context_management,
            provider_metadata=provider_metadata,
            structural_analysis=structural_analysis,
            action_primitives=action_primitives or [],
            extensions=extensions,
            commitment=commitment,
            commitment_verified=False,
            chain_sequence_number=chain_sequence_number,
            previous_entry_hash=previous_entry_hash,
            prompt_hashes=prompt_hashes,
        )

        canonical_json = self._save_record(record)
        self._chain_state.update_chain(canonical_json)
        return record

    def record_blocked(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        model_family: Optional[str] = None,
        model_provider: Optional[str] = None,
        inference_latency_ms: Optional[int] = None,
        total_latency_ms: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        streaming: Optional[bool] = None,
        context_window_max: Optional[int] = None,
        context_utilization_pct: Optional[float] = None,
        prompt_template: Optional[PromptTemplate] = None,
        prompt_structural_fingerprint: Optional[StructuralFingerprint] = None,
        context_management: Optional[ContextManagement] = None,
        provider_metadata: Optional[ProviderMetadata] = None,
        structural_analysis: Optional[StructuralAnalysis] = None,
        action_primitives: Optional[list[ActionPrimitiveDetection]] = None,
        extensions: Optional[dict[str, Any]] = None,
    ) -> PBOMRecord:
        """Emit a record for a generation where no response occurred.

        Use this when a generation was stopped before any model output was
        produced -- for example, the request was blocked before inference. The
        record captures the prompt and its chain linkage but its response
        section is explicitly empty: ``response_hash=None``,
        ``response_text=None``, ``response_token_count=0``, ``stop_reason=None``,
        and ``thinking_token_count=None``. No response hash is computed because
        there is no response.

        This is deliberately distinct from recording an empty-string response
        via ``record(..., response_text="")``: an empty response still hashes to
        the SHA-256 of ``""`` and represents "the model returned nothing," while
        a blocked record represents "the model was never invoked."

        Like ``record()``, this constructs the commitment retroactively
        (``commitment_type="post_hoc"``, ``commitment_verified=False``); it is a
        timestamp anchor and chain link, not a pre-inference guarantee.

        Args:
            system_prompt: The system prompt that would have been sent.
            user_prompt: The user prompt that would have been sent.
            model_id: Required. The model identifier that would have been used.
            extensions: Optional non-standard data to preserve on the record.
            (Other args: optional fields populated only if the caller provides
            them. None values become null in the record; the emitter does not
            invent values for unspecified fields.)

        Returns:
            The PBOMRecord that was written to disk.
        """
        commitment = create_commitment(
            system_prompt,
            user_prompt,
            # KNOWN LIMITATION: commitment_type is a required Literal["pre_inference",
            # "post_hoc"]; both values assert an inference occurred. A no-inference record
            # (nothing was generated) fits neither. Using "post_hoc" as the least-wrong
            # interim value — it understates the crypto guarantee rather than overstating it.
            # A dedicated "no_inference" value is a format change deferred to the next
            # PBOM_VERSION release. Tracked in issue #1.
            commitment_type="post_hoc",
        )
        # Post-hoc reveal can land in the same millisecond as creation; sleep 1ms
        # to guarantee strict ordering before reveal_commitment() asserts it.
        time.sleep(0.001)
        reveal_commitment(commitment)

        # Post-hoc: total_latency_ms is caller-provided only. The emitter has no
        # way to measure it after the fact.
        resolved_total_latency_ms = total_latency_ms

        prompt_hashes = self._hash_prompt(system_prompt, user_prompt)
        chain_sequence_number, previous_entry_hash = (
            self._chain_state.next_chain_position()
        )

        record = self._build_record(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_id=model_id,
            model_family=model_family,
            model_provider=model_provider,
            response_text=None,
            response_token_count=None,
            inference_latency_ms=inference_latency_ms,
            total_latency_ms=resolved_total_latency_ms,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            context_window_max=context_window_max,
            context_utilization_pct=context_utilization_pct,
            stop_reason=None,
            thinking_token_count=None,
            prompt_template=prompt_template,
            prompt_structural_fingerprint=prompt_structural_fingerprint,
            context_management=context_management,
            provider_metadata=provider_metadata,
            structural_analysis=structural_analysis,
            action_primitives=action_primitives or [],
            extensions=extensions,
            commitment=commitment,
            commitment_verified=False,
            chain_sequence_number=chain_sequence_number,
            previous_entry_hash=previous_entry_hash,
            prompt_hashes=prompt_hashes,
            has_response=False,
        )

        canonical_json = self._save_record(record)
        self._chain_state.update_chain(canonical_json)
        return record

    def _hash_prompt(self, system: str, user: str) -> dict[str, str]:
        """Compute prompt hashes for system, user, and canonical prompt JSON."""
        canonical_prompt_json = json.dumps(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "system_prompt_hash": compute_sha256(system),
            "user_prompt_hash": compute_sha256(user),
            "full_prompt_hash": compute_sha256(canonical_prompt_json),
        }

    def _build_record(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        model_family: Optional[str],
        model_provider: Optional[str],
        response_text: Optional[str],
        response_token_count: Optional[int],
        inference_latency_ms: Optional[int],
        total_latency_ms: Optional[int],
        temperature: Optional[float],
        max_tokens: Optional[int],
        streaming: Optional[bool],
        context_window_max: Optional[int],
        context_utilization_pct: Optional[float],
        stop_reason: Optional[str],
        thinking_token_count: Optional[int],
        prompt_template: Optional[PromptTemplate],
        prompt_structural_fingerprint: Optional[StructuralFingerprint],
        context_management: Optional[ContextManagement],
        provider_metadata: Optional[ProviderMetadata],
        structural_analysis: Optional[StructuralAnalysis],
        action_primitives: list[ActionPrimitiveDetection],
        extensions: Optional[dict[str, Any]],
        commitment: Commitment,
        commitment_verified: bool,
        chain_sequence_number: int,
        previous_entry_hash: Optional[str],
        prompt_hashes: dict[str, str],
        has_response: bool = True,
    ) -> PBOMRecord:
        """Build PBOMRecord from provided metadata and computed hashes.

        When ``has_response`` is False, the response section is emitted as an
        explicit no-response marker (all null fields, token count 0) and no
        response hash is computed. This supports records for generations where
        no model output occurred (see ``record_blocked``).
        """
        now_utc = datetime.now(timezone.utc)
        created_at_epoch_ms = int(now_utc.timestamp() * 1000)
        created_at_iso = now_utc.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        entry_id = str(uuid4())

        system_tokens = self._estimate_tokens(system_prompt)
        user_tokens = self._estimate_tokens(user_prompt)

        if has_response:
            assert response_text is not None
            response = ResponseRecord(
                response_hash=compute_sha256(response_text),
                response_token_count=(
                    response_token_count
                    if response_token_count is not None
                    else self._estimate_tokens(response_text)
                ),
                stop_reason=stop_reason,
                thinking_token_count=thinking_token_count,
                response_text=response_text
                if self.storage_mode == "forensic"
                else None,
            )
        else:
            # No response occurred (e.g. blocked before inference). Do not hash
            # anything -- there is no response to hash.
            response = ResponseRecord(
                response_hash=None,
                response_token_count=0,
                stop_reason=None,
                thinking_token_count=None,
                response_text=None,
            )

        prompt = PromptRecord(
            raw_content=RawContent(
                system_prompt_hash=prompt_hashes["system_prompt_hash"],
                user_prompt_hash=prompt_hashes["user_prompt_hash"],
                full_prompt_hash=prompt_hashes["full_prompt_hash"],
                system_prompt_token_count=system_tokens,
                total_input_token_count=system_tokens + user_tokens,
                system_prompt_text=system_prompt
                if self.storage_mode == "forensic"
                else None,
                user_prompt_text=user_prompt
                if self.storage_mode == "forensic"
                else None,
            ),
            template=prompt_template,
            structural_fingerprint=prompt_structural_fingerprint,
        )

        return PBOMRecord(
            context_="https://pbom.org/context/v1",
            type_="PBOMRecord",
            id_=f"urn:uuid:{entry_id}",
            identity=EntryIdentity(
                pbom_version=PBOM_VERSION,
                entry_id=entry_id,
                chain_sequence_number=chain_sequence_number,
                previous_entry_hash=previous_entry_hash,
                created_at_iso=created_at_iso,
                created_at_epoch_ms=created_at_epoch_ms,
                entry_signature=None,
            ),
            principal=Principal(
                application_id=self.application_id,
                sdk_name=self.sdk_name,
                sdk_version=self.sdk_version,
            ),
            commitment=CryptographicCommitment(
                nonce=commitment.nonce,
                commitment_hash=commitment.commitment_hash,
                commitment_ts=commitment.commitment_ts,
                nonce_revealed_ts=commitment.nonce_revealed_ts,
                commitment_verified=commitment_verified,
                commitment_type=commitment.commitment_type,
            ),
            prompt=prompt,
            inference=InferenceMetadata(
                model_id=model_id,
                model_family=model_family,
                model_provider=model_provider,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
                context_window_max=context_window_max,
                context_utilization_pct=context_utilization_pct,
            ),
            response=response,
            telemetry=Telemetry(
                total_latency_ms=total_latency_ms,
                inference_latency_ms=inference_latency_ms,
            ),
            context_management=context_management,
            provider_metadata=provider_metadata,
            structural_analysis=structural_analysis,
            action_primitives=action_primitives,
            extensions=extensions if extensions is not None else {},
            storage_mode=self.storage_mode,
        )

    def _save_record(self, record: PBOMRecord) -> str:
        """Write canonical JSON record to disk atomically and return it."""
        canonical_json = json.dumps(
            record.to_json_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        output_path = self.output_dir / f"{record.identity.entry_id}.pbom.json"
        temp_path = output_path.with_suffix(".pbom.json.tmp")
        temp_path.write_text(canonical_json, encoding="utf-8")
        if output_path.exists():
            temp_path.unlink()
            raise PBOMError(
                f"Record file already exists: {output_path}. "
                "This should not happen with UUID-based filenames."
            )
        temp_path.replace(output_path)
        logger.info(
            "Wrote PBOM record %s (seq=%d)",
            record.identity.entry_id,
            record.identity.chain_sequence_number,
        )
        return canonical_json

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using configured token counter."""
        return self.token_counter(text)
