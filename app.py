import os
import json
import uuid
import hashlib
import sqlite3
import requests
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from groq import Groq

# ─── Flask 앱 ───
app = Flask(__name__)
CORS(app)

# ─── 설정 ───
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    hashlib.sha256("admin1234".encode()).hexdigest()
)
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "mokwon-secret-token-change-this")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ─── 데이터베이스 ───
DB_PATH = "/opt/render/project/src/mokwon.db" if os.environ.get("RENDER") else "mokwon.db"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            category_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            images TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ─── 관리자 인증 ───
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            return jsonify({"error": "관리자 인증이 필요합니다."}), 401
        return f(*args, **kwargs)
    return decorated

def authHeaders():
    return {"Content-Type": "application/json", "Authorization": f"Bearer {ADMIN_TOKEN}"}

# ═══════════════════════════════════════════
#  웹 검색 기능
# ═══════════════════════════════════════════

def search_web(query):
    """Serper API로 구글 검색 실행"""
    if not SERPER_API_KEY:
        return None

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "q": query,
                "gl": "kr",
                "hl": "ko",
                "num": 5
            },
            timeout=5
        )
        data = response.json()

        results = []
        # 일반 검색 결과
        for item in data.get("organic", [])[:5]:
            results.append(f"- {item.get('title', '')}: {item.get('snippet', '')}")

        # 지식 패널
        if "knowledgeGraph" in data:
            kg = data["knowledgeGraph"]
            results.insert(0, f"[정보] {kg.get('title', '')}: {kg.get('description', '')}")

        # Answer Box
        if "answerBox" in data:
            ab = data["answerBox"]
            answer = ab.get("answer") or ab.get("snippet") or ""
            if answer:
                results.insert(0, f"[답변] {answer}")

        return "\n".join(results) if results else None

    except Exception as e:
        print(f"Search error: {e}")
        return None


def needs_search(message):
    """메시지가 웹 검색이 필요한지 판단"""
    search_keywords = [
        "실거래가", "시세", "가격", "얼마", "매매가", "전세가", "월세가",
        "평당", "평균", "최근", "거래", "호가", "매물",
        "분양", "입주", "재건축", "재개발",
        "금리", "대출", "이자",
        "학군", "학교", "교통", "지하철", "버스",
        "인구", "세대수", "입주물량",
        "뉴스", "정책", "규제", "세금", "취득세", "양도세",
        "해링턴", "두산위브", "캐슬", "자이", "래미안", "푸르지오",
        "힐스테이트", "아이파크", "더샵", "e편한세상",
        "황금동", "만촌동", "중동", "범어동", "수성동", "지산동",
        "수성구", "달서구", "동구", "북구", "중구", "서구", "남구"
    ]
    return any(kw in message for kw in search_keywords)


def build_search_query(message):
    """사용자 메시지에서 검색 쿼리 생성"""
    # 지역명이 없으면 대구 수성구를 기본으로 추가
    daegu_areas = ["수성구", "달서구", "동구", "북구", "중구", "서구", "남구", "대구"]
    has_area = any(area in message for area in daegu_areas)

    query = message
    if not has_area:
        query = f"대구 수성구 {message}"

    # 실거래가 관련이면 키워드 추가
    if "실거래" in message or "시세" in message or "가격" in message or "얼마" in message:
        if "실거래" not in query:
            query += " 실거래가"

    return query

# ═══════════════════════════════════════════
#  서버 상태
# ═══════════════════════════════════════════

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "message": "목원부동산 서버 실행 중 🏠"})

# ═══════════════════════════════════════════
#  관리자 인증
# ═══════════════════════════════════════════

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    password = data.get("password", "")
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash == ADMIN_PASSWORD_HASH:
        return jsonify({"success": True, "token": ADMIN_TOKEN, "message": "로그인 성공"})
    else:
        return jsonify({"success": False, "error": "비밀번호가 틀렸습니다."}), 401

# ═══════════════════════════════════════════
#  카테고리 API
# ═══════════════════════════════════════════

@app.route("/categories", methods=["GET"])
def get_categories():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY sort_order, created_at").fetchall()
    return jsonify([dict(c) for c in categories])

@app.route("/categories", methods=["POST"])
@admin_required
def create_category():
    data = request.json
    category_id = str(uuid.uuid4())[:8]
    db = get_db()
    db.execute(
        "INSERT INTO categories (id, name, description, sort_order) VALUES (?, ?, ?, ?)",
        (category_id, data.get("name", ""), data.get("description", ""), data.get("sort_order", 0))
    )
    db.commit()
    return jsonify({"id": category_id, "message": "카테고리가 생성되었습니다."})

