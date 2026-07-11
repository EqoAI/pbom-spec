"""Command-line interface for PBOM utilities."""

from __future__ import annotations

import json
import logging
import sys
from importlib.resources import files
from pathlib import Path

import click

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


@click.group()
def main() -> None:
    """PBOM command-line tools."""


@main.command("init")
def init_command() -> None:
    """Initialize PBOM output directory and local config."""
    pbom_dir = Path(".pbom")
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
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        if ".pbom/" not in lines:
            append_prefix = "" if not lines else "\n"
            gitignore_path.write_text(
                gitignore_path.read_text(encoding="utf-8") + f"{append_prefix}.pbom/\n",
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
    click.echo(f"Valid links: {result.valid_links}")

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

    commitment = result.commitment_results
    click.echo(
        click.style(
            (
                "Commitments: "
                f"verified={commitment['verified']} "
                f"unverifiable={commitment['unverifiable']} "
                f"failed={commitment['failed']}"
            ),
            fg="yellow",
        )
    )

    for detail in result.details:
        detail_color = "yellow"
        lowered = detail.lower()
        if "broken" in lowered or "duplicate" in lowered or "gap" in lowered:
            detail_color = "red"
        click.echo(click.style(f"- {detail}", fg=detail_color))

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
            payload = json.loads(path.read_text(encoding="utf-8"))
            parsed_records.append(PBOMRecord.model_validate(payload))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # Record file unreadable or invalid — skip for status summary
            # but count it so the user knows something was skipped.
            unreadable_count += 1
            logger.warning("Failed to parse PBOM record %s: %s", path, exc)

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

    click.echo(f"Last record timestamp: {latest.identity.created_at_iso}")
    click.echo(f"Storage mode: {latest.storage_mode}")
    click.echo(
        "Chain sequence range: "
        f"{first.identity.chain_sequence_number}..{latest.identity.chain_sequence_number}"
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
    if skill_target.exists() and not force:
        click.echo(
            f"SKILL.md already exists at {skill_target}. Use --force to overwrite."
        )
    else:
        skill_target.parent.mkdir(parents=True, exist_ok=True)
        skill_target.write_text(skill_text, encoding="utf-8")
        click.echo(f"Wrote skill file to {skill_target}")

    claude_md = cwd / "CLAUDE.md"
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
