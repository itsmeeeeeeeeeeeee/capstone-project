from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import base64
import json
import os

load_dotenv()

app = Flask(__name__)
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000", "null"])

OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY")

VISION_API_URL = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_API_KEY}"

COLORS = ['#1D9E75', '#378ADD', '#BA7517', '#7F77DD', '#E24B4A', '#639922']


# ─────────────────────────────────────────
#  HTML 서빙
# ─────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "yakpool_app_v4.html")


# ─────────────────────────────────────────
#  내부 헬퍼
# ─────────────────────────────────────────

def fmt_time_korean(t):
    """'08:00' → '오전 8:00', '13:00' → '오후 1:00'"""
    try:
        h, m = map(int, t.split(":"))
        period = "오전" if h < 12 else "오후"
        display_h = h if h <= 12 else h - 12
        if display_h == 0:
            display_h = 12
        return f"{period} {display_h}:{m:02d}"
    except Exception:
        return t


def _parse_drugs(ocr_text):
    """OCR 텍스트 → drugs 배열 (parse-alarm / analyze-image 공용)"""
    prompt = f"""다음은 약 봉투(또는 처방전)에서 OCR로 추출한 텍스트야.
텍스트에 등장하는 모든 의약품을 찾아 각각의 복약 정보를 추출해 아래 형식의 JSON만 반환해.
다른 말은 절대 하지 마.

반환 형식:
{{
  "drugs": [
    {{
      "name": "타이레놀 500mg",
      "times": ["08:00", "12:00", "18:00"],
      "dose": "1정",
      "meal": "식후",
      "gap": "30분 후",
      "days": [1,2,3,4,5],
      "memo": ""
    }}
  ]
}}

[name 추출 규칙]
- 의약품(약) 이름만 추출해. 병원명, 약국명, 환자명, 날짜, 주소는 절대 포함하지 마.
- 약 이름은 한글/영문 제품명으로 표기되고, "정", "캡슐", "mg", "ml" 같은 단위가 붙는 경우가 많아.
- 약 이름을 특정할 수 없는 항목은 drugs 배열에 포함하지 마.

[times 추출 규칙 - 각 약마다 개별 적용, 24시간 HH:MM 형식]
- "1일 3회" → ["08:00", "12:00", "18:00"]
- "1일 2회" → ["08:00", "18:00"]
- "1일 1회" → ["08:00"]
- "취침 전" → ["22:00"]
- 명시된 시각이 있으면 그 시각을 사용해 (예: "오전 8시" → "08:00")
- 해당 약의 복용 정보를 찾을 수 없으면 ["08:00"]으로 설정해.
- 약마다 복용 횟수/시간이 다를 수 있으니 반드시 개별적으로 추출해.

[meal 추출 규칙]
- "식후", "식전", "식사 직전", "공복" 중 하나로 반환해.
- 정보가 없으면 "식후"로 설정해.

[gap 추출 규칙]
- "즉시", "30분 후", "1시간 후" 중 하나로 반환해.
- 정보가 없으면 "30분 후"로 설정해.

[days 규칙]
- 처방전에 특정 요일이 명시된 경우 해당 요일(0=일,1=월,2=화,3=수,4=목,5=금,6=토)을 배열로.
- 명시되지 않으면 매일 [0,1,2,3,4,5,6]으로 설정해.

[기타 규칙]
- 약이 1개뿐이어도 반드시 drugs 배열에 담아서 반환해.
- 약을 하나도 찾지 못한 경우에만 drugs를 빈 배열로 반환해.

OCR 텍스트:
{ocr_text}

JSON:"""

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "max_tokens": 800,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    if not res.ok:
        raise RuntimeError(f"OpenAI 오류: {res.text}")

    raw = res.json()["choices"][0]["message"]["content"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)

    drugs = parsed.get("drugs", [])
    for i, drug in enumerate(drugs):
        drug["times"]   = [fmt_time_korean(t) for t in drug.get("times", ["08:00"])]
        drug["color"]   = COLORS[i % len(COLORS)]
        drug["enabled"] = True
        drug.setdefault("persons", [0])
        drug.setdefault("memo", "")

    return drugs


# ─────────────────────────────────────────
#  알람 파싱 API
# ─────────────────────────────────────────

