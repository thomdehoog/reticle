# Dozuki API notes (for the ZMB content export)

Reference for a one-off exporter that pulls guides and wikis out of `zmb.dozuki.com`
through Dozuki's public API ("iFixit API v2.0", base `https://zmb.dozuki.com/api/2.0/`).

Researched 2026-10-10. Conventions used below:

- **live** = observed in an anonymous (unauthenticated) GET against `zmb.dozuki.com` on that date.
- **doc** = stated in the API documentation served by the site itself at
  `https://zmb.dozuki.com/api/2.0/doc` (per-section pages `/doc/Guides`, `/doc/Wikis`,
  `/doc/Content_Hierarchy`, `/doc/Authentication`, `/doc/Media`, `/doc/Tags`, `/doc/Users`,
  `/doc/Search`, `/doc/single_sign_on`).
- **unverified** = not confirmed by either; treat as an assumption to test.

Sources and limits of this research:

- `https://www.ifixit.com/api/2.0/doc` is blocked for automated fetching (robots.txt). The
  identical documentation is served on the Dozuki site itself, and that copy was used. No
  ifixit.com API fallback was needed; every example below is from `zmb.dozuki.com`.
- All fetches were anonymous GETs through a tool that summarises pages. JSON shown here was
  transcribed from those responses; long payloads were trimmed and a few counts (e.g. number of
  guides per page) are from the tool's reading of the payload, not from a byte-exact parse.
- Nothing requiring a login was tested: token issuance, `includePrivate`, HTTP response
  headers, error bodies and rate limiting are all **unverified** in practice.

---

## 1. Authentication

### Documented mechanism (doc)

| Step | Detail |
|---|---|
| Obtain token | `POST /api/2.0/user/token`, JSON body `{"email": "...", "password": "..."}` |
| Success | `201 Created`; body is the user profile plus an `authToken` string |
| Send token | Header `Authorization: api <authToken>` on every later request |
| App id | Header `X-App-Id: <appid>`. Doc: needed on login/register requests for sites with public registration enabled; "You don't need an app id for most requests." The app id is obtained from the site administrator. |
| Log out | `DELETE /api/2.0/user/token` -> `204 No Content` (invalidates the current token) |
| Impersonate | `POST /api/2.0/user/token/impersonate`, body `{"login": "<login email of target user>"}` -> `201` with that user's profile and `authToken`. Admin only. |

Dozuki's own example script (`github.com/iFixit/dozuki-api-authentication-example`, `example.php`)
does exactly this:

```php
curl_setopt($curl, CURLOPT_URL, "https://$dozukiDomain/api/2.0/user/token");
curl_setopt($curl, CURLOPT_CUSTOMREQUEST, 'POST');
curl_setopt($curl, CURLOPT_POSTFIELDS, json_encode(['email' => ..., 'password' => ...]));
curl_setopt($curl, CURLOPT_HTTPHEADER, ["X-App-Id: $appId"]);
$authToken = json_decode(curl_exec($curl), true)['authToken'];
// later requests:
curl_setopt($curl, CURLOPT_HTTPHEADER, ["Authorization: api $authToken"]);
```

Other documented auth endpoints (not needed for export): `POST /users` (register),
`POST /users/reset_password`.

Token lifetime / expiry: not documented. **unverified.**

### SSO-only sites (SAML / ADFS)

- The doc page `/doc/single_sign_on` is purely an admin setup guide for SAML (IdP entity id,
  IdP URL, X.509 certificate, logout URL, claim mapping `Display-Name -> username`,
  `E-Mail-Addresses -> email`, `SAML-Account-Name -> userid`, optional `role` claim with values
  `user`/`operator`, `author`, `moderator`, `authorandmod`, `admin`). It says **nothing** about
  how an SSO user obtains an API token.
- `POST /user/token` takes an email and a Dozuki-local password. A user that exists only
  through SAML has no such password, so this call cannot work for them. If email/password login
  is disabled site-wide, whether the endpoint is disabled too is **unverified** (likely).
- Whether the ZMB site is actually SSO-only was not determined (the login page was not probed).
- Options, all **unverified** and to be confirmed with the site admin / Dozuki support:
  1. A local (non-SSO) admin account with a password, if the site allows mixed login, then
     `POST /user/token`.
  2. An admin token used with `POST /user/token/impersonate` (still needs a first admin token).
  3. An API token / app id issued by Dozuki support or from the admin UI. No documentation of a
     self-service "generate API token" screen was found; do not assume it exists.
  4. Reusing a browser session cookie from an SSO login. The API is the same backend the web
     app uses, so a logged-in session cookie plausibly authenticates API GETs, but this is not
     documented and was not tested.
- The `X-App-Id` value for this site is unknown; ask the admin.

### What anonymous access already gives (live)

The site answers anonymous GETs for guide lists, full guides, guide tags, wikis (including
`contents_raw`), categories, the tag list, media metadata and user profiles. Anonymous
responses carry `can_edit: false` and all-false `permissions`. Authentication is needed only
for content that is not public (see section 2).

Note: `GET /users/{userid}` returned the user's `login` (email address) and `privileges` to an
anonymous caller. Treat exported user data as personal data.

---

## 2. Listing guides

`GET /api/2.0/guides`

Query parameters (doc):

| Param | Type | Notes |
|---|---|---|
| `limit` | int | range `[1, 200]`, default `20` |
| `offset` | int | `[0, inf)`, default `0` |
| `order` | enum | `ASC` / `DESC`, by `guideid` |
| `guideids` | comma list | restrict to specific ids |
| `filter` | enum | `replacement`, `installation`, `repair`, `disassembly`, `teardown`, `technique`, `maintenance` (guide types; no tag or category filter) |
| `modifiedSince` | int | UNIX timestamp |
| `includePrivate` | bool | "return all guides, public and private" when Admin authentication is provided |

