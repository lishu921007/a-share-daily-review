from fastapi import APIRouter
from app.services.universe import info
router=APIRouter(prefix='/api/universe', tags=['universe'])
@router.get('/info')
def universe_info(): return info()
@router.post('/reload')
def reload_universe(): return info()
