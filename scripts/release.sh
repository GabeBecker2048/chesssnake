#!/usr/bin/env bash
#
# Release a version: check it, push the tag, and let the workflow do the rest.
#
#   ./scripts/release.sh X.Y.Z              release main as X.Y.Z
#   ./scripts/release.sh X.Y.Z --dry-run    run every check, print the notes, push nothing
#
# Pushing the tag vX.Y.Z is the whole release. .github/workflows/release.yml
# then tests, builds and publishes it, and creates the GitHub release from this
# version's CHANGELOG.md entry. No secrets here: the tag goes over your normal
# git remote, and the workflow authenticates to PyPI by itself.
#
# Before running: in a pull request, bump `version` in pyproject.toml, run
# `uv lock`, and add a "## X.Y.Z - YYYY-MM-DD" section to CHANGELOG.md. Merge
# it, then run this from an up-to-date main. Tests are not run here: CI ran
# them on the pull request, and the workflow runs them again before publishing.
#
# This file is identical in anchorless, chesssnake and whirligig. Change all three.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[2m%s\033[0m\n' "$*"; }
step() { printf '\033[1m==>\033[0m %s\n' "$*"; }
usage() { awk 'NR > 2 && /^#/ {sub(/^# ?/, ""); print; next} NR > 2 {exit}' "${BASH_SOURCE[0]}"; }

version=""
dry_run=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) dry_run=1 ;;
        -*) die "unknown option $1 (try --help)" ;;
        *) [[ -z "$version" ]] || die "give exactly one version"; version="$1" ;;
    esac
    shift
done
[[ -n "$version" ]] || die "usage: ./scripts/release.sh X.Y.Z [--dry-run]"
[[ "$version" != v* ]] || die "give the version without the leading 'v' (e.g. ${version#v})"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$ ]] \
    || die "'$version' does not look like a version (expected 1.2.3, or 1.2.3rc1)"

name=$(grep -m1 -E '^name *= *"' pyproject.toml | cut -d'"' -f2)
tag="v${version}"
notes=$(mktemp)
trap 'rm -f "$notes"' EXIT

# --- the same checks the workflow makes, but on your laptop ------------------
# Each of these would fail the run a minute after pushing. Failing here means
# there is no tag to delete and no red cross on the repo.

# The version is typed by hand, so it has to agree with the one being released.
grep -qE "^version *= *\"${version//./\\.}\"" pyproject.toml \
    || die "pyproject.toml declares $(grep -m1 -E '^version *= *"' pyproject.toml | cut -d'"' -f2), not ${version}"

# The release notes are the CHANGELOG section, so a missing one is a release
# with no notes. The separator after the version may be a hyphen or an em dash.
awk -v v="$version" '
    $0 ~ "^## " v "( |$)" {on=1; next}
    on && /^## / {exit}
    on {print}' CHANGELOG.md | sed -e '/./,$!d' > "$notes"
[[ -s "$notes" ]] || die "CHANGELOG.md has no '## ${version}' section; the release would have no notes"

[[ "$(git branch --show-current)" == main ]] || die "not on main (releases are cut from main)"

# Tracked changes only. The release is built from the tagged commit, so an
# untracked scratch file cannot reach it; worth mentioning in case it was meant to.
[[ -z "$(git status --porcelain --untracked-files=no)" ]] \
    || die "uncommitted changes to tracked files; commit or stash first"
untracked="$(git ls-files --others --exclude-standard)"
[[ -z "$untracked" ]] || note "note: untracked files are not part of this release: $(echo "$untracked" | tr '\n' ' ')"

git fetch --quiet --tags origin
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
    || die "main is not the same commit as origin/main (pull or push first)"

! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null || die "tag ${tag} already exists locally"
[[ -z "$(git ls-remote --tags origin "refs/tags/${tag}")" ]] || die "tag ${tag} already exists on origin"

uv lock --check >/dev/null 2>&1 || die "uv.lock is out of date (run uv lock, in a pull request)"

step "${name} ${tag} -> $(git rev-parse --short HEAD)  ($(git log -1 --format=%s | cut -c1-60))"
echo "--- release notes, from CHANGELOG.md ---"
cat "$notes"
echo "--- end ---"

if [[ "$dry_run" -eq 1 ]]; then
    note "dry run; would tag and push ${tag}"
    exit 0
fi

# Annotated, and dated to the commit: GitHub derives a release's created_at from
# the tag and orders the releases page by it.
GIT_COMMITTER_DATE="$(git log -1 --format=%cI HEAD)" git tag -a "$tag" -m "${name} ${version}"
git push --quiet origin "refs/tags/${tag}"

step "Pushed ${tag}. The workflow now tests, builds, publishes, and creates the release."
note "watch it: gh run watch \$(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
