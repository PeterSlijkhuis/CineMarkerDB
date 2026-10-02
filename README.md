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
