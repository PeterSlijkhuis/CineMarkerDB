"""Generate CineMarker files for popular movies from OpenSubtitles SDH subtitles.

Walks TMDB's movies by vote count (most known first), downloads the best English subtitle
from OpenSubtitles (hearing impaired preferred, since those carry [GUNFIRE]-style cues and
song names) and runs the same detection as generate_drafts.py. Only derived timestamps and
labels are stored, never subtitle text.

Environment: TMDB_TOKEN (TMDB API read access token), OPENSUBTITLES_API_KEY,
OPENSUBTITLES_USERNAME, OPENSUBTITLES_PASSWORD.

Usage: python3 tools/import_opensubtitles.py [--out movies] [--max-movies 500]
Movies tried before are listed in tools/opensubtitles_tried.txt and skipped.
Stops when the OpenSubtitles daily download quota runs out.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

from generate_drafts import build_draft, credits_from_gap, parse_srt

TMDB = os.environ.get("TMDB_API", "https://api.themoviedb.org/3")
OPENSUBTITLES = os.environ.get("OPENSUBTITLES_API", "https://api.opensubtitles.com/api/v1")
USER_AGENT = "CineMarker v0.1"
DELAY = 1.0  # seconds between OpenSubtitles calls; their API allows a few per second
ROOT = Path(__file__).resolve().parent.parent
TRIED = ROOT / "tools" / "opensubtitles_tried.txt"


def http(url, headers=None, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                         **({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        data_in = r.read()
    return data_in if raw else json.loads(data_in)


class OpenSubtitles:
    def __init__(self):
        self.base = OPENSUBTITLES
        self.headers = {"Api-Key": os.environ["OPENSUBTITLES_API_KEY"]}
        login = http(f"{self.base}/login", self.headers, {"username": os.environ["OPENSUBTITLES_USERNAME"], "password": os.environ["OPENSUBTITLES_PASSWORD"]})
        self.headers["Authorization"] = f"Bearer {login['token']}"
        if login.get("base_url") and not os.environ.get("OPENSUBTITLES_API"):
            self.base = f"https://{login['base_url']}/api/v1"  # VIP accounts get their own host
        self.remaining = None

    def best_subtitle(self, tmdb_id):
        time.sleep(DELAY)
        # The API wants parameters sorted and lowercase, or it redirects.
        query = urllib.parse.urlencode(sorted({"languages": "en", "order_by": "download_count", "tmdb_id": tmdb_id}.items()))
        results = http(f"{self.base}/subtitles?{query}", self.headers).get("data", [])
        files = [(r["attributes"].get("hearing_impaired", False), r["attributes"].get("download_count", 0), f["file_id"])
                 for r in results for f in r["attributes"].get("files", [])[:1]]
        return max(files)[2] if files else None

    def download(self, file_id):
        time.sleep(DELAY)
        info = http(f"{self.base}/download", self.headers, {"file_id": file_id, "sub_format": "srt"})
        self.remaining = info.get("remaining")
        return http(info["link"], raw=True).decode("utf-8", "replace")


def tmdb(path):
    return http(f"{TMDB}{path}", {"Authorization": f"Bearer {os.environ['TMDB_TOKEN']}"})


def popular_movie_ids():
    page = 1
    while True:
        result = tmdb(f"/discover/movie?sort_by=vote_count.desc&page={page}")
        yield from (m["id"] for m in result["results"])
        if page >= min(result.get("total_pages", 1), 500):  # TMDB serves at most 500 pages
            return
        page += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "movies"))
    ap.add_argument("--max-movies", type=int, default=500)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tried = set(TRIED.read_text().split()) if TRIED.exists() else set()
    have = {p.stem for p in (ROOT / "movies").glob("*.json")} | {p.stem for p in out.glob("*.json")}
    subs_api = OpenSubtitles()
    attempted = written = 0

    for tmdb_id in popular_movie_ids():
        key = str(tmdb_id)
        if key in tried or key in have:
            continue
        if attempted >= args.max_movies or subs_api.remaining == 0:
            break
        attempted += 1
        try:
            movie = tmdb(f"/movie/{tmdb_id}")
            file_id = subs_api.best_subtitle(tmdb_id)
            if not movie.get("runtime") or not file_id:
                draft = None
            else:
                runtime_s = movie["runtime"] * 60
                subs = parse_srt(subs_api.download(file_id))
                year = int(movie["release_date"][:4]) if movie.get("release_date") else None
                draft = build_draft(tmdb_id, runtime_s, subs, credits_from_gap(subs, runtime_s), movie.get("title"), year, movie.get("imdb_id"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 406, 429):  # bad key or quota/rate limit: stop, retry tomorrow
                print(f"stopping: HTTP {e.code} on TMDB {tmdb_id}", file=sys.stderr)
                break
            print(f"skip TMDB {tmdb_id}: HTTP {e.code}", file=sys.stderr)
            continue
        except Exception as e:  # one bad movie must not stop the run; it is retried next night
            print(f"skip TMDB {tmdb_id}: {e}", file=sys.stderr)
            continue
        tried.add(key)
        if draft:
            (out / f"{tmdb_id}.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            written += 1
            print(f"{movie.get('title')}: {len(draft['markers'])} markers")

    TRIED.write_text("\n".join(sorted(tried, key=int)) + "\n")
    print(f"tried {attempted} movies, wrote {written} files, downloads left today: {subs_api.remaining}")


if __name__ == "__main__":
    main()
