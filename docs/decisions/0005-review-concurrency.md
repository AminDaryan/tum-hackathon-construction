# 0005: Review concurrency

Status: accepted.

## Context

A review is read-check-write: load the issue, check the transition, store the new status,
append an audit event. Two near-simultaneous requests (two tabs, a double click, FastAPI's
thread pool) could both read `pending_review`; the second would overwrite the first and record
an audit event whose `before` no longer matched the stored state. pysqlite's legacy transaction
handling sends `BEGIN` only at the first write, so a read inside `connection.begin()` was not
part of the transaction on a file database.

## Decision

* `ValidationIssue.version` starts at 1 and every review decision increments it
  (`ValidationIssue.with_review`). Clients send the version they saw (`expected_version`); a
  stale version is rejected with `409 conflict`.
* Repositories update issues with `UPDATE … WHERE issue_id = ? AND version = ?` and raise
  `ConflictError` when no row matched.
* The SQLite adapter puts the driver in autocommit mode and issues `BEGIN IMMEDIATE` itself for
  every unit of work, so reads and writes of one unit of work are one transaction and writers
  serialize. PostgreSQL uses its own transaction handling.
* The transition check and the audit event are built in one service function used by every
  caller.
