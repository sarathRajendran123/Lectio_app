"""Strict model output contract and deterministic evidence checks."""
import json
import re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class SourceSupport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:int=Field(ge=1)
    quote:str|None=Field(default=None,min_length=8,max_length=1600)
    excerpt_id:str|None=Field(default=None,pattern=r'^S[1-9][0-9]*Q[1-4]$')

    @model_validator(mode='after')
    def require_quote_or_excerpt(self):
        if self.quote is None and self.excerpt_id is None:
            raise ValueError('A source quote or excerpt ID is required.')
        return self

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

def _verbatim_source_quote(quote, source):
    """Return the exact source substring, allowing whitespace-only copy differences."""
    if quote in source:
        return quote
    words = re.split(r'\s+', quote.strip())
    if len(words) < 2 or not all(words):
        return None
    match = re.search(r'\s+'.join(re.escape(word) for word in words), source)
    return match.group(0) if match else None

def source_excerpts(source, source_number):
    """Return up to four exact, bounded source substrings for model selection."""
    passages = []
    for match in re.finditer(r'[^\n]{1,200}', source):
        text = match.group(0).strip()
        if len(text) >= 8 and text not in passages:
            passages.append(text)
        if len(passages) == 4:
            break
    if not passages:
        text = source.strip()[:200]
        if len(text) >= 8:
            passages.append(text)
    return {f'S{source_number}Q{i}': text for i, text in enumerate(passages, 1)}

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
            if support.excerpt_id is not None:
                quote = source_excerpts(chunk.text, support.source).get(support.excerpt_id)
                if quote is None:
                    raise ValueError('Generated excerpt ID was not offered for its cited source.')
                if support.quote is not None and _verbatim_source_quote(support.quote, chunk.text) is None:
                    raise ValueError('Generated quotation does not occur verbatim in its cited source.')
            else:
                quote = _verbatim_source_quote(support.quote, chunk.text)
            if quote is None:
                raise ValueError('Generated quotation does not occur verbatim in its cited source.')
            # Store and display the actual original characters, never the model's
            # whitespace-adjusted rendering. No wording changes are accepted.
            support.quote = quote
            marker=f'[SOURCE_{support.source}]';markers.append(marker)
            key=(marker,support.quote)
            citations[key]={'marker':marker,'citation':chunk.to_citation(),'chunk_id':chunk.chunk_id,'artifact_id':chunk.artifact_id,
                'quote':support.quote,'page_number':chunk.page_number,'slide_number':chunk.slide_number,'section_title':chunk.section_title,
                'artifact_type':chunk.artifact_type,'verification':'Exact source excerpt resolved; relevance is unverified and the proposed interpretation requires lecturer approval.'}
        # Text is a proposal/inference, not a verified observation; avoid implying entailment.
        rendered+=['### '+section.heading,section.text+' '+' '.join(dict.fromkeys(markers)),
            '_'+section.interpretation.replace('_',' ')+'; lecturer review required._']
    if draft.limitations:rendered+=['### Limitations']+['- '+l for l in draft.limitations]
    return '\n\n'.join(rendered),list(citations.values()),draft
