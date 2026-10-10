"""What the importer refuses, and what it remembers between export runs.

The vendor's API responses, the URLs inside them and the archive directory are
all input from somewhere else. These tests feed the export hostile ids, titles,
manifests, redirects and media hosts, and check that nothing is written or read
outside the archive, that credentials reach the API host only, and that a
download cannot be pointed at the facility's own network. The second half
covers the export's memory: what the site showed anonymously, which items it
did not have, and images whose markers changed.

No network: the vendor site, its media hosts and the name server are stand-ins.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from PIL import ImageDraw

from app.importer import cli
from app.importer.archive import Archive, ArchiveError, filename_title, is_safe_id, safe_id, safe_namespace, title_filename
from app.importer.client import ClientError, DozukiClient, UnsafeAddress, is_public_address, resolve_host, sniff_content_type
from app.importer.exporter import Exporter, capture_report, captures, parse_instant, verify_archive

from .importer_site import API, CDN, GOOD_TOKEN, HOST, SESSION_COOKIE, VIDEO_STORE, FakeSite, encode, photo, write_archive

CREDENTIAL_HEADERS = {"authorization", "cookie", "x-app-id"}
PICTURE = f"{CDN}/Guid000000000900.full"


def export(site: FakeSite, out_dir: Path, *arguments: str, environ: dict[str, str] | None = None):
    lines: list[str] = []
    status = cli.main(
        ["export", "--site", HOST, "--out", str(out_dir), "--delay", "0", *arguments],
        environ={"DOZUKI_TOKEN": GOOD_TOKEN} if environ is None else environ,
        transport=site.transport(), sleep=lambda seconds: None, resolve=site.resolve, out=lines.append,
    )
    return status, "\n".join(lines), Archive(out_dir)


def client_for(site: FakeSite, **options) -> DozukiClient:
    return DozukiClient(HOST, transport=site.transport(), sleep=lambda seconds: None, **{"delay": 0, "resolve": site.resolve, **options})


def everything_under(directory: Path) -> set[str]:
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*")}


@pytest.fixture()
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture()
def out_dir(tmp_path) -> Path:
    return tmp_path / "sandbox" / "export"


# ---------------------------------------------------------------- ids and titles from the vendor


@pytest.mark.parametrize("value", ["../../x", "15/../../../etc/passwd", "/etc/passwd", "15.json", "", " 15", "１５", "-3", "0", 0, -1, 1.5, True, None, [15], "9" * 30, 10**30])
def test_an_id_that_is_not_a_whole_number_is_refused(value):
    assert not is_safe_id(value)
    with pytest.raises(ArchiveError, match="not a usable id"):
        safe_id(value)
    for build in (Archive.guide, Archive.guide_tags, Archive.image_meta, Archive.video_meta, Archive.user):
        with pytest.raises(ArchiveError):
            build(value)
    with pytest.raises(ArchiveError):
        Archive.wiki("WIKI", value)
    with pytest.raises(ArchiveError):
        Archive.wiki_tags("WIKI", value)


def test_whole_number_ids_are_accepted_as_numbers_or_digit_strings():
    assert [safe_id(value) for value in (7, "7", "007", 486)] == [7, 7, 7, 486]
    assert Archive.guide("007") == "api/guides/7/guide.json"
    assert Archive.wiki("CATEGORY", 23) == "api/wikis/CATEGORY/23.json"


@pytest.mark.parametrize("namespace", ["../x", "wiki", "WIKI/..", "", "W" * 40, "CATEGORY\n", 7, None])
def test_a_namespace_that_is_not_a_plain_word_is_refused(namespace):
    with pytest.raises(ArchiveError, match="not a usable wiki namespace"):
        safe_namespace(namespace)
    with pytest.raises(ArchiveError):
        Archive.wiki_index(namespace)
    with pytest.raises(ArchiveError):
        Archive.wiki(namespace, 1)


def test_the_command_line_refuses_a_namespace_that_would_be_a_path(tmp_path, capsys):
    for command in (["export", "--site", HOST, "--out", str(tmp_path)], ["load", "--archive", str(tmp_path)]):
        with pytest.raises(SystemExit):
            cli.main([*command, "--namespaces", "WIKI,../../etc"], environ={})
        assert "is not a usable wiki namespace; namespaces are plain words" in capsys.readouterr().err
    with pytest.raises(ArchiveError):
        Exporter(None, Archive(tmp_path), namespaces=("../x",))


@pytest.mark.parametrize("title", ["../../evil", "..", ".", "a/b", "/etc/passwd", "C:\\Windows", "x\x00y", "dot.dot", "ä ö ü", "T" * 400, "é" * 200])
def test_any_title_becomes_one_harmless_file_name(title):
    name = title_filename(title)

    assert name and len(name) <= 180 and name not in {".", ".."}
    assert not set(name) & set("/\\.\x00:") and name.isascii()
    if len(title) < 40:
        assert filename_title(name) == title.replace("\x00", "")
    assert Archive.category_detail(title).startswith("api/categories/detail/") and Archive.category_detail(title).count("/") == 3


def test_long_titles_that_differ_only_at_the_end_get_different_file_names():
    assert title_filename("T" * 400 + "a") != title_filename("T" * 400 + "b")


@pytest.mark.parametrize(
    "relative",
    ["/etc/passwd", "../outside.json", "api/../../outside.json", "api/guides/../../../x", "./manifest.json", "api//guides", "api/guides/", "",
     "C:/Windows/x", "api\\guides\\15", "api/gu\x00ides", "..", ".", None, 7],
)
def test_no_path_leads_out_of_the_archive(tmp_path, relative):
    archive = Archive(tmp_path)

    with pytest.raises(ArchiveError, match="not a path inside the archive"):
        archive.path(relative)
    assert archive.exists(relative) is False
    assert archive.read_json(relative, "nothing") == "nothing"
    with pytest.raises(ArchiveError):
        archive.write_json(relative, {"x": 1})
    with pytest.raises(ArchiveError):
        archive.write_raw(relative, b"x")


def test_symbolic_links_inside_the_archive_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text('{"secret": true}')
    root = tmp_path / "archive"
    (root / "api").mkdir(parents=True)
    (root / "api" / "leak.json").symlink_to(outside / "secret.json")
    (root / "api" / "guides").symlink_to(outside, target_is_directory=True)
    archive = Archive(root)

    for relative in ("api/leak.json", "api/guides/secret.json", "api/guides/15/guide.json"):
        with pytest.raises(ArchiveError, match="symbolic link"):
            archive.path(relative)
        assert archive.read_json(relative) is None and not archive.exists(relative)
    with pytest.raises(ArchiveError):
        archive.write_json("api/guides/15/guide.json", {})
    assert sorted(path.name for path in outside.iterdir()) == ["secret.json"], "nothing was written through the link"

    linked_root = tmp_path / "link-to-archive"
    linked_root.symlink_to(root, target_is_directory=True)
    Archive(linked_root).write_json("api/ok.json", {"fine": True})
    assert Archive(linked_root).read_json("api/ok.json") == {"fine": True}, "the archive directory itself may be a link"


def test_hostile_ids_in_the_listings_are_ignored_and_nothing_leaves_the_archive(site, out_dir):
    hostile = ["../../x", "15/../../../../pwned", "/tmp/pwned", "15/tags", True, -4, 2.5, {"a": 1}]
    for value in hostile:
        site.lists["/guides"].append({"guideid": value, "title": "Hostile", "category": "IT", "public": True})
        site.lists["/wikis/WIKI"].append({"wikiid": value, "title": "Hostile page", "namespace": "WIKI"})
    site.lists["/wikis/WIKI"] += [{"wikiid": 77, "title": ""}, "junk", {"title": "No id at all"}]
    site.lists["/guides"] += ["junk", {"guideid": None}]
    before = everything_under(out_dir.parent)

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert "8 guide listing entries with an id that is not a whole number were ignored." in text
    assert "8 WIKI page listing entries with an id that is not a whole number were ignored." in text
    assert [entry["guideid"] for entry in archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]
    assert [entry["wikiid"] for entry in archive.read_json(Archive.wiki_index("WIKI"))] == [108]
    assert everything_under(out_dir.parent) - before == {"export"} | {f"export/{name}" for name in everything_under(out_dir)}
    assert not any("pwned" in name or ".." in name for name in everything_under(out_dir))
    assert not any(".." in request.url.path or "pwned" in request.url.path for request in site.requests)
    assert sorted(path.name for path in (out_dir / "api/guides").iterdir()) == ["15", "27", "422", "430", "index.json"]


def test_numeric_ids_sent_as_strings_are_normalised(site, out_dir):
    site.lists["/guides"][0]["guideid"] = "15"
    site.lists["/wikis/WIKI"][0]["wikiid"] = "108"

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert [entry["guideid"] for entry in archive.read_json(Archive.guide_index())] == [15, 27, 422, 430]
    assert archive.read_json(Archive.wiki("WIKI", 108))["wikiid"] == 108
    assert archive.read_json(Archive.guide_index())[0]["anonymousVisible"] is True


def test_hostile_titles_stay_inside_the_archive_and_are_quoted_in_requests(site, out_dir):
    evil = "../../../evil"
    long_title = "L" * 300
    site.lists["/categories/all"] += [evil, "a/b", long_title]
    site.documents[f"/categories/{evil}"] = {"wikiid": 900, "wiki_title": evil, "display_title": "Evil", "children": ["..", "x/../../y"]}
    site.documents[f"/categories/{long_title}"] = {"wikiid": 901, "wiki_title": long_title, "display_title": "Long", "children": []}
    site.lists["/wikis/WIKI"].append({"wikiid": 300, "title": "../../../etc/passwd", "revisionid": 1})
    site.documents["/wikis/WIKI/../../../etc/passwd"] = {"wikiid": 300, "title": "../../../etc/passwd", "contents_raw": "x", "revisionid": 1}
    site.documents["/wikis/CATEGORY/" + evil] = {"wikiid": 900, "title": evil, "contents_raw": "evil page", "revisionid": 1}
    before = everything_under(out_dir.parent)

    status, text, archive = export(site, out_dir)

    assert everything_under(out_dir.parent) - before == {"export"} | {f"export/{name}" for name in everything_under(out_dir)}
    assert archive.read_json(Archive.category_detail(evil))["display_title"] == "Evil"
    assert archive.read_json(Archive.category_detail(long_title))["display_title"] == "Long"
    assert archive.read_json(Archive.wiki("WIKI", 300))["contents_raw"] == "x"
    assert archive.read_json(Archive.wiki("CATEGORY", 900))["contents_raw"] == "evil page"
    names = sorted(path.name for path in (out_dir / "api/categories/detail").iterdir())
    assert "%2E%2E%2F%2E%2E%2F%2E%2E%2Fevil.json" in names and all("/" not in name and not name.startswith(".") for name in names)
    raw_paths = [request.url.raw_path.decode() for request in site.requests]
    assert f"{API}/categories/..%2F..%2F..%2Fevil" in raw_paths and f"{API}/wikis/WIKI/..%2F..%2F..%2Fetc%2Fpasswd" in raw_paths
    assert not any("/../" in path for path in raw_paths)


def test_a_response_cannot_be_written_through_a_link_planted_in_the_archive(site, out_dir, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (out_dir / "api/guides").mkdir(parents=True)
    (out_dir / "api/guides/15").symlink_to(target, target_is_directory=True)
    (out_dir / "files").mkdir()
    (out_dir / "files/images").symlink_to(target, target_is_directory=True)

    status, text, archive = export(site, out_dir)

    assert status == 1
    assert list(target.iterdir()) == [], "nothing went through either link"
    items = archive.manifest()["items"]
    assert items["guide:15"]["status"] == "failed" and "symbolic link" in items["guide:15"]["error"]
    assert items["image-file:900"]["status"] == "failed" and "symbolic link" in items["image-file:900"]["error"]
    assert items["guide:27"]["status"] == "ok"


# ---------------------------------------------------------------- a doctored archive


def test_verify_reports_manifest_paths_that_leave_the_archive(tmp_path):
    write_archive(tmp_path / "archive")
    archive = Archive(tmp_path / "archive")
    outside = tmp_path / "outside.png"
    outside.write_bytes(encode(photo(32, 24), "PNG"))
    (archive.root / "files/images/linked.png").symlink_to(outside)
    manifest = archive.manifest()
    manifest["items"]["image-file:900"]["path"] = str(outside)
    manifest["items"]["image-file:901"]["path"] = "../outside.png"
    manifest["items"]["image-file:902"]["path"] = "files/images/linked.png"
    manifest["items"]["image-file:903"] = "not an entry"
    manifest["namespaces"].append("../../etc")
    archive.write_json("manifest.json", manifest)
    archive.write_json(Archive.guide_index(), archive.read_json(Archive.guide_index()) + [{"guideid": "../../x"}, "junk"])
    archive.write_json(Archive.wiki_index("WIKI"), archive.read_json(Archive.wiki_index("WIKI")) + [{"wikiid": "../x", "title": "T"}, "junk"])
    fresh = Archive(archive.root)

    problems, _ = verify_archive(fresh)
    text = "\n".join(problems)

    assert f"image-file:900: {str(outside)!r} is not a path inside the archive" in text
    assert "image-file:901: '../outside.png' is not a path inside the archive" in text
    assert "image-file:902: 'files/images/linked.png' passes through a symbolic link" in text
    assert "The guide index lists an id that is not a whole number ('../../x')" in text
    assert "The WIKI page index holds an entry without a usable id" in text
    assert "The manifest names a wiki namespace that cannot be one" in text
    for image_id in (900, 901, 902, 903):
        assert fresh.media_file("image", image_id) is None, "and the loader is not given the file either"
    assert fresh.media_file("image", 904) is not None


# ---------------------------------------------------------------- where a download may go


def test_downloads_carry_no_credentials_of_any_kind(site, out_dir):
    site.fail("/guides/15/tags", httpx.Response(200, json=["location-access", "StellUSZ"], headers={"Set-Cookie": "tracking=1; Path=/"}))

    for environ in ({"DOZUKI_TOKEN": GOOD_TOKEN, "DOZUKI_APP_ID": "app-42"}, {"DOZUKI_SESSION_COOKIE": SESSION_COOKIE, "DOZUKI_APP_ID": "app-42"}):
        site.requests.clear()
        status, text, _ = export(site, out_dir / environ.get("DOZUKI_TOKEN", "cookie"), environ=environ)

        assert status == 0, text
        downloads = [request for request in site.requests if request.url.host != HOST]
        assert len(downloads) == 18
        assert all(not CREDENTIAL_HEADERS & set(request.headers) for request in downloads)
        assert all(request.url.scheme == "https" for request in downloads)


def test_the_anonymous_listing_pass_sends_nothing_that_identifies_the_caller(site, tmp_path):
    site.fail("/guides/15", httpx.Response(200, json={"guideid": 15}, headers={"Set-Cookie": "session=sticky; Path=/"}))

    with client_for(site, token=GOOD_TOKEN, app_id="app-42") as client:
        client.get("/guides/15")
        site.fail(f"{CDN}/a", httpx.Response(200, content=b"\x89PNG\r\n\x1a\n", headers={"Set-Cookie": "cdn=1", "Content-Type": "image/png"}))
        client.download(f"{CDN}/a", tmp_path / "a")
        listing, _ = client.get("/guides", {"limit": 5}, anonymous=True)
        with pytest.raises(ClientError, match=r"GET /guides \(anonymously\): not visible without signing in \(HTTP 401\)"):
            client.get("/guides", {"includePrivate": "true"}, anonymous=True)

    anonymous = [request for request in site.requests if request.url.path == f"{API}/guides"]
    assert len(anonymous) == 2 and all(not CREDENTIAL_HEADERS & set(request.headers) for request in anonymous)
    assert [entry["guideid"] for entry in listing] == [15, 27, 422], "and so it is shown what a visitor is shown"


@pytest.mark.parametrize("url", ["http://d3t0tbmlie281e.cloudfront.net/x.full", "ftp://example.org/x", "file:///etc/passwd", "//example.org/x", "https:///nohost", "x"])
def test_media_is_downloaded_over_https_only(site, tmp_path, url):
    with client_for(site) as client, pytest.raises(UnsafeAddress, match="media is fetched over https only"):
        client.download(url, tmp_path / "x")

    assert site.requests == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("host", "addresses"),
    [("intranet.example", ["10.1.2.3"]), ("localhost.example", ["127.0.0.1"]), ("metadata.example", ["169.254.169.254"]),
     ("mixed.example", ["93.184.216.34", "192.168.1.10"]), ("v6.example", ["::1"]), ("ula.example", ["fd00::1"]),
     ("mapped.example", ["::ffff:10.0.0.1"]), ("cgnat.example", ["100.64.0.1"]), ("junk.example", ["not-an-address"])],
)
def test_a_media_host_that_resolves_to_a_private_address_is_refused(site, tmp_path, host, addresses):
    site.addresses[host] = addresses

    with client_for(site) as client:
        for _ in range(2):
            with pytest.raises(UnsafeAddress, match=f"refusing to download from {host}: it resolves to a non-public address") as refusal:
                client.download(f"https://{host}/secret", tmp_path / "x")

    assert "--allow-private-media-hosts" in str(refusal.value)
    assert site.requests == [] and site.lookups == [host], "refused before any request, and looked up once"


@pytest.mark.parametrize("url", ["https://127.0.0.1/x", "https://10.0.0.8:8443/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/x", "https://[fe80::1]/x", "https://0.0.0.0/x"])
def test_a_private_address_written_out_in_the_url_is_refused_without_a_lookup(site, tmp_path, url):
    with client_for(site) as client, pytest.raises(UnsafeAddress, match="non-public address"):
        client.download(url, tmp_path / "x")

    assert site.requests == [] and site.lookups == []


def test_a_media_host_that_cannot_be_looked_up_is_refused(site, tmp_path):
    def failing(host: str) -> list[str]:
        if host == "empty.example":
            return []
        raise socket.gaierror(-2, "Name or service not known")

    with client_for(site, resolve=failing) as client:
        with pytest.raises(UnsafeAddress, match=r"its address could not be looked up \(gaierror\)"):
            client.download("https://nowhere.example/x", tmp_path / "x")
        with pytest.raises(UnsafeAddress, match="it has no address"):
            client.download("https://empty.example/x", tmp_path / "x")

    assert site.requests == []


def test_private_media_hosts_can_be_allowed_explicitly(site, out_dir):
    site.addresses["d3t0tbmlie281e.cloudfront.net"] = ["10.20.30.40"]

    refused_status, refused_text, refused = export(site, out_dir / "refused")
    allowed_status, allowed_text, allowed = export(site, out_dir / "allowed", "--allow-private-media-hosts")

    assert refused_status == 1
    assert refused.manifest()["counts"]["image-file"] == {"failed": 17}
    assert "refusing to download from d3t0tbmlie281e.cloudfront.net: it resolves to a non-public address (10.20.30.40)" in refused_text
    assert refused.manifest()["counts"]["video-file"] == {"ok": 1}, "the video store is another host, and a public one"
    assert allowed_status == 0, allowed_text
    assert allowed.manifest()["counts"]["image-file"] == {"ok": 17}


def test_the_default_name_lookup_and_the_address_test():
    assert resolve_host("127.0.0.1") == ["127.0.0.1"]
    assert is_public_address("93.184.216.34") and is_public_address("2606:4700::1111")
    for private in ("10.0.0.1", "172.16.0.1", "192.168.0.1", "127.0.0.1", "169.254.1.1", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1%eth0", "fc00::1", "::ffff:192.168.0.1", "nonsense"):
        assert not is_public_address(private), private


def redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


def test_a_download_follows_a_few_redirects_and_checks_every_hop(site, tmp_path):
    site.fail(PICTURE, redirect("https://edge-1.example/a"))
    site.fail("https://edge-1.example/a", redirect("/b", 307))
    site.fail("https://edge-1.example/b", redirect("https://edge-2.example/c", 301))
    site.files["https://edge-2.example/c"] = site.files[PICTURE]

    with client_for(site, token=GOOD_TOKEN, app_id="app-42") as client:
        result = client.download(PICTURE, tmp_path / "900")

    assert result.path.read_bytes() == site.files[PICTURE][0]
    assert result.final_url == "https://edge-2.example/c" and result.content_type == "image/png"
    assert [str(request.url) for request in site.requests] == [PICTURE, "https://edge-1.example/a", "https://edge-1.example/b", "https://edge-2.example/c"]
    assert all(not CREDENTIAL_HEADERS & set(request.headers) for request in site.requests)
    assert site.lookups == ["d3t0tbmlie281e.cloudfront.net", "edge-1.example", "edge-2.example"], "each new host is checked before it is asked"


def test_a_fourth_redirect_is_not_followed(site, tmp_path):
    for number in range(5):
        site.fail(f"https://hop-{number}.example/x", redirect(f"https://hop-{number + 1}.example/x"))

    with client_for(site) as client, pytest.raises(ClientError, match="more than 3 redirects"):
        client.download("https://hop-0.example/x", tmp_path / "x")

    assert len(site.requests) == 4 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("location", "message"),
    [("http://d3t0tbmlie281e.cloudfront.net/plain", "https only"), ("https://internal.example/admin", "non-public address"),
     ("https://169.254.169.254/latest/meta-data/", "non-public address"), ("https://127.0.0.1:8000/api/users", "non-public address"),
     ("file:///etc/passwd", "https only")],
)
def test_a_redirect_cannot_lead_a_download_somewhere_it_would_not_go_directly(site, tmp_path, location, message):
    site.addresses["internal.example"] = ["192.168.7.7"]
    site.fail(PICTURE, redirect(location))

    with client_for(site) as client, pytest.raises(UnsafeAddress, match=message):
        client.download(PICTURE, tmp_path / "x")

    assert [str(request.url) for request in site.requests] == [PICTURE], "the redirect target was never requested"
    assert list(tmp_path.iterdir()) == []


def test_a_redirect_without_a_location_is_just_a_failed_download(site, tmp_path):
    site.fail(PICTURE, httpx.Response(302))

    with client_for(site) as client, pytest.raises(ClientError, match="HTTP 302"):
        client.download(PICTURE, tmp_path / "x")


def test_a_redirected_download_is_recorded_in_the_manifest(site, out_dir):
    site.fail(PICTURE, redirect("https://edge-2.example/c"))
    site.files["https://edge-2.example/c"] = site.files[PICTURE]

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    entry = archive.manifest()["items"]["image-file:900"]
    assert entry["url"] == PICTURE and entry["final_url"] == "https://edge-2.example/c"
    assert "final_url" not in archive.manifest()["items"]["image-file:901"]


# ---------------------------------------------------------------- the API's own redirects


def test_the_api_client_follows_a_redirect_on_its_own_host_with_its_credentials(site):
    site.fail("/guides/15", redirect(f"https://{HOST}{API}/guides/15?moved=1"), redirect(f"{API}/guides/15?again=1", 308))

    with client_for(site, token=GOOD_TOKEN, app_id="app-42") as client:
        document, _ = client.get("/guides/15", {"excludePrerequisiteSteps": "true"})

    assert document["guideid"] == 15
    assert [request.url.query.decode() for request in site.requests] == ["excludePrerequisiteSteps=true", "moved=1", "again=1"]
    assert all(request.headers["Authorization"] == f"api {GOOD_TOKEN}" and request.headers["X-App-Id"] == "app-42" for request in site.requests)


@pytest.mark.parametrize("location", ["https://evil.example/api/2.0/guides/15", "https://zmb.dozuki.com.evil.example/x", "http://zmb.dozuki.com/api/2.0/guides/15", "//evil.example/x"])
def test_the_api_client_never_follows_a_redirect_off_its_host(site, location):
    site.fail("/guides/15", redirect(location))

    with client_for(site, token=GOOD_TOKEN, app_id="app-42", cookie=None) as client:
        with pytest.raises(ClientError, match="which is not the API host; not followed"):
            client.get("/guides/15")

    assert len(site.requests) == 1, "the token and the app id were not carried anywhere else"


def test_the_api_client_gives_up_on_a_redirect_loop_and_does_not_redirect_a_sign_in(site):
    site.fail("/guides/15", *[redirect(f"{API}/guides/15")] * 4)
    site.fail("/user/token", redirect(f"{API}/elsewhere"))

    with client_for(site) as client:
        with pytest.raises(ClientError, match="more than 3 redirects"):
            client.get("/guides/15")
        with pytest.raises(ClientError, match=r"Signing in failed \(HTTP 302\)"):
            client.login("someone@zmb.example", "password")

    assert [request.method for request in site.requests] == ["GET"] * 4 + ["POST"]


# ---------------------------------------------------------------- size and type


def test_a_file_over_the_size_limit_is_refused_from_its_declared_length(site, tmp_path):
    with client_for(site) as client, pytest.raises(ClientError, match="over the limit of 0 MB; not downloaded") as refusal:
        client.download(PICTURE, tmp_path / "x", max_bytes=100)

    assert refusal.value.status is None and list(tmp_path.iterdir()) == []


def test_the_size_limit_is_enforced_on_the_bytes_that_arrive(site, tmp_path):
    """A server can lie about the length or not state one; the count is what holds."""
    sent: list[int] = []

    def endless():
        for _ in range(1000):
            sent.append(1)
            yield b"\x89PNG\r\n\x1a\n" + bytes(1024 * 256)

    site.fail(PICTURE, httpx.Response(200, content=endless(), headers={"Content-Type": "image/png"}))

    with client_for(site) as client, pytest.raises(ClientError, match="larger than the limit of 1 MB; download stopped"):
        client.download(PICTURE, tmp_path / "x", max_bytes=1024 * 1024)

    assert len(sent) < 20, "the download stopped at the limit instead of draining the response"
    assert list(tmp_path.iterdir()) == [], "no partial file is left"


def test_the_size_limits_are_set_on_the_command_line(site, out_dir, capsys):
    status, text, archive = export(site, out_dir, "--max-image-mb", "0.002", "--max-video-mb", "0.001")

    assert status == 1
    items = archive.manifest()["items"]
    assert "over the limit of 0 MB" in items["video-file:137"]["error"]
    assert items["image-file:900"]["status"] == "ok", "a small picture is under the limit"
    assert "over the limit of 0 MB" in items["image-file:477"]["error"]
    for value in ("0", "-5", "lots", "9999999999"):
        with pytest.raises(SystemExit):
            cli.main(["export", "--site", HOST, "--out", str(out_dir), "--max-image-mb", value], environ={})
    errors = capsys.readouterr().err
    assert "the size has to be above 0 MB" in errors and "give a size in megabytes, for example 200" in errors


def test_the_default_size_limits_are_two_hundred_megabytes_and_two_gigabytes():
    arguments = cli.build_parser().parse_args(["export", "--site", HOST, "--out", "x"])

    assert arguments.max_image_mb == 200 * 1024 * 1024 and arguments.max_video_mb == 2 * 1024 * 1024 * 1024
    assert arguments.allow_private_media_hosts is False
    assert cli.build_parser().parse_args(["export", "--out", "x", "--max-video-mb", "1.5"]).max_video_mb == int(1.5 * 1024 * 1024)


@pytest.mark.parametrize(
    ("content_type", "expect", "message"),
    [("text/html; charset=utf-8", "image", "the server sent text/html, not an image"), ("application/json", "image", "application/json, not an image"),
     ("video/mp4", "image", "video/mp4, not an image"), ("image/png", "video", "image/png, not a video"), ("text/plain", "video", "text/plain, not a video")],
)
def test_a_response_of_the_wrong_kind_is_not_kept(site, tmp_path, content_type, expect, message):
    site.fail(PICTURE, httpx.Response(200, content=b"<html>Please sign in</html>", headers={"Content-Type": content_type}))

    with client_for(site) as client, pytest.raises(ClientError, match=message):
        client.download(PICTURE, tmp_path / "x", expect=expect)

    assert list(tmp_path.iterdir()) == []


def test_a_login_page_served_in_place_of_a_picture_is_a_recorded_failure(site, out_dir):
    site.files[PICTURE] = (b"<html>Please sign in</html>", "text/html")
    video_url = f"{VIDEO_STORE}/BJGvyPRLJAnukGuV_MP4_720.mp4"
    site.files[video_url] = (site.files[video_url][0], "binary/octet-stream")

    status, text, archive = export(site, out_dir)

    assert status == 1
    items = archive.manifest()["items"]
    assert items["image-file:900"]["error"] == "download Guid000000000900.full: the server sent text/html, not an image; not kept"
    assert list((out_dir / "files/images").glob("900.*")) == [], "the page was not kept as if it were the picture"
    assert items["video-file:137"]["content_type"] == "video/mp4" and items["video-file:137"]["declared_content_type"] == "binary/octet-stream"


def test_a_file_with_no_declared_type_is_named_by_its_first_bytes(site, tmp_path):
    samples = {
        "jpeg": encode(photo(16, 12), "JPEG"), "png": encode(photo(16, 12), "PNG"), "gif": encode(photo(16, 12).convert("P"), "GIF"),
        "webp": encode(photo(16, 12), "WEBP"), "bmp": encode(photo(16, 12), "BMP"), "tiff": encode(photo(16, 12), "TIFF"),
    }
    with client_for(site) as client:
        for name, payload in samples.items():
            site.fail(PICTURE, httpx.Response(200, content=payload))
            result = client.download(PICTURE, tmp_path / name, expect="image")
            assert (result.content_type, result.declared_type) == (f"image/{name}", ""), name
        site.fail(PICTURE, httpx.Response(200, content=b"\x00\x01 neither", headers={"Content-Type": "application/octet-stream"}))
        unknown = client.download(PICTURE, tmp_path / "unknown", expect="image")

    assert (unknown.content_type, unknown.declared_type) == ("", "application/octet-stream")
    assert sniff_content_type(b"\x1a\x45\xdf\xa3....") == "video/webm" and sniff_content_type(b"MM\x00*....") == "image/tiff"
    assert sniff_content_type(b"\x00\x00\x00\x18ftypisom") == "video/mp4" and sniff_content_type(b"GIF87a") == "image/gif" and sniff_content_type(b"") == ""


def test_a_file_that_says_nothing_about_itself_is_named_from_the_metadata_or_not_at_all(site, out_dir):
    for image_id in (900, 901):
        site.files[site.images[image_id]["original"]] = (b"\x00\x01 not a picture anyone can name", "application/octet-stream")
    del site.documents["/media/images/901"]

    status, text, archive = export(site, out_dir)

    items = archive.manifest()["items"]
    assert items["image-file:900"]["path"] == "files/images/900.png", "the metadata's encoding names it"
    assert items["image-file:901"]["path"] == "files/images/901.bin"
    assert "content_type" not in items["image-file:900"] and items["image-file:900"]["declared_content_type"] == "application/octet-stream"


def test_an_extension_offered_by_the_vendor_is_not_trusted_as_a_file_name(site, out_dir):
    encoding = site.documents["/media/videos/137"]["encodings"][0]
    encoding.update(mime="", format="mp4exeLongerThanAnyExtension")
    site.documents["/guides/27"]["steps"][0]["media"]["data"]["encodings"][0].update(mime="", format="mp4exeLongerThanAnyExtension")

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert archive.manifest()["items"]["video-file:137"]["path"] == "files/videos/137.bin"


# ---------------------------------------------------------------- what the site shows anonymously


def test_a_signed_in_export_records_what_an_anonymous_visitor_is_shown(site, out_dir):
    site.private_wikis = {108}

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert {entry["guideid"]: entry["anonymousVisible"] for entry in archive.read_json(Archive.guide_index())} == {15: True, 27: True, 422: True, 430: False}
    assert {entry["wikiid"]: entry["anonymousVisible"] for entry in archive.read_json(Archive.wiki_index("WIKI"))} == {108: False}
    categories = {entry["wikiid"]: entry["anonymousVisible"] for entry in archive.read_json(Archive.wiki_index("CATEGORY"))}
    assert categories == {1: True, 20: True, 23: True, 41: None}, "a page the listing omits was asked for by title, signed in: unknown"
    anonymous = [request for request in site.requests if request.url.host == HOST and "Authorization" not in request.headers]
    assert sorted({request.url.path.removeprefix(API) for request in anonymous}) == ["/guides", "/wikis/CATEGORY", "/wikis/INFO", "/wikis/WIKI"]
    assert len(anonymous) == 7, "one extra listing pass each (a page and the empty page that ends it), and no request per item"


def test_an_anonymous_export_saw_everything_it_has_anonymously(site, out_dir):
    status, text, archive = export(site, out_dir, environ={})

    assert status == 0, text
    assert {entry["anonymousVisible"] for entry in archive.read_json(Archive.guide_index())} == {True}
    assert {entry["wikiid"]: entry["anonymousVisible"] for entry in archive.read_json(Archive.wiki_index("CATEGORY"))} == {1: True, 20: True, 23: True, 41: True}
    assert len([request for request in site.requests if request.url.path == f"{API}/guides"]) == 2, "no second pass is needed"


def test_a_site_that_shows_nothing_without_a_login_leaves_visibility_unknown(site, out_dir):
    site.anonymous_api = False

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert "The anonymous listing of /wikis/WIKI could not be fetched (GET /wikis/WIKI (anonymously): not visible without signing in (HTTP 401))" in text
    assert "`load` will import those pages as drafts" in text
    assert {entry["anonymousVisible"] for entry in archive.read_json(Archive.wiki_index("WIKI"))} == {None}
    assert {entry["anonymousVisible"] for entry in archive.read_json(Archive.guide_index())} == {None}
    assert len(archive.manifest()["warnings"]) == 4


def test_guides_kept_from_an_earlier_run_keep_the_visibility_recorded_then(site, out_dir):
    export(site, out_dir)

    status, text, archive = export(site, out_dir, environ={})

    assert {entry["guideid"]: entry["anonymousVisible"] for entry in archive.read_json(Archive.guide_index())} == {15: True, 27: True, 422: True, 430: False}


# ---------------------------------------------------------------- items the site does not have


def test_absent_items_are_recorded_with_a_time_and_not_asked_for_again(site, out_dir):
    export(site, out_dir)
    first = Archive(out_dir).manifest()["items"]
    absent = {key: entry for key, entry in first.items() if entry["status"] == "absent" and entry["kind"] in {"wiki", "category"}}
    site.requests.clear()

    status, text, archive = export(site, out_dir)

    assert len(absent) >= 5 and all(parse_instant(entry["checked_at"]) is not None and entry["authenticated"] is True for entry in absent.values())
    assert status == 0, text
    asked = {request.url.path.removeprefix(API) for request in site.requests}
    assert not any(path.startswith(("/wikis/CATEGORY/", "/categories/")) and path != "/categories/all" for path in asked)
    second = archive.manifest()["items"]
    assert {key: second[key] for key in absent} == absent, "the record of the absence, and when it was established, is kept"


def test_refresh_asks_again_for_items_that_were_absent(site, out_dir):
    export(site, out_dir)
    site.documents["/wikis/CATEGORY/IT"] = {"wikiid": 11, "title": "IT", "contents_raw": "Now it has a page.", "revisionid": 9}
    site.requests.clear()

    status, text, archive = export(site, out_dir, "--refresh")

    assert status == 0, text
    assert f"{API}/wikis/CATEGORY/IT" in {request.url.path for request in site.requests}
    assert archive.manifest()["items"]["wiki:CATEGORY:11"]["status"] == "ok"
    assert archive.read_json(Archive.wiki("CATEGORY", 11))["contents_raw"] == "Now it has a page."


def test_an_absence_seen_anonymously_is_checked_again_once_signed_in(site, out_dir):
    """What an anonymous visitor may not see can exist all the same."""
    original = site.handle
    hidden = f"{API}/wikis/CATEGORY/Lightsheet microscopy"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == hidden and "Authorization" not in request.headers:
            return httpx.Response(403, json={"message": "Forbidden"})
        return original(request)

    site.handle = handle
    site.documents["/wikis/CATEGORY/Lightsheet microscopy"] = {"wikiid": 24, "title": "Lightsheet microscopy", "contents_raw": "Staff notes.", "revisionid": 3}

    export(site, out_dir, environ={})
    anonymous = Archive(out_dir).manifest()["items"]["wiki:CATEGORY:24"]
    site.requests.clear()
    export(site, out_dir, environ={})
    asked_anonymously_again = [request for request in site.requests if request.url.path == hidden]
    status, text, archive = export(site, out_dir)

    assert anonymous["status"] == "absent" and anonymous["authenticated"] is False
    assert asked_anonymously_again == [], "an anonymous run does not repeat an anonymous run's question"
    assert archive.manifest()["items"]["wiki:CATEGORY:24"]["status"] == "ok", "but a signed-in run asks, and gets the page"
    index = {entry["wikiid"]: entry for entry in archive.read_json(Archive.wiki_index("CATEGORY"))}
    assert index[24]["listed"] is False and index[24]["anonymousVisible"] is None


def test_a_manifest_entry_that_is_not_an_entry_does_not_stop_a_later_run(site, out_dir):
    export(site, out_dir)
    manifest = Archive(out_dir).manifest()
    manifest["items"]["guide:15"] = "damaged"
    manifest["recheck_images"] = "damaged too"
    del manifest["items"]["image-meta:900"]
    Archive(out_dir).write_json("manifest.json", manifest)

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert archive.manifest()["items"]["guide:15"]["status"] == "ok" and archive.manifest()["recheck_images"] == []


# ---------------------------------------------------------------- images that change under the same id


def remark(site: FakeSite, image_id: int, source_id: int, image_format: str = "JPEG") -> bytes:
    """Edit an image's markers on the vendor site: same id, new picture, new marker data."""
    clean = photo(800, 600, 1) if source_id == 477 else photo(640, 480, 5)
    marked = clean.copy()
    ImageDraw.Draw(marked).rectangle((100, 100, 300, 250), outline="#c1280b", width=8)
    payload = encode(marked, image_format)
    meta = site.documents[f"/media/images/{image_id}"]
    site.files[meta["image"]["original"]] = (payload, f"image/{image_format.lower()}")
    meta["markup"] = ";rectangle,100x100,300x250,red;"
    meta["markupState"] = {"annotations": {"type": "NODE_MARKUP", "version": "1", "data": [
        {"shape": "rectangle", "x": 100, "y": 100, "width": 200, "height": 150, "color": "red"}]}}
    return payload


