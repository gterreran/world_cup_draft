from __future__ import annotations

import json
import re
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tournaments.third_place import (
    CACHE_FILENAME,
    FIFA_THIRD_PLACE_OPPONENT_SLOTS,
    GROUPS,
    fifa_third_place_table_path,
    validate_fifa_third_place_table,
)


DEFAULT_SOURCE_URL = (
    "https://en.wikipedia.org/wiki/"
    "Template:2026_FIFA_World_Cup_third-place_table"
)


class TableCellParser(HTMLParser):
    """Small stdlib parser that preserves table rows and cells."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            assert self._current_row is not None
            self._current_row.append(_clean_text(" ".join(self._current_cell)))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None


class Command(BaseCommand):
    help = (
        "Fetch FIFA's 2026 third-place allocation table and save it as "
        f"tournaments/data/{CACHE_FILENAME}."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-url",
            default=DEFAULT_SOURCE_URL,
            help="Page containing the 2026 third-place allocation table.",
        )
        parser.add_argument(
            "--output",
            default=None,
            help=(
                "Output JSON path. Defaults to "
                "tournaments/data/fifa_2026_third_place_table.json."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite the output file if it already exists.",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"] or fifa_third_place_table_path())

        if output_path.exists() and not options["force"]:
            raise CommandError(
                f"Output file already exists: {output_path}. "
                "Use --force to overwrite it."
            )

        html = _download_html(options["source_url"])
        table = parse_fifa_third_place_table_html(html)

        try:
            validate_fifa_third_place_table(table)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(table, fh, indent=2, sort_keys=True)
            fh.write("\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {len(table)} FIFA third-place allocation rows to "
                f"{output_path}."
            )
        )


def _download_html(source_url: str) -> str:
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "world-cup-draft-app/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as exc:
        raise CommandError(
            f"Could not download FIFA third-place table from {source_url!r}."
        ) from exc


def parse_fifa_third_place_table_html(html: str) -> dict[str, dict[str, str]]:
    """Parse the 495-row FIFA third-place table from rendered HTML.

    The parser intentionally has two paths:

    1. table-cell parsing for normal Wikipedia HTML;
    2. full-text regex fallback for cases where the markup changes but the
       rendered row text remains the same.
    """
    table = _parse_from_table_cells(html)

    if len(table) == 495:
        return table

    fallback_table = _parse_from_visible_text(html)

    if len(fallback_table) > len(table):
        table = fallback_table

    return table


def _parse_from_table_cells(html: str) -> dict[str, dict[str, str]]:
    parser = TableCellParser()
    parser.feed(html)

    table: dict[str, dict[str, str]] = {}

    for row in parser.rows:
        tokens: list[str] = []
        for cell in row:
            tokens.extend(cell.split())

        parsed = _parse_row_tokens(tokens)
        if parsed is None:
            continue

        key, row_map = parsed
        table[key] = row_map

    return table


def _parse_from_visible_text(html: str) -> dict[str, dict[str, str]]:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _clean_text(text)

    row_pattern = re.compile(
        r"\b(\d{1,3})\s+"
        r"((?:[A-L]\s+){7}[A-L])\s+"
        r"((?:3[A-L]\s+){7}3[A-L])\b"
    )

    table: dict[str, dict[str, str]] = {}

    for match in row_pattern.finditer(text):
        groups = match.group(2).split()
        assignments = match.group(3).split()
        key = "".join(groups)
        table[key] = dict(zip(FIFA_THIRD_PLACE_OPPONENT_SLOTS, assignments))

    return table


def _parse_row_tokens(tokens: list[str]) -> tuple[str, dict[str, str]] | None:
    for index, token in enumerate(tokens):
        if not token.isdigit():
            continue

        groups = tokens[index + 1 : index + 9]
        assignments = tokens[index + 9 : index + 17]

        if len(groups) != 8 or len(assignments) != 8:
            continue

        if not all(group in GROUPS for group in groups):
            continue

        if not all(re.fullmatch(r"3[A-L]", value) for value in assignments):
            continue

        key = "".join(groups)
        return key, dict(zip(FIFA_THIRD_PLACE_OPPONENT_SLOTS, assignments))

    return None


def _clean_text(text: str) -> str:
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