Related: `GET /guides/featured` (guides with the `GUIDE_STARRED` flag), `GET /users/{userid}/guides`,
`GET /user/guides` (own guides, needs auth), `GET /guides/releases` and
`GET /guides/{guideid}/releases` (release/version records; not examined).

Observed behaviour (live):

- Response is a bare JSON array of guide summaries. No total count, no paging metadata.
- Past the end, the body is `[]`.
- **Pages can be short without being the last page.** With `limit=40`, successive pages
  returned about 38, 37, 35, 37, 31, 33, 32, 17 items, then `[]` at `offset=320`. The limit
  appears to be applied before guides invisible to the caller are filtered out. So: page until
  an empty array, never stop on `len(page) < limit`, and de-duplicate by `guideid`.
- Roughly 260 guides are visible anonymously; guide ids run from 15 to 486. At least ~37 rows in
  the offset space were not returned to an anonymous caller. These are presumably private /
  unpublished / restricted guides and are what `includePrivate=true` with an admin token should
  reveal. **unverified.**
- Every anonymously visible guide had `"public": true`. How private guides look when returned
  (`"public": false`) is from the doc only.
- `limit` above 200: not tested for the server's reaction (the fetch tool truncated the body).
  Use `limit<=200`.
- Rate limits: none documented anywhere in the doc pages; response headers could not be
  inspected. **unverified.** Be polite (a few requests per second, back off on 429/5xx).

List item shape (live, `GET /guides?limit=2`, first element, image URLs trimmed):

```json
{
  "dataType": "guide",
  "guideid": 15,
  "locale": "en",
  "revisionid": 7156,
  "guide_revisionid": 28242,
  "modified_date": 1788435314,
  "prereq_modified_date": 0,
  "url": "https://zmb.dozuki.com/Guide/Leica+Stellaris+5+inverse+(USZ)+-+How+to+get+there/15",
  "type": "how-to",
  "category": "basics access and IT - hidden",
  "subject": "",
  "title": "Leica Stellaris 5 inverse (USZ) - How to get there",
  "summary": "How to get to the Stellaris 5 inverse in USZ, ...",
  "difficulty": "Very easy",
  "time_required_max": 300,
  "public": true,
  "userid": 12,
  "username": "Joana Raquel Delgado Martins",
  "flags": [],
  "image": { "id": 507, "guid": "GGxW5WO3SaVnR5an", "mini": "...", "thumbnail": "...",
             "140x105": "...", "200x150": "...", "standard": "...", "440x330": "...",
             "medium": "...", "large": "...", "huge": "...",
             "original": "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.full" },
  "tags": false,
  "isArchived": false,
  "releaseTitle": "v6.0",
  "periodicReviewSchedule": null,
  "attachedQuiz": null,
  "workLogEnabled": 0,
  "work_log_enabled": 0,
  "workLogUrl": "https://zmb.dozuki.com/Guide/data-capture/15",
  "work_log_url": "https://zmb.dozuki.com/Guide/data-capture/15"
}
```

Notes on the list item:

- `"tags": false` in every list item seen, even for guides that do have tags. Do not use it;
  call `/guides/{id}/tags` (section 6).
- In the list, `flags` is an array of flag id strings (e.g. `["GUIDE_IN_PROGRESS"]`, seen on
  guides 414, 422, 426, 428, 429). In the full guide payload `flags` is an array of objects.
- `isArchived` exists; all visible guides had `false`.
- Only `type: "how-to"` and `locale: "en"` were seen on this site.
- Several categories are named "... - hidden" (e.g. `Confocal - hidden guides`,
  `IT - hidden Guides`, `Image processing - hiden`). Guides live in these and are surfaced on
  the visible category pages through tag-filtered `[guidelist]` widgets (section 4).

---

## 3. Full guide payload

`GET /api/2.0/guides/{guideid}`

Query parameters (doc): `excludePrerequisiteSteps` (bool; by default prerequisite guides' steps
are inlined into `steps` — set this to `true` for a faithful export), `unpatrolled` (bool,
default false), `type` (`JSON`/`XML`), `langid` (default site language; 404 if no version in
that language), `machineTranslateLangid`, `released` (bool, needs the release-versions
feature), `includeComments` (bool, default true), `useSourceLang` (bool).

### Top-level fields (live, guide 15 and 422)

