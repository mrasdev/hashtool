# 003: release

Status: approved, implemented
Issue: #5

## Goal

Pushing a version tag produces a GitHub Release with a wheel and a source
distribution whose version is derived from the tag. The wheel is installed
and smoke-tested outside the source tree before anything is published.

## Interface

### Version option

```
hashtool --version
```

- Prints `hashtool X.Y.Z` (version from the installed package metadata), exit 0

### Release trigger

```
git tag -a v0.1.0 -m "hashtool 0.1.0"
git push origin v0.1.0
```

- Tags have the form `vMAJOR.MINOR.PATCH` and are annotated
- The workflow `.github/workflows/release.yml` runs on `push` of tags `v*`

## Requirements

### Build system

1. Build backend is hatchling with hatch-vcs; setuptools is removed.
2. `version` is no longer in `pyproject.toml`; it is `dynamic` and read from
   the Git tag. Between tags, hatch-vcs produces a development version
   (e.g. `0.1.1.dev3+g1a2b3c4`).
3. A checkout without any reachable tag must still build and install
   (hatch-vcs then produces `0.0.1.devN+g<hash>`); a source tree without Git
   metadata falls back to `0.0.0`. Local development and CI never depend on tags.
4. The wheel contains exactly the package from `src/hashtool` (declared
   explicitly, not left to auto-detection).
5. The CI workflow checks out with `fetch-depth: 0`, so CI builds see the tags.

### Release workflow

Three jobs, all actions pinned to commit SHAs, `persist-credentials: false`,
`timeout-minutes` set. Top-level `permissions: contents: read`.

1. **build** (ubuntu-latest)
   - Checkout with full history (`fetch-depth: 0`)
   - `uv build` creates `dist/*.whl` and `dist/*.tar.gz`
   - Fails if the version in the wheel file name does not equal the tag
     without the leading `v`
   - Uploads `dist/` as a workflow artifact
2. **test-wheel** (needs build; matrix ubuntu-latest and windows-latest,
   Python 3.12 as the lowest supported version)
   - **No checkout**: only the downloaded artifact is available
   - Creates a fresh virtual environment and installs the wheel into it
   - `hashtool --version` prints exactly `hashtool <tag without v>`
   - Smoke test in a temporary directory: `scan` exits 0; `verify` exits 0;
     after modifying a file `verify` exits 1
3. **release** (needs test-wheel; ubuntu-latest)
   - Only this job has `permissions: contents: write`
   - Creates a GitHub Release named after the tag with the wheel and the
     source distribution attached (`gh release create`)
   - Fails if a release for the tag already exists (no silent overwrite)

### Documentation

- README: release process (tag, push, result), `--version`, roadmap updated
- `001-scan.md` / `CLAUDE.md`: mention of setuptools replaced where relevant

## Acceptance criteria

- [ok] `uv sync` and `uv run pytest` work locally on a checkout without tags
- [ok] `uv build` on a tagged commit produces files with exactly that version
- [ok] `hashtool --version` prints `hashtool <version>`; covered by a test
- [ok] CI (`ci.yml`) stays green with `fetch-depth: 0`
- [ok] Wheel contains `hashtool/` package only (no tests, no docs)
- [ok] Pushing `v0.1.0` creates a GitHub Release with `.whl` and `.tar.gz`
- [ok] test-wheel runs on Ubuntu and Windows without a source checkout
- [nok] A tag whose version does not match the built version fails in build
  --> check in place, not exercised
- [ok] Only the release job has write permissions

## Non-goals

- Publishing to PyPI
- Generated changelogs or release notes beyond a short fixed text
- Build provenance attestations
- Signing tags or artifacts

## Recommendation (repository setting, not part of the code)

- Tag ruleset for `v*`: restrict deletions and updates, so a published
  version tag cannot be moved later (the same reason actions are pinned).
