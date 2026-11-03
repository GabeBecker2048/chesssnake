#!/usr/bin/env bash
#
# Cut a GitHub release, which is what publishes the version to PyPI.
#
#   ./scripts/release.sh 0.9.1                  release HEAD as 0.9.1
#   ./scripts/release.sh 0.9.1 --draft          write it up first, publish by hand
#   ./scripts/release.sh 0.7.0 --commit a216b1e tag a past commit (backfilling history)
#   ./scripts/release.sh 0.9.1 --dry-run        print what it would do, change nothing
#
# Authentication is whatever `gh` already has, so this file holds no secrets and
# is safe to commit. Uploading to PyPI happens in the Actions workflow, through
# Trusted Publishing -- never from here, and never from a laptop.
#
# See docs/releasing.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*"; }
step() { printf '\033[1m==>\033[0m %s\n' "$*"; }

usage() {
    sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

VERSION=""
COMMIT=""
DRAFT=0
DRY_RUN=0
PRERELEASE=0

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage 0 ;;
        --draft) DRAFT=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --prerelease) PRERELEASE=1; shift ;;
        --commit) COMMIT="${2:-}"; [ -n "$COMMIT" ] || die "--commit needs a commit-ish"; shift 2 ;;
        -*) die "unknown option $1 (try --help)" ;;
        *)
            [ -z "$VERSION" ] || die "give exactly one version (got '$VERSION' and '$1')"
            VERSION="$1"; shift ;;
    esac
done

[ -n "$VERSION" ] || usage 1
# Reject a leading v so the tag is formed in exactly one place, below.
case "$VERSION" in v*) die "give the version without the leading 'v' (e.g. 0.9.1)" ;; esac
# PEP 440 enough for this project: N.N.N with an optional pre-release suffix.
echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$' \
    || die "'$VERSION' does not look like a version (expected 1.2.3, or 1.2.3rc1)"

TAG="v$VERSION"
TARGET="${COMMIT:-HEAD}"
SHA="$(git rev-parse --verify "$TARGET^{commit}" 2>/dev/null)" || die "no such commit: $TARGET"

command -v gh >/dev/null || die "the gh CLI is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated; run: gh auth login"

# --- the tag must not lie about what it points at --------------------------
# The version in pyproject.toml at the tagged commit is the source of truth; the
# release workflow checks the same thing and refuses to build on a mismatch.
# Checking here means finding out before a tag is pushed rather than after.
declared="$(git show "$SHA:pyproject.toml" 2>/dev/null | sed -n 's/^version[[:space:]]*=[[:space:]]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' | head -1 || true)"
if [ -z "$declared" ]; then
    # Versions before 0.6.7 declared it in setup.py; those are history, not new releases.
    declared="$(git show "$SHA:setup.py" 2>/dev/null | sed -n 's/.*version[[:space:]]*=[[:space:]]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' | head -1 || true)"
fi
[ -n "$declared" ] || die "cannot read a version from $SHA (no pyproject.toml or setup.py)"
[ "$declared" = "$VERSION" ] \
    || die "commit $(git rev-parse --short "$SHA") declares version '$declared', not '$VERSION'.
       Bump pyproject.toml (and VersionHistory.md) first, or pass --commit for the right one."

if [ -z "$COMMIT" ]; then
    # Only enforced for a release of the current tree; a backfill of an old
    # commit legitimately has newer work sitting on top of it.
    [ -z "$(git status --porcelain)" ] || note "warning: the working tree is dirty; the tag points at the last commit, not your edits"
    branch="$(git rev-parse --abbrev-ref HEAD)"
    [ "$branch" = "main" ] || note "warning: you are on '$branch', not main"
    git fetch -q origin main
    git merge-base --is-ancestor "$SHA" origin/main \
        || die "$(git rev-parse --short "$SHA") is not on origin/main -- push and merge it first"
fi

# --- release notes ----------------------------------------------------------
# Pulled from VersionHistory.md, which is the changelog this project actually
# keeps, so the release page and the table cannot drift apart. The row format is
#   | 0.9.1 | 2026-11-02 | ...notes... | Gabe Becker | Latest |
notes_file="$(mktemp)"
trap 'rm -f "$notes_file"' EXIT
row="$(grep -m1 "^| *${VERSION//./\\.} *|" VersionHistory.md || true)"
if [ -n "$row" ]; then
    python3 - "$row" "$VERSION" > "$notes_file" <<'PY'
import sys
row, version = sys.argv[1], sys.argv[2]
cells = [c.strip() for c in row.strip().strip("|").split("|")]
# version | date | notes | author | status -- the notes cell is everything
# between the date and the trailing two, so an embedded pipe cannot truncate it.
date = cells[1] if len(cells) > 1 else ""
body = " | ".join(cells[2:-2]) if len(cells) > 4 else (cells[2] if len(cells) > 2 else "")
print(body.replace("**Breaking.**", "> [!WARNING]\n> **Breaking changes in this release.**\n").strip())
print()
print(f"_Released {date}. See [VersionHistory.md](../../blob/main/VersionHistory.md) for the full table._")
PY
    note "notes taken from VersionHistory.md"
else
    note "no VersionHistory.md row for $VERSION -- falling back to generated notes"
    : > "$notes_file"
fi

# Create and push the tag ourselves rather than letting `gh` do it through
# `--target`. GitHub's release API rejects `target_commitish` for some perfectly
# valid commits with a bare 404 -- reproduced on four of this project's own
# history commits (0.6.7, 0.7.0, 0.7.1, 0.8.0), each of them on main and
# resolvable through every other endpoint, while neighbouring commits were fine.
# Creating the tag first sidesteps the question: the release is then made from a
# ref that already exists.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    existing="$(git rev-parse "refs/tags/$TAG^{commit}")"
    [ "$existing" = "$SHA" ] || die "tag $TAG already exists locally at ${existing:0:9}, not ${SHA:0:9}"
else
    [ "$DRY_RUN" -eq 1 ] || git tag -a "$TAG" -m "$TAG" "$SHA"
fi
[ "$DRY_RUN" -eq 1 ] || git push -q origin "refs/tags/$TAG"

args=(release create "$TAG" --title "$TAG")
if [ -s "$notes_file" ]; then args+=(--notes-file "$notes_file"); else args+=(--generate-notes); fi
[ "$DRAFT" -eq 1 ] && args+=(--draft)
[ "$PRERELEASE" -eq 1 ] && args+=(--prerelease)

step "$TAG -> $(git rev-parse --short "$SHA")  ($(git log -1 --format=%s "$SHA" | cut -c1-60))"
if gh release view "$TAG" >/dev/null 2>&1; then
    die "release $TAG already exists: $(gh release view "$TAG" --json url --jq .url)"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    note "dry run; would run: gh ${args[*]}"
    echo "--- notes ---"; cat "$notes_file"; echo "--- end ---"
    exit 0
fi

gh "${args[@]}"

if [ "$DRAFT" -eq 1 ]; then
    step "Draft created. Publishing it is what triggers the PyPI upload."
else
    step "Published. Watch the upload: gh run watch \$(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
fi
