"""Reusable source-specific helpers; no registry, scope, reverse query or coverage layer."""

from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3

from markdown_it import MarkdownIt


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value is not None:
                    self.links.append((value, *self.getpos()))


def markdown_links(text):
    """Yield actual link occurrences with native URI and containing block location."""
    lines = text.splitlines()
    for token in MarkdownIt("commonmark").parse(text):
        if token.type not in {"inline", "html_block"} or token.map is None:
            continue
        start, end = token.map
        ordinal = 0
        for child in token.children or [token]:
            destinations = []
            if child.type == "link_open":
                destinations.append(child.attrGet("href"))
            elif child.type in {"html_inline", "html_block"}:
                parser = HtmlLinks()
                parser.feed(child.content)
                destinations.extend(uri for uri, _, _ in parser.links)
            for uri in destinations:
                ordinal += 1
                yield {"uri": uri, "line": start + 1, "end_line": end, "ordinal": ordinal,
                       "context": "\n".join(lines[start:end]), "relation": "link"}


def html_links(text):
    parser = HtmlLinks()
    parser.feed(text)
    for ordinal, (uri, line, column) in enumerate(parser.links, 1):
        yield {"uri": uri, "line": line, "column": column, "ordinal": ordinal,
               "relation": "link", "context": text.splitlines()[line - 1]}


def annotation_links(row):
    """The annotation source schema declares subject_ref as the relation field."""
    yield {"uri": "repa:document/" + row["subject_ref"], "field": "subject_ref",
           "ordinal": 1, "relation": "annotates"}


def query_learning_db(query, params=(), root="/work"):
    """Execute native SQL and return row dictionaries; no query translation."""
    with sqlite3.connect(f"file:{Path(root) / 'learning.sqlite'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, params)]


def load_annotations(root="/work"):
    return [json.loads(line) for line in (Path(root) / "annotations.jsonl").read_text().splitlines() if line]
