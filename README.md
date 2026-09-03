# DashaFlow Sidecar

FastAPI service that wraps the [DashaFlow](https://pypi.org/project/dashaflow/)
Vedic astrology library and runs in Vercel's native FastAPI framework. The
deployment entrypoint is pinned as `api.index:app` in `pyproject.toml`, so
Vercel sends the original request path directly to the ASGI app. Do not add a
catch-all rewrite to `/api/index`; that changes the path seen by FastAPI and
turns valid root routes into application-level `404` responses.

Used by [astro-unified-core](https://github.com/socraticsurge/astro-unified-core)
via the `DASHAFLOW_SIDECAR_URL` environment variable.

## Endpoints
- `GET /health` — liveness check, returns DashaFlow version
- `POST /calculate` — body `{date_of_birth, time_of_birth, latitude, longitude, timezone}`,
  returns the full DashaFlow chart (17 sections)
- `POST /transit`, `/career`, `/compatibility`, and `/muhurtha` — legacy application
  routes; their request, response, and authentication behavior is unchanged
- `POST /v1/profile/derive` — minimal server-to-server birth-profile contract described below
- `POST /v1/election-chart/derive` — bounded server-to-server election-chart batch
  described below

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
forms, and a birth date cannot be in the future in the supplied birthplace
timezone. The complete local civil time
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
    "janma_rashi": "Kumbha",
    "lagna": "Vrischika",
    "lagna_degree": 12.5,
    "planets": [
      {
        "name": "Surya",
        "rashi": "Mesha",
        "degree": 1.25,
        "house": 6,
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
or `unknown`; it is not inferred from the package description. The sidecar
fails closed if the Moon's rounded longitude disagrees with its Nakshatra,
Pada, or Janma Rashi, if a profile house disagrees with the Lagna-based Whole
Sign house, if Rahu and Ketu are not opposite within the two-decimal rounding
tolerance, or if a returned degree is not aligned to a hundredth of a degree.

Every response on this path, including errors, carries
`Cache-Control: private, no-store`. Invalid bodies return a sanitized `422`, an
unavailable calculation returns a sanitized `502`, and no raw engine exception
text is returned.

### Authentication and rollout

Set a high-entropy `DASHAFLOW_API_TOKEN` in the sidecar environment and send it
as `Authorization: Bearer <token>`. Generate at least 32 and at most 256 visible
ASCII characters; a 32-byte or longer random value encoded as hexadecimal or
base64url is suitable. This authentication applies to the private
`/v1/profile/derive` and `/v1/election-chart/derive` contracts; all legacy routes
remain compatible. Missing, malformed, or incorrect credentials return `401`.
If `DASHAFLOW_API_TOKEN` itself is absent, shorter than 32 characters, longer
than 256 characters, non-ASCII, or contains whitespace/control characters,
either contract fails closed with `503`.

The token is a server-to-server secret and must never be embedded in browser
code or a `VITE_*` variable. Roll out in this order:

1. Generate one independent secret and configure it as `DASHAFLOW_API_TOKEN` on
   the sidecar.
2. Deploy and verify the sidecar health route and an authenticated contract call.
3. Configure the same value in the server-side caller (currently
   `DASHAFLOW_SIDECAR_TOKEN`) together with `DASHAFLOW_SIDECAR_URL`.
4. Deploy the caller and verify the public gateway; rotate both token settings
   together when rotation is needed.

The caller and sidecar intentionally share the same private-contract bounds:
token length `32..256`, visible non-space ASCII only; contract version `1.0`;
engine `DashaFlow`; ayanamsha `Lahiri`; canonical Panchangam Nakshatra/Rashi
spellings; and the exact ordered, unique nine-graha sequence documented above.
Either service must fail closed if these invariants drift.

## Election-chart contract (`1.0`)

`POST /v1/election-chart/derive` accepts exactly a contract version, one
calculation location, and one to 24 candidate instants:

```json
{
  "contract_version": "1.0",
  "location": {
    "latitude": 17.385,
    "longitude": 78.4867,
    "timezone": "Asia/Kolkata"
  },
  "instants": [
    "2026-09-08T05:29:00.000Z",
    "2026-09-08T06:19:00+00:00"
  ]
}
```

Instants must be offset-aware RFC3339 timestamps and identify distinct absolute
moments. DashaFlow accepts minute-resolution chart times, so seconds and any
fractional seconds must be zero rather than being silently discarded. Each
instant must fall between 366 days before and 1,830 days after the server's
current UTC time, inclusive. The location follows the same numeric coordinate
and IANA-timezone validation as profile derivation. Extra fields are rejected.

Each timestamp is first normalized to its exact UTC instant for the engine
calculation. Latitude and longitude still determine the local horizon and
Ascendant; `location.timezone` is validated and preserved as response metadata.
This UTC invocation is contract-preserving for ordinary civil times and avoids
discarding the offset during a daylight-saving transition. For example, the two
New York `01:30` wall times on a fall-back day remain distinct because callers
send `01:30-04:00` and `01:30-05:00` (equivalently, `05:30Z` and `06:30Z`). A
skipped spring-forward wall time is likewise not an input ambiguity: an
offset-aware instant always maps to one real local representation.

The response preserves the exact request strings and order, so a caller can
join each chart to its candidate without relying on array sorting or timestamp
reformatting:

```json
{
  "contract_version": "1.0",
  "engine": {
    "name": "DashaFlow",
    "version": "1.1.0",
    "ayanamsha": "Lahiri",
    "ephemeris": "moshier",
    "node_convention": "mean"
  },
  "house_system": "whole_sign",
  "location": {
    "latitude": 17.385,
    "longitude": 78.4867,
    "timezone": "Asia/Kolkata"
  },
  "data": {
    "charts": [
      {
        "instant": "2026-09-08T05:29:00.000Z",
        "lagna": {"rashi": "Vrischika", "degree": 12.5},
        "planets": [
          {
            "name": "Surya",
            "rashi": "Simha",
            "degree": 21.4,
            "house": 10,
            "retrograde": false
          }
        ]
      }
    ]
  }
}
```

The actual `planets` array always contains the same canonical nine-graha order
as profile derivation: `Surya`, `Chandra`, `Kuja`, `Budha`, `Guru`, `Shukra`,
`Shani`, `Rahu`, `Ketu`. Houses are derived using the whole-sign convention from
the returned Lagna and Rashi, rather than forwarding an undocumented engine
field. `ephemeris` is `swiss`, `moshier`, or `unknown` when all snapshots agree,
and `mixed` when a batch crosses ephemeris sources. `node_convention` is
contract-bound to `mean`; callers must reject another value rather than blend
different Rahu/Ketu conventions into one scoring run. DashaFlow rounds
within-sign degrees to two decimals, so the sidecar normalizes the engine's
legitimate boundary representation of `30.0` to the largest value below 30
while preserving the sign the engine selected. Values greater than 30 remain
malformed. Values not aligned to a hundredth of a degree and chart snapshots
whose Rahu/Ketu axis is not opposite within the rounding tolerance also fail
closed.

This is an astronomical projection contract, not a Muhurtam scoring endpoint.
It accepts no activity, profile, name, natal-chart, or birth data. Invalid bodies
return a sanitized `422`, private-contract bodies above 16 KiB return a
sanitized `413`, and unavailable calculations return a sanitized `502`.
Every response on the path, including errors, carries
`Cache-Control: private, no-store`, and raw engine exceptions are neither logged
nor returned.

### Repository capture and validation boundary

`tests/fixtures/election_chart_repository_capture.json` records deterministic
DashaFlow `1.1.0` projections immediately before and after minute-level Lagna
changes in Hyderabad (`Asia/Kolkata`) and New York
(`America/New_York`). The tests replay each request twice, protect canonical
graha fields and whole-sign house changes, exercise both representations of a
New York DST fold, and verify that the UTC invocation matches DashaFlow's local
invocation for ordinary unambiguous instants.

This fixture is a **repository engine capture**, not independent astronomical
or traditional-source validation. It can detect conversion, ordering,
projection, and dependency drift within the pinned model. It cannot establish
that the underlying ephemeris, ayanamsha choice, house convention, or Muhurtam
interpretation is externally correct. DashaFlow returns degrees rounded to two
decimal places, so the capture uses an absolute tolerance of `0.01°`; Rashi,
graha order, retrograde flags, houses, boundary direction, and request ordering
remain exact assertions.

## Local

Python 3.12 is the pinned Vercel and CI runtime (`.python-version`).

```bash
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Run contract tests with:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```
