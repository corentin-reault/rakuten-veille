"""Apify connector: run an Actor (by platform) and return normalized posts.

Verified API (2026-08):
  - Actor ID uses '~' separator:  apidojo~tweet-scraper
  - POST /v2/actors/{id}/runs  -> starts a run, returns run object
  - GET  /v2/datasets/{datasetId}/items  -> the scraped rows
  - Use run-sync-get-dataset-items for a blocking call that returns items inline.

Token is read from env APIFY_TOKEN or local .apify_token file (never committed).
"""
import os, urllib.parse, time, json, urllib.request
from common import http_get_json, truncate, UA

# category -> Apify ActorID. IDs verified against live Apify Store.
ACTORS = {
    "x":         "scrape.badger~twitter-tweets-scraper",
    "instagram": "apify~instagram-scraper",
    "tiktok":    "clockworks~tiktok-scraper",
    "facebook":  "danek~facebook-search-ppr",
    "linkedin":  "harvestapi~linkedin-post-search",
    "reddit":    "scrape.badger~reddit-scraper",
}


def _load_token():
    t = os.environ.get("APIFY_TOKEN")
    if t:
        return t
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".apify_token")
    if os.path.exists(p):
        with open(p) as f:
            return f.read().strip()
    return None


def _g(item, *keys):
    """Return first non-empty value, descending into nested dicts (dotted keys or dict values)."""
    for k in keys:
        if "." in k:
            a, b = k.split(".", 1)
            if isinstance(item.get(a), dict):
                v = item[a].get(b)
                if v:
                    return str(v)
            continue
        v = item.get(k)
        if v:
            # could be a small metadata dict (e.g. {'type':'user'}) -> skip
            if isinstance(v, dict):
                continue
            return str(v)
    return ""


def _extract(platform, row):
    """Map one Apify dataset row to our normalized dict."""
    text = (_g(row, "caption", "text", "description", "fullText", "comment",
               "body", "full_text", "title", "message", "postText",
               "videoDescription", "content") or "")
    # Reddit: combine title + selftext/body for a fuller record
    if platform == "reddit":
        _title = str(_g(row, "title") or "")
        _body = str(_g(row, "selftext", "body", "text") or "")
        if _body and _body not in ("[removed]", "[deleted]"):
            text = f"{_title}. {_body}".strip()
        elif _title:
            text = _title
    auteur = _g(row, "user.username", "username", "user_name", "userName",
                "author.username", "author.screenName", "author.name",
                "author.publicName", "authorMeta.name", "author.universalName",
                "author", "ownerUsername", "displayName", "authorName",
                "urlUserName", "user.screenName", "handle", "inReplyToUsername")
    date = _g(row, "createdAt", "created_at", "timestamp", "date",
              "publishedAt", "twitterCreatedAt", "postedAt")
    url = _g(row, "url", "postUrl", "canonicalUrl", "webUrl", "webVideoUrl",
             "permanentUrl", "link", "permalink", "linkedinUrl",
             "shareLinkedinUrl")
    # Reddit permalink is relative (/r/.../comments/...) -> build absolute URL
    if platform == "reddit" and url and url.startswith("/"):
        url = "https://www.reddit.com" + url
    # X/Twitter has no direct url field -> construct x.com/<user>/status/<id>
    if not url and platform == "x":
        base = _g(row, "username", "user_name", "user.screenName")
        tid = _g(row, "id", "tweet_id", "conversation_id")
        if tid and tid.isdigit():
            handle = base.lstrip("@") if base else ""
            url = f"https://x.com/{handle}/status/{tid}"
    return {
        "plateforme": platform,
        "date": _norm_date(date),
        "texte": truncate(text),
        "auteur": auteur,
        "url": url,
        "mots_cles": "",
    }


