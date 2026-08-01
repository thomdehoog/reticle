# Running Reticle day to day

Written for whoever looks after this at ZMB. Read `DEPLOYMENT.md` first for what
the pieces are; this covers keeping them alive.

## The honest summary

Reticle is a small Python process, a static site and a file. There is not much
to go wrong, and almost everything that does go wrong is one of five things
listed in section 6.

Your real obligations are short:

| How often | What |
| --- | --- |
| Automatic, nightly | Backups run (set up once, section 2) |
| Monthly, 5 minutes | Confirm a backup exists and is not 0 bytes |
| Every 6 months | Restore a backup somewhere else and log in to it |
| When staff change | Add or deactivate the person (section 4) |
| A few times a year | Apply updates (section 5) |

The six-monthly restore is the one people skip and the one that matters. A
backup you have never restored is a hypothesis, not a backup.

## 1. What actually holds your data

Only two things. If you have these, you have everything:

- `/opt/reticle/shared/reticle.db` — every guide, user, and publish history
- `/opt/reticle/shared/media/` — every uploaded image and step video

The code is in git and can be rebuilt. `/opt/reticle/shared/.env` is worth
keeping too, though its secret can be regenerated (everyone gets signed out).

## 2. Backups

SQLite must not be copied with `cp` while the service is running — you can catch
it mid-write and get a corrupt file that looks fine until the day you need it.
Use SQLite's own backup command, which is safe on a live database.

`/usr/local/bin/reticle-backup`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR=/var/backups/reticle
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

# .backup is transaction-aware; cp is not.
sqlite3 /opt/reticle/shared/reticle.db ".backup '$BACKUP_DIR/reticle-$STAMP.db'"

tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" -C /opt/reticle/shared media
cp /opt/reticle/shared/.env "$BACKUP_DIR/env-$STAMP"

# Keep 30 days here; the off-machine copy is the one that survives a dead disk.
find "$BACKUP_DIR" -type f -mtime +30 -delete

echo "backup complete: $STAMP"
```

```bash
sudo chmod +x /usr/local/bin/reticle-backup
sudo crontab -e
# 02:30 nightly
30 2 * * * /usr/local/bin/reticle-backup >> /var/log/reticle-backup.log 2>&1
```

**Copy them off the machine.** A backup on the same disk protects you from a bad
update, not from a dead VM. Sync `/var/backups/reticle` to ZMB storage or a UZH
backup service. If you do nothing else this month, do this.

## 3. Restoring

```bash
sudo systemctl stop reticle
sudo -u reticle cp /var/backups/reticle/reticle-<stamp>.db /opt/reticle/shared/reticle.db
sudo -u reticle tar -xzf /var/backups/reticle/media-<stamp>.tar.gz -C /opt/reticle/shared
sudo systemctl start reticle
curl -sf https://reticle.zmb.uzh.ch/api/health
```

To *test* a restore without touching production, copy the backup to your laptop,
point a local `RETICLE_DATABASE_URL` at it, start the app, and log in. That is
the whole drill. Put it in your calendar twice a year.

## 4. People

Everything is in **People** in the top bar (admins only).

- **Someone joins** — Add person, give them `author` if they will write guides,
  `viewer` if they will only read. Send the initial password by a channel other
  than email and ask them to change it under their own account page.
- **Someone leaves** — deactivate rather than delete. Deactivating blocks login
  and revokes their live sessions immediately. Deleting would orphan the
  authorship of every guide they wrote, and at a facility that history is often
  the only record of why a protocol says what it says.
- **Roles**: `viewer` reads published guides · `author` also writes and publishes
  · `admin` also manages people and categories.

Keep at least two admins. One admin who is on sabbatical is not an admin.

## 5. Updates

```bash
sudo /usr/local/bin/reticle-backup     # always first
```

Then follow `DEPLOYMENT.md` section 5, or push a tag and let CI do it. If it goes
wrong, section 6 of that document rolls back in two commands.

Dependency updates: read `backend/requirements.txt` and `frontend/package.json`.
Both pin to compatible releases, so patch and minor updates arrive when you
rebuild and major versions never arrive by surprise. Bump majors deliberately,
one at a time, with CI green before deploying.

## 6. When something is wrong

**Start here, always:**

```bash
sudo systemctl status reticle
journalctl -u reticle -n 100 --no-pager
```

| Symptom | Usual cause | Fix |
| --- | --- | --- |
| Site loads, but every action fails | API is down | `systemctl status reticle`, read the log |
| Nobody can log in, no error in the log | Cookies not reaching the server | Confirm HTTPS works and `RETICLE_COOKIE_SECURE=true` matches reality — a `Secure` cookie is never sent over http |
| Service will not start, "field required" for a setting that is clearly present | `.env` saved with a UTF-8 byte-order mark, fusing the mark to the first variable name | Re-save as UTF-8 without BOM; the app now reads `utf-8-sig`, so this should be historical |
| Blank page, console shows 404s for `/assets/...` | Frontend build not deployed, or deployed to the wrong path | Rebuild and rsync to `/opt/reticle/static` |
| A refresh on a guide URL 404s | nginx missing the SPA fallback | Restore the `try_files ... /index.html` rule |
| Uploads fail on large photographs | nginx `client_max_body_size` below the app's limit | Raise it above 20 MB |
| "Someone else saved this guide while you were editing" | Two people editing the same guide — working as designed | Reload their version and reapply your change |
| Disk full | Media store growing, or backups never pruned | `du -sh /opt/reticle/shared/media /var/backups/reticle` |
| Disk full after a migration | The importer stores every picture at full resolution, which is the point of it | Same check; budget for the whole corpus before running it |

**Two commands that answer most questions:**

```bash
curl -sf https://reticle.zmb.uzh.ch/api/health   # is the API alive
curl -si https://reticle.zmb.uzh.ch/api/guides | head -1   # must be 401
```

That second one is a security check, not a health check. It must always be 401.
If it ever returns 200, your guides are readable without logging in — treat that
as an incident, take the site down, and find out why.

## 7. Security upkeep

- **Rotate `RETICLE_SECRET_KEY`** if it is ever exposed. Everyone signs in again;
  passwords are unaffected. See `DEPLOYMENT.md` section 8.
- **Keep TLS renewing.** `systemctl list-timers | grep certbot`. An expired
  certificate takes the whole site down, because the session cookie is `Secure`.
- **Apply OS updates.** `unattended-upgrades` for security patches is sensible on
  a box like this.
- **Review admins twice a year.** Admin is the role that can read every draft.

Passwords are Argon2id, sessions are stored only as digests, and uploads are
validated by decoding rather than by trusting filenames. You do not need to
maintain any of that — but if someone asks whether a stolen database backup
would leak live sessions, the answer is no.

## 8. Growing out of this setup

Watch for one signal: **staff reporting that saving a guide is slow while
someone else is editing.** SQLite allows one writer at a time. Reading is not a
concern and never will be at this scale.

When that happens, move to PostgreSQL — `DEPLOYMENT.md` section 9. It is an
afternoon, not a rewrite, because SQLAlchemy speaks both.

Do not pre-emptively migrate. A Postgres instance is a second service to back
up, patch and monitor, and for a facility of this size it buys nothing until
that signal appears.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