def revise_guide(site: FakeSite, guide_id: int) -> None:
    site.documents[f"/guides/{guide_id}"]["guide_revisionid"] += 1
    for entry in site.lists["/guides"]:
        if entry["guideid"] == guide_id:
            entry["guide_revisionid"] += 1


def test_a_marker_edit_on_an_existing_image_is_picked_up_when_its_guide_changes(site, out_dir):
    export(site, out_dir)
    before = Archive(out_dir).manifest()["items"]
    payload = remark(site, 507, 477)
    revise_guide(site, 15)
    site.requests.clear()

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert "  image 507 changed on the site (its picture or its markers); downloading it again" in text
    assert (out_dir / "files/images/507.jpg").read_bytes() == payload
    after = archive.manifest()["items"]
    assert after["image-file:507"]["sha256"] != before["image-file:507"]["sha256"]
    assert archive.read_json(Archive.image_meta(507))["markup"] == ";rectangle,100x100,300x250,red;"
    asked = [request.url.path.removeprefix(API) for request in site.requests if request.url.host == HOST]
    assert sorted(path for path in asked if path.startswith("/media/images/")) == ["/media/images/14438", "/media/images/22069", "/media/images/507", "/media/images/900"], (
        "the metadata of the images that guide uses is fetched again, and of no others"
    )
    assert [request.url.path.rsplit("/", 1)[-1] for request in site.requests if request.url.host != HOST] == ["Guid000000000507.full"], (
        "only the image that changed is downloaded again"
    )
    assert after["image-file:900"] == before["image-file:900"] and archive.manifest()["recheck_images"] == []
    assert verify_archive(archive)[0] == []


