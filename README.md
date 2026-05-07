# DashaFlow Sidecar

Python serverless function that wraps the [DashaFlow](https://pypi.org/project/dashaflow/) Vedic
astrology library. Deployed standalone on Vercel (no framework) so the
`/api/*` URL space is owned by the Python function rather than a
framework router.

Used by [astro-unified-core](https://github.com/socraticsurge/astro-unified-core)
via the `DASHAFLOW_SIDECAR_URL` environment variable.

## Endpoints
- `GET /health` — liveness check, returns DashaFlow version
- `POST /calculate` — body `{date_of_birth, time_of_birth, latitude, longitude, timezone}`,
  returns the full DashaFlow chart (17 sections)

## Local
```
pip install -r requirements.txt
uvicorn api.index:app --reload
```