| Field | Type / example | Notes |
|---|---|---|
| `guideid` | int `15` | |
| `title` | string | |
| `summary` | string (plain, may contain `\n`) | |
| `introduction_raw` | string | wiki text (section 4 syntax) |
| `introduction_rendered` | string | HTML, e.g. `<p>...</p>` |
| `introduction_json` | object | ProseMirror-style doc, e.g. `{"type":"doc","content":[{"type":"paragraph"}]}` |
| `conclusion_raw` / `conclusion_rendered` | string | same pattern; often `""` |
| `difficulty` | string | seen: `"Very easy"`, `"Easy"`, `"Moderate"`. Standard iFixit scale also has `"Difficult"` and `"Very difficult"` (**unverified** on this site) |
| `time_required` | string | display form, e.g. `"5 minutes"`, `"10 - 20 minutes"` |
| `time_required_min` / `time_required_max` | int | **seconds** (300 = "5 minutes"; 600/1200 = "10 - 20 minutes"); `0` = unset |
| `type` | string | `"how-to"` (only value seen) |
| `subject` | string | `""` on all seen |
| `category` | string | category *title* (wiki title, not display title), e.g. `"Basic Guides"` |
| `public` | bool | |
| `flags` | array of objects | e.g. `{"title":"In Progress","flagid":"GUIDE_IN_PROGRESS","text":"This guide is currently being written. ...", + an image URL}`. Other flag ids in the doc: `GUIDE_STARRED`, `GUIDE_PREREQ_ONLY` |
| `locale`, `langid` | string `"en"` | |
| `revisionid` | int | deprecated per doc ("included for backwards compatibility") |
| `guide_revisionid` | int | the one to use ("Only 'guide_revisionid' should be used") |
| `created_date`, `published_date`, `modified_date` | int | UNIX epoch **seconds**. Caution: guide 422 has `created_date` 1740643317 later than `published_date` 1561989541, so do not assume ordering |
| `prereq_modified_date` | int | `0` when no prerequisites |
| `url` | string | canonical page URL |
| `body_url_path` | string | path only |
| `author` | object | `userid`, `username`, `unique_username`, `join_date`, `reputation`, `teams` (int ids), `image`, `enabled`, ... (list items carry flat `userid`/`username` instead) |
| `image` | image object | guide cover image (same shape as step images) |
| `prerequisites` | array | empty on all inspected ZMB guides. Doc example items: `guideid`, `title`, `difficulty`, `time_required_max`, `userid`, `username`, `flags`, `image`, ... |
| `documents` | array | attached documents; empty on all inspected (item shape **unverified**) |
| `tools`, `parts` | array | empty on all inspected |
| `steps` | array | see below |
| `comments` | array | guide-level comments (also per step) |
| `intro_video_url`, `intro_video`, `intro_video_media_item` | null | |
| `featured_documentid`, `featured_document_embed_url`, `featured_document_thumbnail_url` | null / `""` | |
| `per_step_time_enabled` | bool | |
| `number_of_dependent_guides` | int | |
| `can_edit`, `can_delete`, `can_edit_language`, `can_edit_permissions`, `should_use_granular_permissions`, `favorited`, `completed`, `patrol_threshold`, `work_log_enabled`, `work_log_url`, `ogdc_enabled` | misc | caller-specific / not content |

Not present in the guide payload: **tags** (separate endpoint, section 6) and **view counts**
(no field exposed; `GET /user_view_history/{doc_type}/{docid}` exists in the doc index but was
not examined — **unverified**).

### Steps (live)

```json
{
  "title": "",
  "guideid": 15,
  "stepid": 72,
  "orderby": 1,
  "revisionid": 18737,
  "time_estimate": 0,
  "imageURL": "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.mini",
  "lines": [
    {
      "text_raw": "Get to the Pathology building at USZ, Schmelzbergstrasse 12 , CH-8091 Zürich.",
      "text_rendered": "Get to the Pathology building at USZ, Schmelzbergstrasse 12 , CH-8091 Zürich.",
      "bullet": "black",
      "bullet_styleid": 1,
      "bullet_style": {
        "bullet_styleid": 1, "type": "dot", "is_default": 1, "color_locked": 1,
        "label": null, "description": null, "is_disabled": 0, "bullet_color": "#11161a",
        "size": "small", "imageid": null, "char": null,
        "last_modified": 1702940726, "userid_modified": 1
      },
      "level": 0,
      "lineid": null
    }
  ],
  "media": { "type": "image", "data": [ { "id": 507, "guid": "GGxW5WO3SaVnR5an", "...": "..." } ] },
  "comments": []
}
```

- Order steps by `orderby` (1-based). `stepid` is stable; `title` is often `""`.
- `time_estimate` is per-step (0 when unused).

#### `lines[]`

- `text_raw`: wiki text (inline subset). `text_rendered`: HTML fragment (no wrapping `<p>`),
  with entities escaped (`"` becomes `&quot;`).
- `level`: int indent level. Seen `0` and `1`; iFixit allows up to `2` (**unverified** here).
- `lineid`: `null` on everything seen.
- `bullet` values:

  | Value | Seen live | `bullet_styleid` | `bullet_color` |
  |---|---|---|---|
  | `black` | yes | 1 | `#11161a` |
  | `red` | yes | 2 | `#c1280b` |
  | `orange` | yes | 3 | `#ff9024` |
  | `yellow` | yes | (not captured) | (not captured) |
  | `green` | yes | 5 | `#16dc81` |
  | `light_blue` | yes | 6 | `#15a1d6` |
  | `icon_note` | yes | (not captured) | |
  | `icon_caution` | yes | (not captured) | |
  | `blue`, `violet` | no — standard iFixit values, **unverified** here | | |
  | `icon_reminder` | no — standard iFixit value, **unverified** here | | |

  `bullet_style.type` was `"dot"` for all colour bullets captured. The `bullet_style` object
  (with `label`, `imageid`, `char`) suggests the site can define custom bullet styles; map on
  `bullet` first and fall back to `bullet_style.bullet_color`. Handle unknown values gracefully.
- Inline markup observed in `text_raw`:
  - `'''bold'''` -> `<strong>bold</strong>`
  - `***text***` -> `<strong>text</strong>` (seen in guide 27; apparently produced by the newer
    editor — treat as bold)
  - `[https://svi.nl/NyquistCalculator|SVI Nyquist Calculator]` -> `<a href="..." rel="nofollow noopener noreferrer">...</a>`
  - `[link|https://svi.nl/HowtoCiteHuygens|cite Huygens]` (in `introduction_raw`) -> same `<a>`
  - Since `text_rendered` is always supplied, converting the rendered HTML to Markdown is a
    safe alternative to parsing wiki text for step lines.

#### `media`

`media.type` is `"image"` or `"video"` on this site. `"embed"` is the third documented iFixit
type; none was found here, its shape is **unverified**.

**Image** — `media.data` is an **array** of image objects (up to 3 per step seen):

