"""Candidate data access API. No model loop and no persistent central index."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .native import markdown_links, html_links, annotation_links, query_learning_db, load_annotations


class ReadFailure(Exception):
    def __init__(self, ref: str, reason: str):
        self.ref, self.reason = ref, reason
        super().__init__(f"{ref}: {reason}")


def target_ref(uri: str) -> tuple[str, str] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "repa" or not parsed.path.startswith("document/"):
        return None
    return unquote(parsed.path.removeprefix("document/")), parsed.fragment


class Space:
    """One synthetic space; provider dispatch follows object metadata."""

    def __init__(self, root: str | Path = "/work"):
        self.root = Path(root).resolve()

    def objects(self) -> list[dict[str, Any]]:
        # Reload so an external move/relink does not freeze identity to a path.
        return json.loads((self.root / "inventory.json").read_text())

    def sql(self, query: str, params=()) -> list[dict[str, Any]]:
        return query_learning_db(query, params, self.root)

    def records(self, name: str = "annotations") -> list[dict[str, Any]]:
        if name != "annotations":
            raise ValueError(f"unknown record source: {name}")
        return load_annotations(self.root)

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
        if within is not None and (not isinstance(within, list) or not all(isinstance(ref, str) for ref in within)):
            raise TypeError("within must be a list of object references or None")
        refs = [entry["ref"] for entry in self.objects()] if within is None else within
        return list(dict.fromkeys(refs))

    def _destination(self, uri: str, source: dict[str, Any]):
        stable = target_ref(uri)
        if stable is not None:
            return stable
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc or "path" not in source:
            return None
        if not parsed.path:
            return source["ref"], parsed.fragment
        path = Path(unquote(parsed.path))
        if path.is_absolute():
            candidate = self.root / path.relative_to("/")
        else:
            candidate = (self.root / source["path"]).parent / path
        candidate = candidate.resolve()
        matches = [entry["ref"] for entry in self.objects()
                   if "path" in entry and (self.root / entry["path"]).resolve() == candidate]
        if len(matches) > 1:
            raise ReadFailure(source["ref"], "ambiguous_target")
        return (matches[0], parsed.fragment) if matches else None

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
                links = list(markdown_links(text))
            elif kind == "html":
                links = list(html_links(text))
            elif kind == "record":
                row = json.loads(text)
                links = [dict(link, context=text) for link in annotation_links(row)]
            else:
                raise ReadFailure(ref, "unsupported_reference_query")
            for link in links:
                destination = self._destination(link.pop("uri"), entry)
                if destination is not None and destination[0] == target:
                    yield {"ref": ref, "target": target, "fragment": destination[1],
                           "revision": revision, **link}

        result = self._scan(within, extract)
        result["items"].sort(key=lambda item: (item["ref"], item.get("line", 0), item["ordinal"]))
        return result