@app.route("/categories/<cid>", methods=["PUT"])
@admin_required
def update_category(cid):
    data = request.json
    db = get_db()
    db.execute("UPDATE categories SET name=?, description=?, sort_order=? WHERE id=?",
               (data.get("name",""), data.get("description",""), data.get("sort_order",0), cid))
    db.commit()
    return jsonify({"message": "카테고리가 수정되었습니다."})

@app.route("/categories/<cid>", methods=["DELETE"])
@admin_required
def delete_category(cid):
    db = get_db()
    db.execute("DELETE FROM posts WHERE category_id=?", (cid,))
    db.execute("DELETE FROM categories WHERE id=?", (cid,))
    db.commit()
    return jsonify({"message": "카테고리와 관련 글이 삭제되었습니다."})

# ═══════════════════════════════════════════
#  게시글 API
# ═══════════════════════════════════════════

@app.route("/posts", methods=["GET"])
def get_posts():
    category_id = request.args.get("category_id", "")
    db = get_db()
    if category_id:
        posts = db.execute(
            "SELECT p.*, c.name as category_name FROM posts p "
            "JOIN categories c ON p.category_id=c.id WHERE p.category_id=? ORDER BY p.created_at DESC",
            (category_id,)
        ).fetchall()
    else:
        posts = db.execute(
            "SELECT p.*, c.name as category_name FROM posts p "
            "JOIN categories c ON p.category_id=c.id ORDER BY p.created_at DESC LIMIT 50"
        ).fetchall()
    result = []
    for p in posts:
        post = dict(p)
        post["images"] = json.loads(post["images"])
        result.append(post)
    return jsonify(result)

@app.route("/posts/<pid>", methods=["GET"])
def get_post(pid):
    db = get_db()
    post = db.execute(
        "SELECT p.*, c.name as category_name FROM posts p "
        "JOIN categories c ON p.category_id=c.id WHERE p.id=?", (pid,)
    ).fetchone()
    if not post:
        return jsonify({"error": "글을 찾을 수 없습니다."}), 404
    result = dict(post)
    result["images"] = json.loads(result["images"])
    return jsonify(result)

@app.route("/posts", methods=["POST"])
@admin_required
def create_post():
    data = request.json
    post_id = str(uuid.uuid4())[:8]
    images = data.get("images", [])[:10]
    db = get_db()
    db.execute(
        "INSERT INTO posts (id, category_id, title, content, images) VALUES (?, ?, ?, ?, ?)",
        (post_id, data.get("category_id",""), data.get("title",""), data.get("content",""), json.dumps(images))
    )
    db.commit()
    return jsonify({"id": post_id, "message": "글이 등록되었습니다."})

@app.route("/posts/<pid>", methods=["PUT"])
@admin_required
def update_post(pid):
    data = request.json
    images = data.get("images", [])[:10]
    db = get_db()
    db.execute(
        "UPDATE posts SET title=?, content=?, images=?, category_id=?, updated_at=datetime('now','localtime') WHERE id=?",
        (data.get("title",""), data.get("content",""), json.dumps(images), data.get("category_id",""), pid)
    )
    db.commit()
    return jsonify({"message": "글이 수정되었습니다."})

@app.route("/posts/<pid>", methods=["DELETE"])
@admin_required
def delete_post(pid):
    db = get_db()
    db.execute("DELETE FROM posts WHERE id=?", (pid,))
    db.commit()
    return jsonify({"message": "글이 삭제되었습니다."})

# ═══════════════════════════════════════════
#  챗봇 API (웹 검색 연동)
# ═══════════════════════════════════════════

