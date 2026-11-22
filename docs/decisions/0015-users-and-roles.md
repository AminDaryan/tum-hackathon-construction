# 0015: User accounts with three roles, signed in by personal access tokens

Status: accepted (2026-11-21). Extends the optional sign-in of the REST API ("Security") and
narrows the "no user accounts" entry of [0008](0008-deferred-to-phase-2.md).

## Context

Sign-in was a list of shared tokens (`TWB_AUTH__TOKENS`): a token named nobody and granted
everything, and the audit trail recorded every decision with the actor `local`. A team that
reviews bills together needs to know who decided what, and to let some people read without
changing anything. The workbench has no identity provider, mail server or password storage, and
should not need one to run on a reviewer's machine or in one container.

## Decision

* **Accounts.** A user has a first and last name, an optional email, job title and phone, a role
  and an active flag. Each user edits their own details (`PATCH /me`, Settings, My profile); the
  role and the active flag are an administrator's. Accounts are stored in the workbench
  database (table `users`, schema version 7). Administrators create, change, deactivate and
  delete them in Settings, Users, or through `/api/v1/users`.
* **Roles.** Three, each including the ones below it:
  * `viewer`: every `GET` and `HEAD`;
  * `reviewer`: also every other method (uploads, validation runs, review decisions,
    corrections, projects, risk reviews);
  * `admin`: also `/users`.
  `GET /me` and `PATCH /me` are open to every role. The check is made once, in the sign-in
  middleware, from the method and the path, so a new route is covered without further code; a
  refusal is `403 forbidden` with `details.role` and `details.required_role`.
* **Personal access tokens, no passwords.** Creating an account, or `POST /users/{id}/token`,
  issues a token (`twb_` and 32 random bytes, URL-safe). It is returned once; only its SHA-256
  digest (unique column, for the lookup) and its last four characters are stored. Issuing a new
  token replaces the old one at once. A deactivated account's token is refused.
* **Who a request acts for.** A configured `TWB_AUTH__TOKENS` token is the administrator
  (`kind: service`), so a deployment can never lock itself out. A user token is that user. With
  sign-in required, anything else is `401`. With sign-in off, a request without a known user
  token acts as the local administrator (`kind: local`), as every request did before: roles then
  name who acts and limit what they may do, but are not a security boundary, because anyone can
  leave the token out.
* **Audit.** The actor of an audit event is the user's name (`service` and `local` for the two
  others), and `context.actor_id` holds the user id, since names can repeat. Background runs
  copy the request's context, so their events name who started them. Account changes are
  audited (`user_created`, `user_updated`, `user_deleted`, `user_token_issued`), never with the
  token or its digest.
* **No self-lockout.** An administrator cannot change their own role, deactivate or delete
  their own account (`409 conflict`); another administrator, or the configured token, can.

## Consequences

* The web interface shows who is signed in and their role beside the avatar at the top right;
  its menu has Profile (Settings, My profile, where a person also signs in with their token) and
  Log out. Viewers see "Read only"; write actions they try are refused by the server with a
  message naming the role.
* Tokens are bearer secrets kept in the browser tab's sessionStorage, like before. There is no
  expiry, no password reset and no single sign-on; an administrator issues a new token instead.
* Roles are per installation, not per project or document.
