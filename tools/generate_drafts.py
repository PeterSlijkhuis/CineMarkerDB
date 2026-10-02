"""Generate draft CineMarker files from your own Jellyfin library.

Sources, all local to your server:
  credits       Jellyfin media segments (type Outro), e.g. from an intro/credits detection plugin,
                else a long dialogue gap near the end that is followed by more dialogue
  post_credits  subtitle dialogue that starts after the credits began
  music         subtitle lines marked with a note symbol; SDH subtitles often name the song
  action        clusters of SDH sound cues like [GUNFIRE], [EXPLOSION], [TIRES SCREECHING]

Usage:
  python3 tools/generate_drafts.py --server http://jellyfin:8096 --api-key KEY [--out drafts] [--limit 20]

Writes drafts/{tmdb_id}.json. Review a draft, fix titles, then move it to movies/.
Existing files in movies/ are never touched. Stdlib only.
"""
import argparse, json, re, sys, urllib.request
from pathlib import Path

TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "vtt", "mov_text", "text"}
NOTE = re.compile(r"[♪♫]")
SONG = re.compile(r"[\"“']([^\"”']{2,60})[\"”'](?:\s+by\s+([^♪♫\]\)]+?))?\s*(?:playing|plays|continues)?\s*[♪♫\]\)]", re.I)
CUE = re.compile(r"[\[(]([^\])]{2,60})[\])]")
ACTION_KINDS = [  # (cue words, marker title); first match wins per cue
    (("gunfire", "gunshot", "shots", "machine gun", "rifle"), "Shootout"),
    (("explosion", "explodes", "blast"), "Explosions"),
    (("tires", "engine revs", "crash", "sirens", "horn honks"), "Chase"),
    (("punch", "grunt", "kick", "thud", "fighting", "groans"), "Fight"),
    (("screams", "screaming", "shrieks"), "Mayhem"),
]


def parse_srt(text):
    """[(start_s, end_s, text)] from SRT."""
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if m:
            g = list(map(int, m.groups()))
            body = block[m.end():].strip()
            out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, body))
    return out


def clusters(times, max_gap):
    """Group sorted (time, payload) pairs whose neighbours are at most max_gap seconds apart."""
    groups = []
    for t, p in times:
        if groups and t - groups[-1][-1][0] <= max_gap:
            groups[-1].append((t, p))
        else:
            groups.append([(t, p)])
    return groups


def music_markers(subs, credits_at):
    lines = [(s, body) for s, _, body in subs if NOTE.search(body) and (credits_at is None or s < credits_at)]
    out = []
    for g in clusters(lines, 20):
        if len(g) >= 3 and g[-1][0] - g[0][0] >= 30:
            song = next((SONG.search(b) for _, b in g if SONG.search(b)), None)
            title = f"{song.group(1).strip()}" + (f" by {song.group(2).strip()}" if song and song.group(2) else "") if song else "Song"
            out.append({"start": g[0][0], "type": "music", "title": title})
    return out


def action_markers(subs, credits_at):
    cues = []
    for s, _, body in subs:
        if credits_at is not None and s >= credits_at:
            continue
        for cue in CUE.findall(body):
            kind = next((title for words, title in ACTION_KINDS if any(w in cue.lower() for w in words)), None)
            if kind:
                cues.append((s, kind))
    out = []
    for g in clusters(cues, 30):
        if len(g) >= 6:
            kinds = [k for _, k in g]
            out.append({"start": g[0][0], "type": "action", "title": max(set(kinds), key=kinds.count)})
    return out


def post_credits_marker(subs, credits_at):
    if credits_at is None:
        return []
    after = [s for s, _, body in subs if s > credits_at + 60 and not NOTE.search(body)]
    return [{"start": after[0], "type": "post_credits", "title": "Post-credits scene"}] if after else []


