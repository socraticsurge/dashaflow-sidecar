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
- `POST /transit`, `/career`, `/compatibility`, and `/muhurtha` — legacy application
  routes; their request, response, and authentication behavior is unchanged
- `POST /v1/profile/derive` — minimal server-to-server birth-profile contract described below

## Profile derivation contract (`1.0`)

`POST /v1/profile/derive` accepts exactly:

```json
{
  "date_of_birth": "1990-04-15",
  "time_of_birth": "14:30",
  "latitude": 17.385,
  "longitude": 78.4867,
  "timezone": "Asia/Kolkata"
}
```

Dates and times must be real values in the exact ISO `YYYY-MM-DD` and `HH:MM`
forms, and a birth date cannot be in the future. The complete local civil time
must resolve to one real instant: repeated and skipped DST wall times are
rejected rather than guessed. Coordinates must be JSON numbers within
`[-90, 90]` latitude and `[-180, 180]` longitude, and `timezone` must be an IANA
timezone identifier. Extra fields are rejected.

The response is deliberately smaller than `/calculate` and never echoes birth
inputs or the rest of the DashaFlow chart. This example abbreviates the planets
array; the actual response contains all nine:

```json
{
  "contract_version": "1.0",
  "engine": {
    "name": "DashaFlow",
    "version": "1.1.0",
    "ayanamsha": "Lahiri",
    "ephemeris": "moshier"
  },
  "data": {
    "nakshatra": "Dhanishtha",
    "pada": 3,
    "janma_rashi": "Vrishabha",
    "lagna": "Vrischika",
    "lagna_degree": 12.5,
    "planets": [
      {
        "name": "Surya",
        "rashi": "Mesha",
        "degree": 1.25,
        "house": 1,
        "retrograde": false
      }
    ]
  }
}
```

`planets` always contains all nine grahas in this order: `Surya`, `Chandra`,
`Kuja`, `Budha`, `Guru`, `Shukra`, `Shani`, `Rahu`, `Ketu`. Nakshatras and
Rashis use the canonical Panchangam Sanskrit spellings. The `ephemeris` value is
derived from the Swiss Ephemeris return flags and is one of `swiss`, `moshier`,
or `unknown`; it is not inferred from the package description.

Every response on this path, including errors, carries
`Cache-Control: private, no-store`. Invalid bodies return a sanitized `422`, an
unavailable calculation returns a sanitized `502`, and no raw engine exception
text is returned.

### Authentication and rollout

Set a high-entropy `DASHAFLOW_API_TOKEN` in the sidecar environment and send it
as `Authorization: Bearer <token>`. This authentication applies only to
`/v1/profile/derive`; all legacy routes remain compatible. Missing, malformed,
or incorrect credentials return `401`. If `DASHAFLOW_API_TOKEN` itself is absent
or malformed, the endpoint fails closed with `503`.

The token is a server-to-server secret and must never be embedded in browser
code or a `VITE_*` variable. Roll out in this order:

1. Generate one independent secret and configure it as `DASHAFLOW_API_TOKEN` on
   the sidecar.
2. Deploy and verify the sidecar health route and an authenticated contract call.
3. Configure the same value in the server-side caller (currently
   `DASHAFLOW_SIDECAR_TOKEN`) together with `DASHAFLOW_SIDECAR_URL`.
4. Deploy the caller and verify the public gateway; rotate both token settings
   together when rotation is needed.

## Local

```bash
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Run contract tests with:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```
