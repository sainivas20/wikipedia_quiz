"""
CRUD operations for WikiQuiz database records.
"""

from sqlalchemy.orm import Session
from models import QuizRecord


def get_quiz_by_url(db: Session, url: str) -> QuizRecord | None:
    return db.query(QuizRecord).filter(QuizRecord.url == url).first()


def get_quiz_by_id(db: Session, quiz_id: int) -> QuizRecord | None:
    return db.query(QuizRecord).filter(QuizRecord.id == quiz_id).first()


def get_all_quizzes(db: Session) -> list[QuizRecord]:
    return db.query(QuizRecord).order_by(QuizRecord.created_at.desc()).all()


def create_quiz_record(db: Session, data: dict) -> QuizRecord:
    """Create and persist a new QuizRecord."""
    record = QuizRecord(
        url=data["url"],
        title=data["title"],
        summary=data.get("summary"),
        sections=data.get("sections", []),
        raw_html=data.get("raw_html"),
        key_entities=data.get("key_entities", {}),
        quiz=data.get("quiz", []),
        related_topics=data.get("related_topics", []),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_quiz(db: Session, quiz_id: int) -> bool:
    record = get_quiz_by_id(db, quiz_id)
    if not record:
        return False
    db.delete(record)
    db.commit()
    return True


def format_quiz_response(record: QuizRecord) -> dict:
    """Serialize a QuizRecord to the standard API response format."""
    return {
        "id": record.id,
        "url": record.url,
        "title": record.title,
        "summary": record.summary,
        "key_entities": record.key_entities or {},
        "sections": record.sections or [],
        "quiz": record.quiz or [],
        "related_topics": record.related_topics or [],
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
