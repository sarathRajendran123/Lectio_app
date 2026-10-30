import io
import pytest

def test_office_pdf_formats_and_empty_pdf(client,headers):
    import fitz
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches
    r=client.post('/api/v1/courses',headers=headers,json={'code':'FORMATS','title':'Format checks'})
    course=r.json()['id'];base=f'/api/v1/courses/{course}'
    pdf=fitz.open();p=pdf.new_page();p.insert_text((50,50),'Binary search algorithm repeatedly halves a sorted sequence of elements.');pdf_bytes=pdf.tobytes();pdf.close()
    doc=Document();doc.add_heading('Algorithms',0);doc.add_paragraph('Students will be able to explain binary search complexity.');out=io.BytesIO();doc.save(out)
    ppt=Presentation();slide=ppt.slides.add_slide(ppt.slide_layouts[1]);slide.shapes.title.text='Binary search';slide.placeholders[1].text='Compare binary search and linear search. Explain logarithmic complexity.';slides=io.BytesIO();ppt.save(slides)
    for name,data,mime in [('lecture.pdf',pdf_bytes,'application/pdf'),('syllabus.docx',out.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),('lecture.pptx',slides.getvalue(),'application/vnd.openxmlformats-officedocument.presentationml.presentation')]:
        r=client.post(base+'/artifacts',headers=headers,files={'file':(name,data,mime)},data={'artifact_type':'slides'})
        assert r.status_code==201,r.text
        status=client.get(base+'/artifacts/'+r.json()['id']+'/status',headers=headers).json()
        assert status['processing_status']=='done',status
    refs=client.get(base+'/evidence',headers=headers).json()
    assert any(r['page']==1 for r in refs)
    assert any(r['slide']==1 for r in refs)
    pdf=fitz.open();pdf.new_page();empty=pdf.tobytes();pdf.close()
    r=client.post(base+'/artifacts',headers=headers,files={'file':('scan.pdf',empty,'application/pdf')},data={'artifact_type':'slides'})
    assert r.status_code==201
    result=client.get(base+'/artifacts/'+r.json()['id']+'/status',headers=headers).json()
    assert result['processing_status']=='error' and 'No extractable text' in result['processing_error']

def test_missing_evidence_not_pass():
    from agents.alignment_agents import MetadataAssessmentAlignmentAgent,ContentDeliveryAlignmentAgent
    from agents.content_assessment_agent import ContentAssessmentAlignmentAgent
    state={'course_id':'none','modules':[],'assessments':[]}
    for agent in [MetadataAssessmentAlignmentAgent(),ContentDeliveryAlignmentAgent(),ContentAssessmentAlignmentAgent()]:
        result=agent.run(state)['alignment_results']
        assert next(iter(result.values())).status=='needs_review'

def test_parser_rejects_encrypted_pdf(client,headers):
    import fitz
    course=client.post('/api/v1/courses',headers=headers,json={'code':'LOCKED-PDF','title':'Encrypted document test'}).json()['id']
    doc=fitz.open();doc.new_page().insert_text((40,40),'Private encrypted course document.')
    payload=doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='secret');doc.close()
    r=client.post(f'/api/v1/courses/{course}/artifacts',headers=headers,files={'file':('locked.pdf',payload,'application/pdf')},data={'artifact_type':'slides'})
    assert r.status_code==201
    status=client.get(f'/api/v1/courses/{course}/artifacts/'+r.json()['id']+'/status',headers=headers).json()
    assert status['processing_status']=='error' and 'Encrypted PDFs' in status['processing_error']
