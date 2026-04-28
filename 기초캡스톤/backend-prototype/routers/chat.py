from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from database import SessionLocal, Medicine

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
    user_message = data.get("message", "").strip()

    # 메시지가 비어있는 경우
    if not user_message:
        return {"response": "메시지를 입력해주세요."}

    # 1. DB에서 약 이름으로 검색
    db_result = db.query(Medicine).filter(
        Medicine.item_name.contains(user_message)
    ).first()

    # 2. 약 정보가 있으면 -> DB 정보만 반환 (AI 설명은 임시 비활성화)
    if db_result:
        response_text = f"""[약 정보]

이름: {db_result.item_name}

효능: {db_result.efcy_info or "정보 없음"}

복용법: {db_result.use_method or "정보 없음"}

주의사항: {db_result.atpn_warn or "정보 없음"}

보관법: {db_result.deposit_method or "정보 없음"}"""

        return {"response": response_text}

    # 3. 약 정보가 없으면 -> 안내 메시지
    return {
        "response": f"'{user_message}'에 대한 약 정보를 찾을 수 없어요.\n\n약 이름을 정확히 입력해주시거나, 다른 약을 검색해보세요.\n\n(현재 AI 챗봇 서버는 점검 중이라 일반 질문은 답변이 어려워요. 약 이름으로 검색해주세요!)"
    }
