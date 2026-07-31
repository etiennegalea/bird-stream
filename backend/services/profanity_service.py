"""Detect and retain English and Maltese profanity without altering chat text."""

import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from models.orm import ProfanityOccurrence


# Variants map to the word displayed in public statistics. Keep this list in
# sync with frontend/src/profanity.js, where masking happens.
_CANONICAL_VARIANTS = {
    # English profanity and common inflections/obfuscations
    "fuck": ("fuck", "fucks", "fucked", "fucker", "fuckers", "fucking", "fuckface", "fuckfaces", "fck", "fuk", "f*ck", "phuck"),
    "motherfucker": ("motherfucker", "motherfuckers"),
    "shit": ("shit", "shits", "shitty", "shithead", "shitheads", "sh1t"),
    "bullshit": ("bullshit",),
    "bitch": ("bitch", "bitches", "b1tch"),
    "bastard": ("bastard", "bastards"),
    "ass": ("ass", "asses"),
    "asshole": ("asshole", "assholes", "a$$hole", "a$$holes"),
    "arse": ("arse", "arses"),
    "arsehole": ("arsehole", "arseholes"),
    "dick": ("dick", "dicks", "dickhead", "dickheads"),
    "cock": ("cock", "cocks"),
    "cunt": ("cunt", "cunts"),
    "piss": ("piss", "pisses", "pissed", "pissing"),
    "wank": ("wank", "wanks", "wanked", "wanking", "wanker", "wankers"),
    "whore": ("whore", "whores"),
    "slut": ("slut", "sluts"),
    "damn": ("damn", "damns", "damned", "damning", "dammit", "goddamn", "goddamned"),
    "crap": ("crap", "craps", "crappy"),
    "bollocks": ("bollock", "bollocks"),
    "bugger": ("bugger", "buggers", "buggered", "buggering"),
    "douchebag": ("douche", "douches", "douchebag", "douchebags"),
    "jackass": ("jackass", "jackasses"),
    "prick": ("prick", "pricks"),
    "twat": ("twat", "twats"),
    "tosser": ("tosser", "tossers"),
    "pussy": ("pussy", "pussies"),
    # Avoid "tit"/"tits": they are bird names in this application.
    "tits": ("titty", "titties"),
    "skank": ("skank", "skanks"),
    "cum": ("cum", "cumming"),
    "jizz": ("jizz", "jizzed", "jizzing"),
    "blowjob": ("blowjob", "blowjobs"),
    "handjob": ("handjob", "handjobs"),
    "sonofabitch": ("sonofabitch",),
    # Abusive slurs
    "nigga": ("nigga", "niggas"),
    "nigger": ("nigger", "niggers"),
    "faggot": ("fag", "fags", "faggot", "faggots"),
    "retard": ("retard", "retards", "retarded"),
    "chink": ("chink", "chinks"),
    "spic": ("spic", "spics"),
    "kike": ("kike", "kikes"),
    "wetback": ("wetback", "wetbacks"),
    "tranny": ("tranny", "trannies"),
    # Maltese, including inflections and unaccented keyboard spellings
    "foxx": ("foxx",),
    "għoxx": ("għoxx", "ghoxx", "oxx", "għoxxi", "ghoxxi", "għoxxok", "ghoxxok", "għoxxu", "ghoxxu", "għoxxha", "ghoxxha", "għoxxna", "ghoxxna", "għoxxkom", "ghoxxkom", "għoxxhom", "ghoxxhom", "għoss", "ghoss"),
    "ħara": ("ħara", "hara"),
    "qaħba": ("qaħba", "qahba", "qħab", "qhab", "qoħob", "qohob"),
    "żobb": ("żobb", "zobb", "żobbi", "zobbi", "żobbok", "zobbok", "żobbu", "zobbu", "żobbha", "zobbha", "żobbna", "zobbna", "żobbkom", "zobbkom", "żobbhom", "zobbhom", "żbub", "zbub", "żbubi", "zbubi"),
    "sorm": ("sorm", "sormi", "sormok", "sormu", "sormha", "sormna", "sormkom", "sormhom"),
    "liba": ("liba",),
    "ostja": ("ostja",),
    "fotta": ("fotta", "tfotta"),
    "mniegħel": ("mniegħel", "mnieghel"),
    "nejk": ("nejk", "nejka", "niek"),
    "paċoċċ": ("paċoċċ", "pacocc"),
    "tirra": ("tirra", "tirma"),
    "toqbi": ("toqbi",),
    "żabbab": ("żabbab", "zabbab"),
    "żagħka": ("żagħka", "zaghka"),
    "żoċċ": ("żoċċ", "zocc"),
    "pufta": ("pufta", "pufti"),
    "beżżula": ("beżżula", "bezzula", "beżżul", "bezzul"),
    "żejżiet": ("żejżiet", "zejziet"),
}

_VARIANTS = {
    variant: canonical
    for canonical, variants in _CANONICAL_VARIANTS.items()
    for variant in variants
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
