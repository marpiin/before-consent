# Method

This document describes how before-consent measures a home page, how it classifies what it sees, and where each interpreted signal comes from. Anything without a source below is not interpreted and stays `unknown`.

## What one visit does

1. Read `robots.txt` for the site (see below). If the home page is disallowed, the site is skipped for the whole run and the reason is stored.
2. Open a new browser context: no profile, locale `es-ES`, time zone `Europe/Madrid`, a 1366 by 768 viewport, service workers blocked, downloads refused, no permissions granted, HTTPS errors not ignored. Dialogs are dismissed and pop-ups closed as soon as they open.
3. Load the home page and wait for the `load` event, then wait a settle period (8 s by default) because many tags fire late.
4. Capture, in this order: the list of requests the browser made, the detected consent manager signals, the `localStorage` and `sessionStorage` keys of every frame, and the cookies in the context.
5. Close the context.

The tool never clicks, scrolls, types or submits anything, so everything recorded happened before the visitor made any choice. A visit must fit in 45 s; if the `load` event does not arrive in time the visit is stored as `failed` with its cause. If the main document answers with an HTTP error, the visit is stored as `http_error`. Only `ok` visits are classified.

Each site is visited 3 times by default, in rotating order: every site once per round, so two visits to one site are a whole round apart. One browser runs at a time, with at least 5 s between any two visits and at least 30 s between two visits to the same site, both measured from the end of the previous visit.

## Network guard

Playwright's `page.route()` is not called for the hops of a redirect. We checked this: a fulfilled or real `302` to another address is followed by the browser without the route handler seeing the second request. A guard built on `route()` alone could therefore be bypassed by any page that redirects a subresource to `169.254.169.254`.

So the browser is launched with a local forward proxy (`before_consent/netguard.py`) and every connection goes through it, including redirects, subresources, workers and websockets. The proxy:

- accepts only `http` and `https` (and `CONNECT` tunnels, which carry `https` and `wss`);
- resolves the host itself and checks every address with Python's `ipaddress` module;
- refuses the connection if any address is loopback, private, link-local (including `169.254.169.254`), shared, multicast, reserved or otherwise not global;
- connects to the exact address it checked.

Refused hosts are remembered for the visit, and the matching requests are stored with a `blocked_reason`. Blocked requests are not counted as contact with a third party. Requests whose host does not resolve are refused the same way and stored with the DNS error as the reason.

WebRTC is restricted to proxied connections with `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`, and since the proxy has no UDP support, WebRTC cannot reach any address directly.

`--allow-local` lets the proxy reach loopback and private addresses, never link-local ones. It exists for tests that serve pages from this machine (the report self-audit and the demo) and is hidden from the CLI help.

DNS rebinding is out of scope. Because the proxy connects to the address it checked, a name that changes its answer between the check and the connection cannot slip through, but we make no further claims about rebinding attacks.

Chromium makes some background requests of its own (component updates, time checks). They pass through the same guard. They are not attributed to any site, because the request log is built from page events, not from the proxy.

## robots.txt

`robots.txt` is fetched once per site and run, in a browser context with JavaScript off, with the same User-Agent and through the same guard. Errors follow RFC 9309 section 2.3.1:

- `2xx`: the body (first 500 KiB) is parsed with `urllib.robotparser` and checked for the product token `before-consent-audit`;
- `4xx`: treated as allow ("unavailable");
- `5xx`, network errors and refusals by the guard: treated as complete disallow ("unreachable").

Source: RFC 9309, "Robots Exclusion Protocol (REP)", https://www.rfc-editor.org/rfc/rfc9309.html

## User-Agent

The User-Agent is the browser's own string followed by `before-consent-audit/<version> (+<contact>)`. The contact comes from `before-consent.toml` and has no default. Without it, `run` and `verify-targets` refuse to start. Headless Chromium says `HeadlessChrome` in its User-Agent, and the tool does not hide it.

## Trackers

Tracker domains come from the Disconnect tracking protection list (`services.json`), downloaded by `fetch-lists` with its source URL, download time and SHA-256 recorded in each run.

- A host matches if it, or any parent domain of it, is listed.
- Only these Disconnect categories count as tracking: Advertising, Analytics, Social, FingerprintingInvasive, FingerprintingGeneral, Cryptomining. A domain listed under several takes the first in this order.
- Content, Email, EmailAggressive and Anti-fraud are left out. Content covers services that also deliver page content (Disconnect lists `google.com` there), and the email categories describe email tracking, not web pages.
- ConsentManagers is not tracking; it is used to detect consent managers (below).
- A request only counts as a tracker request when it is third party: its registrable domain, computed with `tldextract` from the bundled public suffix snapshot, differs from the site's.

