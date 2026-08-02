# Deploying Reticle

This guide is written to be understood, not just pasted. If you know why each
piece is there, you can fix it at 4pm on a Friday when something is wrong.

One host serves several facilities. Read `MULTI_FACILITY.md` first if you have
not — it explains the shape in one page. The short version: **the software
exists once**, and it is started once per facility against a different database.

---

## 1. What the moving parts are

```
        the internet / UZH network
                  │
                  │   zmb.reticle.ch      irchel.reticle.ch
                  ▼
        ┌─────────────────────────────────────────────────┐
        │  nginx                                          │
        │    terminates HTTPS (one wildcard certificate)  │
        │    serves ONE built frontend to all of them     │
        │    forwards /api to the right port per vhost    │
        └───────┬──────────────────────────┬──────────────┘
       127.0.0.1:8000              127.0.0.1:8001
                ▼                          ▼
        ┌──────────────┐           ┌──────────────┐
        │ reticle@zmb  │           │reticle@irchel│   same unit file,
        │  uvicorn     │           │  uvicorn     │   same virtualenv,
        └───────┬──────┘           └───────┬──────┘   same code on disk
                │                          │
        ┌───────┴──────┐           ┌───────┴──────┐
        │ reticle_zmb  │           │reticle_irchel│   PostgreSQL,
        │ media/       │           │ media/       │   one each
        └──────────────┘           └──────────────┘
```

**One release, many processes.** `/opt/reticle/current` is a symlink to one
release directory holding one virtualenv and one built frontend.
`reticle@.service` is a systemd *template*: `reticle@zmb` and `reticle@irchel`
run the same `uvicorn` from the same directory. The only thing that differs is
which environment file each one reads. Adding a facility copies no code.

**The frontend is static files, and it is shared.** `npx vite build` produces
HTML, CSS and JS. There is no Node process in production. The facility's name is
not baked in — it arrives at runtime from `GET /api/config`, which is exactly
why that endpoint exists and why it answers before anybody has signed in.

**The backend never serves the frontend.** It only answers `/api/…`. One process
with one job is easier to reason about, and a backend restart takes down that
facility's data, not its interface.

**Same origin, so no CORS in production.** nginx serves both the pages and
`/api` under one hostname, so the browser is making same-origin requests.
`RETICLE_CORS_ORIGINS` matters only in local development, where the frontend is
on port 5173 and the API on 8000.

**The database is PostgreSQL, one per facility.** That is the isolation
decision: a query that forgets its filter cannot reach another facility's data,
because the connection does not contain it. SQLite is for development.

**Ports are allocated, not chosen.** `provision-facility.sh` takes the first
free port from 8000 upwards and writes it into the facility's environment file.
Nothing else needs to know it — the vhost and the readiness checks read it back
from there.

---

## 2. Two accounts, and why they are two

This is the part that is easiest to get wrong and most annoying to unpick later.

| Account | Shell | What it is for |
| --- | --- | --- |
| `reticle` | none (`/usr/sbin/nologin`) | runs the application. Owns every facility's database password, media and backups. Nobody logs in as it. |
| `reticle-deploy` | `/bin/bash` | receives the deploy over SSH. Owns `/opt/reticle/releases`. |

They cannot be one account. The service account must have no shell — it holds
every secret on the box — and an account with no shell cannot accept an `ssh`
command. So the deploy arrives as `reticle-deploy`, unpacks a release and builds
a virtualenv **with no privilege at all**, and crosses to `reticle` only for the
two things that need it.

Those two things are the whole of `deploy/reticle-deploy.sudoers`:

```
reticle-deploy ALL=(root)    NOPASSWD: /usr/bin/systemctl restart reticle@*
reticle-deploy ALL=(reticle) NOPASSWD: /bin/bash
```

Be clear-eyed about the second line: running any command as `reticle` is, in
practice, everything `reticle` can do, including reading every facility's
database password. That is not a hole in the rule — it is what a deploy *is*,
since it installs the code that runs as `reticle`. The rule is narrow in the
direction that matters, which is that it is **not root**.

Without that file the deploy fails at the migration step with a password prompt
nobody is there to answer. Install it before the first deploy.

---

## 3. What you need before starting

- A Linux VM (Debian or Ubuntu assumed below). 2 vCPU and 4 GB RAM is
  comfortable for a handful of facilities — budget 100–200 MB of memory per
  facility, since each one is its own process.
