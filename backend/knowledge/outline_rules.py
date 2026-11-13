"""Reading stated learning outcomes and the weekly schedule out of course text (English and German).

Rule-based and explainable. A line is taken as an outcome when
  - it carries an outcome code ("CLO1:", "LO 2", "LZ3:"), or
  - it says what students can do ("students will be able to ...", "participants can ...",
    "Die Studierenden sind in der Lage, ..."), or
  - it is a list item under an outcomes heading or under an opening line such as
    "On completion, students will be able to:" and contains an action verb.
It is not taken when it is about organisation (attendance, registration, grades, prerequisites) or negated
("students who are not able to attend").

Plan documents (syllabus, module manual) are read with all rules. Delivery documents (slides, papers,
transcripts) only with the first two, because such text uses "able to" in many other senses.

Measured on datasets/extraction (see docs/EVALUATION.md). Known limits: outcomes written as running prose
without any of these signals are missed; a table layout is not read; the organisation word list is finite.
"""
import re

from knowledge.bloom_classifier import _matches, classify_text

_SUBJECT = (r"(?:students?|learners?|participants?|graduates?|studierende[n]?|lernende[n]?|teilnehmende[n]?|"
            r"teilnehmer(?:innen)?|absolvent(?:en|innen)(?:\s+und\s+absolvent(?:en|innen))?)")
_ABILITY = (r"(?:(?:will|should|shall)\s+be\s+able\s+to|(?:is|are)\s+able\s+to|are\s+expected\s+to(?:\s+be\s+able\s+to)?|can|"
            r"können|sind\s+in\s+der\s+lage|werden\s+in\s+der\s+lage\s+sein|kennen|verstehen|beherrschen)")
_STEM = re.compile(rf"(?i)\b{_SUBJECT}\b[^.;:\n]{{0,40}}?\b{_ABILITY}\b"
                   rf"|\b(?:können|kennen|verstehen|beherrschen)\s+die\s+(?:studierenden|lernenden|teilnehmenden|absolvent\w+)\b")
_MODAL = re.compile(rf"(?i)\b{_SUBJECT}\s+(?:will|should|shall)\s+(?:also\s+)?(?:learn\s+(?:how\s+)?to\s+)?(?=\w)")
_MODAL_DE = re.compile(rf"(?i)\b{_SUBJECT}\s+(?:sollen|werden)\b")
_CODE_ANYWHERE = re.compile(r"(?i)\b(?:CLO|ILO|PLO|MLO|LO)\s*\d")
_CODE_START = re.compile(r"(?i)^\W*(?:LZ|LE)\s*[-.]?\s*\d+\s*[:.)-]")
_NEGATED = re.compile(r"(?i)\b(?:not|cannot|unable|nicht|kein\w*)\b[^.\n]{0,25}\b(?:able|in\s+der\s+lage|können)\b")
_ORGANISATION = re.compile(
    r"(?i)\b(?:attend\w*|register\w*|registration|enrol\w*|grades?|laptop|deadline|submit\w*|office\s+hours|lab\s+groups?|"
    r"assigned\s+to|notify|prerequisit\w*|before\s+the\s+course|have\s+completed|anmeld\w*|abmeld\w*|prüfungsamt|mitbringen|"
    r"abgabe\w*|frist\w*|anwesenheit\w*|voraussetz\w*|vorkenntnis\w*|grundkenntnis\w*|eingeteilt|teilzunehmen)\b")
_OUTCOME_HEADING = re.compile(
    r"(?i)^\W*(?:(?:intended|course|module|expected)\s+)*(?:learning\s+)?(?:outcomes?|objectives?|goals)\W*$"
    r"|^\W*(?:lernziele?|qualifikationsziele?|kompetenzen|kompetenzziele?|lernergebnisse)\W*$")
_LIST_MARKER = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_START_VERB = re.compile(r"(?i)^(?:explain|describe|implement|analyse|analyze|evaluate|design|apply|compare|identify|"
                         r"erklären|beschreiben|implementieren|analysieren|bewerten|entwerfen|anwenden|vergleichen|berechnen)\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\d\.)\s+")          # "bis zum 1. Mai" is not a sentence end

