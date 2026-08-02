# Running Reticle day to day

Written for whoever looks after the host. Read `DEPLOYMENT.md` first for what
the pieces are; this covers keeping them alive.

One host, several facilities. **Almost everything here is per facility**, and
the commands below take a slug (`zmb`, `irchel`) for that reason. A step that
mentions no slug is one of the few that really is host-wide.

## The honest summary

Reticle is a small Python process per facility, one shared static site, and one
PostgreSQL database per facility. There is not much to go wrong, and almost
everything that does is one of the rows in section 6.

Your real obligations are short:

| How often | What |
| --- | --- |
| Automatic, nightly | Backups run for every facility (set up once, section 2) |
| Monthly, 5 minutes | Confirm each facility has a backup and it is not 0 bytes |
| Every 6 months | Restore one somewhere else and log in to it |
| When staff change | Add or deactivate the person, in their facility (section 4) |
| A few times a year | Apply updates (section 5) |

The six-monthly restore is the one people skip and the one that matters. A
backup you have never restored is a hypothesis, not a backup.

## 1. What actually holds your data

Per facility, three things. If you have these three for a facility, you have
that facility:

- the PostgreSQL database `reticle_<slug>` — every guide, user and publish history
- `/opt/reticle/facilities/<slug>/media/` — every uploaded image and step video
- `/opt/reticle/facilities/<slug>/env` — the secret key and the database
  password

The code is in git and can be rebuilt. The env file can be rewritten, but
regenerating its secret key signs everyone at that facility out.

There is nothing shared to lose. That falls out of the model rather than being
built: each facility is a complete corpus that restores on its own, because
there is no step that extracts one facility's rows from a shared anything.

## 2. Backups

```bash
sudo /opt/reticle/current/deploy/backup-facility.sh zmb
```

Two files land in `/opt/reticle/facilities/zmb/backups/`, and both are needed
because neither contains the other:

| File | What it is | Restores with |
| --- | --- | --- |
| `backup-<stamp>.dump` | `pg_dump --format=custom` — the database exactly as it is, including sequences, grants and the `alembic_version` row. **No media**: the pictures are files on disk. | `pg_restore` |
| `backup-<stamp>.tar.gz` | `app.portability export --archive` — the media, plus the same content as documented JSON with a SHA-256 per file. Restores into any engine and into a different version of Reticle. | `app.portability restore` |

**Take the `pg_dump` seriously.** The application-level export is the portable
one and it is the one to hand a facility that is leaving, but it reads through a
running application: it captures rows, not a consistent snapshot, and it knows
nothing about roles, grants, sequences or which migration the database is on.
`pg_dump` is the one that puts the database back exactly as it was.

Everything is written with `umask 077` into a directory created `0700` and owned
by `reticle`. That is deliberate — a dump holds every password hash in the
facility, and the archive holds every photograph. A backup directory any local
account can read is a backup directory that has already leaked.

### Nightly, for every facility

`/usr/local/bin/reticle-backup`:

```bash
#!/bin/bash
set -euo pipefail

# Every facility on the host. A facility exists because its directory does, so
# adding one needs no edit here.
for dir in /opt/reticle/facilities/*/; do
    /opt/reticle/current/deploy/backup-facility.sh "$(basename "$dir")"
done
```

```bash
sudo chown root:root /usr/local/bin/reticle-backup
sudo chmod 700 /usr/local/bin/reticle-backup
sudo crontab -e
# 02:30 nightly
30 2 * * * /usr/local/bin/reticle-backup >> /var/log/reticle-backup.log 2>&1
```

`backup-facility.sh` deletes its own output older than 30 days, per facility, as
the account that can read it.

**Copy them off the machine.** A backup on the same disk protects you from a bad
update, not from a dead VM. Whatever you sync with, it must preserve the modes
and it must land somewhere no more readable than `0700`:

```bash
sudo install -d -m 700 /var/backups/reticle
sudo -u reticle rsync -a --numeric-ids \
     /opt/reticle/facilities/*/backups/ /var/backups/reticle/
```