- PostgreSQL 16, on this host or managed.
- **A wildcard DNS record**, `*.reticle.ch`, pointing at the box. With it,
  adding a facility needs no DNS step at all.
- **A wildcard certificate**, `*.reticle.ch`. Same reason.
- Python 3.12 and `python3-venv`.
- `sudo` on the box.

**HTTPS is not optional.** The session cookie is issued with the `Secure` flag,
so browsers refuse to send it over plain HTTP. Without TLS nobody can log in.
That is a feature: it is the difference between a password crossing the
university network encrypted and in the clear.

---

## 4. First install of the host

You do this once. Adding facilities afterwards is section 5 and is one command.

### 4.1 The accounts and the directory layout

```bash
sudo adduser --system --group --home /opt/reticle --shell /usr/sbin/nologin reticle
sudo adduser --disabled-password --gecos '' reticle-deploy

sudo install -d -o reticle-deploy -g reticle-deploy -m 755 /opt/reticle/releases
sudo install -d -o reticle        -g reticle        -m 755 /opt/reticle/facilities
```

`releases/` holds each version and is owned by the deploy account, which is what
lets a deploy write one without privilege. It is `755` because the service
account has to read the code it runs.

`facilities/` holds one directory per facility — the environment file, the
media, the backups. **Nothing under it is ever touched by a deploy**, which is
what makes rolling the code back safe.

There is no `shared/` and no shared `.env`. Configuration is per facility.

### 4.2 The SSH key and sudo rule

```bash
sudo -u reticle-deploy mkdir -p ~reticle-deploy/.ssh
sudo -u reticle-deploy tee ~reticle-deploy/.ssh/authorized_keys <<< '<the deploy public key>'
sudo chmod 700 ~reticle-deploy/.ssh && sudo chmod 600 ~reticle-deploy/.ssh/authorized_keys

sudo install -o root -g root -m 0440 deploy/reticle-deploy.sudoers /etc/sudoers.d/reticle-deploy
sudo visudo -c -f /etc/sudoers.d/reticle-deploy      # check before you trust it
```

Check it with `visudo` every time. A syntax error in a file under `sudoers.d`
can make `sudo` refuse to run at all, and the machine you would use to fix that
is the machine you just locked yourself out of.

### 4.3 The systemd template

```bash
sudo cp deploy/reticle@.service /etc/systemd/system/reticle@.service
sudo systemctl daemon-reload
```

One file, any number of facilities. Do not create `reticle.service` — the `@` is
the whole mechanism.

Read the containment block at the bottom of that file before you edit it. The
process decodes images from a browser with Pillow; it should be able to touch
its own facility's directory and nothing else on the machine.

### 4.4 The first release

Normally CI puts a release here. For the very first one, by hand:

```bash
sudo -u reticle-deploy mkdir -p /opt/reticle/releases/v0
# copy backend/ as backend/, frontend/dist as static/, deploy/ as deploy/
sudo -u reticle-deploy python3.12 -m venv /opt/reticle/releases/v0/venv
sudo -u reticle-deploy /opt/reticle/releases/v0/venv/bin/pip install \
     --require-hashes -r /opt/reticle/releases/v0/backend/requirements.lock
sudo -u reticle-deploy chmod -R a+rX /opt/reticle/releases/v0
sudo -u reticle-deploy ln -sfn /opt/reticle/releases/v0 /opt/reticle/current
```

`--require-hashes -r requirements.lock`, never `-r requirements.txt`. The `.txt`
files hold version *ranges* and resolve to whatever is newest that minute, so
installing from them puts a dependency set on the server that nothing ever
tested, and makes a rollback rebuild a different environment than the one it is
rolling back to. The lock pins every package and every transitive package to one
version with a hash. Regenerating it is documented at the top of
`backend/requirements.txt`.