def test_a_changed_image_of_another_type_replaces_the_old_file(site, out_dir):
    export(site, out_dir)
    remark(site, 507, 477, "PNG")
    site.documents["/media/images/507"]["encoding"] = "png"
    revise_guide(site, 15)

    status, text, archive = export(site, out_dir)

    assert status == 0, text
    assert archive.manifest()["items"]["image-file:507"]["path"] == "files/images/507.png"
    assert sorted(path.name for path in (out_dir / "files/images").glob("507.*")) == ["507.png"], "the superseded copy is not left to be mistaken for it"
    assert verify_archive(archive)[0] == []


def test_images_waiting_for_a_second_look_survive_an_interrupted_run(site, out_dir):
    export(site, out_dir)
    payload = remark(site, 950, 949)
    revise_guide(site, 27)
    site.fail("/media/images/600", httpx.Response(401, json={"message": "Token expired"}))

    stopped, text, archive = export(site, out_dir)
    waiting = archive.manifest()["recheck_images"]
    resumed, resumed_text, archive = export(site, out_dir)

    assert stopped == 2 and "rejected the API token" in text
    assert 950 in waiting and 600 in waiting
    assert resumed == 0, resumed_text
    assert (out_dir / "files/images/950.jpg").read_bytes() == payload, "the guide is current by now, but its images were still owed a look"
    assert archive.manifest()["recheck_images"] == []