```json
{
  "id": 507,
  "guid": "GGxW5WO3SaVnR5an",
  "mini":      "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.mini",
  "thumbnail": "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.thumbnail",
  "140x105":   "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.140x105",
  "200x150":   "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.200x150",
  "standard":  "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.standard",
  "440x330":   "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.440x330",
  "medium":    "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.medium",
  "large":     "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.large",
  "huge":      "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.huge",
  "original":  "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/GGxW5WO3SaVnR5an.full"
}
```

- Size keys vary per image: smaller uploads lack `huge` (and possibly `large`). Always read the
  keys present; `original` (URL suffix `.full`) was present on every image seen.
- The image object inside a guide has **no** `markup`, `width` or `height`. Those are only on
  `GET /media/images/{id}` (below).

**Image markers / annotations** — `GET /api/2.0/media/images/{imageid or guid}` (live, image 507):

```json
{
  "image": { "id": 507, "guid": "GGxW5WO3SaVnR5an", "...size urls...": "..." },
  "srcid": 477,
  "width": 4032,
  "height": 3024,
  "ratio": "FOUR_THREE",
  "markup": ";arrow,2544.9731115392738x2220.324324324324,932.2163895943447x2208.5092567642882,red;",
  "markupState": {
    "annotations": {
      "type": "NODE_MARKUP", "version": "1",
      "data": [
        { "shape": "arrow", "xStart": 2544.9731115392738, "yStart": 2220.324324324324,
          "xEnd": 932.2163895943447, "yEnd": 2208.5092567642882, "color": "red" }
      ]
    }
  },
  "exif": { "FileName": "DFD62FA6-6789-42A2-9664-3CE818774B2C.jpeg" },
  "encoding": "jpeg",
  "srcImageInfo": {
    "image": { "id": 477, "guid": "XNFA4FAvgAweVCoW", "...": "..." },
    "srcid": null, "width": 4032, "height": 3024, "ratio": "FOUR_THREE",
    "markup": null, "markupState": null, "encoding": "jpeg",
    "suggestedCrop": { "width": 4032, "height": 3024, "x": 0, "y": 0 }
  }
}
```

What this shows:

- **A marked-up image is a separate image record with the markers already burned into its
  pixels.** Image 507 (used in the guide) has `srcid: 477`; image 477 is the clean source
  (`markup: null`). Downloading the guide's image URLs therefore already yields annotated
  pictures; the clean source is reachable via `srcid` / `srcImageInfo` if wanted.
- `markup` string: `;`-delimited records, `shape,<x1>x<y1>,<x2>x<y2>,<color>`.
  `markupState.annotations.data[]` is the structured equivalent (`shape`, `xStart`, `yStart`,
  `xEnd`, `yEnd`, `color`).
- Coordinates are **pixels in the full-resolution image** (values up to 2544 on a 4032x3024
  image), origin presumably top-left (**unverified**, the usual convention).
- Only `arrow` was observed. The marker help page (`/Help/Markers`) describes circles and
  rectangles in red, orange, yellow, green; their exact record layouts (classic iFixit form is
  roughly `circle,<x>x<y>,<radius>,<color>` and `rectangle,<x1>x<y1>,<x2>x<y2>,<color>`) are
  **unverified**.
- `ratio` seen: `FOUR_THREE`, `VARIABLE`.

**Video** — `media.data` is a single **object** (not an array). Same shape as
`GET /api/2.0/media/videos/{videoid}` (live, video 137, used in guide 27 step 4):

```json
{
  "objectid": 163,
  "videoid": 137,
  "srcid": null,
  "filename": "viewfinder.mp4",
  "duration": 8230,
  "width": 1280,
  "height": 720,
  "meta": null,
  "image": {
    "image": { "id": 17613, "guid": "BXNfyPRLbMnukGuV",
               "standard": "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/BXNfyPRLbMnukGuV.standard",
               "original": "https://d3t0tbmlie281e.cloudfront.net/igi/zmb/BXNfyPRLbMnukGuV.full" },
    "srcid": null, "width": 1280, "height": 720, "ratio": "VARIABLE",
    "markup": null, "markupState": null, "exif": [], "encoding": "jpeg"
  },
  "encodings": [
    {
      "column": "MP4_720",
      "label": "480p",
      "width": 720,
      "height": 480,
      "codecs": "avc1.4D401E, mp4a.40.2",
      "ffmpeg_args": "-vcodec libx264 -profile:v main ...",
      "mime": "video/mp4",
      "always_generate": true,
      "url": "https://dozuki-prod-us-east-1-guide-objects.s3.amazonaws.com/igo/video/zmb/BJGvyPRLJAnukGuV_MP4_720.mp4",
      "format": "mp4"
    }
  ]
}
```

- `duration` is in milliseconds (8230 for an ~8 s clip).
- `image` is the poster frame, wrapped one level deeper than step images (`image.image.original`).
- Only one encoding (`MP4_720`, a 720x480 transcode) was offered. The originally uploaded file
  (`filename`, 1280x720 here) has **no download URL** in the payload. The doc example for
  iFixit lists several encodings (MP4/WebM/Ogg); expect only what `encodings[]` contains.

---

## 4. Wikis

### Endpoints (doc index; GETs verified live where marked)

| Endpoint | Notes |
|---|---|
| `GET /wikis/{namespace}` | list; `limit`/`offset` accepted (live). Namespaces per doc: `WIKI`, `CATEGORY`, `INFO`, `ITEM`, `USER`, `TEAM` |
| `GET /wikis/{namespace}?display=titles` | array of title strings (live) |
| `GET /wikis/CATEGORY?display=hierarchy` | category tree + display titles (live, section 5) |
| `GET /wikis/{namespace}/{title}` | full page incl. `contents_raw` (live) |
| `GET /wikis/{namespace}/{title}/tags` | array of tag strings (doc) |
| `GET /wikis/CATEGORY/{title}/children` | (doc index only, not examined) |

