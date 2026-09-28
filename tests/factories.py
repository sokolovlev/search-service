from datetime import datetime

from app.schemas import DocumentCreate


def make_document(text: str, created_date: datetime, rubrics: list[str] | None = None) -> DocumentCreate:
    return DocumentCreate(text=text, created_date=created_date, rubrics=rubrics or [])
