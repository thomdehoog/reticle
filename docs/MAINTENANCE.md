# Running Reticle day to day

Written for whoever looks after this at ZMB. Read `DEPLOYMENT.md` first for what
the pieces are; this covers keeping them alive. Commands assume the Docker
Compose deployment in `/opt/reticle` and are run from that directory.

## The honest summary

Reticle is two small containers and a file. There is not much to go wrong, and
almost everything that does go wrong is one of the things listed in section 9.

Your real obligations are short:

| How often | What |
| --- | --- |
| Automatic, nightly | Backups run (set up once, section 2) |
| Automatic, daily | Backups are copied off the machine (section 2) |
| Monthly, 5 minutes | Confirm last night's backup exists and has a sensible size |
| Every 6 months | Restore a backup somewhere else and log in to it (section 3) |
| When staff change | Add or deactivate the person (section 4) |
| A few times a year | Apply updates (section 5) |
| Yearly, if IT issues the certificate | Renew it before it expires (section 10) |

The six-monthly restore is the one people skip and the one that matters. A
backup you have never restored is a hypothesis, not a backup.

## 1. What actually holds your data

One Docker volume, `reticle_reticle-data`, mounted in the `app` container at
`/data`:

- `/data/reticle.db` — every guide, page, user, tag and publish history —
  **together with `reticle.db-wal` and `reticle.db-shm`**. SQLite runs in
  write-ahead mode: recent changes live in the `-wal` file until they are
  folded into the main one. The three files are one database. Copying only
  `reticle.db`, or copying all three while the server is writing, can give
  you a file that opens today and fails next month.
- `/data/media/` — every uploaded image and video.

Outside the volume, and not in any backup archive:

- `/opt/reticle/.env` — the configuration, including `RETICLE_SECRET_KEY`.
  Keep a copy in the group's password manager. If it is lost the installation
  is not: generate a new key and everyone signs in again.
- `/opt/reticle/deploy/certs/` — the certificate and its key, if IT issued
  one. Replaceable by asking IT again; faster if you kept a copy.

The code is in git and in the published images and can always be fetched
again.

## 2. Backups

```bash
deploy/backup.sh
```

writes `backups/reticle-<UTC timestamp>.tar.gz`: the database, the media
directory and a small `MANIFEST` saying what is inside. It is safe to run
while people are working, and the site stays up.

What it does, and why each part is there:

- The database is copied with **SQLite's online-backup API, inside the
  container** — a consistent snapshot of one committed state, taken through
  the database engine. Never `cp`, never `docker cp`, never a tarball of the
  volume while the stack runs.
- The snapshot is **integrity-checked** before it goes into the archive, and
  the finished archive is read back before the script reports success.
- **Database first, media second.** Uploaded files are written once and never
  modified, so the media in the archive is always at least what the database
  snapshot refers to.
- A failed run leaves **no partial archive** behind and exits non-zero.
- Archives older than `RETICLE_BACKUP_KEEP_DAYS` (default 14) are deleted —
  only after a successful run, so a backup that has been failing for a month
  does not eat its predecessors.
- The archive is readable only by the user who made it: it contains every
  draft and every password hash.

It also works when the `app` container is stopped or will not start (it then
uses a throwaway container on the same volume) — worth knowing on a bad day.

Settings, in `.env`: `RETICLE_BACKUP_DIR` (default `./backups`),
`RETICLE_BACKUP_KEEP_DAYS`. A directory given on the command line wins:
`deploy/backup.sh /mnt/backup/reticle`.

**Each archive is a full copy.** Fourteen days of retention is fourteen times
the size of your media. See "Disk" in `DEPLOYMENT.md` section 10 before the
disk finds out for you.

### Scheduling it

With systemd (preferred: it logs to the journal and catches up after a
reboot):

```bash
sudo cp deploy/systemd/reticle-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reticle-backup.timer
systemctl list-timers reticle-backup.timer        # when it runs next
journalctl -u reticle-backup.service -n 20        # what happened last night
```

