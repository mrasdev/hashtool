# hashtool

CLI that creates SHA-256 manifests of directory trees and verifies files against them.
Practice project for CI and AI-assisted development, see `README.md`.

## Tech stack

- Python 3.12+ (code stays 3.12-compatible; CI tests 3.12 to 3.14 on Ubuntu and Windows)
- Standard library only, no runtime dependencies
- uv for environments (`uv sync`), dev tools in `[dependency-groups]`

## Project structure

- `src/hashtool/manifest.py`: scanning, building, writing and reading manifests (no CLI code, no printing)
- `src/hashtool/cli.py`: argparse, output, exit codes
- `tests/`: pytest, test files grouped by module or feature
- `docs/specs/NNN-<feature>.md`: specification per feature, written and approved before implementation

## Commands

- Tests: `uv run pytest`
- Lint and format: `uv run ruff check --fix .` and `uv run ruff format .`
- Before every commit: `uv run pytest` and `uv run pre-commit run --all-files`

## Conventions

- Code, identifiers, CLI output, comments and documentation in English
- Paths in manifests are relative and use `/`
- Files are read and written with explicit `encoding="utf-8"`; manifests use LF line endings
- Logic functions take dependencies as parameters (e.g. `now`), no hidden global state
- Symlink tests must skip when symlinks cannot be created (Windows without developer mode)

## Workflow

- Implement against the spec in `docs/specs/`; every acceptance criterion is covered by at least one test
- Tests first where practical; do not adapt tests to make the code pass
- Build nothing beyond the spec. Propose additions, do not implement them unasked
- No new dependencies without asking
- Stop after each feature: list changed files and wait for review. Do not commit or push
- New features on their own branch (`feature/<name>`), merged via pull request (squash)