@app.route("/api/parse-alarm", methods=["POST"])
def parse_alarm():
    body     = request.get_json(force=True, silent=True) or {}
    ocr_text = body.get("text", "")

    if not ocr_text:
        return jsonify({"error": "텍스트가 없습니다."}), 400

    try:
        return jsonify({"drugs": _parse_drugs(ocr_text)})
    except json.JSONDecodeError:
        return jsonify({"error": "AI 응답을 JSON으로 파싱할 수 없습니다."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
#  이미지 통합 분석 API (OCR + 알람 파싱)
# ─────────────────────────────────────────

@app.route("/api/analyze-image", methods=["POST"])
def analyze_image():
    if "image" not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400

    image_data   = request.files["image"].read()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    vision_res = requests.post(VISION_API_URL, json={
        "requests": [{
            "image": {"content": image_base64},
            "features": [{"type": "TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ko", "en"]},
        }]
    })
    if vision_res.status_code != 200:
        return jsonify({"error": f"Google Vision 오류: {vision_res.text}"}), 500

    try:
        annotations = vision_res.json()["responses"][0].get("textAnnotations", [])
    except (KeyError, IndexError):
        return jsonify({"error": "OCR 응답 파싱 오류"}), 500

    if not annotations:
        return jsonify({"drugs": [], "message": "텍스트를 인식하지 못했습니다."})

    ocr_text = annotations[0]["description"]

    try:
        return jsonify({"drugs": _parse_drugs(ocr_text), "ocr_text": ocr_text})
    except json.JSONDecodeError:
        return jsonify({"error": "AI 응답을 JSON으로 파싱할 수 없습니다.", "ocr_text": ocr_text}), 500
    except Exception as e:
        return jsonify({"error": str(e), "ocr_text": ocr_text}), 500


# ─────────────────────────────────────────
#  챗봇 대화 API
# ─────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    body     = request.get_json(force=True, silent=True) or {}
    messages = body.get("messages", [])

    if not messages:
        return jsonify({"error": "메시지가 없습니다."}), 400

    system_msg = {
        "role": "system",
        "content": (
            "당신은 '약풀' 앱의 친근한 약사 AI 챗봇입니다. "
            "어르신들이 쉽게 읽을 수 있도록 짧고 명확하게 답변하세요.\n\n"

            "## 답변 형식 (반드시 준수)\n\n"

            "### 경우 1 — 약 이름·정보를 처음 물어볼 때\n"
            "첫 줄: '[약 이름]은/는 [무엇인지 자연스럽게]예요/이에요.' 한 문장으로 시작하세요.\n"
            "그 다음 아래 항목을 사용하세요. 각 항목은 한 문장으로 작성하세요.\n\n"
            "[효능] : 이 약이 어디에 쓰이는지 한 문장.\n"
            "[복용법] : 언제, 몇 알 먹는지 한 문장.\n"
            "[주의사항] : 가장 중요한 주의사항 한 가지만 한 문장.\n\n"
            "예시:\n"
            "타이레놀은 열을 내리고 통증을 줄여주는 약이에요.\n"
            "[효능] : 열을 내리고 몸이 아플 때 쓰는 약이에요.\n"
            "[복용법] : 하루 세 번, 밥 먹은 후에 1알 드세요.\n"
            "[주의사항] : 술 마신 날에는 드시면 안 돼요.\n\n"

            "### 경우 2 — 부작용·복용시간·병용 등 특정 질문을 할 때\n"
            "항목 형식을 쓰지 말고, 질문에 맞게 자연스럽게 1~2문장으로 답하세요.\n\n"
            "예시 (부작용이 있나요?):\n"
            "많이 드시면 속이 불편하거나 간에 무리가 갈 수 있어요. 하루 8알을 넘기지 않는 게 좋아요.\n\n"
            "예시 (식전에 먹어도 되나요?):\n"
            "네, 빈속에 드셔도 괜찮아요.\n\n"

            "## 추가 규칙\n\n"
            "- g·mg 단위 금지. '알', '정', '봉지', '포' 같은 실물 단위 사용.\n"
            "- 성분명·전문 용어 금지. 일상어로 바꿔 쓰세요.\n"
            "  ('아세트아미노펜' → 언급하지 않음, '항히스타민제' → '알레르기 약')\n"
            "- 병 진단은 절대 하지 마세요.\n"
            "- 항상 한국어, 친근한 말투 (~해요, ~세요).\n"
            "- 약 이름, 복용 횟수/시간, 주의사항처럼 특히 중요한 단어나 구절은 **굵게** 표시하세요. 예: **타이레놀**, **하루 세 번**, **술 마신 날에는 드시면 안 돼요**.\n\n"

            "## 후속 질문 제안\n\n"
            "답변 맨 마지막 줄에 반드시 아래 형식으로 후속 질문을 제안하세요.\n"
            "형식: [ACTIONS: 버튼1|버튼2|버튼3]\n"
            "예시 버튼: '부작용이 있나요?', '다른 약과 같이 먹어도 되나요?', '식전에 먹어도 되나요?'\n\n"

            "## 약 지식\n\n"
            "- 타이레놀: 열 내리고 아플 때. 빈속 가능. 하루 8알 이하. 술 마신 날 금지.\n"
            "- 혈압약: 진통제와 함께 먹으면 안 됨.\n"
            "- 소화제: 밥 먹기 직전 또는 직후 복용.\n"
            "- 위장 운동 개선약: 밥 먹기 30분 전 복용.\n"
            "- 진통소염제: 반드시 식후 복용. 신장 안 좋거나 임산부 주의.\n"
            "- 알레르기 약: 졸릴 수 있어 운전 시 주의.\n"
            "- 속 쓰림 약: 밥 먹기 30분~1시간 전 빈속 복용.\n"
        )
    }

    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 500,
                "messages": [system_msg] + messages[-10:]
            }
        )
        if not res.ok:
            return jsonify({"error": res.json().get("error", {}).get("message", "OpenAI 오류")}), 500

        result = res.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("✅ 약풀 서버 시작: http://localhost:5000")
    app.run(debug=True, port=5000)
