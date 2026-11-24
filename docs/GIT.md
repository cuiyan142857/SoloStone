# Git guidelines

How SoloStone's branches and commits are named, and how a change gets into `main`. Pull requests are welcome
([CONTRIBUTING.md](../.github/CONTRIBUTING.md)).

## Branches

| Branch | For | Starts from | Ends in |
|---|---|---|---|
| `main` | The latest accepted work; always buildable, and changed only by a squash-merged pull request | | |
| `feature/<name>` | New behaviour, e.g. `feature/arena-mode` | `main` | `main` |
| `fix/<name>` | A bug fix, e.g. `fix/legend-rank-count` | `main` | `main` |
| `release/<version>` | Getting a release ready: version, notes, signed manifest, e.g. `release/0.1.1` | `main` | `main`, tagged `v<version>` |

- Names are lowercase, with hyphens between words.
- One topic per branch. Delete the branch once it's merged.
- Each release is tagged `v<version>` on `main`, e.g. `v0.1.0`. The launcher downloads updates from that tag.
- Outside contributors work on a branch in their own fork. Maintainers branch in the main repository.

## Pull requests and squash merges

- Every change reaches `main` through a pull request. **Nothing is pushed to `main` directly**, and history on `main`
  and on tags is never rewritten or force-pushed.
- `tests` (`python3 tests/run.py --ci`) and `scan` must pass before a merge.
- `scan` runs `tools/release_scan.py` with the public rules in `tools/release_scan.public.json` over the whole tree and over
  every new commit's message and the files it adds. It looks for Blizzard files and libraries, media outside the allowed
  list, decompiled code, encoded blobs, personal data and email addresses, and wording the project does not use (for
  example offers of payment). Run it locally before you push:
  `python3 tools/release_scan.py --source . --skip-git --allow-no-private-config --strict --trust-public-rules --public-rules tools/release_scan.public.json`.
  A waiver for a real hit goes in the rules file, with a reason, and the owner reviews it.
- The `scan` workflow runs on `pull_request_target`: GitHub runs the workflow, the scanner and the rules **as they are on
  `main`**, and the pull request's files are only read, never run. A pull request therefore cannot loosen the scan that
  judges it. `.github/`, `tools/release_scan.py`, `tools/release_scan.public.json`, `tools/privacy_scan.py` and
  `installer/stage.py` are listed in `.github/CODEOWNERS` under `@KeyStarr`, who reviews changes to them. This is advisory
  while there is one maintainer: GitHub's "require review from code owners" setting stays off, because a sole owner could
  not approve their own pull request.
- A pull request is **squash-merged**: one commit on `main` per pull request. The pull request title becomes the commit
  subject, so write it as a commit subject (below).
- Commit under one identity per person, with an email that person is happy to have public.

## Syncing the macOS fork

In `cuiyan142857/SoloStone`, the upstream sync workflow checks for the latest stable release of
`KeyStarr/SoloStone` daily at 01:17 UTC and can also be run from Actions. It opens a PR for a clean
merge, stops on conflicts, and leaves gameplay changes in draft for review. The sync PR stores the
upstream commit in `.github/upstream-release` so the next sync can use the correct merge base after
squashing.

Create a GitHub Actions environment named `upstream-sync` with a deployment branch rule allowing
only the `main` branch. Store a repository-scoped credential there as the `UPSTREAM_SYNC_TOKEN`
environment secret. Grant it write access to Contents and Pull requests, plus Workflows if the
upstream release changes workflow files. The separate credential lets sync PRs trigger CI. The
environment branch rule keeps the sync credential out of pull request runs.

With GitHub auto-merge enabled and the `tests`, `scan`, and `macos-preview` GitHub Actions checks
required on `main`, the auto-merge workflow queues eligible ready PRs from the fork owner for a
squash merge. Changes to gameplay, CI, or release tooling need manual review. The R7 and live drag
requirements in [TESTING.md](TESTING.md#client-drop-prediction) apply to changes to played-card history.

## Commits

```text
<type>: <change>; <change>; <change>

Optional: why, when a change isn't obvious from the diff.
```

| Type | For |
|---|---|
| `feat` | New behaviour |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `release` | Version, manifest, release notes |

Examples:

```text
feat: Arena draft screen; 3-card picks; run rewards
fix: Legend rank counts every NPC with a Legend medal; rank text no longer overlaps
release: 0.1.1

The manifest seq goes to 2; 0.1.0 installs pick the update up on their next launch.
```

- The subject line is short, in the present tense, with no full stop at the end.
- Separate several changes with `;`. If it no longer fits on one line, split it into more commits.
- A body is optional. Write one only when the reason for the change would surprise a reader.

For example:

```text
fix: Legend rank counts every NPC with a Legend medal
```
