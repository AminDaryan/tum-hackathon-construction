# 0006: A stopped detector makes a run partial

Status: accepted.

## Decision

A run is `queued` while a background run (`Prefer: respond-async`, `202 Accepted`) waits for
a worker and `running` while its detectors execute. A run still waiting when the server shuts
down, or waiting or running when it crashes, becomes `failed` with a warning that says so, and
is never resumed; at a shutdown, running runs finish first.
A run that finishes ends in one of three statuses: `completed` when no detector failed or
stopped; `completed_with_errors` when at least one
detector failed or was stopped by its time limit (it ran, and the findings it made are kept and
stored); `failed` when every detector that executed failed, or when extraction failed and
nothing ran. Skipped detectors (not applicable, missing optional dependency, run time limit)
do not change the status; their reasons are in the run report.

Clients poll a run until its status is `completed`, `completed_with_errors` or `failed`.
`queued` was added with the background runs of round 1 (2026-11-20); a run answered directly
(`201`) is stored only when it has finished.
