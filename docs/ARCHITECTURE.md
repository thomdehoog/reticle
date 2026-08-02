# Where the data lives, and what running this as a service would take

Two audiences. The first half answers "where does everything actually go" for
the installation ZMB is about to run. The second is a considered proposal for
hosting Reticle for other facilities, with a recommendation and the reasons
behind it — because the decisions that are cheap now become expensive later.

---

## Part one: where the data is today

### Code and data are in different places, on purpose

**GitHub holds the software.** Python and TypeScript files, and nothing else.
It is identical for every facility that runs Reticle. Cloning it gives you a
program, not a library of guides.

**The server holds the data**, in exactly two places:

| What | Where | Contains |
| --- | --- | --- |
| The database | PostgreSQL, one per facility, named in that facility's `RETICLE_DATABASE_URL` | Every guide, wiki page, step, bullet, tag, account, publish snapshot and audit entry — all the text and structure |
| `media/` | `/opt/reticle/facilities/<slug>/media/` | The actual image and video files, one per upload |

Nothing else survives a deployment. `releases/` is code, `static/` is the built
frontend; both are replaced on every update.

`.gitignore` excludes `backend/media/`, and `git ls-files` returns nothing
matching it. That is not a convention — a repository is a filing cabinet for
source, and putting a facility's photographs in one means every clone carries
them forever, including the ones taken by mistake.

### What happens when somebody uploads a picture

1. The browser sends the file to `POST /api/media`.
2. The server reads it under a size cap, **decodes it** to find out what it
   really is — the filename and the declared type are discarded — and rejects
   anything that is not a picture or a video it can serve.
3. It **re-encodes** the image, which strips the EXIF a microscope camera
   writes: serial numbers, sometimes GPS.
4. It writes the bytes to `media/<ulid>.png`, under a name the server generated,
   never one the uploader chose.
5. It writes a row in the database pointing at that path.

At no point does anything reach GitHub. The picture is on the server's disk and
a reference to it is in the server's database. That is how essentially every
website works: code in version control, content in a database and a file store.

### How big will it be

The database itself stays small — a few tens of megabytes for the whole corpus,
because it is text. The media dominate. The migration dry run prints the image
and video counts before anything is written:

```
images            3120
videos              90
```

Multiply by what the site actually serves. Microscopy screenshots and instrument
photographs at full resolution generally run 0.5–5 MB, so **budget in the region
of 5–20 GB**, and check the dry run before provisioning the disk rather than
trusting that estimate.

---

## Part two: running it as a service

Two of the three storage decisions below are taken and built; the remaining one
is object storage, which is written and unproven. None of it blocks ZMB going
live self-hosted, and doing ZMB first is the right order: one real facility in
production teaches you more about what a service needs than any amount of
designing for ten imaginary ones.

### The three storage decisions

#### 1. PostgreSQL, and nothing else

**Reticle runs on PostgreSQL, one database per facility, and speaks no other
engine.** `provision-facility.sh` creates the role and the database and writes
the URL into the facility's environment file, and `RETICLE_DATABASE_URL` has no
default — a server that has not been told where its database is refuses to start
rather than quietly creating an empty one and serving a library with nothing in
it.

It also buys the things a hosted service needs and an embedded database cannot
give: concurrent writers, replication, point-in-time recovery measured in
seconds, and a managed offering from providers in Switzerland and the EU — which
matters here, see *Residency* below.

The reason to keep, now that the argument is over, is what it cost to find out.
The project began on a single-file embedded database, and two bugs came out of
running one engine in development and another in production:

- Every search in the application is an `ilike`, which the embedded engine
  rendered as `lower(a) LIKE lower(b)` — and its `lower()` folds A–Z and stops.
  Against a corpus half of which is German, searching *Präparation* in the case
  it appears in the title returned nothing. Keeping it working meant overriding
  a built-in C function on every connection. `ILIKE` on PostgreSQL is a real
  operator that folds by collation, so that code is gone and the German search
  tests pass with nothing standing behind them.
