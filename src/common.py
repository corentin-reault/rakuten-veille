"""Shared HTTP + parsing helpers. Stdlib only."""
import urllib.request, urllib.parse, json, time, html, re

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def http_get(url, headers=None, timeout=20):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def http_get_json(url, headers=None, timeout=20):
    return json.loads(http_get(url, headers=headers, timeout=timeout))


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate(text, n=220):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())