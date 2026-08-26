"""Reddit search via public JSON endpoint (no auth, honest User-Agent)."""
import urllib.parse
from common import http_get_json, truncate

def fetch(keywords, limit=50):
    out = []
    for kw in keywords:
        q = urllib.parse.quote(kw)
        url = (f"https://www.reddit.com/search.json?q={q}"
               f"&limit={limit}&sort=new")
        try:
            data = http_get_json(url, headers={"User-Agent": "reault-social-listener-poc/0.1 (research)"})
        except Exception as e:
            print(f"  [reddit] erreur {kw}: {e}")
            continue
        for ch in data.get("data", {}).get("children", []):
            d = ch.get("data", {})
            created = d.get("created_utc", 0)
            from datetime import datetime, timezone
            date = datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if created else ""
            out.append({
                "plateforme": "reddit",
                "date": date,
                "texte": truncate(d.get("title", "")),
                "auteur": d.get("author", ""),
                "url": "https://reddit.com" + (d.get("permalink", "") or ""),
                "mots_cles": kw,
            })
    return out