def test_without_a_change_to_its_guide_a_marker_edit_needs_refresh(site, out_dir):
    """The documented limit: image metadata has no modification date to compare."""
    export(site, out_dir)
    payload = remark(site, 507, 477)

    plain_status, _, archive = export(site, out_dir)
    unchanged = (out_dir / "files/images/507.jpg").read_bytes() != payload
    refreshed_status, text, archive = export(site, out_dir, "--refresh")

    assert plain_status == 0 and unchanged, "an ordinary run has nothing that tells it to look"
    assert refreshed_status == 0, text
    assert (out_dir / "files/images/507.jpg").read_bytes() == payload
    assert "image 507 changed on the site" in text and text.count("changed on the site") == 1


def test_an_image_whose_metadata_cannot_be_fetched_again_keeps_its_file(site, out_dir):
    export(site, out_dir)
    before = (out_dir / "files/images/507.jpg").read_bytes()
    remark(site, 507, 477)
    revise_guide(site, 15)
    site.fail("/media/images/507", httpx.Response(404))

    status, text, archive = export(site, out_dir)

    assert status == 1 and archive.manifest()["items"]["image-meta:507"]["status"] == "failed"
    assert (out_dir / "files/images/507.jpg").read_bytes() == before


# ---------------------------------------------------------------- how old the copies are