The unit files assume `/opt/reticle`; edit the two paths in
`reticle-backup.service` if yours differs. Or with cron (`sudo crontab -e`):

```cron
30 2 * * * /opt/reticle/deploy/backup.sh >> /var/log/reticle-backup.log 2>&1
```

### Copy them off the machine

A backup on the same disk protects you from a bad update, not from a dead VM,
a deleted VM or a ransomware incident. Sync the backup directory to ZMB
storage or hand it to the UZH backup service — every day, automatically. If
you do nothing else this month, do this.

If the off-machine system keeps its own history (most do), lower
`RETICLE_BACKUP_KEEP_DAYS` to 3–7 and let it do the remembering.

## 3. Restoring

```bash
deploy/restore.sh backups/reticle-20261010T023000Z.tar.gz
```

It shows what is in the archive, asks you to type `restore`, and then:

1. backs up the **current** state first — a restore is the one operation that
   destroys data on purpose, and "the wrong archive" is a real mistake;
2. stops the site;
3. checks the database in the archive, and only then replaces the database
   (removing the old `-wal` and `-shm` files, which would otherwise be
   replayed into the restored one) and the media directory;
4. starts the site and waits until it is healthy. If the backup comes from an
   older release, its schema is upgraded on the way up.

An unreadable archive, or one with a damaged database inside, stops before
anything is touched. `--yes` skips the question (for scripts);
`--no-safety-backup` skips step 1, for when the current data is already gone
or unreadable.

A backup made by a **newer** release than the one installed cannot be
restored into it: the server will refuse to start and say so. Install that
release first.

After a restore, people stay signed in if `RETICLE_SECRET_KEY` is the one that
was in use when the backup was taken, and are asked to sign in again
otherwise. Nothing else depends on it.

### The six-monthly drill

On your own machine, with Docker installed — fifteen minutes:

```bash
git clone https://github.com/thomdehoog/reticle reticle-drill && cd reticle-drill
cat > .env <<EOF
RETICLE_DOMAIN=localhost
RETICLE_SECRET_KEY=$(openssl rand -base64 48)
RETICLE_TLS_MODE=off
RETICLE_COOKIE_SECURE=false
RETICLE_HTTP_PORT=8080
EOF
docker compose up -d --build
deploy/restore.sh --no-safety-backup /path/to/last-nights-backup.tar.gz
```

Open <http://localhost:8080>, sign in with your real account, open a guide
with photographs and one with a video. That is the whole drill. Afterwards
`docker compose down --volumes` removes every trace, which matters: the copy
holds real content and real password hashes.

## 4. People

Everything is in **People** in the top bar (admins only).

- **Someone joins** — Add person, give them `author` if they will write guides,
  `viewer` if they will only read. Send the initial password by a channel other
  than email and ask them to change it under their own account page.
- **Someone leaves** — deactivate rather than delete. Deactivating blocks login
  and revokes their live sessions immediately. Deleting would orphan the
  authorship of every guide they wrote, and at a facility that history is often
  the only record of why a protocol says what it says.
- **Roles**: `viewer` reads published guides and pages · `author` also writes
  and publishes · `admin` also manages people and categories.
- **Someone forgot their password** — an admin sets a new one in People.
- **"Too many attempts"** — sign-in is throttled after repeated wrong
  passwords, for 15 minutes. Waiting fixes it; there is nothing to reset. If
  *everybody* is throttled at once, that is the proxy problem in section 9.

Keep at least two admins. One admin who is on sabbatical is not an admin.

**If the last administrator is locked out**, from the server's console:

```bash
deploy/reset-password.sh        # sets a new password for an existing account
deploy/create-admin.sh          # or: creates an additional administrator
```

Both ask their questions on the terminal and pass the password to the
container on standard input. Whoever has root on the host can run them — which
is a reason to be careful with root on the host, not a weakness of the scripts.

