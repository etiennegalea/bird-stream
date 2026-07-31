"""Detect and retain English and Maltese profanity without altering chat text."""

import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from models.orm import ProfanityOccurrence


# Variants map to the word displayed in public statistics. Keep this list in
# sync with frontend/src/profanity.js, where masking happens.
_VARIANTS = {
    # English
    "fuck": "fuck", "fucks": "fuck", "fucked": "fuck", "fucker": "fuck",
    "fuckers": "fuck", "fucking": "fuck", "motherfucker": "motherfucker",
    "motherfuckers": "motherfucker", "shit": "shit", "shits": "shit",
    "shitty": "shit", "bullshit": "bullshit", "bitch": "bitch",
    "bitches": "bitch", "bastard": "bastard", "bastards": "bastard",
    "asshole": "asshole", "assholes": "asshole", "dick": "dick",
    "dicks": "dick", "cock": "cock", "cocks": "cock", "cunt": "cunt",
    "cunts": "cunt", "piss": "piss", "pissed": "piss", "wanker": "wanker",
    "wankers": "wanker", "whore": "whore", "whores": "whore",
    "slut": "slut", "sluts": "slut",
    # Maltese, including common unaccented keyboard spellings
    "foxx": "foxx", "għoxx": "għoxx", "ghoxx": "għoxx", "ħara": "ħara",
    "hara": "ħara", "qaħba": "qaħba", "qahba": "qaħba", "żobb": "żobb",
    "zobb": "żobb", "sorm": "sorm", "liba": "liba", "ostja": "ostja",
}

_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(word) for word in sorted(_VARIANTS, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


def retention_days() -> int:
    """Return a safe positive retention period from the environment."""
    try:
        return max(1, int(os.environ.get("PROFANITY_RETENTION_DAYS", "7")))
    except ValueError:
        return 7


def extract_profanities(text: str) -> Counter[str]:
    """Return canonical profanity counts from raw text."""
    return Counter(_VARIANTS[match.group(0).lower()] for match in _PATTERN.finditer(text))


def cleanup_expired(session, now: datetime | None = None, user_id: int | None = None) -> None:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days())
    query = delete(ProfanityOccurrence).where(ProfanityOccurrence.occurred_at < cutoff)
    if user_id is not None:
        query = query.where(ProfanityOccurrence.user_id == user_id)
    session.execute(query)


def record_profanities(session, user_id: int, text: str, now: datetime | None = None) -> Counter[str]:
    """Record every raw occurrence. The caller owns the transaction."""
    occurred_at = now or datetime.now(timezone.utc)
    cleanup_expired(session, occurred_at, user_id)
    counts = extract_profanities(text)
    for word, count in counts.items():
        for _ in range(count):
            session.add(ProfanityOccurrence(
                user_id=user_id,
                word=word,
                occurred_at=occurred_at,
            ))
    return counts


def get_profanity_counts(session, user_id: int, now: datetime | None = None) -> list[dict]:
    """Return unexpired rolling counts and remove stale occurrence rows."""
    cleanup_expired(session, now, user_id)
    rows = session.execute(
        select(ProfanityOccurrence.word, func.count(ProfanityOccurrence.id))
        .where(ProfanityOccurrence.user_id == user_id)
        .group_by(ProfanityOccurrence.word)
        .order_by(func.count(ProfanityOccurrence.id).desc(), ProfanityOccurrence.word)
    ).all()
    session.commit()
    return [{"word": word, "count": count} for word, count in rows]