`{title}` is the wiki's internal title, URL-encoded; both `Basic%20Guides` and underscore form
(`Strategy_to_Run_...`) worked. The doc describes this parameter as "display title" for the
tags endpoint, but the internal `title` is what was used successfully here. Paging maxima for
wiki lists are not stated on the page fetched; assume the same `limit` range `[1, 200]`,
default 20 (**unverified**).

Counts seen anonymously: `WIKI` 2 pages, `INFO` at least 3 (system pages: `Answers FAQ`,
`flags`, `Guidebook FAQ`), `CATEGORY` 18 titles. `ITEM`, `USER`, `TEAM` not probed.

### List item (live, `GET /wikis/CATEGORY?limit=2`, trimmed)

```json
{
  "dataType": "wiki",
  "wikiid": 73,
  "revisionid": 517,
  "title": "Archive",
  "display_title": "Archive",
  "namespace": "CATEGORY",
  "summary": "This section contains guides for decommissioned instruments ...",
  "url": "https://zmb.dozuki.com/c/Archive",
  "text": "This section contains guides for decommissioned instruments ...",
  "image": { "id": 12099, "guid": "2QYjASiVCbLOvSHc", "...": "...", "original": "...full" },
  "modified_date": 1626439287,
  "langid": "en",
  "release_title": "Dozuki System Automated Release",
  "attachedQuiz": null,
  "permissions": { "canEdit": false, "...": false }
}
```

(plus approval-process and `can_*` fields that are not content). The list has no
`contents_raw`; fetch each page individually.

### Full page (live, `GET /wikis/CATEGORY/Basic%20Guides`)

