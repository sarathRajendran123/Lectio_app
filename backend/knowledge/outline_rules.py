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

Two more rules read a whole plan document rather than single lines (`prose_outcomes`, `table_schedule`):
module manuals often state outcomes as paragraphs under competence headings ("Fachkompetenz: Wissen und
Verstehen | Die Studierenden verstehen ... Sie beherrschen ..."), and schedules as a "Woche | Thema" table.

Measured on datasets/extraction (see docs/EVALUATION.md). Known limits: prose outcomes are only read under a
competence or outcomes heading, sentence by sentence; the organisation word list is finite.
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


_COMPETENCE = re.compile(
    r"(?i)\b(?:fach|methoden|sozial|selbst|personale|digitale)?kompetenz(?:en)?\b|\bwissen\s+und\s+verstehen\b|"
    r"\b(?:kenntnisse|fertigkeiten|lernziele?|qualifikationsziele?|lernergebnisse)\b|"
    r"\bknowledge\s+and\s+understanding\b|\b(?:learning\s+outcomes?|intended\s+outcomes?)\b|"
    r"\b(?:subject-specific|personal|social|methodological)\s+(?:competences?|competencies|skills)\b")
_PROSE_SUBJECT = re.compile(r"(?i:\b(?:(?:die|the)\s+)?(?:studierenden|students|lernenden|teilnehmenden|learners|participants)\b)|\b(?:Sie|They)\b")   # capital Sie/They only: the students, after a heading
_SCHEDULED = re.compile(r"(?i)\b(?:in|ab|bis|by|from|until)\s+(?:woche|week|kw)\s*\d")   # "Sie bilden in Woche 1 Teams": organisation
_TABLE_HEAD = re.compile(r"(?im)^[ \t]*(?:woche|week|wk\.?|kw|sitzung|session|termin|vorlesung|lecture)[ \t]*\|?[ \t]*"
                         r"(?:thema|themen|topic|topics|inhalt|inhalte|content|title)[ \t]*$")
_TABLE_ROW = re.compile(r"^[ \t]*(\d{1,2})[ \t]*(?:\||[.:)\-–])?[ \t]+(\S[^\n]{2,118}?)[ \t]*$")


def _flowing(text: str) -> str:
    """One line of running text: table bars and line breaks become spaces, a word split at the line end is joined."""
    text = re.sub(r"[ \t]*\|[ \t]*", " ", text or "")
    text = re.sub(r"(\w)-\n(?=[a-zäöüß])", r"\1", text)          # "Wissens-\nerschließung" -> "Wissenserschließung"
    text = re.sub(r"(\w)-\n(?=[A-ZÄÖÜ])", r"\1-", text)          # "Deep-Learning-\nPipelines" keeps its hyphen
    return " ".join(text.split())


def prose_outcomes(text: str) -> list:
    """Outcomes stated as sentences under a competence or outcomes heading of a plan document.

    Each sentence whose subject is the students ("Die Studierenden ...", "Sie ...", "Students ...", "They ...") is one
    outcome, kept as written. Text before the first heading is not read, so organisational slides without such a
    heading give nothing."""
    # A bullet list is not a paragraph: each item ends the sentence before it (the line rules read the items).
    text = re.sub(r"\n[ \t]*(?:[-*•]|\d+[.)])[ \t]+", "\n¶ ", text or "")
    flowing = _flowing(text)
    first = _COMPETENCE.search(flowing)
    if not first:
        return []
    found = []
    for sentence in re.split(r"\s*¶\s*|(?<=[.!?])(?<!\d\.)\s+", flowing[first.start():]):
        subject = _PROSE_SUBJECT.search(sentence)
        if not subject:
            continue
        before = sentence[:subject.start()]
        if before.strip() and not _COMPETENCE.search(before):
            continue                                          # the students are not the subject of this sentence
        candidate = sentence[subject.start():].strip().rstrip(",;")
        if candidate.endswith(":"):
            continue                                          # "Students will be able to:" opens a list
        if not 25 <= len(candidate) <= 600 or len(candidate.split()) < 5:
            continue
        if _ORGANISATION.search(candidate) or _NEGATED.search(candidate) or _SCHEDULED.search(candidate):
            continue
        found.append(candidate)
    # The same paragraph can reach us twice (as a table cell and as plain text) with different line breaks:
    # one outcome per word sequence, preferring the copy without a stray "- " from a broken line.
    unique = {}
    for candidate in found:
        key = " ".join(re.findall(r"\w+", candidate.lower()))
        if key not in unique or unique[key].count("- ") > candidate.count("- "):
            unique[key] = candidate
    return list(unique.values())


def table_schedule(text: str) -> list:
    """(number, topic) from a schedule table: a "Woche | Thema" / "Week | Topic" header followed by rows "1 | Topic".
    Rows must count up from where they start (a gap of one is allowed); the first other line ends the table."""
    entries = {}
    for head in _TABLE_HEAD.finditer(text or ""):
        last = None
        for line in text[head.end():].split("\n"):
            if not line.strip():
                continue
            row = _TABLE_ROW.match(line)
            if not row:
                break
            number, title = int(row.group(1)), row.group(2).strip(" .;:,|")
            if last is not None and not 0 < number - last <= 2:
                break
            last = number
            if number in entries or (_NO_TEACHING.search(title) and len(title.split()) <= 5):
                continue
            entries[number] = title
    return sorted(entries.items())


def is_fragment_of(line: str, sentences: list) -> bool:
    """True when `line` is one of `sentences`, or a piece of one, as read line by line from a wrapped paragraph."""
    def norm(value):
        return " ".join(re.findall(r"\w+", value.lower()))
    piece = norm(re.sub(r"^[^|]{0,40}\|", "", line))
    return bool(piece) and any(piece in norm(s) for s in sentences)          # also the same sentence, read line by line


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
