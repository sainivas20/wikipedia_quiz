"""
SQLAlchemy ORM models for WikiQuiz.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from database import Base


class QuizRecord(Base):
    """
    Stores a processed Wikipedia article and its generated quiz.
    """
    __tablename__ = "quiz_records"

    id = Column(Integer, primary_key=True, index=True)

    # Source
    url = Column(String(2048), unique=True, nullable=False, index=True)
    title = Column(String(512), nullable=False)

    # Scraped content
    summary = Column(Text, nullable=True)
    sections = Column(JSON, nullable=True)       # List[str]
    raw_html = Column(Text, nullable=True)        # First 50k chars of raw HTML

    # LLM-generated content
    key_entities = Column(JSON, nullable=True)   # {"people": [], "organizations": [], "locations": []}
    quiz = Column(JSON, nullable=True)            # List[QuizQuestion]
    related_topics = Column(JSON, nullable=True)  # List[str]

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
