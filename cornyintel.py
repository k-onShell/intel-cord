#!/usr/bin/env python3
"""CornyIntel: public-source Discord alias investigator. Python 3.9+; stdlib only."""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

EPOCH = 1420070400000
UA = "CornyIntel/1.0 (public-profile-investigation; no authentication)"

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def fetch_json(url):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=12) as response:
            if int(response.headers.get("Content-Length", "0")) > 1_000_000:
                return {"status": "error", "error": "Response too large", "source": url}
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                return {"status": "error", "error": "Response too large", "source": url}
            return {"status": "ok", "data": json.loads(raw), "source": url}
    except HTTPError as exc:
        status = "not_found" if exc.code == 404 else ("rate_limited" if exc.code == 429 or (exc.code == 403 and "api.github.com" in url) else "unavailable")
        return {"status": status, "http_status": exc.code, "source": url}
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "error", "error": str(exc), "source": url}

def discord_id_info(user_id):
    if not re.fullmatch(r"\d{17,20}", user_id):
        return {"status": "invalid", "note": "Expected a 17–20 digit numeric Discord ID."}
    stamp_ms = (int(user_id) >> 22) + EPOCH
    date = dt.datetime.fromtimestamp(stamp_ms / 1000, tz=dt.timezone.utc)
    if date > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1):
        return {"status": "invalid", "note": "Timestamp is in the future."}
    return {"status": "decoded", "id": user_id, "created_at_utc": date.isoformat(),
            "profile_link": f"https://discord.com/users/{user_id}",
            "note": "Snowflake timestamp is decoded mathematically; this does not verify account existence."}

def github_check(username):
    name = quote(username, safe="")
    api = fetch_json(f"https://api.github.com/users/{name}")
    result = {"status": api["status"], "source": api["source"]}
    if api["status"] != "ok":
        result.update({k: api[k] for k in ("http_status", "error") if k in api})
        return result
    u = api["data"]
    result.update({"status": "found", "url": u.get("html_url"), "username": u.get("login"),
                   "created_at": u.get("created_at"), "public_repos": u.get("public_repos"),
                   "followers": u.get("followers"), "bio": u.get("bio"), "blog": u.get("blog"),
                   "company": u.get("company")})
    events = fetch_json(f"https://api.github.com/users/{name}/events/public?per_page=5")
    if events["status"] == "ok" and isinstance(events["data"], list):
        result["recent_public_events"] = [{"type": e.get("type"), "repo": (e.get("repo") or {}).get("name"),
                                            "at": e.get("created_at")} for e in events["data"]]
    else:
        result["events_status"] = events["status"]
    return result

def gitlab_check(username):
    url = "https://gitlab.com/api/v4/users?" + urlencode({"username": username})
    api = fetch_json(url)
    result = {"status": api["status"], "source": url}
    if api["status"] != "ok":
        result.update({k: api[k] for k in ("http_status", "error") if k in api})
        return result
    users = api["data"] if isinstance(api["data"], list) else []
    matches = [u for u in users if str(u.get("username", "")).lower() == username.lower()]
    if not matches:
        return {"status": "not_found", "source": url}
    u = matches[0]
    return {"status": "found", "source": url, "url": u.get("web_url"),
            "username": u.get("username"), "account_state": u.get("state")}

def hn_check(username):
    url = f"https://hacker-news.firebaseio.com/v0/user/{quote(username, safe='')}.json"
    api = fetch_json(url)
    if api["status"] != "ok":
        return {"status": api["status"], "source": url}
    u = api["data"]
    if not u:
        return {"status": "not_found", "source": url}
    return {"status": "found", "source": url,
            "url": f"https://news.ycombinator.com/user?id={quote(username, safe='')}",
            "username": u.get("id"), "karma": u.get("karma"),
            "created_at": dt.datetime.fromtimestamp(u["created"], tz=dt.timezone.utc).isoformat() if u.get("created") else None}

