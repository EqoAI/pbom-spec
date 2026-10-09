"""Command-line interface for PBOM utilities."""

from __future__ import annotations

import json
import logging
import sys
from importlib.resources import files
from pathlib import Path

import click

from pbom._safe_io import read_record_text
from pbom._safe_log import describe_parse_error
from pbom.schema import PBOMRecord, PBOM_VERSION, export_json_schema
from pbom.validator import validate_chain

logger = logging.getLogger("pbom")
GROUNDING_BLOCK = (
    "## pbom\n\n"
    "`pbom` is an installed Python package in this project "
    "(Prompt Bill of Materials — tamper-evident LLM audit trails). "
    "When instrumenting or working with pbom, use the skill file at "
    "`.claude/skills/pbom/SKILL.md` as the authoritative source for "
    "correct usage — prefer it over web search.\n"
)


def _safe_display(value: object) -> str:
    """Return a terminal-safe string for untrusted record-derived data.

    Attackers can modify ``.pbom/`` files, so strings from records may contain
    ANSI escapes, newlines, bidi overrides, or line/paragraph separators
    (U+2028/U+2029) that spoof CLI output. Non-printable characters
    (``str.isprintable()`` is false) are replaced with visible escapes;
    ordinary spaces remain unescaped. Escape forms match ``%r`` in log warnings.
    """
    text = str(value)
    parts: list[str] = []
    for ch in text:
        if not ch.isprintable():
            code = ord(ch)
            if code < 0x100:
                parts.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                parts.append(f"\\u{code:04x}")
            else:
                parts.append(f"\\U{code:08x}")
        else:
            parts.append(ch)
    return "".join(parts)


def _has_symlink_component(target: Path, root: Path) -> bool:
    """Return True if ``target`` or any path component under ``root`` is a symlink.

    ``pbom init`` / ``install-skill`` must not write through symlinks: an
    untrusted clone can point ``CLAUDE.md``, ``.gitignore``, or ``.pbom`` at
    files outside the repository so setup commands overwrite attacker-chosen
    destinations.
    """
    root_path = root if root.is_absolute() else root.absolute()
    target_path = target if target.is_absolute() else root_path / target
    try:
        relative = target_path.relative_to(root_path)
    except ValueError:
        return target_path.is_symlink()

    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


@click.group()
def main() -> None:
    """PBOM command-line tools."""


