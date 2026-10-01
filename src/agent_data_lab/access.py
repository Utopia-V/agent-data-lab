"""Candidate data access API. No model loop and no persistent central index."""

from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


class ReadFailure(Exception):
    def __init__(self, ref: str, reason: str):
        self.ref, self.reason = ref, reason
        super().__init__(f"{ref}: {reason}")


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, int, int]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value is not None:
                    self.links.append((value, *self.getpos()))


def target_ref(uri: str) -> tuple[str, str] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "repa" or not parsed.path.startswith("document/"):
        return None
    return unquote(parsed.path.removeprefix("document/")), parsed.fragment


class Space:
    """One synthetic space; provider dispatch follows object metadata."""

    def __init__(self, root: str | Path = "/work"):
        self.root = Path(root).resolve()
        self.markdown = MarkdownIt("commonmark")

    def objects(self) -> list[dict[str, Any]]:
        # Reload so an external move/relink does not freeze identity to a path.
        return json.loads((self.root / "inventory.json").read_text())

    def sql(self, query: str, params=()) -> list[dict[str, Any]]:
        with sqlite3.connect(f"file:{self.root / 'learning.sqlite'}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params)]

    def records(self, name: str = "annotations") -> list[dict[str, Any]]:
        if name != "annotations":
            raise ValueError(f"unknown record source: {name}")
        return [json.loads(line) for line in (self.root / "annotations.jsonl").read_text().splitlines() if line]

    def _entry(self, ref: str) -> dict[str, Any]:
        entries = [entry for entry in self.objects() if entry["ref"] == ref]
        if len(entries) != 1:
            raise ReadFailure(ref, "unknown" if not entries else "ambiguous_identity")
        return entries[0]

    def _load(self, entry: dict[str, Any]) -> tuple[str, str]:
        ref = entry["ref"]
        if entry["kind"] == "record":
            try:
                rows = self.records()
                values = [row for row in rows if row["id"] == entry["key"]]
                if len(values) != 1:
                    raise ReadFailure(ref, "missing" if not values else "ambiguous_identity")
                text = json.dumps(values[0], ensure_ascii=False, sort_keys=True)
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ReadFailure(ref, "unreadable_source") from error
        else:
            path = (self.root / entry["path"]).resolve()
            if not path.is_relative_to(self.root):
                raise ReadFailure(ref, "outside_space")
            try:
                text = path.read_bytes().decode("utf-8")
            except FileNotFoundError as error:
                raise ReadFailure(ref, "missing") from error
            except UnicodeError as error:
                raise ReadFailure(ref, "invalid_utf8") from error
            except OSError as error:
                raise ReadFailure(ref, "unreadable") from error
        return text, sha256(text.encode()).hexdigest()

    def read(self, ref: str, *, lines: tuple[int, int] | None = None, revision: str | None = None):
        entry = self._entry(ref)
        text, current_revision = self._load(entry)
        if revision is not None and revision != current_revision:
            raise ReadFailure(ref, "stale_revision")
        result = {"ref": ref, "revision": current_revision, "text": text}
        if lines is not None:
            start, end = lines
            if start < 1 or end < start:
                raise ValueError("lines must be a positive inclusive range")
            result.update(text="\n".join(text.splitlines()[start - 1:end]), lines=[start, end])
        return result

    def _scope(self, within: list[str] | None) -> list[str]:
        refs = [entry["ref"] for entry in self.objects()] if within is None else within
        return list(dict.fromkeys(refs))

    def _scan(self, within, operation):
        items, covered, unresolved = [], [], []
        for ref in self._scope(within):
            try:
                entry = self._entry(ref)
                text, revision = self._load(entry)
                # Publish a provider's output only when this object completed.
                found = list(operation(entry, text, revision))
                items.extend(found)
                covered.append(ref)
            except ReadFailure as error:
                unresolved.append({"ref": ref, "reason": error.reason})
            except (ValueError, KeyError, TypeError):
                unresolved.append({"ref": ref, "reason": "invalid_source"})
        return {"items": items, "covered": covered, "unresolved": unresolved,
                "complete": not unresolved}

    def search(self, query: str, *, within: list[str] | None = None, limit: int | None = None):
        """Literal search with object scope applied before deterministic ordering/limit."""
        if not query:
            raise ValueError("query must not be empty")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer")

        def find(entry, text, revision):
            for index, line in enumerate(text.splitlines(), 1):
                if query in line:
                    yield {"ref": entry["ref"], "line": index, "text": line, "revision": revision}

        result = self._scan(within, find)
        result["items"].sort(key=lambda item: (item["ref"], item["line"]))
        total = len(result["items"])
        result.update(matched_count=total, truncated=limit is not None and limit < total)
        if limit is not None:
            result["items"] = result["items"][:limit]
        return result

    def references_to(self, target: str, *, within: list[str] | None = None):
        def extract(entry, text, revision):
            ref, kind = entry["ref"], entry["kind"]
            links: list[dict[str, Any]] = []
            if kind == "markdown":
                lines = text.splitlines()
                for token in self.markdown.parse(text):
                    if token.type != "inline" or token.map is None:
                        continue
                    start, end = token.map
                    ordinal = 0
                    for child in token.children or []:
                        if child.type == "link_open":
                            ordinal += 1
                            links.append({"uri": child.attrGet("href"), "line": start + 1,
                                          "end_line": end, "ordinal": ordinal,
                                          "context": "\n".join(lines[start:end]), "relation": "link"})
            elif kind == "html":
                parser = HtmlLinks()
                parser.feed(text)
                for ordinal, (uri, line, column) in enumerate(parser.links, 1):
                    links.append({"uri": uri, "line": line, "column": column,
                                  "ordinal": ordinal, "relation": "link", "context": text.splitlines()[line - 1]})
            elif kind == "record":
                row = json.loads(text)
                # The source schema declares subject_ref. Text fields are not relations.
                links.append({"uri": "repa:document/" + row["subject_ref"],
                              "field": "subject_ref", "ordinal": 1,
                              "relation": "annotates", "context": text})
            else:
                raise ReadFailure(ref, "unsupported_reference_query")
            for link in links:
                destination = target_ref(link.pop("uri"))
                if destination is not None and destination[0] == target:
                    yield {"ref": ref, "target": target, "fragment": destination[1],
                           "revision": revision, **link}

        result = self._scan(within, extract)
        result["items"].sort(key=lambda item: (item["ref"], item.get("line", 0), item["ordinal"]))
        return result
