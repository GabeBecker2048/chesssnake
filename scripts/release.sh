#!/usr/bin/env bash
#
# Release a version: push the tag, and let the workflow do the rest.
#
#   ./scripts/release.sh 0.9.2              release HEAD as 0.9.2
#   ./scripts/release.sh 0.9.2 --dry-run    print what it would do, change nothing
#
# Pushing the tag is the whole release. .github/workflows/release.yml then
# builds, publishes to PyPI and ghcr.io, and creates the GitHub release from
# this version's CHANGELOG.md entry.
#
# No secrets here: the tag goes over your normal git remote, and the workflow
# authenticates to PyPI and the registry by itself.
#
# See docs/releasing.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*"; }
step() { printf '\033[1m==>\033[0m %s\n' "$*"; }

VERSION=""
DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -*) die "unknown option $1 (try --help)" ;;
        *) [ -z "$VERSION" ] || die "give exactly one version"; VERSION="$1"; shift ;;
    esac
done
[ -n "$VERSION" ] || die "usage: ./scripts/release.sh X.Y.Z [--dry-run]"
case "$VERSION" in v*) die "give the version without the leading 'v' (e.g. 0.9.2)" ;; esac
echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$' \
    || die "'$VERSION' does not look like a version (expected 1.2.3, or 1.2.3rc1)"

TAG="v$VERSION"
NOTES="$(mktemp)"
trap 'rm -f "$NOTES"' EXIT

# --- the same checks the workflow makes, but on your laptop ------------------
# Each of these would fail the run a minute after pushing. Failing here means
# there is no tag to delete and no red cross on the repo.
grep -qE "^version = \"${VERSION}\"$" pyproject.toml \
    || die "pyproject.toml declares $(grep -m1 '^version' pyproject.toml | cut -d'"' -f2), not $VERSION"

awk -v v="$VERSION" '
    $0 ~ "^## " v "( |$)" {on=1; next}
    on && /^## / {exit}
    on {print}' CHANGELOG.md | sed -e '/./,$!d' > "$NOTES"
[ -s "$NOTES" ] || die "CHANGELOG.md has no '## $VERSION' section; the release would have no notes"

[ -z "$(git status --porcelain)" ] || die "the working tree is dirty; commit or stash first"

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || note "warning: you are on '$branch', not main"

git fetch -q origin main
git merge-base --is-ancestor HEAD origin/main \
    || die "HEAD is not on origin/main; push and merge it first"

! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
    || die "tag $TAG already exists locally"
[ -z "$(git ls-remote --tags origin "refs/tags/$TAG")" ] \
    || die "tag $TAG already exists on origin"

step "$TAG -> $(git rev-parse --short HEAD)  ($(git log -1 --format=%s | cut -c1-60))"
echo "--- release notes, from CHANGELOG.md ---"
cat "$NOTES"
echo "--- end ---"

if [ "$DRY_RUN" -eq 1 ]; then
    note "dry run; would tag and push $TAG"
    exit 0
fi

# Annotated, and dated to the commit: GitHub derives a release's created_at from
# the tag and orders the releases page by it.
GIT_COMMITTER_DATE="$(git log -1 --format=%cI HEAD)" git tag -a "$TAG" -m "$TAG"
git push origin "refs/tags/$TAG"

step "Pushed. The workflow now builds, publishes to PyPI and ghcr.io, and creates the release."
note "watch it: gh run watch \$(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