SYSTEM_PROMPT = """당신은 "목원부동산중개사무소"의 AI 상담 도우미입니다.

[중개사무소 정보]
- 상호: 목원부동산중개사무소
- 위치: 대구광역시 수성구 희망로24길 24, 수성효성해링턴플레이스 상가 202동 109호
- 주력 매물: 아파트 매매/전세/월세, 상가
- 주요 취급 지역: 대구 수성구 황금동, 만촌동 및 인근 지역
- 영업시간: 평일, 토요일 09:00~19:00 (일요일 휴무)
- 연락처: 053-641-3100
- 특징: 다양한 매물 보유, 친절하고 경험 많은 중개사

[중요한 답변 형식 규칙]
1. 특수문자를 절대 사용하지 마세요. 가운뎃점(·), 제곱미터(m2) 등 특수문자 대신 일반 텍스트를 사용하세요.
   - "18.2평/3층" (O) vs "18.2평·3층" (X)
   - "75m2" 또는 "75제곱미터" (O) vs "75㎡" (X)
   - 쉼표(,)와 마침표(.)만 사용하세요.
2. 웹 검색 결과를 활용한 답변에는 반드시 마지막에 출처를 표시하세요.
   - 형식: (출처: OO검색, OO사이트)
   - 예시: (출처: 네이버 검색, 당근마켓)
   - 예시: (출처: 네이버 부동산, 호갱노노)
   - 검색 결과의 출처 사이트명을 간략히 적어주세요.
3. 답변은 핵심 정보 위주로 읽기 쉽게 정리하세요.

[상담 규칙]
1. 친절하고 전문적인 어조를 사용하세요.
2. 고객의 조건(예산, 지역, 매물 유형, 입주 시기)을 자연스럽게 파악하세요.
3. 웹 검색 결과가 제공되면, 그 정보를 활용하여 구체적으로 답변하세요.
   - 실거래가, 시세, 주변 정보 등을 검색 결과에서 찾아 알려주세요.
   - 검색 결과의 정보를 자연스럽게 정리하여 전달하세요.
   - 단, 검색 결과는 참고 자료이며 정확한 최신 정보는 사무소에 확인하라고 안내하세요.
4. 웹 검색 결과가 없거나 부족한 경우:
   - 일반적인 부동산 지식(중개수수료, 계약 절차, 주의사항 등)은 상세히 답변하세요.
   - 구체적 시세는 "정확한 최신 시세는 전화(053-641-3100)로 확인해주세요"라고 안내하세요.
5. 복잡한 법률/세금은 "세무사나 변호사 등 전문가 상담을 권해드립니다"라고 하세요.
6. 답변 끝에 자연스럽게 방문/전화 상담을 유도하세요.
7. 한국어로만 답변하세요.
8. 부동산 외 질문은 "부동산 관련 질문을 해주세요!"로 안내하세요.

[중개수수료 안내 - 정확하게 답변하세요]
매매:
- 5천만원 미만: 0.6% (한도 25만원)
- 5천만원~2억 미만: 0.5% (한도 80만원)
- 2억~9억 미만: 0.4%
- 9억~12억 미만: 0.5%
- 12억~15억 미만: 0.6%
- 15억 이상: 0.7%

전세/월세:
- 5천만원 미만: 0.5% (한도 20만원)
- 5천만원~1억 미만: 0.4% (한도 30만원)
- 1억~6억 미만: 0.3%
- 6억~12억 미만: 0.4%
- 12억~15억 미만: 0.5%
- 15억 이상: 0.6%

[전세 계약 시 주의사항 - 상세히 안내]
1. 등기부등본 확인: 소유자, 근저당/가압류 등 확인
2. 전입신고 + 확정일자: 이사 당일 바로 하기
3. 임대인 세금 체납 여부 확인
4. 보증보험(HUG, SGI) 가입 가능 여부 확인
5. 특약사항 꼼꼼히 확인
6. 건물 상태, 누수, 하자 점검
"""

conversations = {}

@app.route("/chat", methods=["POST"])
def chat():
    if not client:
        return jsonify({"reply": "챗봇 서비스가 일시적으로 중단되었습니다. 전화(053-641-3100)로 문의해주세요."}), 500

    try:
        data = request.json
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "메시지를 입력해주세요."}), 400

        # 세션별 대화 기록
        if session_id not in conversations:
            conversations[session_id] = []

        conversations[session_id].append({"role": "user", "content": user_message})
        recent = conversations[session_id][-10:]

        # 웹 검색 필요 여부 판단
        search_context = ""
        if needs_search(user_message):
            query = build_search_query(user_message)
            search_result = search_web(query)
            if search_result:
                search_context = f"\n\n[웹 검색 결과 - '{query}']\n{search_result}\n\n위 검색 결과를 참고하여 답변해주세요."

        # 사용자 메시지에 검색 결과 첨부
        augmented_message = user_message
        if search_context:
            augmented_message = user_message + search_context

        # 대화 기록에서 마지막 메시지를 검색 결과 포함 버전으로 교체
        messages_for_api = recent[:-1] + [{"role": "user", "content": augmented_message}]

        # Groq API 호출
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages_for_api
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=800,
        )

        reply = completion.choices[0].message.content
        conversations[session_id].append({"role": "assistant", "content": reply})

        # 메모리 관리
        if len(conversations) > 1000:
            oldest = list(conversations.keys())[:500]
            for key in oldest:
                del conversations[key]

        return jsonify({"reply": reply, "session_id": session_id})

    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            "reply": "죄송합니다, 오류가 발생했습니다. 전화(053-641-3100)로 문의해주세요."
        }), 500

@app.route("/reset", methods=["POST"])
def reset():
    data = request.json
    session_id = data.get("session_id", "default")
    conversations.pop(session_id, None)
    return jsonify({"message": "대화가 초기화되었습니다."})

# ═══════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
