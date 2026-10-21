# hashtool

Create SHA-256 manifests of directory trees and verify files against them.

## Scope

This is a practice project, not a full-featured hashing tool. Mature tools
such as `sha256sum -c`, AIDE or Tripwire already solve this problem.

The goal is to work through the complete workflow of a small Python project
from scratch:

- project setup (`pyproject.toml`, src layout, `uv`, lockfile)
- local quality gates (pytest, ruff, pre-commit)
- continuous integration with GitHub Actions
- branch protection, pull requests and releases
- working with an AI assistant as the implementing developer

The hashing itself is deliberately simple. It is there to give the
pipeline something real to build, test and ship.

## How this project was built

The requirements were worked out in a back-and-forth discussion with
Claude (Anthropic). Both sides challenged each other's proposals:
manifest structure, sort order, symlink handling, overwrite protection,
error handling and CLI design were discussed one by one, and several
initial suggestions were rejected or changed along the way.

The decisions are mine. The implementation and the tests were written by
Claude Opus 5.5 and then reviewed, run and committed by me. This is
stated openly because it is the point of the exercise: specifying,
reviewing and shipping AI-written code within a proper CI workflow.

## Requirements

### Manifest

- JSON, UTF-8, LF line endings, no `\u` escapes for non-ASCII names
- Structured rather than flat, so the format can be extended:
  - `format_version`: allows `verify` to detect older formats
  - `algorithm`: currently always `sha256`
  - `created`: UTC timestamp in ISO 8601
  - `files`: maps each relative path to `{"hash": ..., "size": ...}`
- Paths are relative to the scanned directory and use `/` as separator,
  so a manifest created on Windows can be verified on Linux and vice versa
- Keys are sorted: scanning an unchanged directory produces a byte-identical
  file (apart from `created`), and diffs between manifests are readable
- No modification times (they change on copy) and no absolute root path
  (not portable, and it leaks information about the system)

### Scan

- Recursive, regular files only; empty directories are ignored
- Files are read in blocks via `hashlib.file_digest`
- Symlinks and Windows junctions are skipped by default; with
  `--follow-symlinks` they are followed and directory loops are detected
- The manifest file itself is excluded from the scan
- Exclude patterns (glob) via `-e/--exclude`; nothing is excluded
  implicitly, not even `.git/`
- Unreadable files are skipped with a warning; the manifest is still
  written, but the exit code signals that it is incomplete
- Progress is shown on stderr when it is a terminal (not in CI or pipes)

### Overwrite protection

A second scan into the same file would silently replace the reference
state that `verify` compares against. Therefore `scan` refuses to
overwrite an existing manifest unless `--force` is given.

### Design

Analysis, metadata and file output are separate functions
(`scan`, `build_manifest`, `write_manifest`). This keeps `scan` free of
timestamps and file output and makes it easy to test.

## Installation

Requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/mrasdev/hashtool.git
cd hashtool
uv sync
```

## Usage

```
hashtool scan DIRECTORY [-o FILE] [--force] [-e PATTERN ...]
                        [--follow-symlinks] [--no-progress]
```

| Option | Meaning |
|---|---|
| `-o, --output FILE` | manifest file (default: `DIRECTORY/hashtool-manifest.json`) |
| `--force` | overwrite an existing manifest |
| `-e, --exclude PATTERN` | glob pattern, repeatable; matches the relative path or the file name; a trailing `/` matches directories only |
| `--follow-symlinks` | follow symbolic links and junctions |
| `--no-progress` | disable progress output |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | manifest exists without `--force`, directory not found, or files skipped because they could not be read |
| 2 | invalid command line |

### Examples

Scan a directory, writing the manifest into it:

```
hashtool scan ~/photos
```

Scan a Git working copy without repository metadata and virtual environment:

```
hashtool scan . -e .git/ -e .venv/
```

Write the manifest outside the scanned directory, for example next to a backup:

```
hashtool scan /mnt/backup/projects -o ~/manifests/projects.json
```

Exclude temporary files and a specific path:

```
hashtool scan data -e "*.tmp" -e "*.log" -e cache/ -e reports/draft.docx
```

Rescan and replace an existing manifest:

```
hashtool scan ~/photos --force
```

Run without installing the entry point:

```
uv run python -m hashtool scan .
```

### Manifest example

```json
{
  "algorithm": "sha256",
  "created": "2026-10-21T07:30:15Z",
  "files": {
    "docs/readme.txt": {
      "hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "size": 4
    },
    "img/logo.png": {
      "hash": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
      "size": 3
    }
  },
  "format_version": 1
}
```

## Development

```
uv sync                       # create .venv, install project and dev tools
uv run pre-commit install     # once per clone: ruff on every commit
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting check (as in CI)
```

Symlink tests are skipped on Windows unless symlinks can be created
(developer mode or administrator rights). They run in CI on Linux.

## Status and roadmap

- [x] Project setup, tests, linting, pre-commit
- [x] `scan`
- [ ] `verify` (CHANGED / MISSING / NEW, exit code 0/1)
- [ ] GitHub Actions with a Python version matrix, actions pinned to commit hashes
- [ ] Dependabot, secret scanning
- [ ] Ruleset: pull requests and passing status checks required
- [ ] Feature branch, pull request, squash merge
- [ ] Tag-based release workflow, wheel tested in a fresh virtual environment

## License

MIT, see [LICENSE](LICENSE).
