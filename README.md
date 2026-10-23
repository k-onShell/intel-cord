# CornyIntel

Public-source alias checks for Discord-related investigations. Python 3.9+, no dependencies.

## Run

```bash
python cornyintel.py --username exampleuser --discord-id 80351110224678912
python cornyintel.py --username exampleuser --output reports/case-one
```

Creates `.json` and `.html` reports. Open the HTML report in a browser.

## What is actually checked
- Discord snowflake ID -> embedded creation timestamp (not account verification)
- GitHub public user and latest five public events
- GitLab public user (exact username)
- Hacker News public user
- Manual web-search links for indexed mentions

## Limitations
Username reuse does not establish that accounts belong to the same person. Some APIs may rate-limit or block requests. `not_found` may indicate absence from the queried public API rather than nonexistence. Does not look up private identities, IPs, emails, Discord tokens, private messages, or hidden aliases. No API credentials used. No scraping Discord itself. Use for public-source documentation, not harassment or stalking.
