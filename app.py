import os
import json
import uuid
import base64
import hashlib
import sqlite3
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
ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    hashlib.sha256("admin1234".encode()).hexdigest()  # 기본 비밀번호: admin1234
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

# ═══════════════════════════════════════════
#  서버 상태
# ═══════════════════════════════════════════

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "running",
        "message": "목원부동산 서버 실행 중 🏠"
    })

# ═══════════════════════════════════════════
#  관리자 인증
# ═══════════════════════════════════════════

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    password = data.get("password", "")
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    if password_hash == ADMIN_PASSWORD_HASH:
        return jsonify({
            "success": True,
            "token": ADMIN_TOKEN,
            "message": "로그인 성공"
        })
    else:
        return jsonify({"success": False, "error": "비밀번호가 틀렸습니다."}), 401

# ═══════════════════════════════════════════
#  카테고리 API
# ═══════════════════════════════════════════

@app.route("/categories", methods=["GET"])
def get_categories():
    db = get_db()
    categories = db.execute(
        "SELECT * FROM categories ORDER BY sort_order, created_at"
    ).fetchall()
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

@app.route("/categories/<category_id>", methods=["PUT"])
@admin_required
def update_category(category_id):
    data = request.json
    db = get_db()
    db.execute(
        "UPDATE categories SET name=?, description=?, sort_order=? WHERE id=?",
        (data.get("name", ""), data.get("description", ""), data.get("sort_order", 0), category_id)
    )
    db.commit()
    return jsonify({"message": "카테고리가 수정되었습니다."})

@app.route("/categories/<category_id>", methods=["DELETE"])
@admin_required
def delete_category(category_id):
    db = get_db()
    db.execute("DELETE FROM posts WHERE category_id=?", (category_id,))
    db.execute("DELETE FROM categories WHERE id=?", (category_id,))
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
            "JOIN categories c ON p.category_id = c.id "
            "WHERE p.category_id=? ORDER BY p.created_at DESC",
            (category_id,)
        ).fetchall()
    else:
        posts = db.execute(
            "SELECT p.*, c.name as category_name FROM posts p "
            "JOIN categories c ON p.category_id = c.id "
            "ORDER BY p.created_at DESC LIMIT 50"
        ).fetchall()

    result = []
    for p in posts:
        post = dict(p)
        post["images"] = json.loads(post["images"])
        result.append(post)

    return jsonify(result)

@app.route("/posts/<post_id>", methods=["GET"])
def get_post(post_id):
    db = get_db()
    post = db.execute(
        "SELECT p.*, c.name as category_name FROM posts p "
        "JOIN categories c ON p.category_id = c.id "
        "WHERE p.id=?",
        (post_id,)
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

    # 이미지는 base64 문자열 배열로 저장
    images = data.get("images", [])
    if len(images) > 10:
        images = images[:10]  # 최대 10장

    db = get_db()
    db.execute(
        "INSERT INTO posts (id, category_id, title, content, images) VALUES (?, ?, ?, ?, ?)",
        (post_id, data.get("category_id", ""), data.get("title", ""),
         data.get("content", ""), json.dumps(images))
    )
    db.commit()
    return jsonify({"id": post_id, "message": "글이 등록되었습니다."})

@app.route("/posts/<post_id>", methods=["PUT"])
@admin_required
def update_post(post_id):
    data = request.json
    images = data.get("images", [])
    if len(images) > 10:
        images = images[:10]

    db = get_db()
    db.execute(
        "UPDATE posts SET title=?, content=?, images=?, category_id=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (data.get("title", ""), data.get("content", ""),
         json.dumps(images), data.get("category_id", ""), post_id)
    )
    db.commit()
    return jsonify({"message": "글이 수정되었습니다."})

@app.route("/posts/<post_id>", methods=["DELETE"])
@admin_required
def delete_post(post_id):
    db = get_db()
    db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    db.commit()
    return jsonify({"message": "글이 삭제되었습니다."})

# ═══════════════════════════════════════════
#  챗봇 API
# ═══════════════════════════════════════════

SYSTEM_PROMPT = """당신은 "목원부동산중개사무소"의 AI 상담 도우미입니다.

[중개사무소 정보]
- 상호: 목원부동산중개사무소
- 위치: 대구광역시 수성구 중동 641 1층
- 주력 매물: 아파트 매매/전세/월세, 상가
- 주요 취급 지역: 대구 수성구 황금동, 만촌동 및 인근 지역
- 영업시간: 평일·토요일 09:00~19:00 (일요일 휴무)
- 연락처: 053-641-3100
- 특징: 다양한 매물 보유, 친절하고 경험 많은 중개사

[자주 묻는 질문]
Q: 중개수수료는 얼마인가요?
A: 거래 유형과 금액에 따라 법정 요율이 적용됩니다.
   매매: 5천만원 이하 0.6%, 2억 이하 0.5%, 9억 이하 0.4% 등
   전/월세: 5천만원 이하 0.5%, 1억 이하 0.4% 등
   정확한 금액은 전화(053-641-3100) 주시면 바로 계산해드립니다.

Q: 전세 계약 시 주의사항은?
A: 등기부등본 확인, 전입신고, 확정일자 받기가 가장 중요합니다.

Q: 매물을 보려면?
A: 전화(053-641-3100) 또는 사무소 방문해주시면 안내해드립니다.

[상담 규칙]
1. 친절하고 전문적인 어조를 사용하세요.
2. 고객의 조건(예산, 지역, 매물 유형, 입주 시기)을 자연스럽게 파악하세요.
3. 구체적 매물 가격/시세는 "전화 상담(053-641-3100)으로 안내드립니다"라고 하세요.
4. 복잡한 법률/세금은 "전문가 상담을 권해드립니다"라고 하세요.
5. 답변 끝에 자연스럽게 방문/전화 상담을 유도하세요.
6. 한국어로만, 3~5문장 이내로 답변하세요.
7. 부동산 외 질문은 "부동산 관련 질문을 해주세요!"로 안내하세요.
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

        if session_id not in conversations:
            conversations[session_id] = []

        conversations[session_id].append({"role": "user", "content": user_message})
        recent = conversations[session_id][-10:]

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
        conversations[session_id].append({"role": "assistant", "content": reply})

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
