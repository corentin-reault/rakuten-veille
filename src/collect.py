"""K8s CronJob entrypoint: run the full collection and store into SQLite.

DB path from env DB_PATH (defaults to ./posts.db). No install/network
persistence is needed here — pure stdlib.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import KEYWORDS
import fetch_google_news, fetch_bluesky, fetch_reddit, fetch_mastodon
from store import Store, is_relevant

DB_PATH = os.environ.get("DB_PATH", os.path.join("/data", "posts.db"))

FETCHERS = [
    ("google_news", fetch_google_news.fetch),
    ("bluesky",     fetch_bluesky.fetch),
    ("reddit",      fetch_reddit.fetch),
    ("mastodon",    fetch_mastodon.fetch),
]

# Optional paid coverage via Apify (token from env APIFY_TOKEN -> K8s Secret).
# Free tier verified: x, instagram, tiktok, facebook, linkedin. Reddit paywalled.
APIFY_PLATFORMS = ["instagram", "tiktok", "facebook", "linkedin", "x"]


def collect():
    all_items = []
    for name, fn in FETCHERS:
        print(f"[{name}] recherche...", flush=True)
        try:
            items = fn(KEYWORDS)
            print(f"  -> {len(items)} resultats (bruts)", flush=True)
            all_items.extend(items)
        except Exception as e:
            print(f"  -> ERREUR: {e}", flush=True)

    if APIFY_PLATFORMS:
        import fetch_apify
        for plat in APIFY_PLATFORMS:
            print(f"[apify:{plat}] recherche...", flush=True)
            try:
                plat_items = []
                for kw in KEYWORDS:
                    plat_items.extend(fetch_apify.fetch(plat, kw, limit=30))
                print(f"  -> {len(plat_items)} resultats (bruts)", flush=True)
                all_items.extend(plat_items)
            except Exception as e:
                print(f"  -> ERREUR: {e}", flush=True)
    return all_items


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    items = collect()
    store = Store(DB_PATH)
    n_new = store.insert(items, relevance=is_relevant)
    total = store.count_rows()
    print(f"\nInsertions nouvelles en base (post-filtre pertinence): {n_new} "
          f"(total base: {total})", flush=True)
    print("\n=== Rapport quotidien (posts par jour / plateforme) ===")
    for jour, plats in store.daily_report(7).items():
        tot = sum(plats.values())
        print(f"\n{jour}  (total {tot})", flush=True)
        for plat, cnt in sorted(plats.items(), key=lambda x: -x[1]):
            print(f"    {plat:<14} {cnt}", flush=True)
    store.close()
    return n_new


if __name__ == "__main__":
    main()