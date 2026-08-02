# Is this production ready?

An honest inventory, written to be argued with. Everything marked ✅ has been
run and verified in this repository rather than reasoned about; everything else
says plainly what is missing and how much it matters.

The short answer: **the stack is production ready, for one facility and for
several on one host.** The tenancy model is settled and built — one subdomain,
one database and one process per facility, from a single release
(`MULTI_FACILITY.md`) — and provisioning is one command. What a *service* still
lacks is a control plane: sign-up, per-facility administration, billing.

---

## What is in place

### The database

| | |
| --- | --- |
| ✅ **Migrations** | Alembic. Three tests fail the moment a model is edited without generating one, verified by editing a model and watching them go red. `create_all` never altered an existing table, and that had already bitten once. |
| ✅ **PostgreSQL, and only PostgreSQL** | One engine, in development, in CI and in production. `RETICLE_DATABASE_URL` has no default, so a misconfigured server stops at start-up instead of serving an empty library. Migrations produce a schema with zero drift from the models. |
| ✅ **Foreign keys enforced** | Proved by inserting an orphan row and requiring the `IntegrityError`, because every `ondelete="CASCADE"` in the models is worth what the database enforces and nothing more. |
| ✅ **Non-ASCII text** | German, Greek, Cyrillic and emoji asserted identical through a round trip, and German titles asserted findable in whatever case the reader types. Two real bugs were found this way — see below. |

### Running it

| | |
| --- | --- |
| ✅ **Structured logging** | One JSON line per request with a correlation id, echoed in the `X-Request-ID` header and in every error body. |
| ✅ **Nothing secret in the logs** | Asserted negatively: passwords, session cookies and search terms. uvicorn's access log is *disabled* because it records the query string, which on this application is a log of every search anybody ran. |
| ✅ **Liveness and readiness are separate** | `/api/health` touches nothing — a liveness probe that checks the database turns a blip into a restart loop. `/api/ready` checks the database and reports 503 during startup migrations. |
| ✅ **Rate limiting** | Sliding window, separate budgets for reads, writes and uploads, keyed by session rather than address so one runaway script cannot throttle a whole university. |
| ✅ **Browser crashes reach a person** | An error boundary catches render failures and reports them into the same log stream. Newlines are collapsed so a client cannot forge log entries. |

### Storage

| | |
| --- | --- |
| ✅ **A storage interface** | `LocalStorage` (default) and `S3Storage` behind one protocol. Media were previously written with `Path.write_bytes` from four modules. |
| ✅ **Media stay behind the login** | Objects are written with no ACL and served through short-lived signed URLs after the same visibility check. The test asserts on what is *sent to the client library*, because a public-read ACL would still round-trip correctly. |

### Quality gates

| | |
| --- | --- |
| ✅ **807 backend tests** | Every one of them against PostgreSQL 16, which is what production is. |
| ✅ **384 frontend tests** | Plus two browser suites: 18 checks across desktop, tablet and phone, and a 24-check authoring round trip that writes a guide and reads it back. Both run against the **production build behind nginx**, not the dev server, so the minified bundle and the Content-Security-Policy are exercised on every run. |
| ✅ **Linting and formatting, both halves** | ESLint (the `react-hooks` rules are the point) and `ruff check`. Both found real defects. `ruff format --check` is a gate beside the linter, so an unformatted file fails its own pull request instead of turning up as noise in somebody else's diff. |
| ✅ **Dependency audit** | `pip-audit` and `npm audit`. Zero vulnerabilities. |
| ✅ **Dependencies pinned** | `requirements.lock` and `requirements-dev.lock`, `pip-compile --generate-hashes`. CI and the server install the same versions with `--require-hashes`, so a rollback rebuilds the environment it is rolling back to. A requirement added without regenerating the lock fails CI. |
| ✅ **The security headers are asserted** | CI serves the build through the real headers snippet and fails if any of the five is missing from the HTML document, an asset or an API response. nginx's `add_header` does not stack across levels, so this is otherwise a silent loss. |
| ✅ **Dependabot** | Weekly and grouped, so one maintainer does not learn to skim past it. |

### Getting it out again, and back

| | |
| --- | --- |
| ✅ **Export** | Documented JSON plus the files, with a SHA-256 each. No credential of any kind. |
| ✅ **Restore rehearsal in CI** | Seeds a corpus, exports it, restores into an empty database, and compares the two field for field. A backup nobody has restored is a hypothesis. |
| ✅ **Static snapshot** | Plain HTML with the annotations redrawn as SVG. Needs no software at all. |

### Shipping it