### 4.5 nginx and the certificate

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo certbot certonly --nginx -d '*.reticle.ch'   # DNS challenge; follow the prompts
```

Per-facility vhosts are written for you in section 5. Nothing to hand-write.

---

## 5. Adding a facility

```bash
sudo ./deploy/provision-facility.sh zmb "Center for Microscopy and Image Analysis" admin@zmb.uzh.ch
```

That one command creates the database and a role that can reach nothing else,
creates the directories, allocates a port, writes the environment file, runs the
migrations, seeds the first administrator, starts `reticle@zmb`, waits for
`/api/ready`, writes and enables the vhost, and reloads nginx. It prints the
bootstrap password **once** and deletes it from the environment file, so it is
not left on disk.

Give that password to the administrator by a route that is not email.

**If anything fails, it undoes everything it created** — the role, the database,
the directory, the vhost — and says so. So the fix for a failed run is to fix
the cause and run it again. It will not touch a role or database that existed
before it started; it refuses to begin at all in that case, and tells you the
two commands to remove them deliberately.

With a wildcard record and a wildcard certificate there is nothing else to do.
Without them, add the DNS record and run `certbot --nginx -d zmb.reticle.ch`.

### What lands in the environment file

Every facility gets its own `RETICLE_SECRET_KEY`, and that matters more than it
looks: the key is the pepper for session-token digests, so sharing one would
mean a database stolen from the least careful facility could be used to forge
sessions at the most careful one.

`RETICLE_TRUST_FORWARDED_FOR` is written as **false**, deliberately. See
section 9 before changing it.

---

## 6. Check it actually works

```bash
curl -sf https://zmb.reticle.ch/api/health           # {"status":"ok"}
curl -si https://zmb.reticle.ch/api/guides | head -1 # 401 — correct
curl -sI https://zmb.reticle.ch/ | grep -i content-security-policy
```

That 401 is the single most important check on this page. It proves the site is
behind the login. If it ever returns 200, stop and investigate.

The third one is the second most important. It has to print a policy. nginx's
`add_header` does not stack across levels — a block containing any `add_header`
of its own discards every one it would have inherited — and the block that
answers with the HTML document sets a `Cache-Control`. If the policy is missing
from that response, every security header is missing from every page, silently,
with nothing in any log to say so. The vhost handles this by including the
headers in each block; CI asserts on it on every run.

Then open the site, sign in, create a test guide, upload an image, publish it,
and read it on your phone.

---

## 7. Updating

Tag a release and the pipeline ships it:

```bash
git tag v1.1.0 && git push origin v1.1.0
```

What it does, in order, and why the order is that:

1. Runs the full CI suite against the tag. A tag is exactly the moment somebody
   is in a hurry.
2. Builds the frontend and packs a bundle: `backend/`, `static/`, **and
   `deploy/`** — the release carries the scripts that migrate it, because a
   migration step has to match the migrations it is running.
3. Unpacks it into `releases/<tag>` and builds a virtualenv from the lock.
4. Records what `current` points at right now, so the rollback has somewhere to
   go that is not the release that just failed.
5. Moves the `current` symlink.
6. Runs `migrate-all.sh`: for each facility, **back up, then migrate**, stopping
   at the first failure. The old processes are still serving throughout.
7. Runs `restart-facilities.sh`: restart each facility and wait for it to answer
   `/api/ready` **on its own port** before touching the next.
8. Prunes old releases, never the live one and never the one a rollback would
   return to.

There is deliberately no step that curls the site from the GitHub runner. There
is no page at the bare host name — every vhost answers to `{slug}.reticle.ch` —
and the host is inside the university network, which a runner is not. A check
like that fails on a healthy deploy, and a failing check triggers the rollback.

**By hand**, if the pipeline is unavailable: do the same steps in the same
order. Do not skip `migrate-all.sh` and do not restart facilities before it.

---

## 8. Rolling back

The pipeline does it automatically on failure. By hand:

```bash
ls /opt/reticle/releases
sudo -u reticle-deploy ln -sfn /opt/reticle/releases/<previous> /opt/reticle/current
sudo /opt/reticle/current/deploy/restart-facilities.sh
```

**Moving the symlink is not a rollback on its own.** Each facility is a
long-running process that loaded its code at start-up, so until they are
restarted they are all still executing the release that just failed. That is
what the second command is for, and it is the same script the deploy uses, so
the two cannot drift apart.

This works because the databases and the media live under `facilities/`, outside
any release. Rolling the code back does not roll content back — which is what
you want, since guides written since the update are real work.

It is safe because migrations here are **additive**: a column is added, code
that writes both is deployed, the old one is removed a release later. The
previous release can still read the new schema. A release needing a destructive
migration breaks this, and has to say so in its notes.

---

## 9. `X-Forwarded-For`, and why the setting is off

`reticle@.service` starts uvicorn with `--proxy-headers
--forwarded-allow-ips 127.0.0.1`. uvicorn therefore reads the forwarded header
itself, from the only source it trusts, and replaces the peer address with the
real client's **before any request reaches the application**. Attribution in the
audit log and in the login throttle is already correct.

So `RETICLE_TRUST_FORWARDED_FOR` stays **false**, and turning it on is not
neutral. It switches the application to reading the *leftmost* entry of
`X-Forwarded-For`, and that entry is client-controlled the moment anyone changes
the vhost's

```nginx
proxy_set_header X-Forwarded-For $remote_addr;
```

to the usual `$proxy_add_x_forwarded_for`, which appends rather than overwrites.
Worse, a leftmost value that is not an address at all becomes "no address" —
which drops the per-(account, address) login limit of 5 to the far looser
per-account ceiling of 50, and switches the per-address limit off entirely. The
wrong setting here does not mislabel a log line; it weakens the login throttle.

Do not change that `proxy_set_header` line, and leave the setting false.

---

## 10. Object storage, and the policy that goes with it

A facility can keep its media in S3 or MinIO instead of on local disk:

```ini
RETICLE_STORAGE_BACKEND='s3'
RETICLE_S3_BUCKET='reticle-zmb'
RETICLE_S3_REGION='eu-central-1'
RETICLE_S3_ENDPOINT_URL=''        # set for MinIO or a non-AWS provider
```

**This needs one change outside the environment file, and it is not optional.**
With `s3`, a request for a picture is answered with a `302` to a short-lived
signed URL on the storage provider — a *different origin*. The browser judges
that final URL against the page's Content-Security-Policy, and the default
policy is `img-src 'self' data: blob:`. Every image and every video is blocked,
with nothing in any server log to say so, because the request is never made.

Name the storage origin when provisioning:

```bash
RETICLE_MEDIA_ORIGIN=https://s3.eu-central-1.amazonaws.com \
  sudo ./deploy/provision-facility.sh zmb "…" admin@zmb.uzh.ch