`install -d -m 700`, not `mkdir -p`. Under root's default umask `mkdir` gives
you `0755`, and then every account on the machine can read the database
password and the session pepper out of your backups.

If you do nothing else this month, get the copies off the machine.

## 3. Restoring one facility

```bash
sudo systemctl stop reticle@zmb

# The database, exactly as it was. The connection string comes out of the
# facility's own env file, which only `reticle` can read; `+psycopg` is stripped
# because that word is SQLAlchemy's and pg_restore has never heard of it.
URL=$(sudo -u reticle bash -c \
  'set -a; . /opt/reticle/facilities/zmb/env; set +a; echo "${RETICLE_DATABASE_URL/+psycopg/}"')

sudo -u postgres dropdb --force reticle_zmb
sudo -u postgres createdb -O reticle_zmb reticle_zmb
sudo -u reticle pg_restore --no-owner --dbname "$URL" \
     /opt/reticle/facilities/zmb/backups/backup-<stamp>.dump

# The media.
sudo -u reticle tar -xzf /opt/reticle/facilities/zmb/backups/backup-<stamp>.tar.gz \
     -C /opt/reticle/facilities/zmb

sudo systemctl start reticle@zmb
curl -sf https://zmb.reticle.ch/api/health
```

`--no-owner` because the dump names the role that owned the objects, and after a
`createdb -O` the role is already right.

Other facilities keep serving throughout. That is the model working.

To *test* a restore without touching production, copy the `.tar.gz` to your
laptop, `python -m app.portability restore --from …` into an empty SQLite
database, start the app, and log in. That is the whole drill. Put it in your
calendar twice a year. CI rehearses the same round trip on every run, but CI is
not your data.

## 4. People

Per facility, in **People** in the top bar (admins only). An admin at ZMB is an
ordinary nobody at Irchel — different database, which has never heard of them.

- **Someone joins** — Add person, `author` if they will write guides, `viewer`
  if they will only read. Send the initial password by a channel other than
  email and ask them to change it under their own account page.
- **Someone leaves** — deactivate rather than delete. Deactivating blocks login
  and revokes their live sessions immediately. Deleting would orphan the
  authorship of every guide they wrote, and at a facility that history is often
  the only record of why a protocol says what it says.
- **Somebody who works at two facilities** has two accounts and signs in at each
  subdomain separately. There is no shared identity, on purpose.

Keep at least two admins per facility. One admin who is on sabbatical is not an
admin.

## 5. Updates

Push a tag and let the pipeline do it (`DEPLOYMENT.md` section 7). It backs
every facility up before it migrates anything.

If you are doing something unusual by hand, take a backup first:

```bash
sudo /opt/reticle/current/deploy/backup-facility.sh zmb
```

Before a big one, see what is actually pending:

```bash
sudo /opt/reticle/current/deploy/migrate-all.sh --dry-run
```

`migrate-all.sh` **stops at the first failure** rather than carrying on and
reporting a tally, because the dangerous outcome is facilities one to six on a
new schema while seven to twelve are not, with nobody sure which is which. When
it stops it says where, points at that facility's pre-migration backups, and
tells you not to move the release symlink — the old code is still correct for
the un-migrated facilities, and the migrated ones can read it because migrations
here are additive.

Dependency updates: edit `backend/requirements.txt`, then regenerate
`requirements.lock` — the command is in that file's header. The lock is what CI
and the server install, so an edit without a regeneration changes nothing, and
CI fails to say so. Bump majors deliberately, one at a time, with CI green.

## 6. When something is wrong

**Start here, always** — with the slug of the facility that is unhappy:

```bash
sudo systemctl status reticle@zmb
journalctl -u reticle@zmb -n 100 --no-pager
systemctl --failed | grep reticle    # which facilities are down, if any
```