| Field | Example / notes |
|---|---|
| `wikiid` | `23` |
| `namespace` | `"CATEGORY"` |
| `title` | `"Basic Guides"` (internal, used in URLs and as guides' `category`) |
| `display_title` | `"Confocal Microscopy"` (what users see; can differ completely from `title`) |
| `description` | summary text (the list calls the same thing `summary`) |
| `contents_raw` | wiki text |
| `contents_rendered` | HTML, heavy (each heading wrapped in `div.headerContainer` with inline SVG anchor icons; guidelists expanded) |
| `contents_json` | ProseMirror-style doc mirroring `contents_raw` |
| `revisionid` | `997` |
| `langid` | `"en"` |
| `url`, `fullUrl` | `/c/Basic_Guides`, `https://zmb.dozuki.com/c/Basic_Guides` (WIKI pages: `/Wiki/<Title>`, INFO: `/Info/<Title>`) |
| `image` | image object or `null` |
| `flags` | array |
| `documents` | array |
| `author` | user object (seen on WIKI page) |
| `release_title` | e.g. `"v2.0"` |
| `source_revisionid`, `attachedQuiz`, `can_edit`, `editUrl`, approval fields | not content |

No created/modified date was seen in the full page; `modified_date` is in the list item.

`contents_json` node types seen: `doc`, `heading` (`attrs.level`), `paragraph`, `bulletList`,
`listItem`, `text`. Tables and `[guidelist|...]` tags are **not** structured there — they
appear as plain text nodes containing the wiki markup — so it does not remove the need to
parse wiki text.

### Real ZMB example: tag-filtered guide lists (live, `contents_raw` of CATEGORY "Basic Guides", trimmed)

```
== Abberior STED (Irchel) ==

[guidelist|tags=ASTED|type=howto]

== Evident  Fluoview 4000 (Irchel) ==

[guidelist|tags=E4000|type=howto]

== Leica SP8 inverse (Lengg) ==

[guidelist|tags=SP8B|type=howto]

== Leica Stellaris 5 inverse (USZ) ==

[guidelist|tags=StellUSZ|type=howto]

...
```

The page is about 28 such heading + guidelist pairs, one per instrument. Tags used there:
`ASTED`, `E4000`, `SP8B`, `SP8G`, `SP8IPZ`, `SP8Irchel`, `SP8Sch`, `SP8Falcon`, `SP8up`, `STED`,
`SP8upMP`, `Stellinv`, `StellUSZ`, `StellBOT`, `Stell`, `CICERO`, `moldev`, `MDIrchel`,
`MDLengg`, `NikonA1R`, `NikonSD`, `NikonSDL`, `OSD`, `PEO`, `VSD`, `Zeiss980`, `Zeiss900`.

So on this site **the instrument-to-guide mapping lives in guide tags plus these
`[guidelist|tags=...]` widgets**, not in the category of the guide. Cross-check: guide 15
(category `basics access and IT - hidden`) has tags `["location-access","StellUSZ"]` and is
therefore listed under "Leica Stellaris 5 inverse (USZ)".

### The guide-list / wiki-list syntax

- Help page form (`/Help/Wiki_Formatting_and_Syntax`): `[guidelist|tag=easy|type=howto]`,
  parameters `tag`, `item`, `type` (example `howto`), `title`. "Only public guides appear."
- Form actually used on ZMB: `[guidelist|tags=ASTED|type=howto]` — parameter spelled `tags`.
  Accept both `tag=` and `tags=`. Whether the value can be a comma-separated list, and whether
  multiple tags mean AND or OR, is **unverified** (for `wikilist` the help says articles must
  match *all* tags).
- `[wikilist|tag1,tag2]` with optional `title=` and `namespace=`: lists wiki pages matching all
  tags.
- Single guide link: `[guide|132]`, `[guide|132|Link text]`, step link
  `[guide|6463|Link text|stepid=212]`.
- There is no API filter by tag on `GET /guides`, and `GET /search` filters by doc type only.
  To resolve a guidelist, build a tag index yourself from `/guides/{id}/tags` for every guide,
  or scrape the expanded list out of `contents_rendered`.

### Wiki text syntax reference (from the site's help pages `/Help/Wiki_Formatting_and_Syntax` and `/Help/Tables`, plus live observations)

| Construct | Syntax | Markdown target / note |
|---|---|---|
| Headings | `== H2 ==` ... `====== H6 ======` | single `=` pair is reserved for the page title. Live: `==` and `===` in use, including emoji in heading text |
| Bold | `'''text'''` | also `***text***` seen in guide step text |
| Italic | `''text''` | |
| Bold italic | `'''''text'''''` | |
| Underline | `++text++` | |
| Strikethrough | `~~text~~` | |
| Monospace | double backticks around text | does not escape wiki formatting |
| Superscript / subscript | `x^^2^^` / `H,,2,,O` | |
| Raw (no formatting) | `[raw]text[/raw]` | |
| Code block | `[code]...[/code]` | not allowed in guide steps |
| Comment | `[comment]...[/comment]` | visible on edit pages only; drop or convert to HTML comment |
| Paragraph | blank line | |
| Line break | `[br]` | |
| Bulleted list | `* item`, `** nested`, `*** deeper` | live: `*` and `**` in use |
| Numbered list | `# item`, `## nested` | |
| Internal wiki link | `[[Page]]`, `[[Namespace:Page|Link text]]` | |
| External link | `[http://url|Link text]`, option `|new_window=true`; bare URLs auto-link | live in guide text |
| External link (keyword form) | `[link|https://url|Link text]` | live in `introduction_raw`; not on the help page |
| Mail link | `[mailto|user@example.com]` | |
| Guide link | `[guide|id]`, `[guide|id|text]`, `[guide|id|text|stepid=N]` | |
| Product link | `[product|SKU|text]` | iFixit.com only |
| Image | `[image|<imageid>]` with options `|size=small|medium|large|original`, `|align=left|right|center` (default right), `|caption=text`, `|link=url`, `|new_window=true` | resolve id via `GET /media/images/{id}` |
| Video | `[video|<url>]` (YouTube, Vimeo, Screencast `/embed` URL), options `|size=small|large` (default large), `|align=left|center` (default center) | external embeds only |
| Guide list | `[guidelist|tag=...|item=...|type=howto|title=...]` (ZMB uses `tags=`) | see above |
| Wiki list | `[wikilist|tag1,tag2|namespace=...|title=...]` | |
| Redirect | `[redirect|Category A]` | same page type only |
| Table | see below | |

Tables (help page + live example in WIKI page "Strategy to Run a Full Multiplex SeqIF ..."):

```
{table
|width=50%
|format=30%l:c:r
|! Header A
|! Header B
|! Header C
|--
| cell
| cell
| cell
}
```

- `{table` opens, `}` on its own line closes; `|--` starts a new row; `|` starts a cell; `|!` a
  header cell; one cell per line.
- Option lines directly after `{table`: `|width=50%`, `|format=<spec>` where the spec is
  colon-separated per column, an optional width percentage then `l`/`c`/`r` (horizontal) and
  optional `m`/`b` (vertical middle/bottom). Live: `|format=20%l:40%l:40%l`, `|format=30%l:70%l`.
- Cell attributes: `| <<colspan="2">> text`, `| <<rowspan="2">> text`,
  `| <<bgcolor="#f00" color="#fff">> text`.
- Image grids are built as tables of `[image|id|size=small]` cells.

Not documented on the help page and not observed: `[embed|...]`, `[summary]`, `[title]`,
`[quote]`, `[note]`, `[steps]`. The Content Hierarchy doc mentions category `contents_raw`
containing "tags such as title and summary" on iFixit; nothing like that appeared in the ZMB
pages inspected. Log any unrecognised `[xxx|...]` tag during conversion rather than dropping it.

---

## 5. Categories

| Endpoint | Result (live) |
|---|---|
| `GET /categories` | nested object of category **titles**; leaves are `{}` (doc says empty array; PHP empty-array serialisation, so accept `{}`, `[]` or `null`) |
| `GET /wikis/CATEGORY?display=hierarchy` | `{"hierarchy": {...}, "display_titles": {...}}`; leaves are `null`; `display_titles` maps title -> display title (e.g. `"Basic Guides" -> "Confocal Microscopy"`, `"Light Micrscopy" -> "Light Microscopy"`) |
| `GET /categories/all` | flat array of title strings; paged (default limit 20, so pass `limit`/`offset`) |
| `GET /wikis/CATEGORY?display=titles` | flat array of title strings |
| `GET /categories/{title}` | one category with its guides |

Parameters for the hierarchy endpoints (doc): `requireGuides` (bool, default false),
`includeStubs` (bool, default false; for `/categories` its mere presence enables it), `langid`,
`machineTranslateLangid`.

`GET /categories` (live, complete anonymous response):

```json
{
  "Basics and IT": { "Data Managment": {}, "IT": {} },
  "Light Microscopy Sample Preparation": {},
  "Light Micrscopy": {
    "Widefield Microscopy": {}, "Basic Guides": {}, "Super Resolution Microscopy": {},
    "Multiphoton Microscopy": {}, "Lightsheet microscopy": {}
  },
  "Electron Microscopy": {},
  "Image Analysis": {},
  "Internal Guides": { "Archive": {} },
  "CryoEM": {}
}
```

The tree is incomplete without extra flags/auth: the flat lists and guide payloads reveal more
categories than the tree shows, e.g. `Cell Culture`, `Spatial Biology`, `Root`,
`EM - hidden guides`, `LM - hidden guides`, `hidden - Spatial`, `Internal-hidden`,
`Image processing - hiden`, `Confocal - hidden guides`, `LS - hidden guides`,
`IT - hidden Guides`, `basics access and IT - hidden`, `Slidescanner-Zeiss Z.1 (Schlieren)`.
Try `includeStubs` and an authenticated call, and derive parents from each category's
`ancestors`.

`GET /categories/Basic%20Guides` (live, trimmed):

```json
{
  "wikiid": 23,
  "wiki_title": "Basic Guides",
  "display_title": "Confocal Microscopy",
  "locale": "en",
  "topic_info": [],
  "image": { "id": 4167, "guid": "EEyBfLEsVdl4Q3ou", "...": "..." },
  "description": "In this category you find guides about how to start-up and operate the various light microscopes ...",
  "flags": [],
  "solutions": { "url": "https://zmb.dozuki.com/Answers/Device/Basic%20Guides", "count": 0 },
  "parts": [],
  "tools": [],
  "ancestors": ["Light Microscopy", "Center for Microscopy and Image Analysis"],
  "children": ["Basic Guides", "Confocal - hidden guides"],
  "guides": [ { "dataType": "guide", "guideid": 412, "category": "Basic Guides", "...": "..." } ],
  "documents": [],
  "contents_rendered": "<div class=\"clearer\"></div>..."
}
```

Relationship category <-> wiki page:

- A category **is** a wiki page in the `CATEGORY` namespace; same `wikiid` (23 in both calls).
  `/categories/{title}` gives hierarchy (`ancestors`, `children`), the guides directly in the
  category (`guides[]`, list-item shape; 6 here) and rendered content.
  `/wikis/CATEGORY/{title}` gives `contents_raw`. An exporter needs both.
- `contents_raw` was not seen in the `/categories/{title}` response (the doc example shows it;
  the fetched body may have been cut before it). Rely on `/wikis/CATEGORY/{title}` for raw text.
- `ancestors` is ordered nearest-parent first and holds **display** titles
  (`"Light Microscopy"`, and the root shown by its display title
  `"Center for Microscopy and Image Analysis"`; root's internal title is `Root`).
- Oddity: `children` of "Basic Guides" lists `"Basic Guides"` itself alongside
  `"Confocal - hidden guides"`. Whether `children` holds titles or display titles (possibly a
  hidden child sharing the name) is **unverified**; guard against self-reference/cycles.
- Guides reference their category by internal `title` (`"category": "Basic Guides"`).

---

## 6. Tags

| Endpoint | Result |
|---|---|
| `GET /tags` | site-wide array of tag name strings; `limit` `[1,200]` default 20, `offset`, `order` (by tag id). Page through it — the default returns only 20 |
| `GET /guides/{guideid}/tags` | array of tag name strings for one guide |
| `GET /wikis/{namespace}/{title}/tags` | same for a wiki page |
| `PUT` / `DELETE /guides/{guideid}/tag`, `/wikis/{namespace}/{title}/tag` | write endpoints (body `{"tag": "..."}`); not needed |

Live:

```
GET /tags                -> ["Lightsheet","Maintenance","Zeiss","Deconvolution","SVI","Huygens",
                             "Confocal","Fluorescence","Restoration","Imaris","Leica",
                             "Laserscanning","SP8","Balgrist Campus","OSD","SP8G","Zeiss980",
                             "VSD","account","data"]        (first 20 only)
GET /guides/15/tags      -> ["location-access","StellUSZ"]
```

- Tags are plain strings; no ids, no counts, in the responses.
- Tags are **not** in the guide payload, and the list item's `"tags": false` is useless. One
  extra request per guide is required.
- Tag matching case-sensitivity in `[guidelist]` is **unverified**; compare case-insensitively
  and report collisions.

---

## 7. Media download

- Images: public CloudFront URLs, `https://d3t0tbmlie281e.cloudfront.net/igi/zmb/<guid>.<size>`.
  The URLs are handed out to anonymous API callers and carry no signature or query string, so no
  auth should be needed (the binary download itself was not performed — **unverified**, but
  expected to work).
- The URL has no file extension. `original` -> `<guid>.full` is the full-resolution file.
  Determine the type from the HTTP `Content-Type` or from `encoding` in
  `GET /media/images/{id}` (`"jpeg"` seen).
- Size keys seen: `mini`, `thumbnail`, `140x105`, `200x150`, `standard`, `440x330`, `medium`,
  `large`, `huge`, `original`. `huge`/`large` are absent on smaller uploads.
- `GET /media/images/{id or guid}` adds `width`, `height`, `ratio`, `markup`, `markupState`,
  `exif`, `encoding`, `srcid`, `srcImageInfo` (section 3). Marker annotations are baked into the
  marked-up image's pixels; `srcid` points to the unannotated source image.
- Videos: `encodings[].url` is a direct S3 object URL
  (`https://dozuki-prod-us-east-1-guide-objects.s3.amazonaws.com/igo/video/zmb/<guid>_MP4_720.mp4`),
  unsigned in the anonymous response; whether the object is publicly readable is **unverified**.
  Only a transcoded rendition (label "480p", 720x480 for a 1280x720 source) is exposed; no URL
  for the uploaded original. Poster frame: `image.image.original`.
- Wiki text references images by numeric id (`[image|12345]`); resolve through
  `GET /media/images/{id}`.
- Attached documents (PDF etc., `documents[]` on guides/wikis/categories): none found, download
  path **unverified**.
- `GET /user/media/...` endpoints list the *logged-in user's* media library only; not a
  site-wide media listing.

---

## 8. Other things an exporter must know

### Users (author mapping)

- `GET /users` (doc): `limit` `[1,200]` default 20, `offset`, `order` (by userid),
  `joinedSince`. Items: `userid`, `username`, `unique_username`, `join_date`, `image`,
  `reputation`, `url`, `teams`, `privileges`, `enabled`, `banned`. Whether it works anonymously
  on this site is **unverified**.
- `GET /users/{userid}` (live, anonymous, trimmed):

```json
{
  "userid": 12,
  "username": "Joana Raquel Delgado Martins",
  "unique_username": "jrmartins",
  "login": "joana.delgadomartins@zmb.uzh.ch",
  "uid": "bd7af301-d807-f4ba-5aff-f024f2243b4c",
  "image": null,
  "teams": [1, 3],
  "ownedTeams": [ { "teamid": 1, "name": "ZMB Staff" } ],
  "reputation": 3830,
  "join_date": 1554793315,
  "privileges": ["Admin"],
  "langid": "en",
  "siteid": 4212,
  "sitename": "zmb"
}
```

- Also in the doc index: `GET /users/email/{email}`, `GET /users/sso/{sso_userid}`,
  `GET /users/search/{search}`, `GET /user` (current user, needs auth), `GET /teams`,
  `GET /teams/{teamid}`.
- Many guides are authored by a shared account (`userid` 26, `"z mbstaff"`), so per-person
  attribution is limited.
- Guide access control: `GET /guides/{guideid}/users` and `/guides/{guideid}/teams` (doc index)
  expose per-guide permissions; likely needed to understand which guides are restricted.

### Revisions / history

- Guides: `guide_revisionid` (use this) and deprecated `revisionid`; each step has its own
  `revisionid`. Wikis: `revisionid`. Edits must pass `?revisionid=` and get `409 Conflict` with
  the current resource if stale (doc) — irrelevant for a read-only export.
- No endpoint to list or fetch past revisions was found. Release/version records exist
  (`GET /guides/{guideid}/releases`, `GET /guides/releases`, `released=true` on guide fetch,
  `releaseTitle` such as `"v6.0"` on list items) but were not examined. **unverified.**
- Without `released=true` the guide endpoint presumably returns the current working revision,
  which may be newer than the released version users see. Decide which one to export.
- `modifiedSince` on `GET /guides` supports incremental re-runs.

### Language

- `langid` / `locale` are `"en"` everywhere seen. `langid` query parameter selects a
  translation (404 if none); `useSourceLang` forces the source language. Whether any ZMB
  content has translations is **unverified**.

### Errors

- Doc lists client errors 400, 401, 403, 404, 405, 409, 422. `GET /guides/999999` produced a
  client error (the tool did not expose status code or body). The JSON error body shape is not
  documented on the pages fetched; iFixit conventionally returns `{"message": "..."}`
  (**unverified**).
- A guide that exists but is not visible to the caller presumably returns 403 or 404
  (**unverified**) — an exporter should record these ids rather than abort.

### Misc

- JSON is the default; `?pretty` pretty-prints; some endpoints accept `type=XML`.
- "Make sure to version your API calls with 2.0" (doc).
- Slashes in JSON strings are escaped (`https:\/\/...`); any JSON parser handles this.
- Rate limiting: nothing documented, headers not inspected. **unverified.**
- `GET /search/{query}`: `limit` `[1,200]`, `offset`, `filter` =
  `guide,teardown,wiki,category,item,info,question`; returns `totalResults`, `moreResults`,
  `results[]`. No tag/category filter.
- Comments: `comments[]` on guides and steps, plus `GET /comments`; all empty on inspected
  guides.
- Dozuki-specific content types present in the API index but not examined: courses, quizzes
  (`attachedQuiz`), step forms / data capture (`GET /step_forms/guideid/{guideid}`), work logs,
  periodic review, workspaces, approval processes. Check with the admin whether any are in use.

### Suggested export sequence

1. Authenticate (section 1); keep the token out of logs.
2. `GET /guides?limit=200&offset=N&includePrivate=true` until `[]`; de-duplicate by `guideid`.
3. Per guide: `GET /guides/{id}?excludePrerequisiteSteps=true` and `GET /guides/{id}/tags`.
4. Categories: `GET /wikis/CATEGORY?display=hierarchy` (+ `includeStubs`),
   `GET /categories/all` paged; per title `GET /categories/{title}` and
   `GET /wikis/CATEGORY/{title}`.
5. Other namespaces: `GET /wikis/WIKI`, `/wikis/INFO`, `/wikis/ITEM` paged, then each page.
6. Collect image ids/guids from guides, wiki `image` fields and `[image|id]` tags; download
   `original`; optionally `GET /media/images/{id}` for dimensions, markup and `srcid`.
7. Videos: download `encodings[].url` and the poster image.
8. Users: `GET /users/{userid}` for each distinct author.

---

## Open questions for the site admin

1. Is the site SSO-only, or can a local admin account with email + password be used for
   `POST /user/token`? If SSO-only, how does Dozuki recommend obtaining an API token (support
   issued token, impersonation, other)?
2. What is the site's `X-App-Id`, and is it required for `POST /user/token` here?
3. How many guides exist in total, and how many are private, unpublished, archived or
   restricted to teams? (Anonymous listing shows about 260; some rows are hidden.) Should those
   be exported too?
4. Export the current working revision or the latest *released* version of each guide? Are
   release versions / approval processes in use?
5. Are the "... - hidden" categories purely an organisational trick (guides surfaced through
   tag-based `[guidelist]` widgets), so that the target structure should follow the tags and
   the visible category pages rather than the guides' own categories?
6. In `[guidelist|tags=...]`, can several tags be given, and is matching AND or OR,
   case-sensitive or not?
7. Are original video uploads retrievable anywhere (the API only exposes a 720x480 transcode),
   or do the facility's staff still have the source files?
8. Are attached documents (PDFs), embeds, quizzes, step forms / data capture, courses,
   comments, or translations used anywhere and in scope?
9. Is there any rate limit or preferred time window for a full crawl (roughly 1,000 API calls
   plus a few thousand media downloads)?
10. Author mapping: many guides belong to the shared "z mbstaff" account. Is per-person
    attribution wanted, and may user e-mail addresses from the API be stored in the target
    system?
