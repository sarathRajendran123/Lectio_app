"""Paperclip process runtime: identity -> checkout -> Lectio -> governed review.

No content is automatically approved. Configure a known issue and short-lived
course-owner credentials. Never retry a Paperclip checkout conflict.
"""
import json
import os
import time
import httpx

def request(client,method,path,**kwargs):
    r=client.request(method,path,**kwargs)
    if r.status_code==409:raise RuntimeError('Paperclip checkout/revision conflict; automatic retry is forbidden.')
    r.raise_for_status();return r.json() if r.content else {}

class PaperclipGovernance:
    def __init__(self,api_url,token,run_id,issue_id,transport=None):
        if not run_id:raise ValueError('PAPERCLIP_RUN_ID is required for governance mutations.')
        self.issue_id=issue_id
        self.client=httpx.Client(base_url=api_url.rstrip('/'),timeout=15,trust_env=False,transport=transport,
            headers={'Authorization':'Bearer '+token,'X-Paperclip-Run-Id':run_id})
    def checkout(self):
        identity=request(self.client,'GET','/api/agents/me')
        return request(self.client,'POST',f'/api/issues/{self.issue_id}/checkout',json={
            'agentId':identity['id'],'expectedStatuses':['todo','backlog','blocked','in_review']})
    def handoff(self,result):
        status='blocked' if result['status'] in ('failed','cancelled') else 'in_review'
        summary={'lectio_run_id':result['run_id'],'status':result['status'],'human_approval_required':True}
        return request(self.client,'PATCH',f'/api/issues/{self.issue_id}',json={
            'status':status,'comment':'Lectio audit handoff. '+json.dumps(summary)})
    def close(self):self.client.close()

def main():
    base=os.environ.get('LECTIO_API_URL','http://127.0.0.1:8000').rstrip('/')
    token=os.environ['LECTIO_ACCESS_TOKEN'];course=os.environ['LECTIO_COURSE_ID']
    governance=None;run=None
    issue=os.environ.get('PAPERCLIP_TASK_ID')
    if issue:
        governance=PaperclipGovernance(os.environ['PAPERCLIP_API_URL'],os.environ['PAPERCLIP_API_KEY'],os.environ['PAPERCLIP_RUN_ID'],issue)
        governance.checkout()
    try:
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},timeout=30,trust_env=False) as client:
            response=client.post(f'/api/v1/courses/{course}/run-audit');response.raise_for_status();run=response.json()['run_id']
            deadline=time.monotonic()+540
            while time.monotonic()<deadline:
                response=client.get(f'/api/v1/runs/{run}');response.raise_for_status();result=response.json()
                if result['status']!='running':
                    if governance:governance.handoff(result)
                    print(json.dumps({'lectio':result,'paperclip_issue_id':issue,'human_approval_required':True}))
                    return 1 if result['status'] in ('failed','cancelled') else 0
                time.sleep(2)
            client.post(f'/api/v1/runs/{run}/cancel').raise_for_status()
            if governance:governance.handoff({'run_id':run,'status':'cancelled'})
            raise RuntimeError('Lectio audit exceeded adapter time budget.')
    except Exception:
        if run:
            try:
                with httpx.Client(base_url=base,headers={"Authorization":"Bearer "+token},timeout=10,trust_env=False) as client:
                    client.post(f"/api/v1/runs/{run}/cancel")
            except httpx.HTTPError:pass
        if governance:
            try:governance.handoff({"run_id":run,"status":"failed"})
            except Exception:pass  # preserve original failure; caller/operator sees nonzero exit
        raise
    finally:
        if governance:governance.close()

if __name__=='__main__':raise SystemExit(main())
