"""Parser subprocess: bounded lifetime; Linux CPU/address-space ceilings."""
import json
import sys
from dataclasses import asdict

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
        raise ValueError('No extractable text. For scanned PDFs, install Tesseract or upload a text/OCR version.')
    if len(parsed.all_text()) > 5_000_000:
        raise ValueError('Extracted text exceeds 5 million characters.')
    print(json.dumps(asdict(parsed)))

if __name__ == '__main__':
    main()