def stamp(archive: Archive, **times: str) -> None:
    manifest = archive.manifest()
    for key, entry in manifest["items"].items():
        if entry["status"] == "ok":
            entry.pop("confirmed_at", None)
            entry["fetched_at"] = times.get(entry["kind"].replace("-", "_"), "2026-10-01T08:00:00Z")
    archive.write_json("manifest.json", manifest)


def test_verify_reports_how_old_the_copies_are(tmp_path):
    write_archive(tmp_path / "archive")
    archive = Archive(tmp_path / "archive")
    stamp(archive, guide="2026-09-20T08:00:00Z", image_meta="2026-09-01T12:00:00Z")
    manifest = archive.manifest()
    manifest["items"]["guide:15"]["confirmed_at"] = "2026-10-09T08:00:00Z"
    manifest["items"]["guide:27"]["fetched_at"] = "2026-10-10T09:00:00Z"
    manifest["items"]["user:12"].pop("fetched_at")
    manifest["items"]["user:22"]["fetched_at"] = "garbage"
    manifest["items"]["user:26"]["fetched_at"] = "2026-10-01T08:00:00"
    manifest["items"]["video-file:137"].pop("fetched_at")
    manifest["items"]["video-meta:137"]["fetched_at"] = 7
    manifest["items"]["guide-index"]["fetched_at"] = "2026-10-11T08:00:00Z"
    archive.write_json("manifest.json", manifest)
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    lines = capture_report(Archive(archive.root), now)
    text = "\n".join(lines)

    assert lines[0].startswith("Age of the copies")
    assert "  guide:         4 items, oldest 20 days ago (guide:422, 2026-09-20), newest today — compared with the site's listing on every run" in text
    assert "  image-meta:    17 items, oldest 39 days ago (image-meta:12099, 2026-09-01), newest 39 days ago — fetched again only when a guide or page using the image changed, or with --refresh" in text
    assert "  user:          3 items, oldest 9 days ago (user:26, 2026-10-01), newest 9 days ago, 2 without a recorded time" in text
    assert "  video-file:    1 item, no capture time recorded — never downloaded again" in text
    assert "  video-meta:    1 item, no capture time recorded" in text
    assert "  guide-index:   1 item, oldest in the future (check the clock) (guide-index, 2026-10-11)" in text
    assert "Every item" not in text

    detailed = "\n".join(capture_report(Archive(archive.root), now, every_item=True))
    assert "Every item, oldest first:" in detailed
    assert "  guide:15: fetched 2026-09-20T08:00:00Z, confirmed unchanged 2026-10-09T08:00:00Z (1 day ago)" in detailed
    assert "  guide:27: fetched 2026-10-10T09:00:00Z (today)" in detailed
    assert "  user:12: fetch time not recorded (at an unrecorded time)" in detailed
    assert [capture.key for capture in captures(Archive(archive.root)) if capture.kind == "guide"] == ["guide:422", "guide:430", "guide:15", "guide:27"]


