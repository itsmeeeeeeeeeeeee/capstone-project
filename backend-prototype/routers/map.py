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
    # DB에 저장된 폐의약품 수거함 데이터를 반환
    return [{"place_name": "강남구 보건소", "lat": 37.5173, "lng": 127.0474}]