_UNIT = r"(?:week|wk\.?|woche|vorlesung|sitzung|kw|lecture|session|unit|einheit|termin)"
_WEEK_LINE = re.compile(
    rf"(?im)^[ \t]*(?:[-*•][ \t]*)?(?:{_UNIT}[ \t]*(\d{{1,2}})|(\d{{1,2}})\.[ \t]*(?:woche|week|sitzung|vorlesung|termin))"
    rf"[ \t]*(?:\([^)\n]{{1,40}}\)[ \t]*)?[:\-–—.)][ \t]*(\S[^\n]{{2,118}}?)[ \t]*$")
_NO_TEACHING = re.compile(r"(?i)\b(?:no\s+(?:lecture|class)|reading\s+week|holiday|break|vorlesungsfrei|feiertag|ferien|entfällt|"
                          r"keine\s+vorlesung|midterm|exam(?:ination)?|klausur|prüfung|deadline)\b")


def is_stated_outcome(line: str) -> bool:
    """Strict test for documents that are not course outlines: an outcome code, or students being able to do something."""
    if _ORGANISATION.search(line) or _NEGATED.search(line):
        return False
    return bool(_CODE_ANYWHERE.search(line) or _CODE_START.search(line) or _STEM.search(line))


def _says_what_students_do(unit: str) -> bool:
    """"Students will implement ..." / "Die Studierenden sollen ... implementieren": a modal directly governing an action verb."""
    m = _MODAL.search(unit)
    if m:
        hits = _matches(unit[m.end():])
        return bool(hits) and hits[0][0] == 0
    if _MODAL_DE.search(unit):
        hits = _matches(unit)
        return bool(hits) and len(unit[hits[-1][1]:].split()) <= 1          # the infinitive closes the sentence
    return False


def outcome_lines(text: str, plan: bool) -> list:
    """Stated learning outcomes in `text`, cleaned of list markers. `plan` is True for syllabus and module manual."""
    found, in_outcomes = [], False
    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        marker = bool(_LIST_MARKER.match(line))
        body = _LIST_MARKER.sub("", line).strip()
        if plan and _OUTCOME_HEADING.match(line.lstrip("# ")):
            in_outcomes = True
            continue
        if line.startswith("#") or (not marker and len(body.split()) <= 5 and not re.search(r"[.!?,;:]$", body)
                                    and not _CODE_ANYWHERE.search(body) and not _STEM.search(body)):
            in_outcomes = False                                 # another heading closes the outcomes section
            continue
        for unit in ([body] if marker else _SENTENCE_END.split(body)):
            unit = unit.strip()
            cleaned = unit.rstrip(",;")
            if not 15 <= len(unit) <= 1000:
                continue
            if _CODE_ANYWHERE.search(unit) or _CODE_START.search(unit):
                found.append(cleaned)
                continue
            if _ORGANISATION.search(unit) or _NEGATED.search(unit):
                continue
            stem = bool(_STEM.search(unit))
            if not plan:
                if stem:
                    found.append(cleaned)
                continue
            level = classify_text(unit)[0]
            if stem and (unit.endswith(":") or (level is None and not re.search(r"[.!?]$", unit))):
                in_outcomes = True                              # "..., students will be able to:" opens a list
            elif stem or _says_what_students_do(unit):
                found.append(cleaned)
            elif (in_outcomes and marker and level) or _START_VERB.match(unit):
                found.append(cleaned)
    return list(dict.fromkeys(found))


def schedule_entries(text: str) -> list:
    """(number, topic) for lines such as "Week 3: Hash tables", "Wk. 3 (12 Oct) - ...", "2. Woche: ...", "KW 42: ...".
    Weeks without teaching (holiday, reading week, exam) are not topics and are left out."""
    entries = {}
    for match in _WEEK_LINE.finditer(text or ""):
        number, title = int(match.group(1) or match.group(2)), match.group(3).strip(" .;:,")
        if not 1 <= number <= 52 or not title or number in entries:
            continue
        if _NO_TEACHING.search(title) and len(title.split()) <= 5:
            continue
        entries[number] = title
    return list(entries.items())
