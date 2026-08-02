# One subdomain per facility

`zmb.reticle.ch`, `irchel.reticle.ch`, and so on. This document answers two
questions that came up when that was decided, because both have answers that
are easy to get wrong in a way that is expensive to undo.

---

## Is the software duplicated?

**No. The code exists once. The *process* runs more than once.**

Those are very different things, and the difference is the whole point:

| | Copies |
| --- | --- |
| Git repository | **one** |
| Release directory on the server (`/opt/reticle/current`) | **one** |
| Python virtualenv | **one** |
| Built frontend (the JavaScript and CSS) | **one** |
| CI/CD pipeline | **one** |
| uvicorn process | one **per facility** |
| PostgreSQL database | one **per facility** |
| Media directory | one **per facility** |
| Environment file | one **per facility** |

Adding a facility copies no code. It creates a database, a directory, an
environment file and an nginx vhost, then starts the same binary again:

```
systemctl enable --now reticle@zmb
systemctl enable --now reticle@irchel
```

That is one systemd template — `deploy/reticle@.service` — instantiated twice.
Both instances execute the same `/opt/reticle/current/venv/bin/uvicorn` against
the same `/opt/reticle/current/backend`. The only thing that differs is which
environment file they read.

**The word for the bad version is *fork*.** If each facility had its own copy of
the source, a bug fixed for ZMB would have to be fixed again for everyone else,
and the versions would drift until they were separate products. Nothing here
does that. One release, deployed once, serving every facility.

Even the frontend is shared, and that is not an accident: the facility's name
arrives at runtime from `GET /api/config`, which is precisely why that endpoint
exists and why it is reachable before anybody has signed in. There is one build
of the JavaScript on disk regardless of how many facilities are served.

### What it costs

Being straight about it: each facility is its own process, so each one holds its
own memory — on the order of 100–200 MB for an application this size. Ten
facilities is a couple of gigabytes, which is one ordinary VM. A hundred
facilities on one host is not the right shape, and that is the point at which
the answer becomes containers on more than one machine — the same image, more
copies of it, still not a fork.

The alternative — a single process that reads the `Host` header and picks a
database per request — removes that memory cost and adds a much worse risk: a
bug in tenant resolution serves one institute's documents under another's name.
It also requires real surgery here, because the engine and the settings are
process-wide by design. Not worth it below a few dozen facilities, and possibly
not worth it above.

---

## What exactly gets a database?

The **facility** does. Not an account, and not a group.

This is worth naming precisely, because "account" is doing double duty in
ordinary speech:

```
Reticle                          the software. One codebase.
│
├── Facility: ZMB                zmb.reticle.ch
│   ├── database   reticle_zmb   ← the database is HERE
│   ├── media/
│   │
│   ├── Accounts                 people. Rows in reticle_zmb.users
│   │   ├── thom@zmb.uzh.ch      admin
│   │   ├── anna@zmb.uzh.ch      author
│   │   └── … ~20 more           viewers
│   │
│   └── Categories               content grouping. Rows in reticle_zmb.categories
│       ├── Light Microscopy
│       ├── Electron Microscopy
│       └── …
│
└── Facility: Some Other Institute      other.reticle.ch
    ├── database   reticle_other        ← a completely separate database
    └── …
```

So, in the vocabulary this project uses:

- A **facility** (the industry word is *tenant*) is an institute. It gets a
  subdomain, a database, a media directory and a process. **This is the unit of
  isolation.**
- An **account** is a person. It is a row in one facility's `users` table.
  Twenty accounts at ZMB share ZMB's one database.
- A **category** is a way of grouping *content* inside a facility — Light
  Microscopy, Electron Microscopy. It has nothing to do with isolation.
- A **role** (viewer, author, admin) is what an account may do **within its own
  facility**. An admin at ZMB is an ordinary nobody everywhere else, because
  everywhere else is a different database that has never heard of them.

**One database per facility. Never per account.** A database per account would
be thousands of databases holding one row each, and it would make the ordinary
thing — twenty colleagues editing one shared library of guides — impossible.

### The edge case, since it will come up

Somebody who genuinely works at two facilities has **two accounts**, one in each
database, and signs in separately at each subdomain. There is no shared identity
across facilities.

That is a real inconvenience for a rare case, and it is the correct trade. A
shared account database would reintroduce exactly the cross-facility coupling
that the separate databases exist to prevent, and it would do it in the most
sensitive table there is. If single sign-on is wanted later, the answer is an
external identity provider (UZH already has one) that each facility trusts
independently — not a shared table.

---

## How a facility is added

```bash
sudo ./deploy/provision-facility.sh irchel "Irchel Imaging Core" admin@irchel.example.org
```

That script creates the database and a role that can reach nothing else,
creates the directories, writes an environment file, runs the migrations, seeds
the first administrator, starts `reticle@irchel`, waits for `/api/ready`, and
writes the nginx vhost. It prints the bootstrap password once and removes it
from the environment file, so it is not left on disk.

Two things are still done by hand, and deliberately: DNS and the certificate. A
wildcard record and a wildcard certificate for `*.reticle.ch` make both a
one-time job rather than a per-facility one.

### The per-facility secret key

Each facility gets its own `RETICLE_SECRET_KEY`, and this matters more than it
looks. That key is the pepper for session-token digests. Sharing one across
facilities would mean a database stolen from the least careful facility could be
used to forge sessions at the most careful one.

---

## Updating all of them

```bash
sudo ./deploy/migrate-all.sh --dry-run   # what would run
sudo ./deploy/migrate-all.sh             # back up, then migrate, each in turn
```

This is the cost of the model, stated plainly: migrations are a loop rather than
one command. The loop is short.

The important part is the failure behaviour. It **stops at the first failure**
rather than continuing and reporting a tally, because the dangerous outcome is
facilities one to six on a new schema while seven to twelve are not, with nobody
sure which is which. When it stops it says where, points at that facility's
pre-migration backup, and tells you not to switch the release symlink — the old
code is still correct for the un-migrated facilities, and the migrated ones can
read it because migrations here are additive.

---

## Backups

Each facility backs up independently, into its own `backups/` directory, and
each backup is a complete corpus that restores on its own. This falls out of the
model rather than being built: there is no step that extracts one facility's
rows from a shared backup, because there is no shared backup.

It is also what makes leaving easy, which for this project is the argument
rather than an embarrassment. Reticle exists because ZMB's documentation was
locked inside somebody else's platform. A facility that wants to go elsewhere
gets `python -m app.portability export --archive`, which is documented JSON plus
every image, and it restores into their own instance. Being able to hand a
facility their data and wave them off is the reason anyone should trust the
thing in the first place.
