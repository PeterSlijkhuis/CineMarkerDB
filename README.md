# CineMarkerDB

Chapter markers for the [CineMarker](https://github.com/PeterSlijkhuis/CineMarker) Jellyfin plugin.
One JSON file per movie at `movies/{tmdb_id}.json`. The plugin fetches
`https://raw.githubusercontent.com/PeterSlijkhuis/CineMarkerDB/main/movies/{tmdb_id}.json`
and a 404 means "no markers, keep the existing chapters".

## Format

```json
{
  "$schema": "../schema.json",
  "schema_version": 1,
  "tmdb_id": 578,
  "imdb_id": "tt0073195",
  "title": "Jaws",
  "year": 1975,
  "runtime": "02:04:00",
  "markers": [
    { "start": "00:00:00", "type": "intro", "title": "Opening Titles" },
    { "start": "01:20:50", "type": "scare", "title": "Ben Gardner's Boat", "emoji": "💀" }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Always `1` for now. |
| `tmdb_id` | yes | Must match the file name. |
| `runtime` | yes | Runtime of the cut you timed. The plugin skips the file if the local copy differs by more than a couple of minutes, so a theatrical file never lands on an extended cut. |
| `imdb_id`, `title`, `year` | no | For humans and lookups. The plugin does not use `title`. |
| `markers[].start` | yes | `hh:mm:ss` or `hh:mm:ss.mmm`. Sorted ascending, before `runtime`. |
| `markers[].type` | yes | One of the types below. |
| `markers[].title` | yes | Plain text, no emoji. The chapter name becomes `{emoji} {title}`. |
| `markers[].emoji` | no | Overrides the type's default emoji. |

Start the list with a `00:00:00` marker. Markers replace the movie's chapters, so
without one the first stretch of the movie has no chapter.

## Types and default emoji

| type | emoji | use for |
|---|---|---|
| `intro` | 🎬 | opening titles, cold open |
| `music` | 🎵 | notable song or score moment |
| `scare` | 👻 | jump scare, gore, intense moment |
| `action` | 💥 | fight, chase, set piece |
| `plot` | 📖 | key story beat |
| `credits` | 🎞️ | start of end credits |
| `post_credits` | ⭐ | mid or post credits scene |
| `other` | 📍 | anything else |

## Checking your file

```sh
pip install jsonschema
python3 validate.py
```

## Generating drafts from your Jellyfin library

`tools/generate_drafts.py` reads your own server and writes draft files to `drafts/`:

- `credits` from Jellyfin's credits segments (needs a plugin that detects them)
- `post_credits` when there is dialogue more than a minute after the credits start
- `music` from note-marked subtitle lines; SDH subtitles often name the song
- `action` from clusters of SDH sound cues like `[GUNFIRE]` or `[EXPLOSION]`

```sh
python3 tools/generate_drafts.py --server http://jellyfin:8096 --api-key YOUR_KEY --limit 20
```

Create the API key under Dashboard > API Keys. Review each draft, fix or add markers,
then move it to `movies/` and run `python3 validate.py`. Movies already in `movies/` are skipped.

## Nightly import from OpenSubtitles

`.github/workflows/import.yml` runs every night. It walks TMDB's movies from most to least
voted, downloads the best English subtitle (hearing impaired preferred) from
[OpenSubtitles](https://www.opensubtitles.com), runs the same detection as above, and commits
the new files to the `auto-drafts` branch. Open a PR from `auto-drafts` to `main` to publish
a batch. Only timestamps and short labels are stored, never subtitle text. Credits without
Jellyfin segments are guessed from a long silence near the end followed by more dialogue,
so they only appear for movies with a mid or post-credits scene.

Repository secrets it needs (Settings > Secrets and variables > Actions):

| Secret | Where to get it |
|---|---|
| `TMDB_TOKEN` | themoviedb.org > Settings > API > API Read Access Token |
| `OPENSUBTITLES_API_KEY` | opensubtitles.com > Consumers > new consumer |
| `OPENSUBTITLES_USERNAME`, `OPENSUBTITLES_PASSWORD` | your opensubtitles.com account |

The run stops when the daily OpenSubtitles download quota is used up and continues the next night.
Movies already tried are listed in `tools/opensubtitles_tried.txt`.

Tests: `cd tools && python3 test_generate_drafts.py && python3 test_import_opensubtitles.py`