Source: Disconnect, https://github.com/disconnectme/disconnect-tracking-protection, licensed CC BY-NC-SA 4.0.

## Consent signals

### Google `gcs`

Google's consent mode overview says the `gcs` parameter "is used to transmit the ad_storage and analytics_storage parameters", and that while consent is denied the tags send measurements without cookies.

Source: Google, "Consent mode overview", https://developers.google.com/tag-platform/security/concepts/consent-mode

Google does not document the encoding of the value. We use Simo Ahava's technical analysis: the value has the form `G1xy`, where `x` is ad_storage and `y` is analytics_storage, `1` granted and `0` denied. We also accept `-` as "not set" and record it as such.

Source: Simo Ahava, "Consent Mode V2 For Google Tags", https://www.simoahava.com/analytics/consent-mode-v2-google-tags/

`gcs` is only read on requests to domains Disconnect attributes to Google. The stored value is the interpretation, for example `gcs ad_storage=denied analytics_storage=denied`. A value that does not match the pattern is stored as `gcs=unrecognized`. The raw value is never stored.

### Not interpreted

- `gcd`: the same article describes its letter codes but warns that they "might change in the future", and Google does not document them. Unknown.
- `dma`, `npa`, `gdpr`, `gdpr_consent` (the TCF consent string) and any other vendor's consent parameters: unknown. Their names still appear in `param_names`.

## Known first-party tracker cookies

A first-party cookie counts as a tracker cookie only when its name is documented by the vendor that sets it:

| Cookie | Owner | Source |
| --- | --- | --- |
| `_ga`, `_ga_<container-id>` | Google | "[GA4] Cookie usage on websites", https://support.google.com/analytics/answer/11397207 |
| `_gcl_au`, `_gcl_aw`, `_gcl_dc` | Google | "Cookie information for Google's ad products", https://business.safety.google/adscookies/ |
| `_fbp`, `_fbc` | Meta | "ClickID and the fbp and fbc Parameters", https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/fbp-and-fbc/ |

Third-party cookies count when their domain is a listed tracker, for example `IDE` on `doubleclick.net`.

Unknown: `_gid` and `_gat` (not in the current GA4 cookie page), first-party cookie names of other vendors, and every `localStorage` or `sessionStorage` key name. Storage keys only count when they belong to a frame whose origin is a listed third-party tracker.

## Consent manager detection

A visit has a consent manager (CMP) signal if any of these is true:

| Signal | Source |
| --- | --- |
| `window.__tcfapi` is a function | IAB Tech Lab, "Consent Management Platform API" (TCF v2): "Every consent manager MUST provide the following API function", https://github.com/InteractiveAdvertisingBureau/GDPR-Transparency-and-Consent-Framework/blob/master/TCFv2/IAB%20Tech%20Lab%20-%20CMP%20API%20v2.md |
| `window.Cookiebot` exists | Cookiebot developer documentation, https://www.cookiebot.com/en/developer/ |
| `window.Didomi` exists | Didomi, "API", https://developers.didomi.io/cmp/web-sdk/reference/api |
| `window.OneTrust` exists | OneTrust, "Web CMP JavaScript Methods", https://developer.onetrust.com/onetrust/docs/javascript-api |
| a request went to a domain in Disconnect's ConsentManagers category | Disconnect list, above |

Any other CMP is reported as not detected, which does not mean the site has none.

## Categories

All four are computed by the `finding` view in `schema.sql` over visits with status `ok`.

- `storage_before_choice`: a tracker cookie (listed third-party domain or documented first-party name) or a storage key in a listed third-party tracker frame, present at the end of the visit.
- `tracker_request_before_choice`: a request that reached a third-party tracker domain without a consent-denied signal. "Without a denied signal" includes requests with no signal at all and Google requests where `gcs` grants or leaves unset at least one of the two storages.
- `consent_aware_request`: a request to a third-party tracker where `gcs` says both ad_storage and analytics_storage are denied. In Google's Consent Mode these cookieless requests are part of the design, so this category is reported apart and is not an incident.
- `no_cmp_detected`: the visit reached at least one tracker and none of the CMP signals above was found.

A site shows a kind of finding when at least one of its `ok` visits shows it. The `consistency` query reports how often each kind repeats across rounds.

## What the results do not say

The report describes what was observed. It does not say whether any site complies with any law, and it does not cite legal texts.
