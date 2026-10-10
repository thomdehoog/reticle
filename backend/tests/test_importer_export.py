"""Phase one of the import: the export, against a stand-in for the vendor site.

Nothing here touches a network. The exporter makes real HTTP requests through
``httpx``, and a mock transport answers them with the payload shapes recorded
from the live API.
"""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.importer import ARCHIVE_FORMAT, TOOL_VERSION, cli, exporter
from app.importer.archive import Archive, ArchiveError, filename_title, sha256_file, title_filename
from app.importer.client import AuthenticationError, ClientError, DozukiClient, NotFound, api_base, path_segment, retry_after_seconds
from app.importer.exporter import Exporter, best_encoding, category_titles, encoding_extension, referenced_media, verify_archive

from .importer_site import API, CDN, EMAIL, GOOD_TOKEN, HOST, PASSWORD, SESSION_COOKIE, VIDEO_STORE, FakeSite, write_archive

BACKEND = Path(__file__).resolve().parent.parent
CREDENTIAL_HEADERS = {"authorization", "cookie", "x-app-id"}
LISTINGS = {"/categories/all", "/guides", "/wikis/CATEGORY", "/wikis/INFO", "/wikis/ITEM", "/wikis/WIKI"}


class Run:
    """One invocation of the command line, with everything it printed."""

    def __init__(self, site: FakeSite, out_dir: Path, *arguments: str, environ: dict[str, str] | None = None) -> None:
        self.lines: list[str] = []
        self.sleeps: list[float] = []
        self.status = cli.main(
            ["export", "--site", HOST, "--out", str(out_dir), "--delay", "0", *arguments],
            environ={} if environ is None else environ,
            transport=site.transport(),
            sleep=self.sleeps.append,
            resolve=site.resolve,
            out=self.lines.append,
        )
        self.text = "\n".join(self.lines)
        self.archive = Archive(out_dir)


@pytest.fixture()
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture()
def out_dir(tmp_path) -> Path:
    return tmp_path / "export"


def signed_in() -> dict[str, str]:
    return {"DOZUKI_TOKEN": GOOD_TOKEN}


def client_for(site: FakeSite, sleeps: list[float] | None = None, **options) -> DozukiClient:
    recorded = sleeps if sleeps is not None else []
    return DozukiClient(HOST, transport=site.transport(), sleep=recorded.append, **{"delay": 0, "resolve": site.resolve, **options})


# ---------------------------------------------------------------- a complete export


def test_a_signed_in_export_fetches_everything_and_exits_cleanly(site, out_dir):
    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    manifest = run.archive.manifest()
    assert manifest["counts"]["guide"] == {"ok": 4}
    assert manifest["counts"]["guide-tags"] == {"ok": 4}
    assert manifest["counts"]["image-file"] == {"ok": 17}
    assert manifest["counts"]["video-file"] == {"ok": 1}
    assert manifest["counts"]["user"] == {"ok": 3}
    assert manifest["counts"]["wiki"] == {"ok": 6, "absent": 5}, "five categories have no page of their own"
    assert "Nothing failed." in run.text
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]


