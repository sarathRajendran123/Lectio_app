"""Strict model output contract and deterministic evidence checks."""
import json
import re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

class SourceSupport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:int=Field(ge=1)
    quote:str=Field(min_length=8,max_length=1600)

class DraftSection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    heading:str=Field(min_length=2,max_length=150)
    text:str=Field(min_length=8,max_length=5000)
    supports:list[SourceSupport]=Field(min_length=1,max_length=6)
    interpretation:Literal['source_summary','proposed_content','unverified_inference']='proposed_content'

class EducationalDraft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=3,max_length=200)
    sections:list[DraftSection]=Field(min_length=1,max_length=12)
    limitations:list[str]=Field(default_factory=list,max_length=10)
    bloom_level:Literal['remember','understand','apply','analyse','evaluate','create']|None=None

def parse_draft(raw,chunks):
    cleaned=raw.strip()
    if cleaned.startswith('```'):
        cleaned=re.sub(r'^```(?:json)?\s*','',cleaned);cleaned=re.sub(r'\s*```$','',cleaned)
    draft=EducationalDraft.model_validate_json(cleaned)
    citations={};rendered=['## '+draft.title]
    for section in draft.sections:
        markers=[]
        for support in section.supports:
            if support.source>len(chunks):raise ValueError('Generated source number was not included in the prompt.')
            chunk=chunks[support.source-1]
            if support.quote not in chunk.text:
                raise ValueError('Generated quotation does not occur verbatim in its cited source.')
            marker=f'[SOURCE_{support.source}]';markers.append(marker)
            key=(marker,support.quote)
            citations[key]={'marker':marker,'citation':chunk.to_citation(),'chunk_id':chunk.chunk_id,'artifact_id':chunk.artifact_id,
                'quote':support.quote,'page_number':chunk.page_number,'slide_number':chunk.slide_number,'section_title':chunk.section_title,
                'artifact_type':chunk.artifact_type,'verification':'Verbatim quote validated; proposed interpretation requires lecturer approval.'}
        # Text is a proposal/inference, not a verified observation; avoid implying entailment.
        rendered+=['### '+section.heading,section.text+' '+' '.join(dict.fromkeys(markers)),
            '_'+section.interpretation.replace('_',' ')+'; lecturer review required._']
    if draft.limitations:rendered+=['### Limitations']+['- '+l for l in draft.limitations]
    return '\n\n'.join(rendered),list(citations.values()),draft