University single sign-on (SAML) is not implemented yet; see
`PLAN_AND_PROGRESS.md`. Until it is, these are local accounts with local
passwords.

## 5. Updates

```bash
nano .env                # RETICLE_VERSION=<new version>
deploy/upgrade.sh
```

It backs up, fetches the new images and restarts on them; the database schema
is migrated automatically as the new `app` container starts. Details, and how
to go back if it goes wrong, are in `DEPLOYMENT.md` sections 7 and 8.

Other things that need updating, and how they get it:

- **The host's operating system and Docker** — `unattended-upgrades` for
  security patches is sensible on a box like this. Docker restarts the
  containers when it is upgraded; expect a few seconds of downtime.
- **The operating-system packages inside the images** — they are as old as the
  release. Upgrading Reticle is how they are refreshed; if there has been no
  release for months and you build from a checkout,
  `deploy/upgrade.sh --build` rebuilds on current base images.
- **Dependencies** (for whoever cuts releases): `backend/requirements.txt` and
  `frontend/package.json` pin to compatible releases, so patch and minor
  updates arrive on rebuild and major versions never arrive by surprise. Bump
  majors deliberately, one at a time, with CI green before tagging.

## 6. Logs

```bash
docker compose logs --tail 100 app        # the API: start-up, migrations, errors
docker compose logs --tail 100 web        # Caddy: one line per request, TLS events
docker compose logs -f                    # both, live
docker compose logs --since 1h web | grep '"status": 5'     # server errors, last hour
```

`web` logs each request with the client address (`client_ip`), method, path,
status and duration — no headers, no bodies. `app` does not repeat that; it
logs what only it knows: warnings, tracebacks, and at start-up the schema
revision.

Logs are kept by Docker, rotated at 10 MB with five files per service, so
they cannot fill the disk and they do not reach back for ever. If you need
history, ship them to the university's log service with a Docker logging
driver.

**Who did what** is not in the logs but in the database: Reticle keeps an
audit trail (sign-ins, failed sign-ins, publishes, role changes, each with
the client address). To look at the most recent entries:

```bash
docker compose exec app python -c "
import sqlite3
db = sqlite3.connect('file:/data/reticle.db?mode=ro', uri=True)
for row in db.execute('SELECT created_at, action, ip_address FROM audit_log ORDER BY created_at DESC LIMIT 20'):
    print(*row)"
```

(`mode=ro`: read-only. Never open the live database for writing from outside
the application.)

## 7. Disk

```bash
df -h /var/lib/docker /opt/reticle                 # is there room at all
docker compose exec app du -sh /data/reticle.db /data/media
du -sh backups                                     # usually the biggest number
docker system df                                   # images and build cache
```

What grows, in the order it usually matters:

1. **Backups** — full copies, times the retention.
2. **Media** — videos above all. The 20 largest files:
   `docker compose exec app sh -c 'find /data/media -type f -exec ls -s {} + | sort -rn | head -20'`
3. **Old images** after upgrades. `docker image prune` removes the ones no
   container uses. Keep the previous release until the new one has proven
   itself — it is your rollback.

Media is never removed automatically: a file stays on disk after the step
or page that showed it is deleted. There is no clean-up of unreferenced
uploads yet, so the media directory only ever grows.

