# Reference PR flow

This folder shows how Receipts would sit in a pull-request flow. It is a reference. Nothing here has run against GitHub, and nothing in this repository was pushed anywhere.

## Files

| File | What it is |
|---|---|
| `github-action.yml` | Workflow with two jobs. `review` runs on PRs labelled `agent-authored`. `sign` runs when someone comments `/receipts sign`. |
| `CODEOWNERS.example` | Example owners for the areas in `policy/areas.yaml`, using made-up `example-org` teams. |

## The flow

1. An agent opens a PR and the `agent-authored` label is set.
2. `review` runs `python -m receipts review --change <id>`, then `pr-comment` to write one markdown comment (lane, reading budget, claims with evidence levels, refusals that need an answer, what was not checked). The job posts it, or edits its earlier comment, using a marker on the first line.
3. `required-owner` finds the highest-lane files in the change and looks them up in CODEOWNERS. The result is stored in the comment as `<!-- receipts:owners=... -->`.
4. The job sets the commit status `receipts/owner-signed` to pending. Mark that status as required in branch protection.
5. A required signer approves the PR at its current head commit, then comments `/receipts sign`. The `sign` job checks the commenter against the stored owners (users, or team membership), checks the approval, and sets the status to success.
6. No lane merges by itself. Without the signature the status stays pending.

## What works today, locally

- `python -m receipts pr-comment --change 2283` prints the comment.
- `python -m receipts required-owner --change 2283` prints the signing owners from `route.json`. It reads `integration/CODEOWNERS.example` unless you pass `--codeowners`.
- `github-action.yml` parses as YAML and the three inline JavaScript blocks pass a syntax check.

## What is not implemented

- **Never run on GitHub.** No real PR, no real token, no branch protection. Expect to fix small things on the first run. `actionlint` was not available here, so it has had no full lint.
- **Arbitrary PRs.** `receipts review` resolves a change from the four Tieto branches listed in `receipts/config.py`. A real PR needs `--base` and `--head` options on `ingest`, and a way to run the evidence stages for it. Neither exists.
- **Evidence in CI.** Time Machine, X-Ray and the model stages are not run by the workflow. It would post whatever `runs/<id>/` already holds, so the first comment on a new PR would show claims with no evidence behind them.
- **The receipt itself.** `/receipts sign` only flips the status. Answering each refusal and writing the residual risk in your own words, which `python -m receipts receipt` enforces, happens outside GitHub.
- **Revert tracking.** Nothing marks an escape after a revert, so the trust ledger is not fed from real merges.
- **Fork PRs.** Fork tokens are read-only, so the comment and status steps would fail there. The workflow uses `pull_request`, not `pull_request_target`, on purpose.
- **Team lookups.** Checking team membership needs a token that can read the organisation's teams. The default `GITHUB_TOKEN` usually cannot.
- **Paths.** The workflow assumes this folder sits at `receipts/` in the target repository and that CODEOWNERS is at `.github/CODEOWNERS`.
