"""SQLite store for normalized posts + daily aggregation."""
import sqlite3, os, json

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plateforme TEXT,
    date TEXT,
    texte TEXT,
    auteur TEXT,
    url TEXT,
    mots_cles TEXT,
    content_hash TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_dedup ON posts(plateforme, content_hash);
CREATE INDEX IF NOT EXISTS idx_posts_plat_date ON posts(plateforme, date);
"""

class Store:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)

    def insert(self, items, relevance=None):
        """Dedupe by content fingerprint + optional relevance filter.

        relevance: callable(text)->bool. When given, only rows where it returns
        True are stored, so noise (off-topic posts) is dropped at ingestion.
        """
        relevance = relevance or (lambda t: True)
        n_new = 0
        for it in items:
            text = (it.get("texte", "") or "").strip()
            if not relevance(text):
                continue
            fp = _fingerprint(text)
            if not fp:
                continue
            try:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO posts(plateforme,date,texte,auteur,url,mots_cles,content_hash) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (it["plateforme"], it.get("date", ""), text,
                     it.get("auteur", ""), it.get("url", ""),
                     it.get("mots_cles", ""), fp),
                )
                n_new += cur.rowcount
            except Exception:
                pass
        self.conn.commit()
        return n_new

    def count_rows(self):
        try:
            return self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        except Exception:
            return 0

    def daily_report(self, window_days=7):
        from datetime import datetime, timezone, timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.conn.execute(
            """SELECT substr(date,1,10) AS jour, plateforme, COUNT(*)
               FROM posts WHERE datetime(date) >= ? GROUP BY jour, plateforme
               ORDER BY jour DESC""", (since,)).fetchall()
        # group by jour
        by_day = {}
        for jour, plat, cnt in rows:
            by_day.setdefault(jour, {})[plat] = cnt
        return by_day

    def close(self):
        self.conn.close()


def _fingerprint(text):
    """Normalize text (lowercase, strip accents/punct/whitespace) -> stable hash."""
    import re, unicodedata, hashlib
    t = text.lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 20:  # too short to be a meaningful signature
        return ""
    return hashlib.sha1(t.encode()).hexdigest()[:24]


# --- Relevance filter for the topic closure ("fermeture Rakuten France") ---
# Closure/activity vocabulary
_CLOSURE = (
    "fermeture", "fermera", "ferme", "clos", "cesse", "c'est la fin", "la fin",
    "fini", "dernier", "au revoir", "disparait", "dispara", "30 septembre",
    "arrete", "arret", "liquidation", "activite", "place de marche",
    "marketplace", "repreneur", "annonce", "price minister est", "rachet",
    "rachat", "solde", "e-commerce ferme", "site ferme", "video", "bons plans",
)
# Remarque: "fin" seul est trop vague (évite). Utilisons "la fin"/"c'est la fin".

_RAKUTEN = ("rakuten", "priceminister", "ex-priceminister", "price minister")

def is_relevant(text):
    """True if the post plausibly concerns the closure of Rakuten France.

    Tolerant: keep if it mentions Rakuten AND (a closure term OR a marketplace/
    activity word), which captures short social posts without over-filtering.
    """
    t = (text or "").lower()
    if not any(r in t for r in _RAKUTEN):
        return False
    # closure OR activity/marketplace context
    return any(c in t for c in _CLOSURE)