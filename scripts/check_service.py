"""Проверка поднятого сервиса «чёрным ящиком» на реальном датасете.

    python scripts/check_service.py [--base-url URL] [--csv PATH]

Запускается после ``make up && make load``; нужна только стандартная библиотека.
Удаляет из базы один документ.
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DOCUMENTS_PATH = "/api/v1/documents"
SEARCH_LIMIT = 20
DOCUMENT_FIELDS = frozenset({"id", "rubrics", "text", "created_date"})
QUERIES = ("конкурс", "Скидка", "новый скин", "Москва", "привет", "2019", "ёлка")
EDGE_QUERIES = ("", " ", "zzzzqqqxxx", "\"'; DROP TABLE documents;--", "a" * 5000, "🎁")
MISSING_ID = 999_999_999


class Checker:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.passed = 0
        self.failed = 0

    def check(self, condition: bool, message: str) -> None:
        print(f"  {'OK  ' if condition else 'FAIL'} {message}")
        if condition:
            self.passed += 1
        else:
            self.failed += 1

    def request(self, method: str, path: str) -> tuple[int, Any]:
        request = urllib.request.Request(self.base_url + path, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")

    def search(self, query: str) -> tuple[int, Any]:
        return self.request("GET", f"{DOCUMENTS_PATH}/search?{urllib.parse.urlencode({'query': query})}")

    def delete(self, document_id: int | str) -> int:
        status, _ = self.request("DELETE", f"{DOCUMENTS_PATH}/{document_id}")
        return status


def items_of(body: Any) -> list[dict[str, Any]] | None:
    """Documents from a search response (``{"total": ..., "items": [...]}``, see docs.json)."""
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        return body["items"]
    return None


def load_texts(path: Path) -> set[str]:
    # utf-8-sig: the loader accepts files saved with a BOM, so the check must as well.
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {row["text"] for row in csv.DictReader(file)}


def check_search(checker: Checker, texts: set[str]) -> None:
    print("\n[1] Поиск")
    for query in QUERIES:
        status, body = checker.search(query)
        items = items_of(body)
        print(f"— {query!r}: status={status}, найдено={None if items is None else len(items)}")
        checker.check(status == 200, "status 200")
        if items is None:
            checker.check(False, f"в ответе нет списка items: {str(body)[:200]}")
            continue
        checker.check(len(items) <= SEARCH_LIMIT, f"не больше {SEARCH_LIMIT} документов")
        if not items:
            continue
        checker.check(all(DOCUMENT_FIELDS <= item.keys() for item in items), "у документов все поля БД")
        checker.check(all(item["text"] in texts for item in items), "тексты совпадают с CSV без искажений")
        checker.check(all(isinstance(item["rubrics"], list) for item in items), "rubrics — массив")
        dates = [item["created_date"] for item in items]
        checker.check(dates == sorted(dates, reverse=True), "упорядочено по created_date, сначала новые")
        checker.check(len({item["id"] for item in items}) == len(items), "id уникальны")


def check_edge_queries(checker: Checker) -> None:
    print("\n[2] Граничные запросы")
    for query in EDGE_QUERIES:
        status, _ = checker.search(query)
        checker.check(status < 500, f"{query[:25]!r}: нет 5xx (status={status})")


def check_delete(checker: Checker) -> None:
    print("\n[3] Удаление")
    items = items_of(checker.search("конкурс")[1]) or []
    if not items:
        checker.check(False, "нет документа для проверки удаления")
        return
    victim = items[0]
    victim_id = victim["id"]

    status = checker.delete(victim_id)
    checker.check(status == 204, f"DELETE id={victim_id} -> {status}")
    remaining = items_of(checker.search("конкурс")[1]) or []
    checker.check(all(item["id"] != victim_id for item in remaining), "документ исчез из выдачи")
    own_text = " ".join(victim["text"].split()[:6])
    remaining = items_of(checker.search(own_text)[1]) or []
    checker.check(all(item["id"] != victim_id for item in remaining), "не находится и по собственному тексту")

    status = checker.delete(victim_id)
    checker.check(status == 404, f"повторный DELETE -> 404 (получили {status})")
    status = checker.delete(MISSING_ID)
    checker.check(status == 404, f"DELETE несуществующего -> 404 (получили {status})")
    status = checker.delete("abc")
    checker.check(status == 422, f"DELETE с некорректным id -> 422 (получили {status})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/check_service.py", description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000", help="адрес сервиса (default: %(default)s)")
    parser.add_argument("--csv", type=Path, default=Path("data/posts.csv"), help="датасет (default: %(default)s)")
    args = parser.parse_args(argv)

    texts = load_texts(args.csv)
    print(f"CSV: {len(texts)} уникальных текстов")

    checker = Checker(args.base_url)
    check_search(checker, texts)
    check_edge_queries(checker)
    check_delete(checker)

    print(f"\nИтого: {checker.passed} OK, {checker.failed} FAIL")
    return 1 if checker.failed else 0


if __name__ == "__main__":
    sys.exit(main())
