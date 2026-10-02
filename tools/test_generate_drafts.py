"""Run: python3 tools/test_generate_drafts.py  (end to end against a fake Jellyfin)"""
import json, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import generate_drafts as g

def srt(entries):
    def ts(s):
        return f"{int(s // 3600):02}:{int(s % 3600 // 60):02}:{int(s % 60):02},000"
    return "\n\n".join(f"{i}\n{ts(s)} --> {ts(s + 2)}\n{t}" for i, (s, t) in enumerate(entries, 1))

SUBS = srt(
    [(60, "Hello there.")]
    + [(270 + i * 10, "♪ 'Come and Get Your Love' by Redbone playing ♪" if i == 0 else "♪ Hail, what's the matter with your head? ♪") for i in range(5)]
    + [(3000 + i * 5, "[GUNFIRE]" if i % 2 else "[explosion]") for i in range(4)] + [(3020 + i * 4, "[gunfire continues]") for i in range(4)]
    + [(4000, "♪ hum ♪")]  # lone note line: no music marker
    + [(6600, "Last line before credits.")]
    + [(7200, "I am Groot.")]  # after credits start (6690) + 60s
)

class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        assert self.headers["Authorization"] == 'MediaBrowser Token="k"'
        if self.path.startswith("/Items"):
            body = {"Items": [
                {"Id": "abc", "Name": "Guardians of the Galaxy", "ProductionYear": 2014, "RunTimeTicks": 7260 * 10**7,
                 "ProviderIds": {"Tmdb": "999001"},
                 "MediaSources": [{"Id": "src1", "MediaStreams": [
                     {"Type": "Subtitle", "Codec": "pgssub", "Index": 2, "Language": "eng"},
                     {"Type": "Subtitle", "Codec": "subrip", "Index": 3, "Language": "eng", "IsHearingImpaired": True}]}]},
                {"Id": "nosubs", "Name": "No Subs", "RunTimeTicks": 10**10, "ProviderIds": {"Tmdb": "999002"}, "MediaSources": [{"Id": "s", "MediaStreams": []}]},
                {"Id": "x", "Name": "No TMDB", "RunTimeTicks": 10**10, "ProviderIds": {}},
            ]}
        elif self.path == "/MediaSegments/abc":
            body = {"Items": [{"Type": "Intro", "StartTicks": 0}, {"Type": "Outro", "StartTicks": 6690 * 10**7}]}
        elif self.path == "/MediaSegments/nosubs":
            self.send_response(404); self.end_headers(); return
        elif self.path == "/Videos/abc/src1/Subtitles/3/Stream.srt":
            self.send_response(200); self.end_headers(); self.wfile.write(SUBS.encode()); return
        else:
            raise AssertionError(self.path)
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())

server = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
out = Path(tempfile.mkdtemp()) / "drafts"
subprocess.run([sys.executable, Path(__file__).with_name("generate_drafts.py"), "--server", f"http://127.0.0.1:{server.server_port}",
                "--api-key", "k", "--out", out], check=True)

draft = json.loads((out / "999001.json").read_text())
got = [(m["start"], m["type"], m["title"]) for m in draft["markers"]]
assert got == [
    ("00:00:00", "intro", "Opening"),
    ("00:04:30", "music", "Come and Get Your Love by Redbone"),
    ("00:50:00", "action", "Shootout"),
    ("01:51:30", "credits", "End credits"),
    ("02:00:00", "post_credits", "Post-credits scene"),
], got
assert draft["runtime"] == "02:01:00" and draft["title"] == "Guardians of the Galaxy"
assert not (out / "999002.json").exists()  # nothing beyond Opening: no file

# Drafts must pass the real schema once moved to movies/.
try:
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads(Path(__file__).resolve().parent.parent.joinpath("schema.json").read_text())).validate(draft)
except ImportError:
    print("jsonschema not installed, schema check skipped")
print("all checks passed")
