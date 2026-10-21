# 002: verify

Status: approved, not implemented
Issue: #2

## Goal

Compare a directory against a manifest created by `scan` and report every
difference, with an exit code that scripts and CI can rely on.

## Interface

```
hashtool verify DIRECTORY [-m FILE] [--no-progress]
```

- `-m/--manifest FILE`: manifest to verify against
  (default: `DIRECTORY/hashtool-manifest.json`)

## Exit codes (all commands)

Same scheme as `diff` and `cmp`:

| Code | Meaning |
|---|---|
| 0 | success; for `verify`: no differences |
| 1 | `verify` only: differences found (CHANGED, MISSING or NEW) |
| 2 | error: invalid arguments, directory or manifest not found, manifest invalid or unsupported, manifest exists without `--force`, file unreadable |

If `verify` finds both differences and errors, the exit code is 2.

## Requirements

1. The manifest is read and validated before the directory is scanned:
   - not found or not valid JSON → error, exit 2
   - `format_version` other than 1 → error naming the version, exit 2
   - `algorithm` other than `sha256` → error naming the algorithm, exit 2
   - missing `files` object → error, exit 2
2. The directory is scanned with the options stored in the manifest's
   `scan_options` (see "Changes to scan"). If `scan_options` is absent,
   defaults are used (no excludes, symlinks not followed).
3. The manifest file is excluded from the scan, as in `scan`.
4. Each path is classified:
   - `OK`: in manifest and directory, same size and hash
   - `CHANGED`: in both, size or hash differs
   - `MISSING`: in manifest, not in directory
   - `NEW`: in directory, not in manifest
   - `ERROR`: in directory but could not be read
5. Size is compared first; if it differs, the file is `CHANGED` without
   hashing it.
6. Output on stdout, one line per non-OK path, sorted by path:
   `STATUS  path` with the status padded to 7 characters, e.g.
   `CHANGED  docs/a.txt`, `MISSING  b.txt`, `NEW      c.txt`.
   `ERROR` lines additionally carry the error message.
7. Final summary line on stdout:
   `N ok, N changed, N missing, N new` (plus `, N errors` if any).
8. Progress on stderr under the same conditions as `scan`.
9. Comparison logic lives in `manifest.py` (or a new module) as a pure
   function that takes the stored and the current file entries and returns
   the classification; the CLI only prints.

## Changes to scan

1. `scan` stores its options in the manifest:
   ```json
   "scan_options": {"exclude": [".git/"], "follow_symlinks": false}
   ```
   `exclude` keeps the order given on the command line.
2. `format_version` stays 1: the field is additive and optional for readers.
3. Exit codes follow the table above: errors now return 2 instead of 1
   (existing manifest without `--force`, directory not found, unreadable files).

## Acceptance criteria

- [ok] Unchanged directory: exit 0, no status lines, summary shows only ok count
- [ok] Modified content with equal size → `CHANGED`
- [ok] Modified size → `CHANGED`, file is not hashed (verified via test double)
- [ok] Deleted file → `MISSING`; added file → `NEW`; exit 1
- [ok] Output lines sorted by path, status padded as specified
- [ok] Excludes stored by `scan` are applied: files matching them are not `NEW`
- [ok] Manifest without `scan_options` is accepted
- [ok] Manifest file itself is never reported as `NEW`
- [ok] `-m` with a manifest outside the directory works
- [ok] Missing manifest, invalid JSON, unknown `format_version`, unknown
      `algorithm`, missing `files` → exit 2 with a clear message on stderr
- [ok] Unreadable file → `ERROR` line, exit 2
- [ok] `scan` writes `scan_options`; `scan` errors exit with 2
- [ok] Existing `scan` tests adapted only where exit codes changed

## Non-goals

- Machine-readable output (`--json`), `--quiet`
- Overriding stored scan options on the command line
- Unicode normalization, case-insensitive matching
- Updating the manifest from `verify`