- The login throttle joined two fields with a NUL byte, which a PostgreSQL text
  column cannot hold at all. It stored happily in development. Every login on
  the deployed system would have failed, on the first day, for everybody.

That is why **the suite runs on the engine production runs, and only on it**:
there is no second engine to fall back to, so a green run is evidence about
PostgreSQL. Every CI job that touches a database — the backend suite, the
restore rehearsal and the browser smoke test — brings up a `postgres:16`
service. Schema changes go through Alembic in `backend/migrations/`, which runs
on start-up and handles an empty database, one that predates migrations, and one
already stamped; `deploy/migrate-all.sh` is the multi-facility equivalent.

Moving a corpus between databases, if a facility ever needs to, is
`portability export` followed by `restore`; that round trip is rehearsed on
every CI run rather than described here and hoped for.

#### 2. Local disk → object storage

Media on local disk cannot be shared between processes, does not survive an
instance being replaced, and is backed up by tarring tens of gigabytes nightly.
S3-compatible object storage — including Swiss and EU providers, and MinIO if it
must stay on-premises — is durable, versioned, and priced for this.

One rule survives the move, and it is the one most easily lost: **media stay
behind the login.** Reticle refuses a viewer a file unless a published guide or
page actually shows it, and that has been fixed twice in this codebase because
each new way of displaying a file was a fresh copy of the same hole. A public
bucket throws all of it away. Serve through **short-lived signed URLs** issued
after the same visibility check the application already performs.

**The storage interface is done.** `app/storage.py` holds one protocol with
`LocalStorage` and `S3Storage` behind it, `build_storage(settings)` is the only
way to obtain one, and every writer and reader in the application goes through
it — the routers, the exporter, the static site generator, the importer and the
restore. What remains is operational: choosing a provider, and running against a
real bucket rather than only the fake the suite uses.

#### 3. Tenancy: a database per facility

**Decided, and built.** One cluster, one database, one media directory and one
process per facility, from a single release; `MULTI_FACILITY.md` describes the
shape and `deploy/provision-facility.sh` creates one in a command. The two
alternatives are recorded because the choice is expensive to revisit, not
because it is open: a pooled design — one database with `tenant_id` on every
table — is cheapest per tenant, and a silo — separate everything — is the
highest isolation at the highest cost and stays available for the facility that
insists on it.

The pool model is the default for consumer SaaS and the wrong default for this
data. What Reticle holds is internal operating procedure: building access, what
is taped to which instrument, screenshots containing unpublished results. The
failure mode is not "a user sees another user's playlist", it is one research
institute reading another's internal documentation, and the mechanism is a
single forgotten filter in a single query. That risk is carried by every query
anybody writes for the lifetime of the product.

A database per facility makes that class of bug *unreachable*: the connection
does not contain the other facility's data. It also gives, for free, things a
pooled design has to build:

- **Backup and restore per facility**, rather than extracting one tenant's rows
  from a shared backup.
- **Export and leave.** `python -m app.portability export` already produces a
  facility's entire corpus as documented JSON plus its files, and `restore`
  reads it back. For a product whose origin story is "our data was locked in
  somebody else's platform", being able to hand a facility their instance and
  wave them off is not a feature to be embarrassed about — it is the argument.
- **Residency per facility.** A facility that must stay in Switzerland gets a
  database in Switzerland without redesigning anything.

The cost is real and worth stating: migrations must run across N databases, and
provisioning a facility becomes a job rather than a row insert. Both are
well-trodden; neither is a research problem.

### What to store, and what not to

Store: the content, the media, accounts, sessions, the audit trail, and publish
snapshots.

Do not store anything you would not want to explain holding. Two decisions
already made, worth keeping:

- Passwords are **Argon2id hashes**; session cookies are stored only as
  **HMAC digests**, so a stolen backup yields no live sessions.
- The export carries **no credential of any kind** — no hash, no token. It gets
  copied to a laptop and emailed; it should be worth nothing to whoever else
  ends up with it.