| | |
| --- | --- |
| ✅ **CI on every push** | Frontend, backend, PostgreSQL, restore rehearsal, dependency audit, browser e2e. |
| ✅ **A tag cannot skip the checks** | Deploy calls the CI workflow and will not build unless it passes. |
| ✅ **Back up before migrating** | Automatic, before migrations run, while the old code is still serving. |
| ✅ **Migrations run before traffic** | The deploy runs `alembic upgrade head` per facility while the old processes are still serving, so a failure stops the deploy with the old release live. `db.init_db` *also* runs pending migrations at start-up, which is the safety net for a deployment that skips the step — belt and braces, not one or the other. A destructive migration must not rely on the start-up path; see the warning in `db.init_db`. |
| ✅ **Automatic rollback** | Moves the symlink back to the release recorded *before* it moved, and restarts every facility onto it — a symlink alone changes nothing, because each process loaded its code at start-up. Safe because every facility was backed up first and migrations are additive. |
| ✅ **Provisioning** | `deploy/provision-facility.sh`: database, role, directories, environment, migrations, first administrator, service, readiness, vhost — one command. It undoes everything it created if any step fails, and refuses to touch a role or database that existed before it started. |
| ✅ **Per-facility backups before every migration** | `pg_dump --format=custom` for the database and an `app.portability` archive for the media, both `0600` in a `0700` directory. |

---

## Four real bugs these found

Worth listing, because they are the argument for the tooling rather than a
claim about it.

1. **German search returned nothing.** Every search is an `ilike`, and the
   engine it was written against rendered that with a `lower()` that folds A–Z
   and stops. Searching *Präparation* in the case it appears in a title matched
   nothing, against a corpus half of which is German. Found by reading the
   compiled SQL. `ILIKE` on PostgreSQL folds by collation, so the workaround
   that fixed it has since been deleted and the tests still pass.
2. **Every login would have failed.** The throttle key joined two fields with a
   NUL byte, which a PostgreSQL text column cannot hold. The engine used in
   development stored it silently. Found on the first run against PostgreSQL,
   which is now the only engine anything runs against.
3. **The importer would fetch `file://` URLs.** Image addresses come out of the
   *source system's* payloads, so a hostile source could have had a local file
   read, stored as media, and served back. Found by ruff's bandit rules.
4. **A render failure showed a blank tab.** There was no error boundary at all.

---

## What is missing

### For one facility — nothing that blocks going live

One thing is configured deliberately and not enforced:

- **mypy** reports around a hundred errors across sixteen files, almost all type
  narrowing it cannot follow rather than defects. A gate that red is a gate
  somebody turns off. Fix a file at a time, then make it a gate. Re-check with
  `.venv/bin/mypy .` in `backend/` rather than trusting that number; it moves
  with the code.

### For hosting as a service — two things, in this order

Provisioning is done: `deploy/provision-facility.sh` creates the facility, the
database, the directories and the vhost, migrates, seeds the first
administrator, starts the service and waits for it to answer. DNS and the
certificate stay manual on purpose, and a wildcard record with a wildcard
certificate makes both a one-time job rather than a per-facility one.

1. **A control plane.** Sign-up, per-facility administration, billing. This is a
   separate application; do not put it inside Reticle.
2. **A container image.** The deploy ships a tarball and builds a virtualenv on
   the host, which is right for one server and wrong for ten. Not hard, but it
   changes the deploy workflow.

### Smaller, and worth knowing about

- **Rate limiting is per process.** Two workers give twice the configured rate.
  The interface is the seam for moving it to Redis when there is more than one.
- **No metrics.** Logs answer "what happened"; they do not answer "how many,
  how fast, trending which way". A `/metrics` endpoint is an afternoon, and is
  worth doing once there is something to watch it with.
- **No error aggregation.** Crashes reach the log; nothing groups them or tells
  anybody. Fine while one person reads the logs.
- **No load test.** Nothing here has been run under concurrent load. The
  expected usage — a few dozen people, a handful of writes a minute — is far
  from any interesting limit, but that is a prediction, not a measurement.

---

## The tenancy model

A database per facility, one process per facility, one release for all of them.
`MULTI_FACILITY.md` is the whole argument; `ARCHITECTURE.md` gives the reasoning
behind it.

It is not the cheapest and it is the one that lets you sleep: what Reticle holds
is internal operating procedure, and the pooled alternative makes one forgotten
`WHERE` clause into one institute reading another's documentation. The cost is
stated plainly rather than hidden — 100–200 MB of memory per facility, and
migrations as a loop rather than one command.
