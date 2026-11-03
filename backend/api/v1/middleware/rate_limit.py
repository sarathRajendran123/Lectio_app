"""Bounded in-process login throttle; use a shared proxy limit for multi-instance deployments."""
import time
from collections import OrderedDict,deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class LoginRateLimit(BaseHTTPMiddleware):
    def __init__(self,app):super().__init__(app);self.windows=OrderedDict()
    async def dispatch(self,request,call_next):
        if request.method=='POST' and request.url.path in ('/api/v1/auth/login','/api/v1/auth/refresh'):
            key=request.client.host if request.client else 'unknown'
            now=time.monotonic();window=self.windows.setdefault(key,deque())
            self.windows.move_to_end(key)
            while window and now-window[0]>60:window.popleft()
            if len(window)>=30:
                return JSONResponse({'detail':'Too many authentication attempts. Try again in one minute.'},status_code=429,headers={'Retry-After':'60'})
            window.append(now)
            while len(self.windows)>10000:self.windows.popitem(last=False)
        return await call_next(request)
