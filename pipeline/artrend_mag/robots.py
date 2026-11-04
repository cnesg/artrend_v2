"""RFC 9309 robots.txt matcher (longest-match, Allow wins ties, * and $ wildcards).

urllib.robotparser applies first-match order, which mis-reads files such as
"Disallow: /" followed by "Allow: /kr/whatson"; this module follows the RFC.
"""
from __future__ import annotations

import re
import urllib.parse


class Robots:
    def __init__(self, text: str):
        self.groups: list[tuple[list[str], list[tuple[str, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[str, str]] = []
        delay = None
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if last_was_rule:
                    self.groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], None
                agents.append(v.lower())
                last_was_rule = False
            elif k in ("allow", "disallow"):
                rules.append((k, v))
                last_was_rule = True
            elif k == "crawl-delay":
                try:
                    delay = float(v)
                except ValueError:
                    pass
                last_was_rule = True
        if agents:
            self.groups.append((agents, rules, delay))

    def _group(self, ua: str):
        token = ua.split("/")[0].lower()
        star = None
        for agents, rules, delay in self.groups:
            if any(a != "*" and a in token for a in agents):
                return rules, delay
            if "*" in agents and star is None:
                star = (rules, delay)
        return star or ([], None)

    @staticmethod
    def _pattern(path: str):
        anchored = path.endswith("$")
        body = re.escape(path[:-1] if anchored else path).replace(r"\*", ".*")
        return re.compile("^" + body + ("$" if anchored else ""))

    def can_fetch(self, ua: str, url: str) -> bool:
        rules, _ = self._group(ua)
        parts = urllib.parse.urlsplit(url)
        target = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        best_len, allowed = -1, True
        for kind, path in rules:
            if path == "":
                continue  # empty Disallow = allow all
            if self._pattern(path).match(target) or self._pattern(urllib.parse.unquote(path)).match(urllib.parse.unquote(target)):
                ln = len(path)
                if ln > best_len or (ln == best_len and kind == "allow"):
                    best_len, allowed = ln, kind == "allow"
        return allowed

    def crawl_delay(self, ua: str):
        return self._group(ua)[1]
