"""Run: python3 tools/test_import_opensubtitles.py  (end to end against fake TMDB and OpenSubtitles)"""
import json, os, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from test_generate_drafts import SUBS  # Guardians-like SDH subtitle with music, action, credits gap

HERE = Path(__file__).resolve().parent
downloads = []

class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, body, raw=False):
        self.send_response(200); self.end_headers()
        self.wfile.write(body if raw else json.dumps(body).encode())

    def do_GET(self):
        p = self.path
        if p.startswith("/tmdb/"):
            assert self.headers["Authorization"] == "Bearer tm"
            if p.startswith("/tmdb/discover/movie"):
                return self.reply({"results": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}], "total_pages": 1})
            ids = {"/tmdb/movie/1": {"title": "Has Subs", "runtime": 121, "release_date": "2014-07-30", "imdb_id": "tt2015381"},
                   "/tmdb/movie/2": {"title": "No Subs", "runtime": 100}, "/tmdb/movie/4": {"title": "Over Limit", "runtime": 90}}
            return self.reply(ids[p])
        if p == "/file/11.srt":  # download links are plain URLs, no API headers
            return self.reply(SUBS.encode(), raw=True)
        assert self.headers["Api-Key"] == "os" and self.headers["Authorization"] == "Bearer tok"
        if p == "/os/subtitles?languages=en&order_by=download_count&tmdb_id=1":
            return self.reply({"data": [
                {"attributes": {"hearing_impaired": False, "download_count": 900, "files": [{"file_id": 10}]}},
                {"attributes": {"hearing_impaired": True, "download_count": 50, "files": [{"file_id": 11}]}}]})
        if p.startswith("/os/subtitles"):
            return self.reply({"data": []})
        raise AssertionError(p)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/os/login":
            assert body == {"username": "u", "password": "p"}
            return self.reply({"token": "tok", "base_url": "ignored.example"})
        if self.path == "/os/download":
            downloads.append(body["file_id"])
            return self.reply({"link": f"http://127.0.0.1:{server.server_port}/file/{body['file_id']}.srt", "remaining": 0 if len(downloads) >= 2 else 5})
        raise AssertionError(self.path)

server = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}"

work = Path(tempfile.mkdtemp())
shutil.copytree(HERE.parent, work / "db", ignore=shutil.ignore_patterns(".git", "__pycache__", "opensubtitles_tried.txt"))
(work / "db" / "movies" / "3.json").write_text("{}")  # already in the DB: must be skipped
env = dict(os.environ, TMDB_API=f"{url}/tmdb", OPENSUBTITLES_API=f"{url}/os", TMDB_TOKEN="tm",
           OPENSUBTITLES_API_KEY="os", OPENSUBTITLES_USERNAME="u", OPENSUBTITLES_PASSWORD="p")
subprocess.run([sys.executable, work / "db" / "tools" / "import_opensubtitles.py"], env=env, check=True)

draft = json.loads((work / "db" / "movies" / "1.json").read_text())
assert downloads == [11], downloads  # hearing impaired subtitle preferred over the more popular one
assert draft["imdb_id"] == "tt2015381" and draft["year"] == 2014 and draft["runtime"] == "02:01:00"
got = [(m["start"], m["type"], m["title"]) for m in draft["markers"]]
assert got == [
    ("00:00:00", "intro", "Opening"),
    ("00:04:30", "music", "Come and Get Your Love by Redbone"),
    ("00:50:00", "action", "Shootout"),
    ("01:50:02", "credits", "End credits"),  # end of the last line before the long gap
    ("02:00:00", "post_credits", "Post-credits scene"),
], got
assert not (work / "db" / "movies" / "2.json").exists()
assert (work / "db" / "tools" / "opensubtitles_tried.txt").read_text().split() == ["1", "2", "4"]  # 3 already existed

from jsonschema import Draft202012Validator
Draft202012Validator(json.loads((HERE.parent / "schema.json").read_text())).validate(draft)
print("all checks passed")
