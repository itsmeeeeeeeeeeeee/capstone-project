# api/map.py
from fastapi import APIRouter
import requests

router = APIRouter()
KAKAO_KEY = "YOUR_KAKAO_REST_API_KEY"

@router.get("/pharmacies")
async def get_pharmacies(lat: float, lng: float):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    params = {"query": "약국", "x": lng, "y": lat, "radius": 2000}
    return requests.get(url, headers=headers, params=params).json()

@router.get("/waste-bins")
async def get_bins():
    # DB의 waste_bins 테이블에 있는 모든 데이터를 리스트로 가져옵니다.
    bins = db.query(models.WasteBin).all()
    return bins