def search_links(username, user_id):
    q = f'"{username}"' if username else f'"{user_id}"'
    queries = {"Web exact match": q, "Discord mentions": q + " discord",
               "Reddit mentions": q + " site:reddit.com",
               "GitHub mentions": q + " site:github.com"}
    if user_id:
        queries["Discord ID mentions"] = f'"{user_id}"'
    return {name: "https://www.google.com/search?" + urlencode({"q": query}) for name, query in queries.items()}

def write_html(report, path):
    safe = lambda value: html.escape(str(value), quote=True)
    rows = []
    for service, finding in report["checks"].items():
        url = finding.get("url")
        link = (f'<a href="{safe(url)}" rel="noopener noreferrer">View public profile</a>' if url and url.startswith("https://") else "")
        rows.append(f"<tr><td>{safe(service)}</td><td>{safe(finding.get('status', '?'))}</td><td>{link}</td><td><pre>{safe(json.dumps(finding, indent=2, ensure_ascii=False))}</pre></td></tr>")
    links = "".join(f'<li><a href="{safe(url)}">{safe(label)}</a></li>' for label, url in report["manual_searches"].items())
    page = f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>CornyIntel report</title><style>
    body{{font:15px system-ui,sans-serif;max-width:1150px;margin:auto;padding:24px;background:#10151c;color:#ebf0f5}}
    a{{color:#83c9ff}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #405062;padding:12px;text-align:left;vertical-align:top}}
    pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-width:620px}}.note{{color:#ffcc8a}}</style></head><body>
    <h1>CornyIntel public-source report</h1><p>Generated: {safe(report['generated_at'])}</p>
    <p>Username: {safe(report['input'].get('username'))} | Discord ID: {safe(report['input'].get('discord_id'))}</p>
    <p class="note">Username matches are NOT proof of common ownership. No private Discord profile data was collected.</p>
    <h2>Discord ID</h2><pre>{safe(json.dumps(report['discord'], indent=2))}</pre>
    <h2>Live public API checks</h2><table><tr><th>Service</th><th>Status</th><th>Link</th><th>Evidence</th></tr>{''.join(rows)}</table>
    <h2>Manual public searches</h2><ul>{links}</ul>
    <p>Unavailable and rate-limited results are inconclusive. Sources were checked at report generation time.</p></body></html>'''
    path.write_text(page, encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(description="Public-source Discord alias OSINT. Does not deanonymize users.")
    ap.add_argument("--username", help="Public username/alias to check on independent sites")
    ap.add_argument("--discord-id", help="Numeric Discord user ID to decode")
    ap.add_argument("--output", default="cornyintel-report", help="Output filename prefix")
    args = ap.parse_args()
    if not (args.username or args.discord_id):
        ap.error("Provide --username and/or --discord-id")
    if args.username and (not 1 <= len(args.username) <= 40 or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.username)):
        ap.error("Username must be 1–40 characters, consisting of letters, numbers, _, . or -")
    if args.discord_id and not re.fullmatch(r"\d{17,20}", args.discord_id):
        ap.error("Discord ID must contain 17–20 digits")
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"tool": "CornyIntel 1.0", "generated_at": now(),
              "input": {"username": args.username, "discord_id": args.discord_id},
              "discord": discord_id_info(args.discord_id) if args.discord_id else {"status": "not_provided"},
              "checks": {}, "manual_searches": search_links(args.username, args.discord_id),
              "interpretation": "Matching usernames may belong to different people. Do not use as identity proof."}
    if args.username:
        for name, checker in (("GitHub", github_check), ("GitLab", gitlab_check), ("Hacker News", hn_check)):
            print(f"[+] Checking {name}...", flush=True)
            report["checks"][name] = checker(args.username)
            print(f"    {report['checks'][name]['status']}", flush=True)
            time.sleep(0.4)
    json_path = path.with_suffix(".json")
    html_path = path.with_suffix(".html")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(report, html_path)
    print(f"\nReports saved: {json_path}  |  {html_path}")

if __name__ == "__main__":
    main()
