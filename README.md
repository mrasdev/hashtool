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
  - `scan_options`: exclude patterns and symlink setting used by `scan`,
    so that `verify` selects exactly the same files (optional for readers)
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

### Verify

- Reads and validates the manifest first; an unknown `format_version` or
  `algorithm` is an error, not a guess
- Selects files with the options stored in `scan_options`; files excluded
  at scan time are not reported as new
- Compares sizes first and hashes only files whose size is unchanged
- Reports every path that is not OK as `CHANGED`, `MISSING`, `NEW` or
  `ERROR`, sorted by path, followed by a summary line

### Overwrite protection

A second scan into the same file would silently replace the reference
state that `verify` compares against. Therefore `scan` refuses to
overwrite an existing manifest unless `--force` is given.

### Design

Analysis, metadata and file output are separate functions
(`scan`, `build_manifest`, `write_manifest`). This keeps `scan` free of
timestamps and file output and makes it easy to test. The classification
in `verify` is a pure function (`compare`) that receives the hash lookup
as a parameter, so it can be tested without touching the file system.

Specifications per feature live in [`docs/specs/`](docs/specs/), conventions
for the AI assistant in [`CLAUDE.md`](CLAUDE.md).

## Installation

Requires Python 3.12 or later.

From a release: download the wheel from the
[releases page](https://github.com/mrasdev/hashtool/releases) and install it
as a command line tool:

```
uv tool install hashtool-0.1.0-py3-none-any.whl
hashtool --version
```

From source (requires [uv](https://docs.astral.sh/uv/)):

```
git clone https://github.com/mrasdev/hashtool.git
cd hashtool
uv sync
```

## Usage

`hashtool --version` prints the installed version.

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

```
hashtool verify DIRECTORY [-m FILE] [--no-progress]
```

| Option | Meaning |
|---|---|
| `-m, --manifest FILE` | manifest to verify against (default: `DIRECTORY/hashtool-manifest.json`) |
| `--no-progress` | disable progress output |

Output of `verify`, one line per difference and a summary:

```
CHANGED  docs/readme.txt
NEW      img/banner.png
MISSING  img/logo.png
3 ok, 1 changed, 1 missing, 1 new
```

### Exit codes

Same scheme as `diff` and `cmp`:

| Code | Meaning |
|---|---|
| 0 | success; for `verify`: no differences |
| 1 | `verify`: differences found |
| 2 | error: invalid command line, directory or manifest not found, manifest invalid or unsupported, manifest exists without `--force`, file unreadable |

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

Verify a directory against its manifest, for example in a script:

```
hashtool verify ~/photos || echo "photos changed or verification failed"
```

Verify a backup against a manifest stored elsewhere:

```
hashtool verify /mnt/backup/projects -m ~/manifests/projects.json
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
  "format_version": 1,
  "scan_options": {
    "exclude": [".git/"],
    "follow_symlinks": false
  }
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
(developer mode or administrator rights). They run in CI on Linux and on
the Windows runners.

## Releases

The version is not written anywhere in the code. It is derived from the Git
tag by [hatch-vcs](https://github.com/ofek/hatch-vcs): a tagged commit builds
as `0.1.0`, later commits as development versions such as
`0.1.1.dev3+g1a2b3c4`, and a source tree without Git metadata as `0.0.0`.

To publish a release, tag a commit on `main` and push the tag:

```
git switch main
git pull
git tag -a v0.1.0 -m "hashtool 0.1.0"
git push origin v0.1.0
```

The [release workflow](.github/workflows/release.yml) then

1. builds the wheel and the source distribution and checks that their
   version matches the tag and that the wheel contains only the package,
2. installs the wheel into a fresh virtual environment on Ubuntu and
   Windows, without the source tree, and runs `--version`, `scan` and
   `verify` against a temporary directory,
3. creates a GitHub Release with both files attached. Only this last job
   has write access to the repository.

## Status and roadmap

- [x] Project setup, tests, linting, pre-commit
- [x] `scan`
- [x] `verify` (CHANGED / MISSING / NEW / ERROR, exit codes 0/1/2)
- [x] GitHub Actions with a Python version matrix, actions pinned to commit hashes
- [x] Dependabot, secret scanning
- [x] Ruleset: pull requests and passing status checks required
- [x] Feature branch, pull request, squash merge
- [x] Tag-based release workflow, wheel tested in a fresh virtual environment

## License

MIT, see [LICENSE](LICENSE).
