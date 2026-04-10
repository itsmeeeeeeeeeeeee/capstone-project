# services/ai_service.py
import httpx

AI_SERVER_URL = "http://localhost:5000/generate"

async def get_ai_response(user_message: str):

    async with httpx.AsyncClient() as client:
        res = await client.post(
            AI_SERVER_URL,
            json={"message": user_message}
        )

    data = res.json()
    return data["response"]