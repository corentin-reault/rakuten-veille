"""Google News RSS by keyword. No key needed."""
import urllib.parse
from common import http_get, strip_html, truncate

# Google News RSS params: hl=fr, gl=FR, ceid=FR:fr
def fetch(keywords):
    out = []
    for kw in keywords:
        q = urllib.parse.quote(kw)
        url = ("https://news.google.com/rss/search?"
               f"q={q}&hl=fr&gl=FR&ceid=FR%3Afr")
        if not url.endswith('&'):
            url = url
        xml = http_get(url)
        items = _parse_items(xml)
        for it in items:
            out.append({
                "plateforme": "google_news",
                "date": it["date"],
                "texte": truncate(it["title"]),
                "auteur": it.get("source", ""),
                "url": it.get("link", ""),
                "mots_cles": kw,
            })
    return out


def _parse_items(xml):
    # minimal RSS/XML item parse
    items = []
    for block in re_split_items(xml):
        title = _grab(block, "title")
        link = _grab(block, "link")
        pub = _grab(block, "pubDate")
        source = _grab_source(block)
        items.append({
            "title": title, "link": link,
            "date": _norm_date(pub),
            "source": source,
        })
    return items


import re

def re_split_items(xml):
    return re.findall(r"<item>(.*?)</item>", xml, re.S)

def _grab(block, tag):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S)
    if not m:
        return ""
    return strip_html(m.group(1)).strip()

def _grab_source(block):
    m = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
    return m.group(1).strip() if m else ""

def _norm_date(d):
    if not d:
        return _now()
    from datetime import datetime, timezone
    try:
        dt = datetime.strptime(d, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return d

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")