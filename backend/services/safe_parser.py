import asyncio
import json
import sys
from pathlib import Path
from config import settings
from rag.parsers.base_parser import ParsedBlock, ParsedDocument

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
        raise ValueError(message[-1][:350] if message else 'Document parser failed.')
    data = json.loads(stdout)
    data['blocks'] = [ParsedBlock(**block) for block in data['blocks']]
    return ParsedDocument(**data)
