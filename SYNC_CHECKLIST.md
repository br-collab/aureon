# Sync Checklist

Local folder: `The Grid 3`
GitHub mirror: `../project-aureon-portfolio`

## Operating Rule

`The Grid 3` is the internal command center.
`project-aureon-portfolio` is the outward-facing GitHub mirror.

Anything intended to be public-facing should be updated in both places as part of the same task.

## Default Workflow

1. Make the working change in `The Grid 3`.
2. Identify whether the change is public-facing or local-only.
3. If public-facing, copy the same change into `../project-aureon-portfolio`.
4. Verify the mirrored files match.
5. If requested, commit and push from `../project-aureon-portfolio`.

## Treat As Local-Only Unless Explicitly Requested

- Personal notes
- Logs
- Cached files
- Local environment secrets
- Machine-specific helper files
- Temporary experiments

## Verification Standard

For mirrored files, confirm the local and GitHub-copy versions match before closing the task.