| Symptom | Usual cause | Fix |
| --- | --- | --- |
| One facility is down, the others are fine | That facility's process or database | `systemctl status reticle@<slug>`, read its log |
| Every facility is down at once | nginx, TLS, or the host | `nginx -t`, `systemctl status nginx`, check the certificate |
| Site loads, every action fails | The API is down for that facility | `systemctl status reticle@<slug>` |
| Nobody can log in, no error in the log | Cookies not reaching the server | Confirm HTTPS works and `RETICLE_COOKIE_SECURE=true` matches reality — a `Secure` cookie is never sent over http |
| Service will not start, "field required" for a setting that is clearly present | The env file was saved with a UTF-8 byte-order mark, fusing the mark to the first variable name | Re-save as UTF-8 without BOM; the app reads `utf-8-sig`, so this should not survive |
| Service will not start, `ModuleNotFoundError: psycopg` | The virtualenv was built from `requirements.txt` instead of `requirements.lock`, or not rebuilt at all | Rebuild it with `--require-hashes -r requirements.lock` |
| Blank page, console shows 404s for `/assets/…` | The build did not ship, or `root` points somewhere with no build in it | Check `/opt/reticle/current/static/assets` exists |
| A refresh on a guide URL 404s | The vhost lost its SPA fallback | Restore `try_files … /index.html` |
| Images fail, console says they are blocked by the policy | Object storage without its origin in the CSP | `DEPLOYMENT.md` section 10 |
| No security headers on any page | A `location` gained an `add_header` without the headers include | `DEPLOYMENT.md` section 6 |
| Uploads fail on large photographs | nginx `client_max_body_size` below the app's limit | It is 210M in the template; check the facility's vhost |
| "Someone else saved this guide while you were editing" | Two people editing the same guide — working as designed | Reload their version and reapply the change |
| A new facility fails to provision | Read the message: the script undoes everything it created and says why | Fix the cause, run it again |
| Disk full | Media growing, or backups never pruned | `du -sh /opt/reticle/facilities/*/media /opt/reticle/facilities/*/backups /opt/reticle/releases` |

**Two commands that answer most questions, per facility:**

```bash
curl -sf https://zmb.reticle.ch/api/health          # is the API alive
curl -si https://zmb.reticle.ch/api/guides | head -1 # must be 401
```

That second one is a security check, not a health check. It must always be 401.
If it ever returns 200, that facility's guides are readable without logging in —
treat it as an incident, take the site down, and find out why.

## 7. Security upkeep

- **Rotate a `RETICLE_SECRET_KEY`** if it is ever exposed. Per facility;
  `DEPLOYMENT.md` section 12.
- **Keep TLS renewing.** `systemctl list-timers | grep certbot`. An expired
  certificate takes *every* facility down at once, because the session cookie is
  `Secure`. This is the one failure that is genuinely host-wide.
- **Check the headers after any vhost edit.** `DEPLOYMENT.md` section 6.
- **Apply OS updates.** `unattended-upgrades` for security patches is sensible
  on a box like this.
- **Read the dependency audit.** CI runs `pip-audit` against the lock and `npm
  audit` on every run and does not fail the build on them, so somebody has to
  actually read them — the weekly Dependabot pass is the moment.
- **Review admins twice a year, per facility.** Admin is the role that can read
  every draft.

Passwords are Argon2id, sessions are stored only as digests, and uploads are
validated by decoding rather than by trusting filenames. You do not need to
maintain any of that — but if someone asks whether a stolen database backup
would leak live sessions, the answer is no.

## 8. Growing out of one host

Watch two numbers:

- **Memory.** Each facility is its own process, on the order of 100–200 MB. Ten
  facilities is a couple of gigabytes, which is one ordinary VM. A hundred is
  not the right shape for one box.
- **Ports.** Allocated from 8000 upwards, one per facility, recorded in each
  env file. There is no practical ceiling before the memory one.

The answer at that point is the same image on more than one machine, not a
different architecture: still one codebase, still one database per facility.
`MULTI_FACILITY.md` explains why the pooled alternative is not the answer.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