```

For a facility that already exists, edit its headers snippet:

```bash
sudo nano /etc/nginx/snippets/reticle-zmb-headers.conf
#   img-src   'self' data: blob: https://s3.eu-central-1.amazonaws.com;
#   media-src 'self' blob:       https://s3.eu-central-1.amazonaws.com;
sudo nginx -t && sudo systemctl reload nginx
```

Name the origin, never a wildcard. The point of the policy is that a script
injected into a guide cannot phone out.

The media themselves stay behind the login regardless of backend: the visibility
check runs *before* the signed URL is minted, and objects are written with no
public ACL.

---

## 11. Where things are

| Thing | Path |
| --- | --- |
| Live code (symlink) | `/opt/reticle/current` |
| Releases | `/opt/reticle/releases/<tag>` |
| Built frontend, shared | `/opt/reticle/current/static` |
| A facility's configuration | `/opt/reticle/facilities/<slug>/env` (0600, `reticle`) |
| A facility's uploads | `/opt/reticle/facilities/<slug>/media/` |
| A facility's backups | `/opt/reticle/facilities/<slug>/backups/` (0700) |
| A facility's database | PostgreSQL `reticle_<slug>` |
| Logs | `journalctl -u reticle@<slug>` |
| Service template | `/etc/systemd/system/reticle@.service` |
| A facility's vhost | `/etc/nginx/sites-available/reticle-<slug>` |
| A facility's security headers | `/etc/nginx/snippets/reticle-<slug>-headers.conf` |
| The deploy's sudo rule | `/etc/sudoers.d/reticle-deploy` |

---

## 12. Rotating a facility's secret key

If a `RETICLE_SECRET_KEY` is ever exposed — pasted into a ticket, on a stolen
laptop — generate a new one, put it in **that facility's** env file, and restart
**that facility**:

```bash
sudo -u reticle python3 -c "import secrets; print(secrets.token_urlsafe(48))"
sudo -u reticle nano /opt/reticle/facilities/zmb/env
sudo systemctl restart reticle@zmb
```

Everyone at that facility signs in again. Nobody at any other facility is
affected, because the keys are separate. Passwords are unaffected either way;
they are hashed with Argon2id independently of this key.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
