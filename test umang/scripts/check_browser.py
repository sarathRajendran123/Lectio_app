"""Real-browser smoke checks; screenshots stay in disposable local data only."""
import os
import sys
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import httpx
root=Path(__file__).resolve().parents[1];load_dotenv(root/'.env');os.chdir(root)
logs=open(root/'data/browser-services.log','w')
processes=[]
try:
    processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--app-dir','backend','--host','127.0.0.1','--port','8011'],stdout=logs,stderr=logs))
    env=dict(os.environ,BACKEND_URL='http://127.0.0.1:8011')
    processes.append(subprocess.Popen([sys.executable,'-m','streamlit','run','frontend/app.py','--server.address','127.0.0.1','--server.port','8511','--browser.gatherUsageStats','false'],env=env,stdout=logs,stderr=logs))
    with httpx.Client(trust_env=False,timeout=1) as client:
        for _ in range(120):
            try:
                if client.get('http://127.0.0.1:8011/health').status_code==200 and client.get('http://127.0.0.1:8511/_stcore/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto('http://127.0.0.1:8511');page.get_by_label('Email',exact=True).fill(os.environ['ADMIN_EMAIL']);page.get_by_label('Password',exact=True).fill(os.environ['ADMIN_PASSWORD'])
        page.get_by_role('button',name='Login',exact=True).click()
        page.get_by_role('heading',name='Your courses, in alignment').wait_for(timeout=30000)
        page.screenshot(path=str(root/'data/desktop-dashboard.png'),full_page=True)
        page.get_by_text('Course workbench',exact=True).click()
        page.get_by_role('heading',name='Course workbench',exact=True).wait_for()
        page.get_by_role('tab',name='Create drafts',exact=True).click()
        page.get_by_label('Purpose and relevant course topic',exact=True).fill('Practice binary search complexity')
        page.get_by_role('button',name='Generate draft alternatives',exact=True).click()
        page.get_by_text('Drafts are saved. Review, edit or approve them in Approval Center.',exact=True).wait_for(timeout=30000)
        page.screenshot(path=str(root/'data/desktop-workbench.png'),full_page=True)
        page.get_by_text('Approval Center',exact=True).first.click()
        page.get_by_role('heading',name='Approval Center',exact=True).wait_for()
        page.get_by_role('button',name='Approve',exact=True).first.click()
        page.get_by_role('button',name='Confirm Approval',exact=True).first.click()
        page.wait_for_timeout(500)
        phone=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        phone.goto('http://127.0.0.1:8511')
        phone.get_by_label('Email',exact=True).fill(os.environ['ADMIN_EMAIL'])
        phone.get_by_label('Password',exact=True).fill(os.environ['ADMIN_PASSWORD'])
        phone.get_by_role('button',name='Login',exact=True).click()
        phone.get_by_role('heading',name='Your courses, in alignment').wait_for(timeout=30000)
        phone.screenshot(path=str(root/'data/mobile-dashboard.png'),full_page=True)
        errors=phone.locator('[data-testid="stException"]').count()+page.locator('[data-testid="stException"]').count()
        assert errors==0,'Application displayed a browser exception'
        print('PASS browser login, dashboard, draft generation, approval and fresh mobile session')
        browser.close()
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill()
    logs.close()
