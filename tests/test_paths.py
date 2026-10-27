"""Host-independent mapping and project configuration; no TCP required."""

from pathlib import PurePosixPath, PureWindowsPath

from hypothesis import given, strategies as st
import pytest

from dbgpilot import PathMapper, PathMapping, PathMappingError


def mapper(*mappings):
    return PathMapper([PathMapping(local, remote) for local, remote in mappings])


def test_no_mappings_preserves_original_outbound_behavior_and_does_not_invent_reverse_mapping(tmp_path):
    paths = PathMapper(base_dir=tmp_path)
    assert paths.to_remote("src/a b.php") == (tmp_path / "src/a b.php").as_uri()
    assert paths.to_remote("file:///remote/a%20b.php") == "file:///remote/a%20b.php"
    assert paths.to_remote("dbgp:eval-42") == "dbgp:eval-42"
    assert paths.location("file:///remote/a.php") == {"local_file": None, "path_mapping_error": None}
    with pytest.raises(PathMappingError, match="no remote root"):
        paths.to_local("file:///remote/a.php")


@pytest.mark.parametrize("suffix,encoded", [
    ("/index.php", "/index.php"), ("", ""), ("/", ""),
    ("/café #?%.php", "/caf%C3%A9%20%23%3F%25.php"),
    ("/src/../index.php", "/index.php"),
    ("/binary-\udcff.php", "/binary-%FF.php"),
])
def test_posix_round_trips_with_uri_encoding_and_lexical_normalization(suffix, encoded):
    paths = mapper(("/work/project/", "file:///var/www/html/"))
    uri = paths.to_remote("/work/project" + suffix)
    assert uri == "file:///var/www/html" + encoded
    assert paths.to_local(uri) == str(PurePosixPath("/work/project" + suffix.replace("src/../", "")))


def test_longest_directory_prefix_in_each_direction():
    paths = mapper(("/work", "file:///app"), ("/work/vendor", "file:///shared/vendor"))
    assert paths.to_remote("/work/vendor/lib/a.php") == "file:///shared/vendor/lib/a.php"
    assert paths.to_local("file:///shared/vendor/lib/a.php") == "/work/vendor/lib/a.php"
    assert paths.to_remote("/work/vendor-other/a.php") == "file:///app/vendor-other/a.php"
    with pytest.raises(PathMappingError, match="no local root"):
        paths.to_remote("/workspace/file.php")
    with pytest.raises(PathMappingError, match="no remote root"):
        paths.to_local("file:///application/file.php")


def test_inconsistent_nested_mappings_report_non_round_trippable_paths():
    paths = mapper(("/work", "file:///app"), ("/elsewhere", "file:///app/vendor"))
    with pytest.raises(PathMappingError, match="round-trip") as caught:
        paths.to_remote("/work/vendor/lib.php")
    assert caught.value.path == "/work/vendor/lib.php" and caught.value.direction == "to_remote"
    paths = mapper(("/work", "file:///app"), ("/work/vendor", "file:///vendor"))
    with pytest.raises(PathMappingError, match="round-trip"):
        paths.to_local("file:///app/vendor/lib.php")
    location = paths.location("file:///app/vendor/lib.php")
    assert location["local_file"] is None and "round-trip" in location["path_mapping_error"]


@pytest.mark.parametrize("mappings", [
    [("/work", "file:///a"), ("/work/", "file:///b")],
    [("/a", "file:///app"), ("/b", "file:///app/")],
    [(r"C:\Work", "file:///a"), (r"c:\work", "file:///b")],
    [("/a", "file://localhost/app"), ("/b", "file:///app")],
])
def test_duplicate_normalized_roots_are_rejected(mappings):
    with pytest.raises(ValueError, match="Duplicate"):
        mapper(*mappings)


def test_windows_drive_roots_work_on_posix_and_case_is_handled_per_side():
    paths = mapper((r"C:\Users\Alice\Site", "file:///var/www/html"))
    assert paths.to_remote(r"c:\users\ALICE\site\src\café.php") == "file:///var/www/html/src/caf%C3%A9.php"
    assert paths.to_local("file:///var/www/html/src/a.php") == r"C:\Users\Alice\Site\src\a.php"
    with pytest.raises(PathMappingError):
        paths.to_local("file:///VAR/www/html/src/a.php")

    paths = mapper(("/work", "file:///C:/App"))
    assert paths.to_remote("/work/src/a.php") == "file:///C:/App/src/a.php"
    assert paths.to_local("file:///c:/APP/src/a.php") == "/work/src/a.php"
    assert mapper(("/work", "file:///C:/")).to_remote("/work") == "file:///C:/"


def test_unc_local_paths_and_explicit_remote_case_policy():
    paths = mapper((r"\\SERVER\share\Site", "file:///app"))
    assert paths.to_remote(r"\\server\SHARE\site\a.php") == "file:///app/a.php"
    assert paths.to_local("file:///app/a.php") == r"\\SERVER\share\Site\a.php"
    paths = PathMapper([PathMapping("/work", "file://SERVER/share/Site", remote_case_sensitive=False)])
    assert paths.to_local("file://server/SHARE/site/a.php") == "/work/a.php"
    assert paths.to_remote("/work/a.php") == "file://server/share/Site/a.php"


