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
Both sides have to agree or the upload is rejected — that is the point.

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

1. **Bump the version** in `pyproject.toml` and add the row to
   `VersionHistory.md` (move the previous `Latest` to `Released`). The version
   there is the source of truth; the tag only has to agree with it.
2. **Merge that to `main`** and let CI go green.
3. **Draft the release** on GitHub — `gh release create v0.9.1 --draft --generate-notes`,
   or the web UI. Tag `v0.9.1` (a bare `0.9.1` is accepted too).
4. **Publish it.** That is the trigger. Nothing ships from a draft, so the notes
   can be written and rewritten first.

The workflow then, in order:

- **checks the tag matches `pyproject.toml`** and stops if not. Tagging `v0.9.2`
  while the project still says `0.9.1` is the easy mistake, and it would
  otherwise either be rejected by PyPI as a duplicate or publish something you
  did not mean to.
- **runs lint, mypy and the full suite on both backends** with the coverage
  gate. `ci.yml` covers pushes to `main` and pull requests, neither of which is
  "the exact tree this tag points at".
- **builds** the sdist and wheel with `uv build`, runs `twine check` so a README
  PyPI will not render is caught *before* upload, then **installs the wheel into
  a clean venv** and plays a move, loads the packaged font and images, and
  renders a board. That last step is what catches a missing
  `[tool.setuptools.package-data]` entry, which the test suite cannot see
  because it runs against the source tree.
- **publishes to PyPI**, then **attaches the identical sdist and wheel to the
  GitHub release**, so what is on PyPI and what is on the release page are
  provably the same files.

A pre-release works the same way: mark it as a pre-release on GitHub and give it
a pre-release version (`0.10.0rc1`). PyPI takes it, and `pip install chesssnake`
skips it unless asked. Nothing in the workflow treats it specially — the version
number is what carries that meaning.

## If it goes wrong

- **Tag/version mismatch** — the first job fails and nothing is built. Fix the
  version or the tag and publish the release again.
- **Tests fail** — nothing is published. The release stays up on GitHub, so fix
  forward and re-publish, or delete the release and tag.
- **`File already exists` from PyPI** — that version is already published.
  **PyPI does not allow re-uploading a version, even after deleting it.** Bump
  to the next patch and release that. The workflow deliberately does not pass
  `skip-existing`, because a publish that quietly did nothing would leave you
  believing the new code shipped.
- **A bad release is already on PyPI** — you cannot replace it. Yank it
  (Manage → Releases → Yank), which hides it from new installs while leaving it
  resolvable for anyone who pinned it, then release a fixed version.

## Note: PyPI is behind

PyPI's latest is **0.6.6**, which predates the REST api-endpoint entirely. 0.7.0
through 0.9.0 are marked Released in `VersionHistory.md` but were never
uploaded, so `pip install chesssnake` gets a version with no server, no config
system and no SQLite support, and none of the documentation in the README
applies to it. Worth publishing a current version early, whether or not it is
through this workflow.
