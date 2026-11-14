import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from config import settings
from rag.parsers.base_parser import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)
PATH_LIKE = re.compile(r'[A-Za-z]:[\\/]|[\\/]\w+[\\/]')

def lecturer_message(last_line, file_type):
    """What the lecturer is shown when parsing fails: the reasons our parsers give as written, anything else without internals.

    Our parsers raise ValueError with a plain sentence. A library error can carry its class name and the server's
    file path; neither belongs in the interface."""
    line = (last_line or '').strip()
    text = line[len('ValueError:'):].strip()
    if line.startswith('ValueError:') and text and not PATH_LIKE.search(text):
        return text[:350]
    return f'The file could not be read as {file_type.upper()}. It may be damaged or incomplete; export or save it again and upload the new file.'

async def parse_document(path, file_type, artifact_type):
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'services.parser_worker', str(Path(path).resolve()), file_type, artifact_type,
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), settings.parser_timeout_seconds)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.communicate()
        raise ValueError('Document processing exceeded its time limit.')
    if process.returncode:
        message = stderr.decode(errors='replace').strip().splitlines()
        logger.warning('Parser failed for a %s file: %s', file_type, message[-1][:500] if message else 'no error output')
        raise ValueError(lecturer_message(message[-1] if message else '', file_type))
    data = json.loads(stdout)
    data['blocks'] = [ParsedBlock(**block) for block in data['blocks']]
    return ParsedDocument(**data)