def credits_from_gap(subs, runtime_s):
    """Credits start guessed from subtitles: the first silence of 150 s or more in the last 15%
    of the movie that is followed by more dialogue (a mid or post-credits scene).
    Returns None when there is no such gap, because then the credits start can't be told apart
    from a quiet ending."""
    # ponytail: heuristic; a long silent finale with an epilogue after it reads as credits
    lines = [(s, e) for s, e, body in subs if not NOTE.search(body)]
    for (_, end), (start, _) in zip(lines, lines[1:]):
        if end >= 0.85 * runtime_s and start - end >= 150:
            return end
    return None


def hms(seconds):
    s = int(seconds)
    return f"{s // 3600:02}:{s % 3600 // 60:02}:{s % 60:02}"


def build_draft(tmdb_id, runtime_s, subs, credits_at, title=None, year=None, imdb_id=None):
    markers = [{"start": 0, "type": "intro", "title": "Opening"}]
    markers += music_markers(subs, credits_at) + action_markers(subs, credits_at)
    if credits_at is not None:
        markers.append({"start": credits_at, "type": "credits", "title": "End credits"})
    markers += post_credits_marker(subs, credits_at)
    markers.sort(key=lambda m: m["start"])
    kept = [m for i, m in enumerate(markers) if i == 0 or m["start"] - markers[i - 1]["start"] >= 10]
    if len(kept) < 2:
        return None  # nothing beyond "Opening": not worth a file
    draft = {
        "$schema": "../schema.json",
        "schema_version": 1,
        "tmdb_id": int(tmdb_id),
        "imdb_id": imdb_id,
        "title": title,
        "year": year,
        "runtime": hms(runtime_s),
        "markers": [dict(m, start=hms(m["start"])) for m in kept],
    }
    return {k: v for k, v in draft.items() if v is not None}


class Jellyfin:
    def __init__(self, server, api_key):
        self.server = server.rstrip("/")
        self.headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}

    def get(self, path, raw=False):
        req = urllib.request.Request(self.server + path, headers=self.headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        return data.decode("utf-8", "replace") if raw else json.loads(data)

    def movies(self):
        return self.get("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=ProviderIds,MediaSources")["Items"]

    def credits_start(self, item_id):
        try:
            segments = self.get(f"/MediaSegments/{item_id}")["Items"]
        except Exception:
            return None
        outro = [s["StartTicks"] for s in segments if s.get("Type") in ("Outro", 4)]
        return min(outro) / 1e7 if outro else None

    def subtitles(self, item):
        source = (item.get("MediaSources") or [{}])[0]
        streams = [s for s in source.get("MediaStreams", []) if s.get("Type") == "Subtitle" and (s.get("Codec") or "").lower() in TEXT_CODECS]
        if not streams:
            return []

        def score(s):
            english = (s.get("Language") or "").lower() in ("eng", "en")
            sdh = s.get("IsHearingImpaired") or "sdh" in (s.get("Title") or s.get("DisplayTitle") or "").lower()
            return (english, bool(sdh))

        best = max(streams, key=score)
        return parse_srt(self.get(f"/Videos/{item['Id']}/{source['Id']}/Subtitles/{best['Index']}/Stream.srt", raw=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--out", default="drafts")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    jf, out = Jellyfin(args.server, args.api_key), Path(args.out)
    existing = {p.stem for p in Path(__file__).resolve().parent.parent.joinpath("movies").glob("*.json")}
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in jf.movies()[: args.limit]:
        tmdb = (item.get("ProviderIds") or {}).get("Tmdb")
        if not tmdb or tmdb in existing or not item.get("RunTimeTicks"):
            continue
        try:
            runtime_s, subs = item["RunTimeTicks"] / 1e7, jf.subtitles(item)
            credits_at = jf.credits_start(item["Id"]) or credits_from_gap(subs, runtime_s)
            draft = build_draft(tmdb, runtime_s, subs, credits_at, item.get("Name"), item.get("ProductionYear"), (item.get("ProviderIds") or {}).get("Imdb"))
        except Exception as e:  # one broken movie must not stop the run
            print(f"skip {item.get('Name')}: {e}", file=sys.stderr)
            continue
        if draft:
            (out / f"{tmdb}.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            written += 1
            print(f"{item.get('Name')}: {len(draft['markers'])} markers")
    print(f"wrote {written} drafts to {out}/")


if __name__ == "__main__":
    main()
