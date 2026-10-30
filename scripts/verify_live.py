"""Opt-in actual-provider verification. A failure is reported; never fallback to test templates."""
import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1];load_dotenv(root/'.env');sys.path.insert(0,str(root/'backend'))
from config import settings
from services.health_service import probe_services
from rag.chunking.chunk_models import RetrievedChunk
from rag.generation.grounded_generator import GroundedGenerator

def main():
    if settings.runtime_mode!='live':raise SystemExit('Set RUNTIME_MODE=live and configure GROQ_API_KEY first. Local-test results are not accepted by this check.')
    print(json.dumps(asyncio.run(probe_services()),indent=2))
    source=RetrievedChunk('live-verification-source','Binary search repeatedly halves a sorted array. Its time complexity is logarithmic in the array length.',1.,'live-verification-fixture','slides','live-verification-course',1,None,None,None)
    # Clearly synthetic provider smoke fixture. This is not a real-course evaluation.
    result=GroundedGenerator().generate('Create one measurable objective and one short exercise about binary search. Include marking guidance.',[source])
    assert result.model!='local-test-template' and result.citations
    print(json.dumps({'status':'inference_passed','model':result.model,'tokens_used':result.tokens_used,'citations_validated':len(result.citations),'fixture':'synthetic provider smoke test'}))

if __name__=='__main__':main()