A full disk shows up as failed uploads first and as failed saves ("database or
disk is full" in `docker compose logs app`) second. Free space, then
`docker compose restart app`.

## 8. Is it up?

```bash
docker compose ps                                        # both "healthy"?
curl -fsS https://reticle.zmb.uzh.ch/api/health          # {"status":"ok"}
curl -si  https://reticle.zmb.uzh.ch/api/guides | head -1   # must be 401
```

`/api/health` needs no login and answers 200 only when the API is running and
the database responds, so it is the URL to give a monitoring system. If the
university runs one, ask for an HTTPS check on that URL **with certificate
expiry warning** — that covers the outage most likely to actually happen.

That third command is a security check, not a health check. It must always be
401. If it ever returns 200, your guides are readable without logging in —
treat that as an incident, take the site down (`docker compose stop web`), and
find out why.

Docker restarts a container that **exits**; it does not restart one that is
merely **unhealthy**. A hung API therefore shows as `unhealthy` in
`docker compose ps` and as a failing health URL, and the fix is
`docker compose restart app` — after reading its logs, so the cause is not
lost.

Two more things worth a monitoring check, because they fail silently:

```bash
# A backup newer than two days exists
find /opt/reticle/backups -name 'reticle-*.tar.gz' -mtime -2 | grep -q . || echo "NO RECENT BACKUP"
# The certificate has more than 30 days left (files mode)
openssl x509 -checkend 2592000 -noout -in /opt/reticle/deploy/certs/fullchain.pem || echo "CERTIFICATE EXPIRES SOON"
```

## 9. When something is wrong

**Start here, always:**

```bash
docker compose ps
docker compose logs --tail 50 app
docker compose logs --tail 50 web
```

| Symptom | Usual cause | Fix |
| --- | --- | --- |
| `docker compose` prints "Set RETICLE_SECRET_KEY…" or "Set RETICLE_DOMAIN…" and does nothing | `.env` is missing, or you are not in `/opt/reticle` | `cd /opt/reticle`; create `.env` from `.env.example` |
| `web` keeps restarting; log ends with `File to import not found: modes/….caddy` | Typo in `RETICLE_TLS_MODE` | It is one of `auto`, `files`, `internal`, `off` |
| `web` keeps restarting; log ends with `open /certs/privkey.pem: permission denied` | The key is not readable by Caddy's user | `sudo chown 10002 deploy/certs/*.pem`, then `docker compose up -d` |
| `web` keeps restarting; log says `no such file or directory` under `/certs` | File names differ from `fullchain.pem` / `privkey.pem` | Rename, or set `RETICLE_TLS_CERT_FILE` / `RETICLE_TLS_KEY_FILE` |
| Browser: certificate warning; `curl` fails but the desktop browser works | Intermediate certificate missing from `fullchain.pem` | Concatenate leaf + intermediates (`DEPLOYMENT.md` section 4), restart `web` |
| Browser: certificate warning in `auto` mode; `web` log shows challenges failing | The host is not reachable from the internet, so Let's Encrypt cannot validate it | Use `files` mode with a certificate from IT |
| Site suddenly down for everyone with a certificate error | The certificate expired | Replace the files, `docker compose restart web` |
| `app` keeps restarting; log mentions `secret_key` | `RETICLE_SECRET_KEY` shorter than 16 characters | Generate a proper one |
| `app` will not start after going back to an older version; log explains the schema is newer | The newer release migrated the database | Restore the pre-upgrade backup, or return to the newer release (`DEPLOYMENT.md` section 8) |
| `app` log: "already has tables but no migration history" | A database from a development build that predates migrations | There is no upgrade path; move it aside and start empty |
| Site loads, but every action fails | The API is down or unhealthy | `docker compose ps`, read the `app` log, `docker compose restart app` |
| Nobody can sign in, no error anywhere | The session cookie is not coming back: plain http with `RETICLE_COOKIE_SECURE=true` | Use HTTPS — or, for a localhost trial only, set it to `false` |
| Everybody is "rate limited" at once; the audit trail shows one address for everyone | A proxy in front that Reticle was not told about, or IPv6 through Docker's userland proxy | `RETICLE_UPSTREAM_PROXIES` (`DEPLOYMENT.md` section 5), or the IPv6 note in section 6 |
| A large video fails with 413 | Above `RETICLE_MAX_VIDEO_BYTES` (200 MB), or a proxy in front with a smaller limit | Raise it together with `RETICLE_PROXY_UPLOAD_LIMIT`; ask IT about their proxy's limit |
| Uploads fail with 500, saves fail | Disk full | Section 7 |
| An image in a wiki page does not show; browser console says "Refused to load the image… Content Security Policy" | The page links to an image on another website | Upload the image instead; hot-linking is blocked on purpose |
| Blank page; console shows Content-Security-Policy errors for scripts or styles | A frontend change that the policy in `deploy/caddy/Caddyfile` does not allow | Fix the frontend, or widen the policy deliberately — CI should have caught it |
| PDF export shows boxes instead of λ, Å, ≥ | DejaVu fonts missing | Cannot happen with the published image; on a bare VM `apt install fonts-dejavu-core` |
| `docker compose up` fails: "port is already allocated" | Something else listens on 80 or 443 | Stop it, or set `RETICLE_HTTP_PORT` / `RETICLE_HTTPS_PORT` |
| After a host reboot nothing is running | Docker is not enabled at boot | `sudo systemctl enable --now docker` |
| `database is locked` in the `app` log | The volume is on a network filesystem, or some other program has the database open | Local disk only; never open the live file with another tool |
| "Someone else saved this guide while you were editing" | Two people editing the same guide — working as designed | Reload their version and reapply your change |
| Service will not start (bare VM), "field required" for a setting that is clearly present | Env file saved with a UTF-8 byte-order mark | Re-save without BOM; the app reads `utf-8-sig`, so this should be historical |
| A refresh on a guide URL gives 404 (bare VM) | nginx is missing the single-page fallback | Restore `try_files $uri /index.html` |

When you ask for help, attach the output of the three "start here" commands.
They contain no secrets: Caddy's request log has no headers or bodies, and the
API never logs passwords or tokens.

## 10. Security upkeep

- **Rotate `RETICLE_SECRET_KEY`** if it is ever exposed. Everyone signs in
  again; passwords are unaffected. `DEPLOYMENT.md` section 12.
- **Keep the certificate valid.** In `auto` mode Caddy renews by itself; glance
  at `docker compose logs web | grep -i -E 'renew|obtain|error'` twice a year.
  In `files` mode it is a calendar entry: an expired certificate takes the
  whole site down, because the session cookie is `Secure`.
- **Apply updates** — section 5.
- **Review admins twice a year.** Admin is the role that can read every draft.
- **Treat backups as the crown jewels they are.** An archive holds everything
  the site does. Restrict who can read the backup directory and wherever it is
  copied to.
- **Do not publish the API port, and do not serve the media directory.** Both
  would bypass the login. `compose.yaml` does neither; keep it that way in any
  override.

Passwords are Argon2id, sessions are stored only as digests, and uploads are
validated by decoding rather than by trusting filenames. You do not need to
maintain any of that — but if someone asks whether a stolen backup would leak
live sessions, the answer is no; it would leak the content and the password
*hashes*, which is why the previous point stands.

## 11. SQLite, briefly

The things that are different from a database server, all in one place:

- **Three files, one database.** `reticle.db`, `reticle.db-wal`,
  `reticle.db-shm`. The `-wal` file can be larger than the database for a
  while; that is normal.
- **Back up through SQLite, never around it.** `deploy/backup.sh`.
- **Restore by replacing all three**, with the server stopped — which is to
  say, by deleting the old `-wal` and `-shm`. `deploy/restore.sh`.
- **Local disk only.** File locking over NFS or SMB is not trustworthy, and
  SQLite depends on it.
- **One writer at a time.** Saves queue for up to five seconds behind each
  other; readers never wait. With a handful of people editing, nobody notices.
- **To check a database** that you suspect:
  `docker compose exec app python /usr/local/lib/reticle/dbtool.py check /data/reticle.db`
  runs SQLite's integrity check, read-only.

## 12. Growing out of this setup

Watch for one signal: **staff reporting that saving a guide is slow while
someone else is editing.** Reading is not a concern and never will be at this
scale.

When that happens, the next step is PostgreSQL — `DEPLOYMENT.md` section 15,
which is honest about the fact that nobody has run Reticle on it yet. Do not
migrate pre-emptively.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
