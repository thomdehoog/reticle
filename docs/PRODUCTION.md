# Is this production ready?

An honest inventory, written to be argued with. Everything marked ✅ has been
run and verified in this repository rather than reasoned about; everything else
says plainly what is missing and how much it matters.

The short answer: **the stack is production ready for one facility, and about
two thirds of the way to being ready to host as a service.** The gap is not
quality — it is that a service needs a control plane and per-tenant
provisioning, and neither exists yet.

---

## What is in place

### The database

| | |
| --- | --- |
| ✅ **Migrations** | Alembic. Three tests fail the moment a model is edited without generating one, verified by editing a model and watching them go red. `create_all` never altered an existing table, and that had already bitten once. |
| ✅ **PostgreSQL** | The whole suite runs on either engine; CI runs it against PostgreSQL 16. Migrations produce a schema with zero drift on both. |
| ✅ **Foreign keys enforced** | SQLite has them off by default. Proved by inserting an orphan row and requiring the `IntegrityError`. |
| ✅ **WAL journal** | Without it an autosave locks out every reader while somebody types. |
| ✅ **Non-ASCII text** | German, Greek, Cyrillic and emoji asserted identical through a round trip, on both engines. Two real bugs were found this way — see below. |

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
| ✅ **716 backend tests** | Passing on SQLite and on PostgreSQL. |
| ✅ **315 frontend tests** | Plus two browser suites: 18 checks across desktop, tablet and phone, and a 24-check authoring round trip that writes a guide and reads it back. |
| ✅ **Linting, both halves** | ESLint (the `react-hooks` rules are the point) and ruff. Both found real defects. |
| ✅ **Dependency audit** | `pip-audit` and `npm audit`. Zero vulnerabilities. |
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
| ✅ **Migrations run before traffic** | Explicitly, not left to startup, so a failure stops the deploy while the old release is live. |
| ✅ **Automatic rollback** | To the release recorded *before* the symlink moved. Safe because the backup was taken first and migrations are additive. |

---

## Four real bugs these found

Worth listing, because they are the argument for the tooling rather than a
claim about it.

1. **German search returned nothing.** SQLite's `lower()` folds A–Z and stops,
   and every search is an `ilike`. Searching *Präparation* in the case it
   appears in a title matched nothing, against a corpus half of which is
   German. Found by reading the compiled SQL.
2. **Every login would have failed on PostgreSQL.** The throttle key joined two
   fields with a NUL byte, which a PostgreSQL text column cannot hold. SQLite
   stored it silently. Found on the first run of the PostgreSQL job.
3. **The importer would fetch `file://` URLs.** Image addresses come out of the
   *source system's* payloads, so a hostile source could have had a local file
   read, stored as media, and served back. Found by ruff's bandit rules.
4. **A render failure showed a blank tab.** There was no error boundary at all.

---

## What is missing

### For one facility — nothing that blocks going live

Two things are configured deliberately and not enforced, both documented at the
point of decision:

- **`ruff format`** would reformat 53 of 72 files. Adopt it in a quiet week, in
  a commit that does nothing else.
- **mypy** reports 48 errors, almost all type narrowing it cannot follow rather
  than defects. A gate that red is a gate somebody turns off. Fix a file at a
  time, then make it a gate.

### For hosting as a service — three things, in this order

1. **Provisioning.** Create facility → create database → migrate → seed admin →
   certificate, as one command. Today this is a person following
   `DEPLOYMENT.md`.
2. **A control plane.** Sign-up, per-facility administration, billing. This is a
   separate application; do not put it inside Reticle.
3. **A container image.** The deploy ships a tarball and builds a virtualenv on
   the host, which is right for one server and wrong for ten. Not hard, but it
   changes the deploy workflow, so it should follow the tenancy decision rather
   than precede it.

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

## The decision still outstanding

**Which tenancy model.** `ARCHITECTURE.md` recommends a database per facility
on a shared cluster, and gives the reasons. It is not the cheapest and it is the
one that lets you sleep: what Reticle holds is internal operating procedure, and
the pooled alternative makes one forgotten `WHERE` clause into one institute
reading another's documentation.

Implementing the alternative later is a migration of every table in the product.
Settle it deliberately, before provisioning is built.
