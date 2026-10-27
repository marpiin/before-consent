# before-consent

before-consent opens the home pages of a list of public websites in a clean browser, does not touch the cookie banner, and records what the page loads and stores before the visitor decides anything: requests to third parties, cookies and storage keys. It stores the results in SQLite, analyses them with the SQL files in `queries/`, and writes a static HTML report with the method, the results and the limitations.

It is a measurement tool. The report describes what was observed and does not say whether a site complies with any law.

## How it measures

For each site in `targets.csv`:

1. It reads `robots.txt` with an honest User-Agent and skips the site if the home page is disallowed. Server errors count as disallow, client errors as allow (RFC 9309).
2. It opens the home page in a new browser context with no profile, Spanish locale and Madrid time zone, waits for the `load` event and then 8 more seconds.
3. Without clicking anything, it records every request, the cookies, the `localStorage` and `sessionStorage` keys, and whether a consent manager is present.
4. It repeats this 3 times per site in rotating order, with at least 5 s between visits and 30 s between visits to the same site.

Requests are matched against the Disconnect tracker list and classified into four kinds:

- `storage_before_choice`: a tracker cookie or storage key exists before any interaction.
- `tracker_request_before_choice`: a request reached a tracker without a consent-denied signal.
- `consent_aware_request`: a request reached a Google tracker carrying a `gcs` value that denies both ad and analytics storage. These are reported apart and are not incidents, since Consent Mode sends them by design.
- `no_cmp_detected`: trackers were contacted and no consent manager was found.

[docs/method.md](docs/method.md) has the details and the source for every interpreted signal. [docs/data-collected.md](docs/data-collected.md) lists every stored column; cookie values, storage values and URL parameter values are never stored.

### Safety

- The browser runs with its sandbox on, blocks service workers, downloads, permissions, dialogs and pop-ups, and does not ignore HTTPS errors.
- Every connection goes through a local proxy that resolves the host, checks each address with `ipaddress` and refuses loopback, private, link-local and other non-public ranges. A proxy is needed because Playwright's `page.route()` does not see redirect hops; the tests include a redirect to `169.254.169.254` that only the proxy can stop.
- No API keys or tokens are needed.
- The User-Agent ends with `before-consent-audit/<version> (+<contact>)`. The contact has no default, and real visits are refused until you set it.

## Running it

Python 3.11 or later. The commands are the same on Windows and Linux except for activating the virtual environment.

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-cache-dir -r requirements-dev.txt
python -m playwright install chromium --no-shell
python -m before_consent fetch-lists
python -m before_consent doctor
```

bash:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-cache-dir -r requirements-dev.txt
python -m playwright install chromium --no-shell
python -m before_consent fetch-lists
python -m before_consent doctor
```

Then set `contact` in `before-consent.toml` to a project URL or an address site owners can write to, and run:

```
python -m before_consent verify-targets          # DNS, robots.txt and HTTP status, once per site
python -m before_consent run --country ES        # every site, 3 rounds
python -m before_consent report                  # report/index.html and report/data/*.csv
python -m before_consent export                  # only the CSVs
```

`--country` records where you are measuring from; the tool cannot know it. `run --limit 3 --repetitions 1` visits only the first three sites once. With 40 sites and 3 rounds there are 120 visits of roughly 15 to 25 s each (load, 8 s settle, 5 s gap), so expect around 30 to 50 minutes; this is an estimate, not a measurement.

If Windows application control blocks Playwright's Chromium, use an installed browser instead: `python -m before_consent --browser-channel msedge doctor` (or `chrome`). The same flag works with every command.

Checks, all offline:

```
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
detect-secrets-hook --baseline .secrets.baseline (git ls-files)     # PowerShell
detect-secrets-hook --baseline .secrets.baseline $(git ls-files)    # bash
```

The tests serve fixture pages with `route.fulfill` on fake hosts (`site.example`, `tracker.example`) and make every DNS lookup fail, so nothing reaches the network. CI runs the same checks on every push and never audits a real website.

## Settings

`before-consent.toml` holds the contact, timings, browser channel, locale and paths. The politeness floors (5 s, 30 s, 45 s per visit) cannot be lowered. `show_site_names = false` makes the report use pseudonyms such as `news-03`, and `min_sites_per_category = 5` hides any category with fewer measured sites. A SHA-256 of the settings is stored with each run.

## What it cannot do

- It only sees the state before any choice. Measuring after "reject" or "accept" is future work; the demo below clicks its own banner in a test, but the CLI never does.
- It visits only the home page, from one IP, on one date. Sites show different banners, or none, by country and by time, and run A/B tests. The report repeats this.
- It runs headless and says so. Sites that detect automation may block it or change what they serve, and the tool does not try to hide.
- It recognises trackers only through the Disconnect list and consent signals only where documented (Google `gcs`). `gcd`, TCF consent strings and other vendors' signals are not interpreted.
- It detects a consent manager through the TCF API, Cookiebot, Didomi, OneTrust or a domain in Disconnect's ConsentManagers category. Any other is reported as not detected.
- There is no scheduled run in CI: from a CI region the results would describe the wrong country.

## Tracker list attribution

Tracker and consent manager domains come from the Disconnect tracking protection list, Copyright Disconnect, Inc., licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (https://creativecommons.org/licenses/by-nc-sa/4.0/). Source: https://github.com/disconnectme/disconnect-tracking-protection. The list is not included in this repository; `fetch-lists` downloads it and records its URL, date and SHA-256. Commercial use of the list needs a separate license from Disconnect.

## License

The code is MIT licensed; see [LICENSE](LICENSE).
