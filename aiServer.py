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
    return send_from_directory(".", "index.html")


# ─────────────────────────────────────────
#  OCR API
# ─────────────────────────────────────────

@app.route("/api/ocr", methods=["POST"])
def ocr():
    if "image" not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400

    image_data   = request.files["image"].read()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    payload = {
        "requests": [{
            "image": {"content": image_base64},
            "features": [{"type": "TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ko", "en"]},
        }]
    }

    response = requests.post(VISION_API_URL, json=payload)
    if response.status_code != 200:
        return jsonify({"error": f"Google API 오류: {response.text}"}), 500

    try:
        annotations = response.json()["responses"][0].get("textAnnotations", [])
        if not annotations:
            return jsonify({"text": "", "message": "텍스트를 찾을 수 없습니다."})
        return jsonify({"text": annotations[0]["description"]})
    except (KeyError, IndexError) as e:
        return jsonify({"error": f"응답 파싱 오류: {str(e)}"}), 500


# ─────────────────────────────────────────
#  알람 파싱 API
#  반환: HTML alarms 배열 구조와 호환되는 형식
#  times 포맷: "오전 8:00", "오후 12:00" 등
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


@app.route("/api/parse-alarm", methods=["POST"])
def parse_alarm():
    body     = request.get_json()
    ocr_text = body.get("text", "")

    if not ocr_text:
        return jsonify({"error": "텍스트가 없습니다."}), 400

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
- 약 이름을 찾을 수 없으면 "복약 알람"으로 써.

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

    raw = ""
    try:
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
            return jsonify({"error": f"OpenAI 오류: {res.text}"}), 500

        raw    = res.json()["choices"][0]["message"]["content"].strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)

        # times를 HTML 표시 형식("오전 8:00")으로 변환하고 color/enabled 추가
        drugs = parsed.get("drugs", [])
        for i, drug in enumerate(drugs):
            drug["times"] = [fmt_time_korean(t) for t in drug.get("times", ["08:00"])]
            drug["color"]   = COLORS[i % len(COLORS)]
            drug["enabled"] = True
            drug.setdefault("persons", [0])
            drug.setdefault("memo", "")

        return jsonify({"drugs": drugs})

    except json.JSONDecodeError:
        return jsonify({"error": "AI 응답을 JSON으로 파싱할 수 없습니다.", "raw": raw}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
#  이미지 통합 분석 API (OCR + 알람 파싱)
#  약봉지 사진 한 장으로 알람 데이터 반환
# ─────────────────────────────────────────

@app.route("/api/analyze-image", methods=["POST"])
def analyze_image():
    if "image" not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400

    # 1) OCR
    image_data   = request.files["image"].read()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    vision_payload = {
        "requests": [{
            "image": {"content": image_base64},
            "features": [{"type": "TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ko", "en"]},
        }]
    }
    vision_res = requests.post(VISION_API_URL, json=vision_payload)
    if vision_res.status_code != 200:
        return jsonify({"error": f"Google Vision 오류: {vision_res.text}"}), 500

    try:
        annotations = vision_res.json()["responses"][0].get("textAnnotations", [])
    except (KeyError, IndexError):
        return jsonify({"error": "OCR 응답 파싱 오류"}), 500

    if not annotations:
        return jsonify({"drugs": [], "message": "텍스트를 인식하지 못했습니다."})

    ocr_text = annotations[0]["description"]

    # 2) 알람 파싱 (parse_alarm 로직 재사용)
    parse_res = requests.post(
        "http://localhost:5000/api/parse-alarm",
        json={"text": ocr_text}
    )
    if not parse_res.ok:
        return jsonify({"error": "파싱 오류", "ocr_text": ocr_text}), 500

    result = parse_res.json()
    result["ocr_text"] = ocr_text
    return jsonify(result)


# ─────────────────────────────────────────
#  챗봇 대화 API
#  HTML의 BOT_QA 키워드 범주에 맞는 약학 AI 챗봇
# ─────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    body     = request.get_json()
    messages = body.get("messages", [])

    if not messages:
        return jsonify({"error": "메시지가 없습니다."}), 400

    system_msg = {
        "role": "system",
        "content": (
            "당신은 '약풀' 앱의 친근한 약사 AI 챗봇입니다. "
            "사용자의 복약 관리를 돕고, 의약품 정보와 복약 지도를 제공합니다.\n\n"
            "답변 가이드:\n"
            "- 타이레놀(아세트아미노펜): 해열·진통제, 공복 복용 가능, 하루 최대 4g, 음주 후 금지\n"
            "- 혈압약: NSAIDs와 병용 주의, 칼륨 함유 식품·보충제 주의\n"
            "- 소화효소제: 식사 직전·식후 즉시 / 위장운동 개선제(가스모틴): 식전 30분\n"
            "- 이부프로펜: 반드시 식후 복용, 신장 약하거나 임산부 주의\n"
            "- 아스피린: 이부프로펜 병용 시 효과 감소 주의, 식후 복용\n"
            "- 항히스타민제(알레르기): 졸음 유발 주의, 운전 금지\n"
            "- 위산억제제(오메프라졸): 식전 30분~1시간 공복 복용\n\n"
            "규칙:\n"
            "- 항상 한국어로 답변하세요.\n"
            "- 의학적 진단은 제공하지 마세요.\n"
            "- 쉬운 말로 3~5문장으로 간결하게 답변하세요.\n"
            "- 마지막에 '더 궁금한 점이 있으면 언제든 물어보세요 😊'를 추가하세요."
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