def _norm_date(d):
    """Normalize a date to ISO YYYY-MM-DD[THH:MM:SSZ] when possible; else '' (or as-is)."""
    # LinkedIn posts wrap {timestamp, date, ...} in an object
    if isinstance(d, dict):
        if d.get("date"):
            d = d["date"]
        elif d.get("timestamp"):
            ts = d["timestamp"]
            # epoch can be ms (13, 16 digits) or seconds (10)
            div = 1000 if len(str(ts)) >= 13 else 1
            try:
                import datetime
                return datetime.datetime.fromtimestamp(int(ts)/div,
                         datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return ""
        else:
            return ""
    if not d:
        return ""
    d = str(d).strip()
    # epoch seconds (Facebook etc.)
    if d.isdigit() and len(d) >= 10:
        try:
            import datetime
            ts = int(d)
            # milliseconds (13+ digits)
            if len(d) >= 13:
                ts = ts / 1000.0
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return d
    # ISO already: truncate to date
    if len(d) >= 10 and d[4] == "-":
        return d[:10]
    # Text-ish dates like 'Mon Aug 10' (X sends these) -> parse with current year
    # Verify "Wed May 06", "Tue Aug 25", and full 'Fri Aug 07 08:35:02 +0000 2026'
    return _parse_twitter_ts(d)


def _parse_twitter_ts(d):
    import datetime, re as _re
    # Full format: 'Fri Aug 07 08:35:02 +0000 2026' (has year at end)
    m = _re.match(r"^\s*(?:\w{3,9}\s+)?([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+([+-]\d{4})\s+(\d{4})\s*$", d)
    if m:
        mon_s, day_s, _hhmm, _off, yr_s = m.groups()
        mon = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}.get(mon_s.lower()[:3])
        if mon:
            try:
                dt = datetime.date(int(yr_s), mon, int(day_s))
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return d
    # Short: 'Wed May 06' / 'Tue Aug 25' (no year) -> assume current year
    m2 = _re.match(r"^\s*(?:\w{3,9}\s+)?([A-Za-z]{3})\s+(\d{1,2})\s*$", d)
    if m2:
        mon = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}.get(m2.group(1).lower()[:3])
        if mon:
            day = int(m2.group(2))
            yr = datetime.datetime.now(datetime.timezone.utc).year
            try:
                dt = datetime.date(yr, mon, day)
                if dt > datetime.date.today() + datetime.timedelta(days=30):
                    dt = datetime.date(yr-1, mon, day)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return d
    return d


def _input(platform, keyword, limit):
    """Build the actor input for the given platform/keyword (per actor input-schema)."""
    if platform == "x":
        # scrape.badger/twitter-tweets-scraper: mode must be 'Advanced Search'
        # (default 'Get Tweet by ID' fails needing an id). query + query_type.
        return {"mode": "Advanced Search", "query": keyword,
                "query_type": "Latest", "max_results": limit}
    if platform == "reddit":
        # scrape.badger/reddit-scraper: mode 'Search Posts' + query + max_results
        # (PAY_PER_EVENT, ~$1/1k items; no rental required, unlike trudax paywall)
        return {"mode": "Search Posts", "query": keyword,
                "max_results": limit, "sort": "relevance", "time_filter": "all"}
    if platform == "tiktok":
        # clockworks/tiktok-scraper: searchQueries (array) + resultsPerPage.
        # searchSection enum is ["", "/video", "/user"] -> use "/video".
        return {"searchQueries": [keyword], "resultsPerPage": limit,
                "searchSection": "/video"}
    if platform == "instagram":
        # Direct URL to the hashtag explore page = robust way to get POSTS
        # (searchType=hashtag via Google returns tag names, not posts).
        tag = keyword.lstrip("#").replace(" ", "")
        return {"directUrls": [f"https://www.instagram.com/explore/tags/{tag}/"],
                "resultsType": "posts", "resultsLimit": limit}
    if platform == "facebook":
        # danek/facebook-search-ppr: query + search_type + max_posts
        return {"query": keyword, "search_type": "posts", "max_posts": limit}
    if platform == "linkedin":
        # harvestapi/linkedin-post-search: searchQueries (array) + maxPosts.
        # Target the topic precisely to avoid "top posts" global noise.
        q = f'"{keyword}" fermeture'
        return {"searchQueries": [q], "maxPosts": limit}
    return {"query": keyword, "maxItems": limit}


def fetch(platform, keyword, limit=50, token=None, timeout=240):
    """Run actor for 'platform' with 'keyword', wait, drain dataset -> posts.

    Retries once if the sync call returns an empty/non-JSON body (the dataset
    can lag the run completion -> Apify may return 200 with 'undefined' body).
    """
    token = token or _load_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN manquant")
    actor = ACTORS.get(platform)
    if not actor:
        raise ValueError(f"plateforme inconnue: {platform}")
    payload = _input(platform, keyword, limit)

    sync_url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}&timeout={timeout}"
    data = _post_json_safe(sync_url, payload)
    if data is None:
        time.sleep(5)  # dataset lag -> give it a moment, then retry once
        data = _post_json_safe(sync_url, payload)

    rows = data if isinstance(data, list) else data.get("items", data.get("data", []))
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("noResults"), bool) or "noResults" in r:
            continue
        norm = _extract(platform, r)
        if not norm["texte"].strip():
            continue
        norm["mots_cles"] = keyword
        out.append(norm)
    return out


def _post_json_safe(url, payload):
    """POST to run-sync; return parsed JSON, or None on empty/non-JSON body."""
    try:
        return _post_json(url, payload)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [apify] body non-JSON/empty: {e}")
        return None


def _post_json(run_url, payload):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    return _request(run_url, bytes=body, headers=headers)


def _request(url, bytes=None, headers=None, timeout=300):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=bytes, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return json.loads(raw)