# Data collected

The tool keeps the minimum needed to answer the questions in `queries/`. Values are read in memory only where needed to drop them or to interpret a known consent signal, and are never written to disk.

Never stored:

- cookie values;
- `localStorage` and `sessionStorage` values;
- URL parameter values, query strings and fragments;
- request or response bodies, headers, screenshots or page content;
- anything typed or shown in the page.

## run

| Column | Content |
| --- | --- |
| `started_at`, `finished_at` | UTC timestamps |
| `country` | the two-letter code given with `--country`; where the operator measured from |
| `tool_version` | before-consent version |
| `browser_channel`, `browser_version` | `chromium`, `chrome` or `msedge`, and its version |
| `list_source`, `list_sha256`, `list_fetched_at` | where the tracker list came from, its hash and download time |
| `config_sha256` | SHA-256 of the settings used, including the contact |
| `note` | optional free text from `--note` |

## site

`url` (home page only) and `category`, from `targets.csv`.

## visit

| Column | Content |
| --- | --- |
| `round` | 1 to the number of repetitions |
| `started_at`, `started_unix` | when the visit started |
| `status` | `ok`, `failed`, `http_error` or `skipped_robots` |
| `error` | the cause of a failure or skip, first line of the error only |
| `final_host` | host of the page after redirects |
| `http_status` | status of the main document |
| `load_ms` | milliseconds to the `load` event |
| `cmp` | detected CMP signals, for example `tcf,request:OneTrust` |

## request_log

One row per request the browser made, including blocked ones.

| Column | Content |
| --- | --- |
| `started_ms` | milliseconds since the visit started |
| `host` | request host |
| `path` | at most the first two path segments; segments longer than 32 characters or containing 4 or more digits in a row, 16 or more hex characters in a row, `=`, `;` or `,` are replaced with `{id}` |
| `resource_type` | Playwright's type: document, script, image, xhr, fetch, websocket... |
| `is_third_party` | registrable domain differs from the site's |
| `blocked_reason` | why the guard refused the connection, if it did |
| `param_names` | names of the URL parameters, sorted, comma-separated, at most 40, each cut to 100 characters |
| `consent_signal`, `consent_denied` | the interpreted Google `gcs` value, only on requests to Google tracker domains |
| `tracker_domain`, `tracker_owner`, `tracker_category` | the matching Disconnect entry for third-party trackers |

## cookie

Cookies present at the end of the visit: `name` (cut to 100 characters), `domain`, `expires_unix` (empty for session cookies), `secure`, `http_only`, `same_site`, `is_third_party`, and `tracker_owner` with `tracker_source` (`list` or `cookie_name`).

## storage_key

For every frame: `storage` (`local` or `session`), `origin_host`, `key` (cut to 100 characters), `is_third_party`, and `tracker_owner` when the origin is a listed third-party tracker.

## Published files

`report/index.html` and `report/data/*.csv` contain aggregates only, plus the request log of one representative visit. With `show_site_names = false` (the default):

- sites appear as pseudonyms such as `news-03`;
- in the request log, first-party hosts and non-tracker third-party hosts are replaced with a label and their paths are dropped, because they could name the site;
- categories with fewer than `min_sites_per_category` measured sites (5 by default) are left out of the category table and of `site_summary.csv`.

The SQLite database in `data/` holds site URLs and is not meant to be published. `data/` is in `.gitignore`.
