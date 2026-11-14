"""Parser subprocess: bounded lifetime; Linux CPU/address-space ceilings."""
import sys
RESULT, sys.stdout = sys.stdout, sys.stderr   # stdout is reserved for the one JSON result (see workflow_worker)
import json
from dataclasses import asdict

NO_TEXT = {
    'pdf': 'No extractable text. For scanned PDFs, install Tesseract or upload a text/OCR version.',
    'vtt': 'No spoken text was found. A transcript needs cue lines such as "00:00:01.000 --> 00:00:05.000", each followed by what was said.',
}

def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    except ImportError:
        pass  # Windows still has parent-enforced wall-clock timeout.
    from rag.parsers import get_parser
    parsed = get_parser(sys.argv[2]).parse(sys.argv[1], sys.argv[3])
    if not parsed.all_text().strip():
        raise ValueError(NO_TEXT.get(sys.argv[2], 'The document contains no text.'))
    import re
    from config import settings
    words = {w.lower() for w in re.findall(r'[^\W\d_]{3,}', parsed.all_text()[:200_000])}
    if len(words) < settings.min_distinct_words:
        raise ValueError('The document contains no readable text: fewer than %d different words were found.' % settings.min_distinct_words)
    if len(parsed.all_text()) > 5_000_000:
        raise ValueError('Extracted text exceeds 5 million characters.')
    RESULT.write(json.dumps(asdict(parsed)))
    RESULT.flush()

if __name__ == '__main__':
    main()
