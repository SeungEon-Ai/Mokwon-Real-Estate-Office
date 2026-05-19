from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
import os

# ─── Flask 앱 ───
app = Flask(__name__)
CORS(app)

# ─── Groq 클라이언트 ───
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─── 시스템 프롬프트 ───
SYSTEM_PROMPT = """당신은 "목원부동산중개사무소"의 AI 상담 도우미입니다.

[중개사무소 정보]
- 상호: 목원부동산중개사무소
- 위치: 대구광역시 수성구 중동
- 주력 매물: 아파트 매매/전세/월세, 상가
- 주요 취급 지역: 대구 수성구 황금동, 만촌동 및 인근 지역
- 영업시간: 평일·토요일 09:00~19:00 (일요일 휴무)
- 연락처: 010-4520-5114
- 특징: 다양한 매물 보유, 친절하고 경험 많은 중개사

[자주 묻는 질문]

Q: 중개수수료는 얼마인가요?
A: 중개수수료는 거래 유형과 금액에 따라 법정 요율이 적용됩니다.
   매매: 5천만원 이하 0.6%, 2억 이하 0.5%, 9억 이하 0.4% 등
   전/월세: 5천만원 이하 0.5%, 1억 이하 0.4% 등
   정확한 금액은 매물에 따라 다르니 전화 주시면 바로 계산해드립니다.

Q: 전세 계약 시 주의사항은?
A: 등기부등본 확인, 전입신고, 확정일자 받기가 가장 중요합니다.
   임대인의 세금 체납 여부도 확인하시는 것이 좋습니다.

Q: 매물을 보려면?
A: 전화(010-4520-5114) 또는 사무소 방문해주시면 조건에 맞는 매물을 안내해드립니다.

[상담 규칙]
1. 친절하고 전문적인 어조를 사용하세요.
2. 고객의 조건(예산, 지역, 매물 유형, 입주 시기)을 자연스럽게 파악하세요.
3. 구체적 매물 가격/시세는 "최신 매물은 전화 상담(010-4520-5114)으로 안내드립니다"라고 하세요.
4. 복잡한 법률/세금은 "전문가 상담을 권해드립니다"라고 하세요.
5. 답변 끝에 자연스럽게 방문/전화 상담을 유도하세요.
6. 한국어로만, 3~5문장 이내로 답변하세요.
7. 부동산 외 질문은 "부동산 관련 질문을 해주세요!"로 안내하세요.
"""

# ─── 대화 기록 (세션별) ───
conversations = {}

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "running",
        "message": "목원부동산 AI 챗봇 서버가 실행 중입니다 🏠"
    })

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "메시지를 입력해주세요."}), 400

        # 세션별 대화 기록 (최근 10개만 유지)
        if session_id not in conversations:
            conversations[session_id] = []

        conversations[session_id].append({
            "role": "user",
            "content": user_message
        })
        recent = conversations[session_id][-10:]

        # Groq API 호출
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *recent
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=500,
        )

        reply = completion.choices[0].message.content

        conversations[session_id].append({
            "role": "assistant",
            "content": reply
        })

        # 오래된 세션 정리 (메모리 관리)
        if len(conversations) > 1000:
            oldest = list(conversations.keys())[:500]
            for key in oldest:
                del conversations[key]

        return jsonify({
            "reply": reply,
            "session_id": session_id
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({
            "reply": "죄송합니다, 일시적인 오류가 발생했습니다. 직접 전화(010-4520-5114)로 문의해주세요.",
            "error": str(e)
        }), 500

@app.route("/reset", methods=["POST"])
def reset():
    data = request.json
    session_id = data.get("session_id", "default")
    conversations.pop(session_id, None)
    return jsonify({"message": "대화가 초기화되었습니다."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