def test_the_archive_holds_the_raw_responses(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    archive = Archive(out_dir)

    assert archive.read_json(Archive.guide(15)) == site.documents["/guides/15"]
    assert archive.read_json(Archive.guide_tags(15)) == ["location-access", "StellUSZ"]
    assert archive.read_json(Archive.wiki("CATEGORY", 23))["contents_raw"].startswith("== Leica Stellaris 5 inverse (USZ) ==")
    assert archive.read_json(Archive.image_meta(507))["markupState"]["annotations"]["data"][0]["shape"] == "arrow"
    assert archive.read_json(Archive.category_detail("Basic Guides"))["display_title"] == "Confocal Microscopy"
    assert archive.read_json("api/categories/hierarchy.json")["display_titles"]["Light Micrscopy"] == "Light Microscopy"
    assert archive.read_json(Archive.user(12))["login"] == "ada.example@zmb.example"
    assert archive.path("files/videos/137.mp4").read_bytes() == site.files[f"{VIDEO_STORE}/BJGvyPRLJAnukGuV_MP4_720.mp4"][0]


def test_the_manifest_describes_the_run(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    manifest = Archive(out_dir).manifest()

    assert manifest["tool"] == "reticle-importer" and manifest["tool_version"] == TOOL_VERSION
    assert manifest["format"] == ARCHIVE_FORMAT
    assert manifest["site"] == HOST and manifest["api_base"] == f"https://{HOST}/api/2.0"
    assert manifest["authenticated"] is True and manifest["include_private"] is True
    assert datetime.fromisoformat(manifest["finished_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))

    image = manifest["items"]["image-file:507"]
    assert image["status"] == "ok" and image["rendition"] == "original" and image["content_type"] == "image/jpeg"
    assert image["path"] == "files/images/507.jpg"
    assert image["sha256"] == sha256_file(out_dir / image["path"]) and image["bytes"] == (out_dir / image["path"]).stat().st_size
    assert manifest["items"]["video-file:137"]["encoding"] == "MP4_720"
    assert manifest["items"]["guide:15"] == {"kind": "guide", "status": "ok", "path": "api/guides/15/guide.json",
                                             "fetched_at": manifest["items"]["guide:15"]["fetched_at"], "bytes": manifest["items"]["guide:15"]["bytes"]}


def test_the_clean_source_of_every_marked_up_image_is_exported_too(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    archive = Archive(out_dir)

    for marked, clean in ((507, 477), (14438, 14435), (22069, 22066), (600, 599), (950, 949)):
        assert archive.read_json(Archive.image_meta(marked))["srcid"] == clean
        assert archive.read_json(Archive.image_meta(clean))["srcid"] is None
        assert archive.media_file("image", clean) is not None
    assert archive.media_file("image", 17613) is not None, "the video's poster frame"
    assert archive.media_file("image", 12099) is not None, "a category's picture"
    assert archive.media_file("image", 123456) is None


def test_a_holding_categorys_page_is_found_although_the_listing_omits_it(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    archive = Archive(out_dir)

    index = {entry["wikiid"]: entry for entry in archive.read_json(Archive.wiki_index("CATEGORY"))}
    assert index[41]["title"] == "LS - hidden guides" and index[41]["listed"] is False
    assert "[guidelist|tags=mesoSPIM]" in archive.read_json(Archive.wiki("CATEGORY", 41))["contents_raw"]


def test_full_guides_are_requested_without_inlined_prerequisite_steps(site, out_dir):
    Run(site, out_dir, environ=signed_in())

    requests = [request for request in site.requests if request.url.path == f"{API}/guides/15"]
    assert [dict(request.url.params) for request in requests] == [{"excludePrerequisiteSteps": "true"}]


# ---------------------------------------------------------------- credentials


def test_the_token_goes_to_the_api_host_and_nowhere_else(site, out_dir):
    Run(site, out_dir, environ={**signed_in(), "DOZUKI_APP_ID": "app-42"})

    api_requests = [request for request in site.requests if request.url.host == HOST]
    other_requests = [request for request in site.requests if request.url.host != HOST]
    signed = [request for request in api_requests if "Authorization" in request.headers]
    unsigned = [request for request in api_requests if "Authorization" not in request.headers]
    assert signed and other_requests
    assert all(request.headers["Authorization"] == f"api {GOOD_TOKEN}" and request.headers["X-App-Id"] == "app-42" for request in signed)
    assert {request.url.path.removeprefix(API) for request in unsigned} == {"/guides", "/wikis/CATEGORY", "/wikis/WIKI", "/wikis/INFO"}, (
        "the only API requests without the token are the listing passes that ask what an anonymous visitor sees"
    )
    assert all(not CREDENTIAL_HEADERS & set(request.headers) for request in unsigned + other_requests)
    assert {request.url.host for request in other_requests} == {"d3t0tbmlie281e.cloudfront.net", "dozuki-prod-us-east-1-guide-objects.s3.amazonaws.com"}


def test_email_and_password_are_exchanged_for_a_token(site, out_dir):
    site.app_id_required = "app-42"
    run = Run(site, out_dir, environ={"DOZUKI_EMAIL": EMAIL, "DOZUKI_PASSWORD": PASSWORD, "DOZUKI_APP_ID": "app-42"})

    assert run.status == 0, run.text
    assert site.paths("POST") == ["/user/token"]
    assert f"Signed in to {HOST} as {EMAIL}." in run.lines
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]


def test_credentials_never_reach_the_disk_or_the_console(site, out_dir):
    run = Run(site, out_dir, environ={"DOZUKI_EMAIL": EMAIL, "DOZUKI_PASSWORD": PASSWORD})

    secrets = (GOOD_TOKEN.encode(), PASSWORD.encode())
    for path in out_dir.rglob("*"):
        if path.is_file():
            payload = path.read_bytes()
            assert not any(secret in payload for secret in secrets), path
    assert GOOD_TOKEN not in run.text and PASSWORD not in run.text


def test_a_browser_session_cookie_can_stand_in_for_a_token(site, out_dir):
    run = Run(site, out_dir, environ={"DOZUKI_SESSION_COOKIE": SESSION_COOKIE})

    assert run.status == 0, run.text
    assert "Using the browser session cookie from DOZUKI_SESSION_COOKIE" in run.text
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]
    with_cookie = [request for request in site.requests if "Cookie" in request.headers]
    assert with_cookie and all(request.headers["Cookie"] == SESSION_COOKIE and request.url.host == HOST for request in with_cookie)
    without = [request for request in site.requests if request.url.host == HOST and "Cookie" not in request.headers]
    assert {request.url.path.removeprefix(API) for request in without} <= LISTINGS, "only the anonymous listing passes go without it"
    assert all("Cookie" not in request.headers for request in site.requests if request.url.host != HOST)
    assert not any(SESSION_COOKIE.encode() in path.read_bytes() for path in out_dir.rglob("*") if path.is_file())
    assert SESSION_COOKIE not in run.text


def test_an_expired_session_cookie_stops_the_run(site, out_dir):
    run = Run(site, out_dir, environ={"DOZUKI_SESSION_COOKIE": "session=stale"})

    assert run.status == 2 and "rejected the session cookie (HTTP 401)" in run.text


def test_a_refused_sign_in_stops_before_anything_is_fetched(site, out_dir):
    run = Run(site, out_dir, environ={"DOZUKI_EMAIL": EMAIL, "DOZUKI_PASSWORD": "wrong"})

    assert run.status == 2
    assert "Signing in failed (HTTP 401)" in run.text and "single sign-on" in run.text
    assert site.paths() == []


def test_a_sign_in_that_returns_no_token_is_an_error(site):
    site.fail("/user/token", httpx.Response(201, json={"userid": 1}), httpx.Response(201, content=b"<html>"))

    for _ in range(2):
        with client_for(site) as client, pytest.raises(AuthenticationError, match="no authToken"):
            client.login(EMAIL, PASSWORD)


def test_an_anonymous_export_warns_loudly_and_misses_private_guides(site, out_dir):
    run = Run(site, out_dir)

    assert run.status == 0, run.text
    assert "exporting ANONYMOUSLY" in run.text and "WILL BE MISSING" in run.text
    assert "NOTE: exported anonymously" in run.text
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422]
    assert run.archive.manifest()["authenticated"] is False
    assert all("includePrivate" not in request.url.params for request in site.requests)


def test_a_rejected_token_stops_the_run_and_keeps_what_was_fetched(site, out_dir):
    site.fail("/guides/27", httpx.Response(401, json={"message": "Token expired"}))
    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 2
    assert "STOPPED: The site rejected the API token (HTTP 401)" in run.text
    assert run.archive.exists(Archive.guide(15)) and not run.archive.exists(Archive.guide(27))
    assert run.archive.manifest()["finished_at"] is None

    resumed = Run(site, out_dir, environ=signed_in())
    assert resumed.status == 0, resumed.text
    assert resumed.archive.manifest()["finished_at"] is not None


def test_a_token_that_was_never_valid_is_reported_as_such(site, out_dir):
    run = Run(site, out_dir, environ={"DOZUKI_TOKEN": "not-the-token"})

    assert run.status == 2 and "rejected the API token" in run.text


def test_an_account_that_may_not_list_private_guides_falls_back_to_the_public_ones(site, out_dir):
    site.fail("/guides", httpx.Response(403, json={"message": "Admin only"}))
    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    assert "refused includePrivate" in run.text and "MISSING" in run.text
    assert run.archive.manifest()["include_private"] is False
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422]


# ---------------------------------------------------------------- paging


def test_paging_continues_past_a_short_page_until_an_empty_one(site, out_dir, monkeypatch):
    """The vendor applies the limit before hiding rows, so a short page is not the last."""
    monkeypatch.setattr(exporter, "PAGE_SIZE", 2)
    order = {15: 0, 430: 1, 27: 2, 422: 3}
    site.lists["/guides"].sort(key=lambda entry: order[entry["guideid"]])

    run = Run(site, out_dir)

    offsets = [request.url.params["offset"] for request in site.requests if request.url.path == f"{API}/guides"]
    assert offsets == ["0", "2", "4"], "page one held a single visible guide and was not taken for the end"
    assert all(request.url.params["limit"] == "2" for request in site.requests if request.url.path == f"{API}/guides")
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422]


def test_paging_asks_for_the_largest_page_the_api_allows(site, out_dir):
    Run(site, out_dir)

    assert {request.url.params["limit"] for request in site.requests if "limit" in request.url.params} == {"200"}


def test_a_listing_that_refuses_large_pages_is_read_in_smaller_ones(site, out_dir):
    """200 is documented for guides only; the wiki listings may allow less."""
    site.max_limit = {"/wikis/CATEGORY": 100, "/wikis/WIKI": 20}

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    limits = lambda path: [request.url.params["limit"] for request in site.requests if request.url.path == f"{API}{path}" and "limit" in request.url.params]
    assert limits("/wikis/CATEGORY") == ["200", "100", "100"] * 2, "once signed in, once anonymously"
    assert limits("/wikis/WIKI") == ["200", "100", "20", "20"] * 2
    assert "  /wikis/WIKI: a page of 100 was refused (GET /wikis/WIKI: HTTP 400); trying 20" in run.lines
    assert run.archive.manifest()["counts"]["wiki"]["ok"] == 6


def test_a_listing_that_refuses_every_page_size_is_a_failure(site, out_dir):
    site.max_limit = {"/wikis/WIKI": 5}

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 1
    assert run.archive.manifest()["items"]["wiki-index:WIKI"]["error"] == "GET /wikis/WIKI: HTTP 400"


def test_a_server_that_ignores_the_offset_cannot_spin_the_loop(site):
    def stuck(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"guideid": 1}, {"guideid": 1}, {"guideid": 2}])

    with DozukiClient(HOST, transport=httpx.MockTransport(stuck), delay=0) as client:
        collected = Exporter(client, Archive("unused"), log=lambda message: None).pages("/guides", {}, lambda entry: entry["guideid"])

    assert collected == [{"guideid": 1}, {"guideid": 2}]
    assert client.requests_made == 2