def test_a_second_export_run_records_when_each_unchanged_item_was_confirmed(site, out_dir):
    export(site, out_dir)
    first = Archive(out_dir).manifest()["items"]

    export(site, out_dir)
    second = Archive(out_dir).manifest()["items"]

    assert "confirmed_at" not in first["guide:15"]
    for key in ("guide:15", "guide-tags:15", "wiki:WIKI:108", "wiki-tags:WIKI:108"):
        assert parse_instant(second[key]["confirmed_at"]) >= parse_instant(second[key]["fetched_at"]), key
        assert second[key]["fetched_at"] == first[key]["fetched_at"]
    assert "confirmed_at" not in second["image-meta:507"] and "confirmed_at" not in second["user:12"], "nothing compared these with the site"

    export(site, out_dir)
    assert parse_instant(Archive(out_dir).manifest()["items"]["guide:15"]["confirmed_at"]) >= parse_instant(second["guide:15"]["confirmed_at"])


def test_the_verify_command_prints_the_ages_and_can_list_every_item(tmp_path):
    write_archive(tmp_path / "archive")

    def verify(*arguments: str) -> tuple[int, str]:
        lines: list[str] = []
        return cli.main([*arguments], out=lines.append), "\n".join(lines)

    status, summary = verify("verify", "--archive", str(tmp_path / "archive"))
    _, detailed = verify("verify", "--archive", str(tmp_path / "archive"), "--ages")
    _, through_export = verify("export", "--verify", "--ages", "--out", str(tmp_path / "archive"))
    _, nothing = verify("verify", "--archive", str(tmp_path / "nothing"))

    assert status == 0
    assert "Age of the copies" in summary and "  image-meta:    17 items, oldest today" in summary and "Every item" not in summary
    assert "  image-file:507: fetched 20" in detailed and "(today)" in detailed
    assert "  image-file:507: fetched 20" in through_export
    assert "Age of the copies" not in nothing and "has no readable manifest.json" in nothing
    assert json.loads((tmp_path / "archive/manifest.json").read_text())["recheck_images"] == []
