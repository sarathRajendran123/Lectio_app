"""Explicit probes with bounded timeouts; configuration never equals readiness."""
import asyncio
import shutil
from config import settings

async def probe_services():
    import httpx
    results={'mode':settings.runtime_mode,'database':{'status':'unknown'},'ocr':{'status':'available' if shutil.which('tesseract') else 'not_installed'}}
    from db.session import AsyncSessionLocal
    from sqlalchemy import text
    try:
        async with AsyncSessionLocal() as db:await asyncio.wait_for(db.execute(text('SELECT 1')),5)
        results['database']={'status':'operational'}
    except Exception:results['database']={'status':'unavailable','message':'Database probe failed.'}
    if settings.runtime_mode=='local_test':results['llm']={'status':'disabled','message':'Deterministic testing mode; no model inference.'}
    elif not settings.llm_ready:results['llm']={'status':'not_configured'}
    else:
        try:
            async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
                response=await client.get(settings.openrouter_base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+settings.openrouter_api_key})
                response.raise_for_status();models={m['id'] for m in response.json().get('data',[])}
            results['llm']={'status':'reachable' if settings.openrouter_model in models else 'model_unavailable','model':settings.openrouter_model,'inference_tested':False}
        except Exception:results['llm']={'status':'unavailable','message':'Provider probe failed; verify network, credentials and model availability.'}
    if settings.runtime_mode=='local_test' or settings.retrieval_backend=='lexical':
        results['retrieval']={'status':'operational','backend':'lexical hash vectors; not neural embeddings'}
    else:
        results['retrieval']={'status':'operational' if results['database']['status']=='operational' else 'unavailable',
            'backend':'multilingual dense ('+settings.embedding_model+') + BM25 / transactional SQL vectors','embedding_inference_tested':False,
            'message':'Vector persistence uses the course database. Neural model files require first use.'}
    if not settings.paperclip_api_url or not settings.paperclip_api_key:results['paperclip']={'status':'not_configured'}
    else:
        try:
            async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
                r=await client.get(settings.paperclip_api_url.rstrip('/')+'/api/agents/me',headers={'Authorization':'Bearer '+settings.paperclip_api_key});r.raise_for_status()
                agent=r.json()
            results['paperclip']={'status':'reachable','agent_id':agent.get('id'),'company_id':agent.get('companyId')}
        except Exception:results['paperclip']={'status':'unavailable','message':'Paperclip agent identity probe failed.'}
    return results
