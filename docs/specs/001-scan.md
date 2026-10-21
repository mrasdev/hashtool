# 001: scan

Status: implemented (amended by [002](002-verify.md): exit codes, `scan_options`)

## Goal

Create a manifest that records the SHA-256 hash and size of every regular file
below a directory, as the reference state for `verify`.

## Interface

```
hashtool scan DIRECTORY [-o FILE] [--force] [-e PATTERN ...]
                        [--follow-symlinks] [--no-progress]
```

- Default manifest: `DIRECTORY/hashtool-manifest.json`

## Requirements

1. Recursively hash all regular files; empty directories do not appear.
2. Files are read in blocks (`hashlib.file_digest`).
3. Keys are paths relative to `DIRECTORY` in `/` notation.
4. Symlinks and junctions are skipped unless `--follow-symlinks` is given;
   when following, directory loops are detected and not traversed twice.
5. `-e/--exclude` takes glob patterns (repeatable). A pattern matches the full
   relative path or the last path component; a trailing `/` matches
   directories only. Nothing is excluded implicitly.
6. The manifest file itself is never included (compared by resolved path).
7. An existing manifest is not overwritten unless `--force` is given.
8. Unreadable files are skipped with a warning on stderr; the manifest is
   still written; the exit code signals the incomplete result.
9. Progress is printed to stderr only if stderr is a terminal and
   `--no-progress` is not set.
10. Analysis, metadata and writing are separate functions
    (`scan`, `build_manifest`, `write_manifest`).

## Manifest format (version 1)

```json
{
  "algorithm": "sha256",
  "created": "2026-10-21T07:30:15Z",
  "files": {"docs/a.txt": {"hash": "<hex>", "size": 4}},
  "format_version": 1
}
```

- UTF-8 without `\u` escapes, LF line endings, keys sorted, trailing newline
- `created` in UTC, ISO 8601, seconds precision, suffix `Z`
- No modification times, no absolute root path

## Non-goals

- Unicode normalization of file names (NFC/NFD), case-insensitive matching
- Machine-readable CLI output
