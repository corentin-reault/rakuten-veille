"""Bluesky searchPosts. Use api.bsky.app (public.api.* is IP-blocked: 403).
Rate-limits burst requests -> space them out with a small sleep."""
import urllib.parse, time
from common import http_get_json, truncate

# api.bsky.app works from datacenter IPs; public.api.bsky.app is blocked (403).
PUBLIC = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"

def fetch(keywords, limit=100):
    out = []
    for kw in keywords:
        q = urllib.parse.quote(kw)
        cursor = None
        collected = 0
        while collected < limit:
            url = f"{PUBLIC}?q={q}&limit={min(50, limit - collected)}"
            if cursor:
                url += f"&cursor={urllib.parse.quote(cursor)}"
            try:
                data = http_get_json(url)
            except Exception as e:
                print(f"  [bluesky] erreur {kw}: {e}")
                time.sleep(2)  # backoff before next burst request
                break
            for p in data.get("posts", []):
                rec = p.get("record", {})
                out.append({
                    "plateforme": "bluesky",
                    "date": rec.get("createdAt", ""),
                    "texte": truncate(rec.get("text", "")),
                    "auteur": p.get("author", {}).get("handle", ""),
                    "url": _post_url(p),
                    "mots_cles": kw,
                })
                collected += 1
            cursor = data.get("cursor")
            if not cursor or not data.get("posts"):
                break
            time.sleep(1)  # avoid burst throttling while paginating
    return out


def _post_url(p):
    did = p.get("author", {}).get("did", "")
    # uri like at://did/... we only have rkey in cid? use record uri
    uri = p.get("uri", "")
    parts = uri.split("/")
    rkey = parts[-1] if len(parts) >= 4 else ""
    return f"https://bsky.app/profile/{did}/post/{rkey}" if did and rkey else uri