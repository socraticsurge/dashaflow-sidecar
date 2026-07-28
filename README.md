# DashaFlow Sidecar

Python serverless function that wraps the [DashaFlow](https://pypi.org/project/dashaflow/) Vedic
astrology library. Deployed standalone on Vercel (no framework) so the
`/api/*` URL space is owned by the Python function rather than a
framework router.

Used by [astro-unified-core](https://github.com/socraticsurge/astro-unified-core)
via the `DASHAFLOW_SIDECAR_URL` environment variable.

## Endpoints
- `GET /health` — liveness check, returns DashaFlow version
- `POST /calculate` — body
  `{date_of_birth, time_of_birth, latitude, longitude, timezone, query_date?}`,
  returns the full DashaFlow chart (17 sections). `query_date` is an optional
  profile-local ISO date used for current Dasha selection.
- `POST /dasha-subperiods` — the same birth body plus `path`, an array of one
  to four zero-based period indexes. Returns exactly one set of nine child
  periods using DashaFlow 1.1.0's server-side `_build_sub_periods` rounding
  sequence. Examples:
  - `[2]` returns Antardashas for the third Mahadasha.
  - `[2, 8]` returns Pratyantardashas for its ninth Antardasha.
  - `[2, 8, 3, 8]` returns Prana periods for the selected Sukshma period.

The path API exists to support lazy accordions without transferring or storing
an exponentially large five-level tree. Astro calls it server-to-server through
an authenticated profile-owned route; browser clients do not send birth data.

## Local
```
pip install -r requirements.txt
uvicorn api.index:app --reload
```