# ---------------------------------------------------------------- resuming


def test_a_second_run_skips_everything_already_on_disk(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    before = Archive(out_dir).manifest()
    site.requests.clear()

    again = Run(site, out_dir, environ=signed_in())

    assert again.status == 0, again.text
    assert set(site.paths()) == LISTINGS, "only the listings are read again: nothing on disk, and nothing the site said it does not have"
    assert all(request.url.host == HOST for request in site.requests), "no media file is downloaded twice"
    after = again.archive.manifest()
    assert after["items"]["image-file:507"] == before["items"]["image-file:507"]
    assert after["items"]["guide:15"]["fetched_at"] == before["items"]["guide:15"]["fetched_at"]
    assert after["started_at"] == before["started_at"]


def test_a_guide_that_changed_on_the_site_is_fetched_again(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    site.documents["/guides/27"]["title"] = "MesoSPIM - Part 1: Start-up (revised)"
    site.documents["/guides/27"]["guide_revisionid"] += 1
    site.lists["/guides"][1]["guide_revisionid"] += 1
    site.documents["/guides/27/tags"] = ["Lightsheet"]
    site.requests.clear()

    Run(site, out_dir, environ=signed_in())

    assert [path for path in site.paths() if path.startswith("/guides/")] == ["/guides/27", "/guides/27/tags"]
    assert Archive(out_dir).read_json(Archive.guide(27))["title"].endswith("(revised)")
    assert Archive(out_dir).read_json(Archive.guide_tags(27)) == ["Lightsheet"]


def test_refresh_fetches_every_response_again(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    site.requests.clear()

    Run(site, out_dir, "--refresh", environ=signed_in())

    assert "/guides/15" in site.paths() and "/media/images/507" in site.paths()
    assert all(request.url.host == HOST for request in site.requests), "media files with a matching size are still kept"


def test_a_failed_item_is_recorded_and_retried_on_the_next_run(site, out_dir):
    site.fail("/guides/27", *[httpx.Response(500)] * 3)
    site.fail(f"{CDN}/Guid000000000507.full", httpx.Response(404))

    first = Run(site, out_dir, "--retries", "2", environ=signed_in())

    assert first.status == 1
    assert "2 item(s) FAILED:" in first.text
    assert "  guide:27: GET /guides/27: HTTP 500 after 3 attempts" in first.lines
    assert "Run the same command again to retry them" in first.text
    failed = first.archive.manifest()["items"]
    assert failed["guide:27"] == {"kind": "guide", "status": "failed", "error": "GET /guides/27: HTTP 500 after 3 attempts"}
    assert failed["image-file:507"]["status"] == "failed" and failed["image-file:507"]["url"].endswith("Guid000000000507.full")
    assert first.archive.exists(Archive.guide(15)), "one bad guide does not stop the others"
    site.requests.clear()

    second = Run(site, out_dir, environ=signed_in())

    assert second.status == 0, second.text
    assert "/guides/27" in site.paths() and "/guides/15" not in site.paths()
    assert second.archive.manifest()["items"]["guide:27"]["status"] == "ok"
    assert second.archive.media_file("image", 507) is not None


def test_files_already_downloaded_are_adopted_when_the_manifest_is_lost(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    recorded = Archive(out_dir).manifest()["items"]["image-file:507"]["sha256"]
    (out_dir / "manifest.json").unlink()
    (out_dir / "files/images/507.download").write_bytes(b"left over from an interrupted download")
    site.requests.clear()

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    assert all(request.url.host == HOST for request in site.requests)
    adopted = run.archive.manifest()["items"]["image-file:507"]
    assert adopted["adopted"] is True and adopted["sha256"] == recorded and adopted["path"] == "files/images/507.jpg"


def test_a_truncated_media_file_is_downloaded_again(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    (out_dir / "files/videos/137.mp4").write_bytes(b"cut short")
    (out_dir / "files/images/900.png").unlink()
    site.requests.clear()

    Run(site, out_dir, "--refresh", environ=signed_in())

    assert sorted(request.url.path.rsplit("/", 1)[-1] for request in site.requests if request.url.host != HOST) == [
        "BJGvyPRLJAnukGuV_MP4_720.mp4", "Guid000000000900.full"
    ]
    assert verify_archive(Archive(out_dir))[0] == []


def test_guides_that_vanish_from_the_listing_keep_their_exported_copies(site, out_dir):
    Run(site, out_dir, environ=signed_in())

    run = Run(site, out_dir)  # anonymously this time: the private guide is no longer listed

    assert "1 guide(s) from an earlier run are no longer listed by the site" in run.text
    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]
    assert run.archive.exists(Archive.guide(430))


def test_an_unreachable_guide_list_falls_back_to_the_previous_one(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    site.fail("/guides", *[httpx.Response(500)] * 2)

    run = Run(site, out_dir, "--retries", "1", environ=signed_in())

    assert run.status == 1
    assert "continuing with the list from the previous run" in run.text
    assert run.archive.manifest()["items"]["guide-index"]["status"] == "failed"
    assert run.archive.manifest()["counts"]["guide"] == {"ok": 4}


def test_an_unreachable_guide_list_on_a_first_run_exports_no_guides(site, out_dir):
    site.fail("/guides", httpx.Response(403), httpx.Response(500))

    run = Run(site, out_dir, "--retries", "0", environ=signed_in())

    assert run.status == 1
    assert run.archive.manifest()["items"]["guide-index"]["error"] == "GET /guides: HTTP 500 after 1 attempts"
    assert "guide" not in run.archive.manifest()["counts"]


# ---------------------------------------------------------------- retries


def test_temporary_failures_are_retried_with_backoff_and_retry_after(site):
    site.fail("/guides/15", httpx.Response(503), httpx.Response(429, headers={"Retry-After": "7"}), httpx.ReadTimeout("slow"))
    sleeps: list[float] = []
    notes: list[str] = []

    with client_for(site, sleeps, log=notes.append) as client:
        document, raw = client.get("/guides/15")

    assert document["guideid"] == 15 and json.loads(raw) == document
    assert sleeps == [1.0, 7.0, 4.0], "1s, then what the server asked for, then 2^2"
    assert notes == [
        "  GET /guides/15: HTTP 503; retrying in 1s",
        "  GET /guides/15: HTTP 429; retrying in 7s",
        "  GET /guides/15: ReadTimeout; retrying in 4s",
    ]
    assert client.requests_made == 4


def test_retries_give_up_eventually(site):
    site.fail("/guides/15", *[httpx.ConnectError("down")] * 3)
    sleeps: list[float] = []

    with client_for(site, sleeps, retries=2) as client, pytest.raises(ClientError, match="ConnectError after 3 attempts") as failure:
        client.get("/guides/15")

    assert sleeps == [1.0, 2.0] and failure.value.status is None


def test_the_pause_between_requests_is_configurable(site):
    sleeps: list[float] = []

    with client_for(site, sleeps, delay=0.5) as client:
        client.get("/guides/15")
        client.get("/guides/15/tags")
        client.get("/guides/27/tags")

    assert sleeps == [0.5, 0.5], "a pause before every request but the first"


def test_client_errors_are_not_retried(site):
    site.fail("/guides/15", httpx.Response(400))
    sleeps: list[float] = []

    with client_for(site, sleeps) as client:
        with pytest.raises(ClientError, match="HTTP 400") as failure:
            client.get("/guides/15")
        with pytest.raises(NotFound, match="not found or not visible"):
            client.get("/guides/99999")
        with pytest.raises(NotFound, match="not visible without signing in"):
            client.get("/guides", {"includePrivate": "true"})

    assert failure.value.status == 400 and not isinstance(failure.value, NotFound)
    assert sleeps == []


def test_a_response_that_is_not_json_is_an_error(site):
    site.fail("/guides/15", httpx.Response(200, content=b"<html>Maintenance</html>"))

    with client_for(site) as client, pytest.raises(ClientError, match="not JSON"):
        client.get("/guides/15")


def test_downloads_are_retried_and_leave_no_partial_file(site, tmp_path):
    url = f"{CDN}/Guid000000000900.full"
    site.fail(url, httpx.Response(503, headers={"Retry-After": "3"}), httpx.ReadError("reset"))
    sleeps: list[float] = []

    with client_for(site, sleeps) as client:
        result = client.download(url, tmp_path / "deep" / "900.download")

    assert result.path.read_bytes() == site.files[url][0]
    assert result.sha256 == sha256_file(result.path) and result.size == len(site.files[url][0])
    assert result.content_type == "image/png"
    assert sleeps == [3.0, 2.0]
    assert sorted(path.name for path in (tmp_path / "deep").iterdir()) == ["900.download"]


def test_a_download_that_keeps_failing_gives_up_cleanly(site, tmp_path):
    url = f"{CDN}/Guid000000000900.full"
    site.fail(url, *[httpx.Response(502)] * 2)

    with client_for(site, retries=1) as client:
        with pytest.raises(ClientError, match="HTTP 502 after 2 attempts"):
            client.download(url, tmp_path / "900.download")
        with pytest.raises(NotFound):
            client.download(f"{CDN}/nothing.full", tmp_path / "nothing.download")

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", 7.0), (" 2.5 ", 2.5), ("-3", 0.0), (None, None), ("", None), ("soon", None), ("Sat, 10 Oct 2026 12:00:30 GMT", 30.0), ("Sat, 10 Oct 2026 11:00:00 GMT", 0.0), ("10 Oct 2026 12:00:10", 10.0)],
)
def test_retry_after_in_both_of_its_forms(header, expected):
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)

    assert retry_after_seconds(header, lambda: now) == expected


def test_retry_after_as_a_date_uses_the_real_clock_by_default():
    assert retry_after_seconds("Sat, 10 Oct 2020 12:00:30 GMT") == 0.0


def test_a_very_long_retry_after_is_capped(site):
    site.fail("/guides/15", httpx.Response(429, headers={"Retry-After": "86400"}))
    sleeps: list[float] = []

    with client_for(site, sleeps) as client:
        client.get("/guides/15")

    assert sleeps == [600.0]


def test_a_download_waits_its_turn_like_any_other_request(site, tmp_path):
    sleeps: list[float] = []

    with client_for(site, sleeps, delay=0.5) as client:
        client.get("/guides/15/tags")
        client.download(f"{CDN}/Guid000000000900.full", tmp_path / "900.download")

    assert sleeps == [0.5]


def test_a_refusal_from_a_media_host_is_not_mistaken_for_a_rejected_token(site, out_dir):
    site.fail(f"{CDN}/Guid000000000507.full", httpx.Response(401))

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 1, "the run goes on; one file is missing"
    assert run.archive.manifest()["items"]["image-file:507"]["error"] == "download Guid000000000507.full: not visible without signing in (HTTP 401)"


def test_a_media_file_on_the_api_host_itself_is_still_downloaded_without_credentials(site, out_dir):
    site.documents["/media/images/900"]["image"]["original"] = f"https://{HOST}{API}/blob/900"
    site.fail("/blob/900", httpx.Response(401))

    run = Run(site, out_dir, environ={**signed_in(), "DOZUKI_APP_ID": "app-42"})

    assert run.status == 1, "a file is missing; the token was never shown to that URL, so it was not rejected either"
    assert run.archive.manifest()["items"]["image-file:900"]["error"] == "download 900: not visible without signing in (HTTP 401)"
    (download,) = [request for request in site.requests if request.url.path == f"{API}/blob/900"]
    assert not CREDENTIAL_HEADERS & set(download.headers)


@pytest.mark.parametrize("path", ["/categories/all", "/wikis/WIKI"])
def test_a_token_rejected_part_way_through_a_listing_stops_the_run(site, out_dir, path):
    site.fail(path, httpx.Response(401))

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 2 and "rejected the API token" in run.text


def test_a_token_rejected_while_falling_back_to_public_guides_stops_the_run(site, out_dir):
    site.fail("/guides", httpx.Response(403), httpx.Response(401))

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 2 and "rejected the API token" in run.text


# ---------------------------------------------------------------- odd payloads


def test_progress_is_reported_during_a_long_run(site, out_dir, monkeypatch):
    monkeypatch.setattr(exporter, "GUIDE_PROGRESS_EVERY", 2)
    monkeypatch.setattr(exporter, "IMAGE_PROGRESS_EVERY", 5)

    run = Run(site, out_dir, environ=signed_in())

    assert "  guide 2 of 4" in run.lines and "  guide 4 of 4" in run.lines
    assert any(line.startswith("  image 5 of ") for line in run.lines)


def test_a_listing_longer_than_the_page_ceiling_is_cut_off(site, out_dir, monkeypatch):
    monkeypatch.setattr(exporter, "PAGE_SIZE", 1)
    monkeypatch.setattr(exporter, "MAX_PAGES", 2)

    run = Run(site, out_dir, environ=signed_in())

    assert [entry["guideid"] for entry in run.archive.read_json(Archive.guide_index())] == [15, 27]


def test_a_response_damaged_on_disk_is_fetched_again(site, out_dir):
    Run(site, out_dir, environ=signed_in())
    (out_dir / Archive.guide_tags(15)).write_text("[ truncated")
    site.requests.clear()

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0 and "/guides/15/tags" in site.paths()
    assert run.archive.read_json(Archive.guide_tags(15)) == ["location-access", "StellUSZ"]


def test_category_endpoints_that_answer_in_unexpected_shapes_are_tolerated(site, out_dir):
    site.fail("/wikis/CATEGORY", httpx.Response(404))  # the hierarchy call comes first
    site.lists["/categories/all"].insert(0, 12345)
    site.documents["/categories/IT"] = []

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    items = run.archive.manifest()["items"]
    assert items["category-hierarchy"]["status"] == "absent"
    assert items["category:Basic Guides"]["status"] == "ok"
    assert run.archive.read_json(Archive.category_detail("IT")) == []


def test_an_image_without_an_original_falls_back_to_the_largest_rendition(site, out_dir):
    record = site.documents["/media/images/901"]["image"]
    site.files[record["large"]] = site.files.pop(record["original"])
    del record["original"]

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 0, run.text
    assert "Image 901 has no original rendition; kept the “large” one." in run.text
    assert run.archive.manifest()["items"]["image-file:901"]["rendition"] == "large"
    assert "Image 901 has no original rendition" in run.archive.manifest()["warnings"][0]


def test_media_with_nothing_to_download_is_a_recorded_failure(site, out_dir):
    site.documents["/media/images/902"]["image"] = {"id": 902, "guid": "Guid000000000902"}
    for step in site.documents["/guides/27"]["steps"]:
        if step["media"]["type"] == "image":
            step["media"]["data"] = [{"id": image["id"], "guid": image["guid"]} if image["id"] == 902 else image for image in step["media"]["data"]]
    site.documents["/media/videos/137"]["encodings"] = []
    site.documents["/guides/27"]["steps"][0]["media"]["data"]["encodings"] = []

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 1
    items = run.archive.manifest()["items"]
    assert items["image-file:902"]["error"] == "no download URL in the image metadata"
    assert items["video-file:137"]["error"] == "the video offers no encoding to download"


def test_an_image_whose_metadata_is_unavailable_is_still_downloaded_from_the_guides_own_url(site, out_dir):
    del site.documents["/media/images/903"]
    site.files[site.images[903]["original"]] = (site.files[site.images[903]["original"]][0], "application/octet-stream")

    run = Run(site, out_dir, environ=signed_in())

    assert run.status == 1
    items = run.archive.manifest()["items"]
    assert items["image-meta:903"]["status"] == "failed"
    assert items["image-file:903"]["status"] == "ok" and items["image-file:903"]["path"] == "files/images/903.png", "named by what its first bytes are"
    assert items["image-file:903"]["content_type"] == "image/png" and items["image-file:903"]["declared_content_type"] == "application/octet-stream"


def test_image_ids_named_only_in_wiki_text_are_resolved_through_the_metadata(site, out_dir):
    site.documents["/wikis/WIKI/Strategy to Run a Full Multiplex SeqIF Without Prior Optimization"]["contents_raw"] += "\n[image|12099|size=small]\n[image|77777]\n"
    for title in ("Basic Guides",):
        site.documents[f"/wikis/CATEGORY/{title}"]["image"] = None
        site.documents[f"/categories/{title}"]["image"] = None
    site.lists["/wikis/CATEGORY"][2]["image"] = None

    run = Run(site, out_dir, environ=signed_in())

    items = run.archive.manifest()["items"]
    assert items["image-file:12099"]["status"] == "ok"
    assert items["image-meta:77777"]["status"] == "failed" and items["image-file:77777"]["error"] == "no download URL in the image metadata"


def test_a_missing_core_wiki_listing_is_a_failure_and_an_unused_namespace_is_not(site, out_dir):
    site.fail("/wikis/WIKI", *[httpx.Response(500)] * 2)

    run = Run(site, out_dir, "--retries", "1", "--namespaces", "wiki,team", environ=signed_in())

    items = run.archive.manifest()["items"]
    assert run.status == 1
    assert items["wiki-index:WIKI"]["status"] == "failed"
    assert items["wiki-index:TEAM"]["status"] == "absent"
    assert run.archive.manifest()["namespaces"] == ["WIKI", "TEAM"]


def test_a_category_list_that_cannot_be_fetched_is_recorded(site, out_dir):
    site.fail("/categories/all", *[httpx.Response(500)] * 2)
    site.fail("/categories", httpx.Response(404))

    run = Run(site, out_dir, "--retries", "1", environ=signed_in())

    items = run.archive.manifest()["items"]
    assert items["category-all"]["status"] == "failed"
    assert items["category-tree"]["status"] == "failed"
    assert items["category:Basic Guides"]["status"] == "ok", "categories are still found through the guides and the hierarchy"


def test_helpers_for_the_shapes_the_api_returns():
    assert category_titles({"A": {"B": {}, "C": []}, "D": None}) == [("A", None), ("B", "A"), ("C", "A"), ("D", None)]
    assert category_titles([]) == [] and category_titles(None) == []

    images, videos = referenced_media({
        "image": {"id": 5, "guid": "g5"},
        "author": {"image": {"id": 6, "guid": "avatar"}},
        "placeholder": {"standard": "https://example.org/none.jpg"},
        "default_avatar": {"id": -32, "guid": "default"},
        "flag": {"id": True, "guid": "bool"},
        "contents_raw": "[image|7] and [image|5]",
        "steps": [{"media": {"type": "video", "data": {"videoid": 9, "encodings": [], "image": {"image": {"id": 8, "guid": "g8"}}}}}],
    })
    assert sorted(images) == [5, 7, 8] and images[7] == {} and sorted(videos) == [9]


def test_the_best_video_encoding_is_the_largest_one_a_browser_can_play():
    encodings = [
        {"column": "OGG_1080", "width": 1920, "height": 1080, "mime": "video/ogg", "url": "https://v.example/a.ogv"},
        {"column": "MP4_720", "width": 720, "height": 480, "mime": "video/mp4", "url": "https://v.example/a.mp4"},
        {"column": "WEBM_HD", "width": 1280, "height": 720, "format": "webm", "url": "https://v.example/a.webm"},
        {"column": "NO_URL", "width": 4000, "height": 4000, "mime": "video/mp4"},
        "junk",
    ]

    assert best_encoding({"encodings": encodings})["column"] == "WEBM_HD"
    assert best_encoding({"encodings": encodings[:1]})["column"] == "OGG_1080"
    assert best_encoding({"encodings": []}) is None and best_encoding({}) is None
    assert encoding_extension({"mime": "video/mp4; codecs=avc1"}) == "mp4"
    assert encoding_extension({"format": "MOV"}) == "mov"
    assert encoding_extension({"url": "https://v.example/clip.M4V?x=1"}) == "m4v"
    assert encoding_extension({"url": "https://v.example/clip"}) == "bin"


def test_small_helpers():
    assert api_base("zmb.dozuki.com") == "https://zmb.dozuki.com/api/2.0"
    assert api_base(" http://localhost:8080/ ") == "http://localhost:8080/api/2.0"
    with pytest.raises(ValueError, match="not a site address"):
        api_base("https://")
    assert path_segment("Basic Guides/α & β") == "Basic%20Guides%2F%CE%B1%20%26%20%CE%B2"
    for title in ("Basic Guides", "a/b", "v2.0 notes", "..", "Ünïcode ✓", ""):
        name = title_filename(title)
        assert "/" not in name and "." not in name and name
        assert filename_title(name) == title


# ---------------------------------------------------------------- verification


@pytest.fixture()
def exported(tmp_path) -> Archive:
    write_archive(tmp_path / "archive")
    return Archive(tmp_path / "archive")


def verify(archive: Archive) -> tuple[int, str]:
    lines: list[str] = []
    status = cli.main(["verify", "--archive", str(archive.root)], out=lines.append)
    return status, "\n".join(lines)


def test_a_complete_archive_verifies(exported):
    status, text = verify(exported)

    assert status == 0
    assert "4 guides, 6 pages, 16 image and 1 video references, 18 file checksums" in text
    assert "The archive is complete" in text


def test_verification_is_also_reachable_as_a_flag_of_export(exported):
    lines: list[str] = []

    assert cli.main(["export", "--verify", "--out", str(exported.root)], out=lines.append) == 0
    assert "The archive is complete" in lines[-1]


def test_verification_finds_missing_and_damaged_files(exported):
    exported.path("files/images/477.jpg").unlink()
    exported.path("files/images/900.png").write_bytes(b"corrupted in transit")
    exported.path("files/videos/137.mp4").unlink()
    exported.path(Archive.guide(27)).write_text("{ not json")
    exported.path(Archive.guide_tags(15)).unlink()
    exported.path(Archive.image_meta(507)).unlink()
    exported.path(Archive.wiki("WIKI", 108)).unlink()

    status, text = verify(exported)

    assert status == 1
    for expected in (
        "image-file:477: file files/images/477.jpg is missing",
        "image-file:900: files/images/900.png does not match its recorded checksum",
        "video-file:137: file files/videos/137.mp4 is missing",
        "guide:27: api/guides/27/guide.json is not readable JSON",
        "guide 27: the guide itself is missing or unreadable",
        "guide 15: its tags are missing",
        "guide 15: image 507 has no metadata (markers cannot be imported)",
        "image-meta:507: file api/media/images/507.json is missing",
        "WIKI page “Strategy to Run a Full Multiplex SeqIF Without Prior Optimization”: missing or unreadable",
    ):
        assert expected in text, expected


def test_verification_checks_the_clean_source_of_marked_up_images(exported):
    exported.path("files/images/14435.png").unlink()

    status, text = verify(exported)

    assert status == 1
    assert "guide 15: clean source 14435 of marked-up image 14438 has no downloaded file" in text


def test_verification_notices_media_the_manifest_never_recorded(exported):
    manifest = exported.manifest()
    del manifest["items"]["image-file:900"]
    del manifest["items"]["video-file:137"]
    exported.write_json("manifest.json", manifest)

    status, text = verify(exported)

    assert status == 1
    assert "guide 15: image 900 has no downloaded file" in text
    assert "guide 27: video 137 has no downloaded file" in text


def test_verification_reports_export_failures_and_unfinished_runs(tmp_path):
    site = FakeSite()
    site.fail("/guides/27", httpx.Response(404))
    write_archive(tmp_path / "archive", site)
    archive = Archive(tmp_path / "archive")
    manifest = archive.manifest()
    manifest["finished_at"] = None
    archive.write_json("manifest.json", manifest)
    archive.path(Archive.guide_index()).unlink()

    status, text = verify(archive)

    assert status == 1
    assert "The export did not run to completion" in text
    assert "guide:27: failed during export — GET /guides/27: not found or not visible to this account (HTTP 404)" in text
    assert "The guide index (api/guides/index.json) is missing or unreadable." in text


def test_a_directory_that_is_not_an_archive_is_refused(tmp_path):
    status, text = verify(Archive(tmp_path))

    assert status == 1 and "has no readable manifest.json" in text
    (tmp_path / "manifest.json").write_text('{"items": []}')
    with pytest.raises(ArchiveError):
        Archive(tmp_path).manifest()


# ---------------------------------------------------------------- the command line


def test_export_needs_a_site(tmp_path):
    lines: list[str] = []

    assert cli.main(["export", "--out", str(tmp_path)], environ={}, out=lines.append) == 2
    assert lines == ["export needs --site, for example --site zmb.dozuki.com"]
    assert cli.main(["export", "--site", "https://", "--out", str(tmp_path)], environ={}, out=lines.append) == 2
    assert "not a site address" in lines[-1]


def test_an_empty_namespace_list_is_refused(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["export", "--site", HOST, "--out", str(tmp_path), "--namespaces", " , "], environ={})

    assert "give at least one namespace" in capsys.readouterr().err


def test_quiet_keeps_warnings_failures_and_the_summary(site, out_dir):
    site.fail("/guides/27", httpx.Response(404))
    run = Run(site, out_dir, "--quiet", environ=signed_in())

    assert run.status == 1
    assert "Listing guides…" not in run.text
    assert any(line.startswith("  FAILED guide:27") for line in run.lines)
    assert f"Export of {HOST} written to {out_dir}" in run.text


def test_a_run_that_cannot_reach_the_site_at_all_says_so(out_dir):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    lines: list[str] = []
    status = cli.main(
        ["export", "--site", HOST, "--out", str(out_dir), "--retries", "0"],
        environ={"DOZUKI_EMAIL": EMAIL, "DOZUKI_PASSWORD": PASSWORD},
        transport=httpx.MockTransport(refuse),
        out=lines.append,
    )

    assert status == 2
    assert lines[-1] == "STOPPED: sign-in: ConnectError after 1 attempts"


def test_the_module_runs_as_a_command(tmp_path, monkeypatch, capsys):
    write_archive(tmp_path / "archive")
    monkeypatch.setattr(sys, "argv", ["app.importer", "verify", "--archive", str(tmp_path / "archive")])

    with pytest.raises(SystemExit) as finished:
        runpy.run_module("app.importer", run_name="__main__")

    assert finished.value.code == 0
    assert "The archive is complete" in capsys.readouterr().out


def test_export_and_verify_need_no_reticle_configuration():
    """They must run on any machine, today — before a Reticle server exists."""
    script = (
        "import sys; import app.importer.cli; "
        "loaded = [name for name in ('app.db', 'app.settings', 'app.models', 'app.importer.loader') if name in sys.modules]; "
        "print(loaded)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, env={"PATH": "", "RETICLE_ENV_FILE": ""}
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_importing_the_entry_module_does_nothing():
    import importlib

    module = importlib.import_module("app.importer.__main__")

    assert module.main is cli.main