def test_posix_case_is_preserved_and_not_folded():
    paths = mapper(("/Work", "file:///App"))
    with pytest.raises(PathMappingError):
        paths.to_remote("/work/a.php")
    with pytest.raises(PathMappingError):
        paths.to_local("file:///app/a.php")
    assert paths.to_local("file:///App/Foo.php") == "/Work/Foo.php"


def test_file_uri_authorities_include_ipv6_without_contacting_the_host():
    paths = mapper(("/work", "file://[::1]/app"))
    assert paths.to_remote("/work/a.php") == "file://[::1]/app/a.php"
    assert paths.to_local("file://[::1]/app/a.php") == "/work/a.php"


def test_symlinks_are_lexical_and_need_an_explicit_mapping(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    paths = mapper((str(alias), "file:///app"))
    assert paths.to_local("file:///app/a.php") == str(alias / "a.php")
    assert paths.to_remote(alias / "a.php") == "file:///app/a.php"
    with pytest.raises(PathMappingError):
        paths.to_remote(target / "a.php")


@pytest.mark.parametrize("uri", [
    "file:///app/../outside/a.php", "file:///app/%2e%2e/outside/a.php",
    "file:///app/%2F../outside/a.php", "file:///application/a.php",
    "file://other/app/a.php",
])
def test_remote_traversal_and_wrong_prefixes_cannot_escape_into_a_local_root(uri):
    paths = mapper(("/work", "file:///app"))
    with pytest.raises(PathMappingError):
        paths.to_local(uri)


def test_explicit_remote_and_virtual_uris_bypass_outbound_mapping():
    paths = mapper(("/work", "file:///app"))
    for uri in ("file:///unmapped/a%20b.php", "dbgp:eval-42"):
        assert paths.to_remote(uri) == uri
    assert paths.location("dbgp:eval-42")["path_mapping_error"] is None
    assert paths.location("<console>")["path_mapping_error"] is None
    assert paths.location("file:///unmapped/file.php")["path_mapping_error"]


@pytest.mark.parametrize("remote", [
    "/app", "dbgp:eval", "https://example.com/app", "file:relative",
    "file:///app?query", "file:///app#fragment", "file://user@host/app",
    "file:///app/%00", "file:///app/%GG",
])
def test_invalid_remote_root_configuration_is_rejected(remote):
    with pytest.raises(ValueError):
        mapper(("/work", remote))


def test_invalid_inputs_and_nonrepresentable_windows_components_have_clear_errors():
    with pytest.raises(ValueError):
        mapper((r"C:relative", "file:///app"))
    with pytest.raises(ValueError):
        PathMapper([{"local": "/work", "remtoe": "file:///app"}])
    with pytest.raises(ValueError):
        PathMapper([PathMapping("/work", "file:///app", remote_case_sensitive="no")])
    paths = mapper((r"C:\Work", "file:///app"))
    with pytest.raises(PathMappingError, match="Windows"):
        paths.to_local("file:///app/a%5Cb.php")
    paths = mapper(("/work", "file:///C:/App"))
    with pytest.raises(PathMappingError, match="Windows"):
        paths.to_remote("/work/a\\b.php")
    with pytest.raises(ValueError):
        paths.to_remote(123)
    with pytest.raises(PathMappingError):
        paths.to_local("dbgp:eval")


def test_overlapping_roots_cannot_mix_remote_case_policies():
    with pytest.raises(ValueError, match="case policy"):
        PathMapper([PathMapping("/work", "file:///App"),
                    PathMapping("/vendor", "file:///app/vendor", remote_case_sensitive=False)])


def test_project_config_relative_roots_discovery_and_cli_style_overrides(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    config = root / "dbgpilot.toml"
    config.write_text('[[path_mappings]]\nlocal = "."\nremote = "file:///app"\n')
    child = root / "src"
    child.mkdir()
    assert PathMapper.find_config(child) == config
    paths = PathMapper.from_file(config)
    monkeypatch.chdir(tmp_path)
    assert paths.to_remote("src/a.php") == "file:///app/src/a.php"
    assert paths.to_local("file:///app/src/a.php") == str(child / "a.php")
    replaced = paths.with_overrides([PathMapping(str(root), "file:///different")])
    assert replaced.to_remote(root / "a.php") == "file:///different/a.php"
    assert paths.to_remote(root / "a.php") == "file:///app/a.php"


@pytest.mark.parametrize("body", [
    'path_mappings = "wrong"', 'path_mappings = [42]',
    '[path_mappings]\nlocal="/work"', 'unexpected = true',
    '[[path_mappings]]\nlocal="/work"',
])
def test_malformed_project_config_fails_explicitly(tmp_path, body):
    config = tmp_path / "dbgpilot.toml"
    config.write_text(body)
    with pytest.raises(ValueError):
        PathMapper.from_file(config)


_component = st.text(alphabet="abcXYZ012 café#?%._-", min_size=1, max_size=15).filter(lambda text: text not in {".", ".."})


@given(st.lists(_component, min_size=1, max_size=5))
def test_arbitrary_posix_suffixes_round_trip(parts):
    paths = mapper(("/work", "file:///app"))
    local = PurePosixPath("/work", *parts)
    assert paths.to_local(paths.to_remote(local)) == str(local)
