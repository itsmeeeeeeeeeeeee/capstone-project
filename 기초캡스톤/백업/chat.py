from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from database import SessionLocal, Medicine
from services.ai_service import get_ai_response

router = APIRouter()

# DB 연결
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/chat")
async def chat(request: Request, db: Session = Depends(get_db)):

    data = await request.json()
    user_message = data.get("message")

    # 1️⃣ 약 이름 먼저 DB 검색
    db_result = db.query(Medicine).filter(
        Medicine.item_name.contains(user_message)
    ).first()

    if db_result:
        base_info = f"""
[약 정보]
이름: {db_result.item_name}
효능: {db_result.efcy_info}
복용법: {db_result.use_method}
주의사항: {db_result.atpn_warn}
"""

        # 2️⃣ AI 추가 설명
        ai_response = await get_ai_response(user_message)

        return {
            "response": base_info + "\n[추가 설명]\n" + ai_response
        }

    # 3️⃣ 일반 질문 → AI만
    ai_response = await get_ai_response(user_message)

    return {"response": ai_response}