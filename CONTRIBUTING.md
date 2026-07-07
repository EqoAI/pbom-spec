# Contributing to PBOM

Thanks for helping improve PBOM.

## Getting started

- Clone: `git clone https://github.com/eqo/pbom-spec.git`
- Install with dev deps: `pip install -e ".[dev]"`
- Python 3.10+ required

## Contribution workflow

- Fork the repository and create a feature branch from `main`
- Make your changes and commit with DCO sign-off (see below)
- Open a pull request against `main`
- All pull requests require review before merge

## Code style

- Run `ruff check src/ tests/` and ensure it passes with zero warnings
- Run `ruff format src/ tests/` so code is formatted consistently
- Do not use `print()` in library code under `src/pbom/`; use `logging.getLogger("pbom")`
- `src/pbom/cli.py` may use `click.echo` for command output
- Type hints are required on all public function signatures, including return types
- Docstrings are required on all public classes and functions

## Testing

- Run: `pytest -v`
- All existing tests must pass before a pull request is mergeable
- New behavior must include new tests
- Use `tmp_path` for file operations in tests

## Dependencies

- Core package runtime dependencies are limited to `pydantic` and `click`
- Do not add new runtime dependencies without prior discussion and approval
- Dev dependencies such as `pytest`, `ruff`, and `pytest-cov` are acceptable

## Spec / format changes

- Open an issue first to discuss any change to the PBOM record format
- Do not submit breaking format changes without prior discussion and consensus
- Read `.claude/constitution.md` before contributing; it contains 15 inviolable project rules

## DCO sign-off

All commits must include a Developer Certificate of Origin sign-off line:

```text
Signed-off-by: Real Name <email@example.com>
```

Use `git commit -s` to add this automatically. This certifies that you have the right to submit the contribution under the project's Apache 2.0 license.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 license (see `LICENSE`).
