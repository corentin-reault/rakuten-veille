"""Mastodon search across a set of instances (public API, no auth)."""
import urllib.parse
from common import http_get_json, truncate

# Common French / large instances. Add more as you like.
INSTANCES = [
    "https://mastodon.social",
    "https://mastodon.fr",
    "https://piaille.fr",
]

def fetch(keywords, instances=None):
    out = []
    for inst in (instances or INSTANCES):
        for kw in keywords:
            q = urllib.parse.quote(kw)
            url = f"{inst}/api/v2/search?q={q}&limit=40&resolve=false"
            try:
                data = http_get_json(url)
            except Exception as e:
                print(f"  [mastodon {inst}] erreur {kw}: {e}")
                continue
            for s in data.get("statuses", []):
                out.append({
                    "plateforme": f"mastodon",
                    "date": s.get("created_at", ""),
                    "texte": truncate(s.get("content", "")),
                    "auteur": s.get("account", {}).get("acct", ""),
                    "url": s.get("url", ""),
                    "mots_cles": kw,
                    "_instance": inst,
                })
    return out