**Residency.** A Swiss university's material on Swiss or EU infrastructure is a
much shorter conversation with a data protection officer than the alternative,
and this project exists because the data was somewhere it should not have been.
Choose the region before the first facility signs up, not after.

### Updating

- Deploy from a **tag**, never a branch. The pipeline already builds a release
  directory and switches a symlink, so a rollback is switching it back.
- **Back up before migrating**, every time, without exception.
- Migrations run before the new code serves traffic. With a database per
  facility, that is a loop with a report at the end, and a failure on facility
  seven must not leave facilities one to six on a new schema with old code.
- Additive-then-destructive: add a column, deploy code that writes both, remove
  the old one a release later. It is the only way to keep rollback real.

### Backing up

| What | How | How often |
| --- | --- | --- |
| Database | Managed PITR, plus a nightly logical dump | Continuous |
| Media | Object storage versioning, replicated to a second region | Continuous |
| The whole corpus | `portability export --archive` | Nightly, kept 30 days |
| A static snapshot | `portability publish` | Weekly |

The last two are not redundant with the first two, and the reason is worth
stating. A database backup restores into *this* software. The export is
readable by anything, documented in `EXPORT.md`, and would survive Reticle
itself being abandoned. The static snapshot needs no software at all.

### How easy is it to get a backup back

Today, and this has been done end to end rather than assumed:

```bash
python -m app.portability restore --from reticle-export.tar.gz
```

It refuses a database that already holds content, verifies every file against
its checksum, exits non-zero if anything was missing or corrupt, and preserves
identifiers so citations and bookmarks still resolve. Restoring a corpus and
serving it from a second instance takes minutes.

The honest caveats:

- Accounts come back **without passwords**, deliberately. Everybody signs in
  again after a restore. That is a safe default, not an oversight.
- The suite proves the round trip on every run — export a corpus, restore it
  into an empty database, compare the two documents field for field — because
  an export nobody has restored is a hypothesis.
- **Rehearse it twice a year against production data**, as `MAINTENANCE.md`
  already says. A restore procedure that has only ever been run in a test is a
  procedure with an unknown failure rate.

### The order to do it in, and where it has got to

1. ~~**Alembic migrations.**~~ Done — `backend/migrations/`, run on start-up.
2. ~~**Storage interface**, with the local implementation as the default.~~
   Done — `app/storage.py`.
3. ~~**PostgreSQL, as the only engine**, with CI running the suite against it.~~
   Done — `RETICLE_TEST_DATABASE_URL` and the PostgreSQL job in CI.
4. ~~**S3 storage implementation**, with signed URLs behind the existing
   visibility check.~~ Done — `S3Storage` writes with no ACL and issues
   five-minute signed URLs, always *after* the same visibility check the local
   backend's route performs. Not yet exercised against a real provider.
5. ~~**Provisioning**: create facility → create database → migrate → seed admin
   → certificate → done, as one command.~~ Done — `deploy/`, including a
   rollback that undoes everything it created if any step fails.
6. **A control plane**: sign-up, per-facility administration, and whatever
   billing the arrangement needs. **This is the one that remains.** It is a
   separate application; do not put it inside Reticle.
7. ~~**Operability**: structured logs with a request id, metrics, a readiness
   probe distinct from the liveness one, rate limits beyond the login endpoint,
   and a written incident runbook.~~ Done except metrics — JSON logs with a
   request id on every line and in every error body (`app/observability.py`),
   `/api/ready` separate from `/api/health`, read/write/upload rate limits with
   `Retry-After` (`app/ratelimit.py`), and `MAINTENANCE.md`. There is still no
   metrics endpoint; the logs are the only quantitative signal.

Step 6 should wait until at least one facility other than ZMB is live, because
the first real tenant will change the requirements. Everything below it is
already carrying ZMB, which is the point: none of steps 1–5 and 7 was worth
doing only for a hosted service, and each is worth having for the single
institute running Reticle today.

The one thing not to reopen along the way is the tenancy model. A database per
facility on a shared cluster is what steps 1–5 were built against, and switching
to a pooled design later is a migration of every table in the product.