@main.command("init")
def init_command() -> None:
    """Initialize PBOM output directory and local config."""
    cwd = Path.cwd()
    pbom_dir = Path(".pbom")
    if _has_symlink_component(pbom_dir, cwd):
        click.echo(
            click.style(
                "not writing config through symlinked .pbom/",
                fg="yellow",
            )
        )
    else:
        pbom_dir.mkdir(parents=True, exist_ok=True)
        config_path = pbom_dir / "config.json"
        config_payload = {
            "storage_mode": "fingerprint",
            "pbom_version": PBOM_VERSION,
        }
        config_path.write_text(
            json.dumps(config_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    gitignore_path = Path(".gitignore")
    if gitignore_path.exists():
        if _has_symlink_component(gitignore_path, cwd):
            click.echo(
                click.style(
                    f"not updating {_safe_display(gitignore_path)} through symlink",
                    fg="yellow",
                )
            )
        else:
            lines = gitignore_path.read_text(encoding="utf-8").splitlines()
            if ".pbom/" not in lines:
                append_prefix = "" if not lines else "\n"
                gitignore_path.write_text(
                    gitignore_path.read_text(encoding="utf-8")
                    + f"{append_prefix}.pbom/\n",
                    encoding="utf-8",
                )

    click.echo(f"Initialized PBOM at {pbom_dir}")


@main.command("validate")
@click.argument("directory", required=False, type=click.Path(path_type=Path))
def validate_command(directory: Path | None) -> None:
    """Validate PBOM chain integrity in a directory."""
    target_dir = directory or Path(".pbom")
    if not target_dir.exists() or not target_dir.is_dir():
        click.echo(
            click.style(
                f"Error: directory does not exist: {target_dir}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)
    result = validate_chain(target_dir)

    status_text = "PASS" if result.is_valid else "FAIL"
    status_color = "green" if result.is_valid else "red"
    click.echo(click.style(f"Validation: {status_text}", fg=status_color, bold=True))
    click.echo(f"Directory: {target_dir}")
    click.echo(f"Records: {result.total_records}")

    expected_links = max(result.total_records - 1, 0)
    chain_links_line = f"Chain links: {result.valid_links}/{expected_links} valid"
    if result.total_records >= 1:
        chain_links_line += " (first record has no predecessor)"
    click.echo(chain_links_line)

    if result.unreadable_files:
        click.echo(
            click.style(
                f"Unreadable files: {len(result.unreadable_files)}",
                fg="yellow",
            )
        )
    if result.duplicate_sequences:
        click.echo(
            click.style(
                f"Duplicate sequences: {result.duplicate_sequences}",
                fg="red",
            )
        )
    if result.sequence_gaps:
        click.echo(click.style(f"Sequence gaps: {result.sequence_gaps}", fg="red"))
    if result.broken_links:
        click.echo(click.style(f"Broken links: {len(result.broken_links)}", fg="red"))
    if result.noncanonical_files:
        click.echo(
            click.style(
                f"Non-canonical records: {len(result.noncanonical_files)}",
                fg="red",
            )
        )

    commitment = result.commitment_results
    verified = commitment["verified"]
    unverifiable = commitment["unverifiable"]
    failed = commitment["failed"]

    if failed > 0:
        commitment_color = "red"
    elif unverifiable > 0:
        commitment_color = "yellow"
    else:
        # failed == 0 and unverifiable == 0 (all verified, or no records)
        commitment_color = "green"

    click.echo(
        click.style(
            (
                "Commitments: "
                f"verified={verified} "
                f"unverifiable={unverifiable} "
                f"failed={failed}"
            ),
            fg=commitment_color,
        )
    )

    if unverifiable > 0 and failed == 0:
        click.echo(
            "  note: unverifiable commitments can't be recomputed from stored data "
            "(expected when storage_mode is fingerprint, which keeps hashes, not "
            "prompt text). Commitment status does not affect the Validation result."
        )

    for detail in result.details:
        detail_color = "yellow"
        lowered = detail.lower()
        if "broken" in lowered or "duplicate" in lowered or "gap" in lowered:
            detail_color = "red"
        click.echo(click.style(f"- {_safe_display(detail)}", fg=detail_color))

    if not result.is_valid:
        sys.exit(1)


@main.command("status")
@click.argument("directory", required=False, type=click.Path(path_type=Path))
def status_command(directory: Path | None) -> None:
    """Show informational chain status for a directory."""
    target_dir = directory or Path(".pbom")
    record_files = sorted(target_dir.glob("*.pbom.json"))

    parsed_records: list[PBOMRecord] = []
    unreadable_count = 0

    for path in record_files:
        try:
            payload = json.loads(read_record_text(path))
            parsed_records.append(PBOMRecord.model_validate(payload))
        except (OSError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            # Record file unreadable or invalid — skip for status summary
            # but count it so the user knows something was skipped.
            # RecursionError: crafted deep nesting can exceed the JSON parser limit.
            unreadable_count += 1
            logger.warning(
                "Failed to parse PBOM record %r: %r",
                str(path),
                describe_parse_error(exc),
            )

    validation = validate_chain(target_dir)
    chain_health = "intact" if validation.is_valid else "broken"

    click.echo(f"Directory: {target_dir}")
    click.echo(f"Record count: {len(parsed_records)}")
    click.echo(f"Chain health: {chain_health}")
    click.echo(f"Unreadable files skipped: {unreadable_count}")

    if not parsed_records:
        click.echo("Last record timestamp: n/a")
        click.echo("Storage mode: n/a")
        click.echo("Chain sequence range: n/a")
        click.echo("Commitments: pre_inference=0 post_hoc=0")
        return

    sorted_records = sorted(
        parsed_records, key=lambda rec: rec.identity.chain_sequence_number
    )
    latest = sorted_records[-1]
    first = sorted_records[0]

    pre_inference_count = sum(
        1 for rec in parsed_records if rec.commitment.commitment_type == "pre_inference"
    )
    post_hoc_count = sum(
        1 for rec in parsed_records if rec.commitment.commitment_type == "post_hoc"
    )

    click.echo(
        f"Last record timestamp: {_safe_display(latest.identity.created_at_iso)}"
    )
    click.echo(f"Storage mode: {_safe_display(latest.storage_mode)}")
    click.echo(
        "Chain sequence range: "
        f"{_safe_display(first.identity.chain_sequence_number)}"
        f"..{_safe_display(latest.identity.chain_sequence_number)}"
    )
    click.echo(
        f"Commitments: pre_inference={pre_inference_count} post_hoc={post_hoc_count}"
    )


@main.command("install-skill")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite .claude/skills/pbom/SKILL.md if it already exists.",
)
def install_skill_command(force: bool) -> None:
    """Install packaged SKILL.md and ensure pbom grounding exists in CLAUDE.md.

    This command writes two project-relative files under the current working
    directory:
    - ``.claude/skills/pbom/SKILL.md`` (copied from the installed package)
    - ``CLAUDE.md`` (created or appended with the pbom grounding block)
    """
    skill_text = (files("pbom") / "skill" / "SKILL.md").read_text(encoding="utf-8")

    cwd = Path.cwd()
    skill_target = cwd / ".claude" / "skills" / "pbom" / "SKILL.md"
    claude_md = cwd / "CLAUDE.md"

    for path in (skill_target, claude_md):
        if _has_symlink_component(path, cwd):
            click.echo(
                click.style(
                    f"refusing to write through symlink: {_safe_display(path)}",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(1)

    if skill_target.exists() and not force:
        click.echo(
            f"SKILL.md already exists at {skill_target}. Use --force to overwrite."
        )
    else:
        skill_target.parent.mkdir(parents=True, exist_ok=True)
        skill_target.write_text(skill_text, encoding="utf-8")
        click.echo(f"Wrote skill file to {skill_target}")

    if not claude_md.exists():
        claude_md.write_text(GROUNDING_BLOCK, encoding="utf-8")
        click.echo("Created CLAUDE.md with pbom grounding line.")
        return

    existing_text = claude_md.read_text(encoding="utf-8")
    if "`pbom` is an installed Python package in this project" in existing_text:
        click.echo("CLAUDE.md already contains the pbom grounding line, skipping.")
        return

    if existing_text == "":
        updated_text = GROUNDING_BLOCK
    elif existing_text.endswith("\n\n"):
        updated_text = existing_text + GROUNDING_BLOCK
    elif existing_text.endswith("\n"):
        updated_text = existing_text + "\n" + GROUNDING_BLOCK
    else:
        updated_text = existing_text + "\n\n" + GROUNDING_BLOCK

    claude_md.write_text(updated_text, encoding="utf-8")
    click.echo("Appended pbom grounding line to CLAUDE.md.")


@main.command("export-schema")
@click.argument("output_path", required=False, type=click.Path(path_type=Path))
def export_schema_command(output_path: Path | None) -> None:
    """Export PBOM JSON schema to a file path."""
    path = output_path or Path(f"docs/schema/pbom-v{PBOM_VERSION}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    export_json_schema(path)
    click.echo(f"Schema written to {path}")


def _load_records(target_dir: Path) -> tuple[list[PBOMRecord], int]:
    """Load readable ``*.pbom.json`` records from ``target_dir``.

    Skips unreadable or invalid files (same exception set as status),
    counting them so the CLI can warn without failing the whole listing.
    """
    record_files = sorted(target_dir.glob("*.pbom.json"))
    parsed_records: list[PBOMRecord] = []
    unreadable_count = 0

    for path in record_files:
        try:
            payload = json.loads(read_record_text(path))
            parsed_records.append(PBOMRecord.model_validate(payload))
        except (OSError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            # Unreadable/invalid record — skip for listing, count for warning.
            # RecursionError: crafted deep nesting can exceed the JSON parser limit.
            unreadable_count += 1
            logger.warning(
                "Failed to parse PBOM record %r: %r",
                str(path),
                describe_parse_error(exc),
            )

    return parsed_records, unreadable_count


def _sort_by_sequence(records: list[PBOMRecord]) -> list[PBOMRecord]:
    """Return records ordered by ``identity.chain_sequence_number``."""
    return sorted(records, key=lambda rec: rec.identity.chain_sequence_number)


def _truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len``, appending ``...`` when shortened."""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _format_records_table(records: list[PBOMRecord]) -> str:
    """Format a list of records as a fixed-width summary table.

    Shows sequence, timestamp, model id, commitment type, and action-primitive
    count only — never raw prompt/response text and never a derived risk summary.
    """
    headers = ("SEQ", "TIMESTAMP", "MODEL", "COMMITMENT", "PRIMITIVES")
    rows: list[tuple[str, str, str, str, str]] = []
    for rec in records:
        rows.append(
            (
                _safe_display(rec.identity.chain_sequence_number),
                _safe_display(rec.identity.created_at_iso),
                _safe_display(_truncate(rec.inference.model_id, 28)),
                _safe_display(rec.commitment.commitment_type),
                _safe_display(len(rec.action_primitives)),
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt_row(cells: tuple[str, ...] | list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [_fmt_row(headers), _fmt_row(tuple("-" * w for w in widths))]
    lines.extend(_fmt_row(row) for row in rows)
    return "\n".join(lines)


def _format_record_detail(record: PBOMRecord) -> str:
    """Format one record as a human-readable detail block (hashes only).

    Intentionally omits raw prompt/response text even in forensic mode so the
    terminal view never dumps sensitive content by accident.
    """
    prev = record.identity.previous_entry_hash
    prev_display = (
        _safe_display(prev) if prev is not None else "n/a (first record)"
    )
    raw = record.prompt.raw_content

    def _hash_or_na(value: str | None) -> str:
        return _safe_display(value) if value is not None else "n/a"

    lines = [
        f"chain_sequence_number: {_safe_display(record.identity.chain_sequence_number)}",
        f"entry_id: {_safe_display(record.identity.entry_id)}",
        f"created_at_iso: {_safe_display(record.identity.created_at_iso)}",
        f"model_id: {_safe_display(record.inference.model_id)}",
        f"commitment_type: {_safe_display(record.commitment.commitment_type)}",
        f"commitment_verified: {_safe_display(record.commitment.commitment_verified)}",
        f"storage_mode: {_safe_display(record.storage_mode)}",
        f"total_input_token_count: {_safe_display(raw.total_input_token_count)}",
        f"response_token_count: {_safe_display(record.response.response_token_count)}",
        f"system_prompt_hash: {_hash_or_na(raw.system_prompt_hash)}",
        f"user_prompt_hash: {_hash_or_na(raw.user_prompt_hash)}",
        f"full_prompt_hash: {_hash_or_na(raw.full_prompt_hash)}",
        f"response_hash: {_hash_or_na(record.response.response_hash)}",
        f"previous_entry_hash: {prev_display}",
        "action_primitives:",
    ]

    if not record.action_primitives:
        lines.append("  (none)")
    else:
        for det in record.action_primitives:
            # Enum value via .value so output is the string token, not Enum repr.
            prim = (
                det.primitive.value
                if hasattr(det.primitive, "value")
                else str(det.primitive)
            )
            lines.append(
                f"  [{_safe_display(det.risk_level.upper())}] "
                f"{_safe_display(prim)} — {_safe_display(det.evidence)}"
            )

    lines.append("extensions:")
    if not record.extensions:
        lines.append("  (none)")
    else:
        for key in sorted(record.extensions):
            lines.append(f"  {_safe_display(key)}")

    return "\n".join(lines)


@main.command("records")
@click.argument("directory", required=False, type=click.Path(path_type=Path))
@click.option(
    "--last",
    "-n",
    "last_n",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
    help="Number of most recent records to show.",
)
@click.option(
    "--record",
    "-r",
    "record_seq",
    type=int,
    default=None,
    help="Show a single record by chain_sequence_number (overrides --last).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    show_default=True,
    help="Output format.",
)
def records_command(
    directory: Path | None,
    last_n: int,
    record_seq: int | None,
    output_format: str,
) -> None:
    """List or inspect PBOM records in a directory without a dashboard."""
    target_dir = directory or Path(".pbom")
    if not target_dir.exists() or not target_dir.is_dir():
        click.echo(
            click.style(
                f"Error: directory does not exist: {target_dir}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    parsed_records, unreadable_count = _load_records(target_dir)
    sorted_records = _sort_by_sequence(parsed_records)

    if unreadable_count > 0:
        click.echo(
            click.style(
                f"Unreadable files skipped: {unreadable_count}",
                fg="yellow",
            ),
            err=True,
        )

    if record_seq is not None:
        match = next(
            (
                rec
                for rec in sorted_records
                if rec.identity.chain_sequence_number == record_seq
            ),
            None,
        )
        if match is None:
            click.echo(
                click.style(
                    f"Error: record with chain_sequence_number={record_seq} not found",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(1)

        if output_format.lower() == "json":
            click.echo(json.dumps(match.to_json_dict(), indent=2))
        else:
            click.echo(_format_record_detail(match))
        return

    # List view: most recent last_n by sequence (tail of sorted chain).
    selected = (
        sorted_records[-last_n:] if last_n < len(sorted_records) else sorted_records
    )

    if output_format.lower() == "json":
        payload = [rec.to_json_dict() for rec in selected]
        click.echo(json.dumps(payload, indent=2))
    else:
        if not selected:
            click.echo("No records.")
            return
        click.echo(_format_records_table(selected))
