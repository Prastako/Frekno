"""Tests for pipeline.fetch.download."""

import functools
import http.server
import threading

import pytest
import requests

from pipeline.fetch.download import download, download_many


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    (root / "a.bin").write_bytes(b"x" * 3000)
    (root / "b.bin").write_bytes(b"y" * 10)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_writes_and_keeps(server, tmp_path):
    dest = tmp_path / "out" / "a.bin"
    assert download(f"{server}/a.bin", dest) == 3000
    assert dest.read_bytes() == b"x" * 3000
    assert download(f"{server}/a.bin", dest) == 0
    assert not (tmp_path / "out" / "a.bin.part").exists()


def test_download_missing_raises(server, tmp_path):
    with pytest.raises(requests.HTTPError):
        download(f"{server}/none.bin", tmp_path / "n.bin", retries=1)
    assert not (tmp_path / "n.bin").exists()


def test_download_many(server, tmp_path):
    (tmp_path / "b.bin").write_bytes(b"old")
    items = [(f"{server}/a.bin", tmp_path / "a.bin"), (f"{server}/b.bin", tmp_path / "b.bin"), (f"{server}/none.bin", tmp_path / "c.bin")]
    stats = download_many(items, workers=3, retries=1)
    assert stats == {"files": 1, "bytes": 3000, "kept": 1, "failed": [f"{server}/none.bin"]}
    assert (tmp_path / "b.bin").read_bytes() == b"old"
