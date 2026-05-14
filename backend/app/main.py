from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers.review import router as review_router
from app.routers.universe import router as universe_router

app=FastAPI(title='A股每日复盘系统', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.include_router(review_router)
app.include_router(universe_router)

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={'detail': f'系统异常：{exc}'})
