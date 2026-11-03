# Releasing to PyPI

Publishing a GitHub release publishes the same version to PyPI. The workflow is
`.github/workflows/release.yml`; this page is the one-time setup and the
per-release checklist.

## One-time setup: trust this repository on PyPI

No API token is involved. PyPI's **Trusted Publishing** lets GitHub prove which
repository, workflow and environment is asking, and hands back a one-off upload
token. There is nothing to store in GitHub secrets, nothing to rotate, and a
leaked log cannot be replayed.

On <https://pypi.org/manage/project/chesssnake/settings/publishing/>, add a
publisher:

| Field | Value |
|---|---|
| Owner | `GabeBecker2048` |
| Repository name | `chesssnake` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The environment name must match the `environment: name: pypi` in the workflow.
Both sides have to agree or the upload is rejected, which is the point.

Optionally, in the repo's **Settings → Environments → pypi**, add yourself as a
required reviewer. Releases then pause for a click before the upload, which is
worth it if you ever automate the release itself.

### If you would rather use an API token

Trusted publishing is better, but a token works: create one scoped to the
`chesssnake` project, store it as the `PYPI_API_TOKEN` secret, drop the
`permissions: id-token: write` block from the publish job, and give the publish
step `with: { password: ${{ secrets.PYPI_API_TOKEN }} }`. You then own a
long-lived credential that can upload on your behalf until you revoke it.

## Releasing

1. **Bump the version** in `pyproject.toml` and add a `## X.Y.Z - YYYY-MM-DD`
   section to `CHANGELOG.md`. That section becomes the release notes, so a
   missing one fails the run.
2. **Merge to `main`** and let CI go green.
3. **Push the tag:**

   ```sh
   ./scripts/release.sh 0.9.2
   ./scripts/release.sh 0.9.2 --dry-run   # print what it would do
   ```

Pushing the tag is the whole release. `scripts/release.sh` re-runs the
workflow's own checks on your laptop first (version matches, CHANGELOG section
exists, tree clean, commit on `origin/main`, tag unused), so a mistake costs
nothing instead of leaving a tag to delete and a red cross on the repo. It then
creates an annotated tag, dated to the commit, and pushes it.

The workflow then, in order:

- **checks** the tag against `pyproject.toml`, extracts the CHANGELOG section
  into the release notes, runs lint, mypy and the full suite on both backends
  with the coverage gate, builds the sdist and wheel, runs `twine check`, and
  **installs the wheel into a clean venv** to render a board from it. That last
  step catches a missing `[tool.setuptools.package-data]` entry, which the test
  suite cannot see because it runs against the source tree.
- **publishes to PyPI** through Trusted Publishing.
- **builds and pushes the container image** to
  `ghcr.io/gabebecker2048/chesssnake` for `linux/amd64` and `linux/arm64`,
  tagged `X.Y.Z`, `X.Y`, `X` and `latest`.
- **creates the GitHub release** last, with the notes and the built artifacts
  attached, so the release page only appears once both registries have the
  version.

The tag is the trigger rather than a GitHub release, so the release page is
created by the same run that built the artifacts. There is no window in which a
release exists but nothing was published.

## If it goes wrong

- **Tag/version mismatch**: the first job fails and nothing is built. Fix the
  version or the tag and publish the release again.
- **Tests fail**: nothing is published. No release is created, so fix
  forward and re-publish, or delete the release and tag.
- **`File already exists` from PyPI**: that version is already published.
  **PyPI does not allow re-uploading a version, even after deleting it.** Bump
  to the next patch and release that. The workflow deliberately does not pass
  `skip-existing`, because a publish that quietly did nothing would leave you
  believing the new code shipped.
- **A bad release is already on PyPI**: you cannot replace it. Yank it
  (Manage → Releases → Yank), which hides it from new installs while leaving it
  resolvable for anyone who pinned it, then release a fixed version.

## Backfilling historical releases

Not applicable any more: every version through 0.9.1 already has a tag and a
release. If you ever need to add one for an old commit, create the tag by hand
with `GIT_COMMITTER_DATE` set to that commit's date (GitHub orders the releases
page by the tag's date) and create the release with `gh release create`. Do not
route it through this workflow: its test step runs
`--extra postgres --group pg`, and those extras did not exist before 0.9.0, so
0.8.0 and earlier fail the gate with `Extra 'postgres' is not defined`.
