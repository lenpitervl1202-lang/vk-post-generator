from flask import Flask, render_template, request, jsonify, send_from_directory
from gigachat import GigaChat
import json, os, threading, time, uuid, re, ssl
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# ===== НАСТРОЙКИ ГЕНЕРАТОРА =====
GIGACHAT_CREDENTIALS = os.environ.get("GIGACHAT_CREDENTIALS")
GIGACHAT_MODEL = "GigaChat"
VERIFY_SSL = False

TONE = "креативный"
POST_LENGTH = "средний"
EMOJI_COUNT = "умеренно"
HEADLINE_STYLE = "громкий"
# =================================

# ===== НАСТРОЙКИ ВКОНТАКТЕ =====
VK_ACCESS_TOKEN = "vk1.a.5Z4Hiaux7_zRYxpNxd3-sMTJspcE7JUlYVHbVq7za4LciyH0BThr9lvBHrpQ8cAwo4w5sQTJvIKeAg8hnKrzw2_t7UdlGemUW5b1kejQ1Jjr-m5P-6wdqyr-NJdS23hvBYDAfKAWjoHt5X7M1Wcmdp7PoRqLTO7EAOCfVXPqAFuR2qpxWe_dyScrVnYmQ7OHhFkBinvg64Fj1Rt1LwZ7Qw"
VK_COMMUNITY_ID = "239607335"
# =================================

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
FAVORITES_PATH = os.path.join(DATA_DIR, "favorites.json")
SCHEDULED_PATH = os.path.join(DATA_DIR, "scheduled.json")
UPLOADS_PATH = os.path.join(DATA_DIR, "uploads")
LOG_PATH = os.path.join(DATA_DIR, "debug.log")
os.makedirs(UPLOADS_PATH, exist_ok=True)


def dbg(msg):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

MOOD_TITLES = {
    "креативный": "Креативный и яркий",
    "профессиональный": "Профессиональный",
    "дерзкий": "Дерзкий и смелый",
    "полезный": "Полезный / экспертный",
}

MOOD_DESCRIPTIONS = {
    "креативный": "Ярко, эмоционально, с неожиданными метафорами. Много эмодзи.",
    "профессиональный": "Сдержанно, экспертно, с акцентом на характеристики.",
    "дерзкий": "Коротко, смело, цепляюще. Без лишней воды.",
    "полезный": "Обучающий тон, разбор преимуществ, советы покупателю.",
}

# ===== РАБОТА С JSON-ФАЙЛАМИ =====

def read_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== VK НАСТРОЙКИ =====

def load_vk_config():
    env_token = os.environ.get("VK_ACCESS_TOKEN") or ""
    env_group = os.environ.get("VK_COMMUNITY_ID") or ""
    env_user_token = os.environ.get("VK_USER_TOKEN") or ""
    if env_token and env_group:
        cfg = {"access_token": env_token, "community_id": env_group, "enabled": True}
        if env_user_token:
            cfg["user_token"] = env_user_token
        return cfg
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        vk = cfg.get("vk", {})
        if vk.get("enabled") and vk.get("access_token"):
            return vk
    return {
        "access_token": VK_ACCESS_TOKEN,
        "community_id": VK_COMMUNITY_ID,
        "enabled": True,
    }

def load_github_config():
    env_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    env_repo = os.environ.get("GH_REPO") or ""
    if env_token and env_repo:
        return {"access_token": env_token, "repo": env_repo, "enabled": True}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        gh = cfg.get("github", {})
        if gh.get("enabled") and gh.get("access_token") and gh.get("repo"):
            return gh
    return {"enabled": False}

# ===== ГЕНЕРАЦИЯ ПОСТА =====

def build_prompt(product_url, mood):
    mood_instruction = MOOD_DESCRIPTIONS.get(mood, MOOD_DESCRIPTIONS["креативный"])
    return f"""Ты — профессиональный копирайтер. Напиши пост для соцсетей о товаре по ссылке.

Ссылка на товар: {product_url}

Стиль поста: {mood_instruction}
Тон: {TONE}
Длина: {POST_LENGTH}
Количество эмодзи: {EMOJI_COUNT}
Стиль заголовка: {HEADLINE_STYLE}

Структура поста:
1. ЗАГОЛОВОК — цепляющий заголовок с эмодзи
2. ЭМОДЗИ — 2-4 уместных эмодзи отдельной строкой
3. ОСНОВНОЙ ТЕКСТ — описание товара, его особенности, почему он классный
4. ПОЛЬЗА ДЛЯ ПОКУПАТЕЛЯ — что получит покупатель
5. ПРИЗЫВ К ДЕЙСТВИЮ (CTA)

Важно: пост должен быть оригинальным, интересным, нешаблонным.
Используй живой язык, обращайся к читателю на «ты».
Не используй markdown-разметку (не пиши **).
НЕ используй хэштеги и символ #. Просто напиши готовый пост."""

def generate_post(product_url, mood):
    prompt = build_prompt(product_url, mood)
    try:
        with GigaChat(credentials=GIGACHAT_CREDENTIALS, model=GIGACHAT_MODEL, verify_ssl_certs=VERIFY_SSL) as giga:
            response = giga.chat(prompt)
        text = response.choices[0].message.content
    except Exception as e:
        dbg(f"GigaChat error: {e}")
        raise
    text = text.replace("#", "").replace("**", "")
    text = re.sub(r"(\S)-(\s)", r"\1 - \2", text)
    text = re.sub(r"(\S)—(\s)", r"\1 — \2", text)
    text = re.sub(r"([.!?])\s+", r"\1\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()

# ===== ИЗВЛЕЧЕНИЕ ФОТО С САЙТА =====

def download_image(src, url):
    try:
        if not src or not isinstance(src, str):
            return None
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("http"):
            from urllib.parse import urljoin
            src = urljoin(url, src)
        ext = os.path.splitext(src.split("?")[0])[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        name = str(uuid.uuid4()) + ext
        path = os.path.join(UPLOADS_PATH, name)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        img_resp = urlopen(Request(src, headers=headers), timeout=15)
        with open(path, "wb") as f:
            f.write(img_resp.read())
        return name
    except Exception:
        return None

def extract_product_image(url):
    """Извлечь фото товара со страницы."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        req = Request(url, headers=headers)
        resp = urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        candidates = []

        # 1. Meta-теги (og:image — лучший для соцсетей)
        for prop in ("og:image", "twitter:image"):
            meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if meta and meta.get("content"):
                candidates.append(meta["content"])

        # 2. JSON-LD (структурированные данные)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "image" in data:
                    v = data["image"]
                    if isinstance(v, str):
                        candidates.append(v)
                    elif isinstance(v, list):
                        candidates.extend(v)
                    elif isinstance(v, dict) and v.get("url"):
                        candidates.append(v["url"])
            except Exception:
                pass

        # 3. Картинка по CSS-селекторам (частые классы в магазинах)
        selectors = [
            "img[data-zoom]", "img[data-main-image]", "img[data-gallery]",
            ".gallery-current img", ".gallery__item--active img",
            ".product__image img", ".product-image img", ".main-image img",
            ".swiper-slide-active img", ".swiper-slide img",
            "[data-testid='product-image'] img", "[data-product-image] img",
            "figure img", ".card__image img", ".item__image img",
            ".product-media img", ".media-item img", ".image-gallery img",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                src = el.get("src") or el.get("data-src") or el.get("data-lazy") or ""
                if src and len(src) > 5:
                    candidates.append(src)

        # 4. Все <img> достаточного размера
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy") or ""
            if src and len(src) > 10:
                w = img.get("width", "0")
                h = img.get("height", "0")
                try:
                    if w.isdigit() and h.isdigit() and int(w) < 100 and int(h) < 100:
                        continue
                except ValueError:
                    pass
                candidates.append(src)

        # 5. Дубликаты исключаем, пробуем скачать
        seen = set()
        for img_src in candidates:
            if img_src in seen:
                continue
            seen.add(img_src)
            result = download_image(img_src, url)
            if result:
                return result

    except Exception:
        pass
    return None

# ===== ЗАГРУЗКА НА GITHUB =====

def upload_to_github(image_path):
    """Upload image to GitHub repo, return blob URL or None."""
    config = load_github_config()
    if not config.get("enabled"):
        dbg("GitHub: disabled in config")
        return None
    import base64
    token = config["access_token"]
    repo_full = config["repo"].strip("/")
    parts = repo_full.split("/")
    if len(parts) < 2:
        dbg(f"GitHub: bad repo format: {repo_full}")
        return None
    owner = parts[0]
    repo_name = "/".join(parts[1:])
    try:
        size = os.path.getsize(image_path)
        dbg(f"GitHub: uploading {os.path.basename(image_path)} ({size} bytes)")
        with open(image_path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(image_path)[1] or ".jpg"
        gh_path = f"uploads/{uuid.uuid4().hex}{ext}"
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{gh_path}"
        payload = json.dumps({"message": f"Add {gh_path}", "content": content}).encode()
        req = Request(url, data=payload, method="PUT")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "PostGenerator/1.0")
        urlopen(req).read()
        blob = f"https://raw.githubusercontent.com/{owner}/{repo_name}/main/{gh_path}"
        dbg(f"GitHub: success -> {blob}")
        return blob
    except Exception as e:
        dbg(f"GitHub: upload failed: {e}")
        return None

# ===== ПУБЛИКАЦИЯ В ВК =====

def publish_to_vk(post_text, image_path=None):
    config = load_vk_config()
    if not config.get("enabled") or not config.get("access_token") or not config.get("community_id"):
        return {"success": False, "error": "ВК не настроен. Заполните данные в data/config.json"}

    community_id = config["community_id"]
    if not community_id.startswith("-"):
        community_id = "-" + community_id

    token = config["access_token"]
    user_token = config.get("user_token") or None
    attachments = []

    abs_path = None
    image_url = None

    if image_path:
        dbg(f"publish: image_path='{image_path}'")
        if image_path.startswith("http"):
            image_url = image_path
            try:
                hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = urlopen(Request(image_path, headers=hdrs), timeout=15)
                ext = ".jpg"
                ct = resp.headers.get("Content-Type", "")
                if "png" in ct: ext = ".png"
                elif "gif" in ct: ext = ".gif"
                elif "webp" in ct: ext = ".webp"
                abs_path = os.path.join(UPLOADS_PATH, f"_tmp_{uuid.uuid4().hex}{ext}")
                with open(abs_path, "wb") as f:
                    f.write(resp.read())
            except:
                pass
        else:
            fn = os.path.basename(image_path)
            for candidate in [os.path.join(UPLOADS_PATH, fn),
                              os.path.join(UPLOADS_PATH, fn.replace("/uploads/", ""))]:
                dbg(f"publish: checking candidate {candidate}")
                if os.path.exists(candidate):
                    abs_path = candidate
                    dbg(f"publish: found file at {abs_path}")
                    break
            if not abs_path:
                dbg("publish: file NOT FOUND in uploads")

        if abs_path and os.path.exists(abs_path):
            native_done = False
            # 1. Пробуем VK (user_token или group_token)
            upload_token = user_token or token
            for attempt_label, attempt_token in [("user_token", user_token), ("group_token", token)]:
                if not attempt_token or native_done:
                    continue
                try:
                    dbg(f"publish: trying VK upload with {attempt_label}")
                    upload_data = urlencode({
                        "group_id": config["community_id"],
                        "access_token": attempt_token,
                        "v": "5.199",
                    }).encode()
                    req = Request("https://api.vk.com/method/photos.getWallUploadServer", data=upload_data)
                    resp = json.loads(urlopen(req).read().decode("utf-8"))
                    if "error" in resp and resp["error"].get("error_code") == 27:
                        dbg(f"publish: {attempt_label} got error 27, skipping")
                        continue
                    if "error" not in resp:
                        up_url = resp["response"]["upload_url"]
                        import mimetypes
                        mime = mimetypes.guess_type(abs_path)[0] or "image/jpeg"
                        boundary = "----" + str(uuid.uuid4().hex)
                        with open(abs_path, "rb") as f:
                            body = f.read()
                        body_data = (
                            f"--{boundary}\r\n"
                            f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(abs_path)}"\r\n'
                            f"Content-Type: {mime}\r\n\r\n"
                        ).encode() + body + f"\r\n--{boundary}--\r\n".encode()
                        req2 = Request(up_url, data=body_data)
                        req2.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
                        up_resp = json.loads(urlopen(req2).read().decode("utf-8"))
                        save_data = urlencode({
                            "group_id": config["community_id"],
                            "photo": up_resp["photo"],
                            "server": up_resp["server"],
                            "hash": up_resp["hash"],
                            "access_token": attempt_token,
                            "v": "5.199",
                        }).encode()
                        req3 = Request("https://api.vk.com/method/photos.saveWallPhoto", data=save_data)
                        sv_resp = json.loads(urlopen(req3).read().decode("utf-8"))
                        if "error" not in sv_resp:
                            photo = sv_resp["response"][0]
                            attachments.append(f"photo{photo['owner_id']}_{photo['id']}")
                            native_done = True
                            dbg("publish: VK native photo uploaded successfully")
                except Exception as e:
                    dbg(f"publish: VK upload {attempt_label} failed: {e}")

            # 2. GitHub — если нативное фото не загрузилось
            if not native_done and os.path.exists(abs_path):
                gh_url = upload_to_github(abs_path)
                if gh_url:
                    image_url = gh_url
                else:
                    dbg("publish: GitHub upload failed, no URL")

        # Ссылка на фото в текст поста (только если нативное фото не прикрепилось)
        if image_url and not attachments:
            post_text += f"\n\n{image_url}"
            dbg(f"publish: added GitHub URL to text")
        elif image_url and attachments:
            dbg("publish: native photo attached, skipping URL in text")
        elif not image_url and not attachments:
            dbg("publish: no photo at all")
    else:
        dbg("publish: image_path is empty/None")

    post_text = post_text.replace("\r\n", "\n")
    dbg(f"publish: final text length={len(post_text)}, attachments={len(attachments)}")
    params = {"owner_id": community_id, "message": post_text, "access_token": token, "v": "5.199"}
    if attachments:
        params["attachments"] = ",".join(attachments)

    req = Request("https://api.vk.com/method/wall.post", data=urlencode(params).encode())
    resp = json.loads(urlopen(req).read().decode("utf-8"))

    if "error" in resp:
        dbg(f"publish: VK error: {resp['error']['error_msg']}")
        return {"success": False, "error": resp["error"]["error_msg"]}
    dbg(f"publish: SUCCESS post_id={resp['response']['post_id']}")
    result = {"success": True, "post_id": resp["response"]["post_id"]}
    if image_url and not attachments:
        result["photo_warning"] = "фото ссылкой (для встроенного задайте user_token в /vk-setup)"
    return result

# ===== ПЛАНИРОВЩИК ОТЛОЖЕННЫХ ПОСТОВ =====

def scheduler_loop():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%dT%H:%M")
            posts = read_json(SCHEDULED_PATH)
            remaining = []
            for post in posts:
                if not post.get("published") and post.get("publish_at") <= now:
                    result = publish_to_vk(post["text"], post.get("image_path"))
                    post["published"] = True
                    post["published_at"] = now
                    post["publish_error"] = result.get("error") if not result["success"] else None
                remaining.append(post)
            write_json(SCHEDULED_PATH, remaining)
        except Exception:
            pass
        time.sleep(30)

scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

# ===== МАРШРУТЫ =====

@app.route("/")
def index():
    return render_template("index.html", moods=MOOD_TITLES)

@app.route("/generate", methods=["POST"])
def generate():
    product_url = request.form.get("product_url", "").strip()
    mood = request.form.get("mood", "креативный")
    image_url = request.form.get("image_url", "").strip()
    image_path = request.form.get("image_path", "").strip()
    if not product_url:
        return jsonify({"error": "Введите ссылку на товар"}), 400
    try:
        post = generate_post(product_url, mood)
        image = None
        # 1. Уже загруженный файл
        if image_path and image_path.startswith("/uploads/"):
            fn = os.path.basename(image_path)
            if os.path.exists(os.path.join(UPLOADS_PATH, fn)):
                image = fn
        if not image and image_path and not image_path.startswith("http"):
            fn = os.path.basename(image_path)
            if os.path.exists(os.path.join(UPLOADS_PATH, fn)):
                image = fn
        # 2. Ссылка из формы
        if not image and image_url:
            image = download_image(image_url, image_url)
            print(f"[DEBUG] Downloaded from URL: {image_url} -> {image}")
        # 3. Извлечь со страницы товара
        if not image:
            print(f"[DEBUG] Extracting from product page: {product_url}")
            image = extract_product_image(product_url)
            print(f"[DEBUG] Extraction result: {image}")
        return jsonify({"post": post, "image": image})
    except Exception as e:
        return jsonify({"error": f"Ошибка генерации: {str(e)}"}), 500

@app.route("/improve", methods=["POST"])
def improve():
    post_text = request.form.get("post_text", "").strip()
    if not post_text:
        return jsonify({"error": "Нет текста для улучшения"}), 400
    mood = request.form.get("mood", "креативный")
    try:
        mood_instruction = MOOD_DESCRIPTIONS.get(mood, MOOD_DESCRIPTIONS["креативный"])
        prompt = f"""Ты — профессиональный копирайтер. Улучши этот пост для соцсетей.
Сделай его более интересным, живым и цепляющим. Сохрани всю фактуру и смысл.

Стиль: {mood_instruction}

Пост для улучшения:
{post_text}

Напиши улучшенную версию. Не используй markdown (**), хэштеги (#). Используй эмодзи уместно."""
        with GigaChat(credentials=GIGACHAT_CREDENTIALS, model=GIGACHAT_MODEL, verify_ssl_certs=VERIFY_SSL) as giga:
            response = giga.chat(prompt)
        text = response.choices[0].message.content
        text = text.replace("#", "").replace("**", "")
        text = re.sub(r"(\S)-(\s)", r"\1 - \2", text)
        text = re.sub(r"(\S)—(\s)", r"\1 — \2", text)
        text = re.sub(r"([.!?])\s+", r"\1\n\n", text)
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return jsonify({"post": text.strip()})
    except Exception as e:
        return jsonify({"error": f"Ошибка улучшения: {str(e)}"}), 500

@app.route("/upload-image", methods=["POST"])
def upload_image():
    if "file" not in request.files:
        return jsonify({"error": "Файл не найден"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Файл не выбран"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return jsonify({"error": "Неподдерживаемый формат"}), 400
    name = str(uuid.uuid4()) + ext
    path = os.path.join(UPLOADS_PATH, name)
    file.save(path)
    return jsonify({"path": name})

@app.route("/uploads/<name>")
def serve_upload(name):
    return send_from_directory(UPLOADS_PATH, name)

@app.route("/publish", methods=["POST"])
def publish():
    post_text = request.form.get("post_text", "").strip()
    image_path = request.form.get("image_path", "").strip()
    if not post_text:
        return jsonify({"error": "Нет текста поста"}), 400
    result = publish_to_vk(post_text, image_path or None)
    if result["success"]:
        msg = "Пост опубликован!"
        resp = {"message": msg, "post_id": result["post_id"]}
        if result.get("photo_warning"):
            resp["photo_warning"] = result["photo_warning"]
        return jsonify(resp)
    return jsonify({"error": result["error"]}), 400

@app.route("/schedule", methods=["POST"])
def schedule():
    post_text = request.form.get("post_text", "").strip()
    publish_at = request.form.get("publish_at", "").strip()
    if not post_text or not publish_at:
        return jsonify({"error": "Нет текста поста или времени"}), 400
    posts = read_json(SCHEDULED_PATH)
    image_path = request.form.get("image_path", "").strip() or None
    posts.append({
        "id": str(int(time.time())),
        "text": post_text,
        "publish_at": publish_at,
        "published": False,
        "image_path": image_path,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    write_json(SCHEDULED_PATH, posts)
    return jsonify({"message": "Пост запланирован!"})

@app.route("/scheduled", methods=["GET"])
def get_scheduled():
    posts = read_json(SCHEDULED_PATH)
    return jsonify({"posts": posts})

@app.route("/scheduled/<post_id>", methods=["DELETE"])
def delete_scheduled(post_id):
    posts = read_json(SCHEDULED_PATH)
    posts = [p for p in posts if p["id"] != post_id]
    write_json(SCHEDULED_PATH, posts)
    return jsonify({"message": "Запланированный пост удалён"})

@app.route("/favorites", methods=["GET"])
def get_favorites():
    return jsonify({"posts": read_json(FAVORITES_PATH)})

@app.route("/favorite", methods=["POST"])
def toggle_favorite():
    post_text = request.form.get("post_text", "").strip()
    if not post_text:
        return jsonify({"error": "Нет текста поста"}), 400
    posts = read_json(FAVORITES_PATH)
    exists = any(p["text"] == post_text for p in posts)
    if exists:
        posts = [p for p in posts if p["text"] != post_text]
        write_json(FAVORITES_PATH, posts)
        return jsonify({"message": "Удалено из избранного", "favorited": False})
    posts.append({
        "id": str(int(time.time())),
        "text": post_text,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    write_json(FAVORITES_PATH, posts)
    return jsonify({"message": "Добавлено в избранное", "favorited": True})

@app.route("/vk-status", methods=["GET"])
def vk_status():
    config = load_vk_config()
    return jsonify({"enabled": config.get("enabled", False)})

@app.route("/vk-setup", methods=["GET", "POST"])
def vk_setup():
    if request.method == "POST":
        config = read_json(CONFIG_PATH)
        if not isinstance(config, dict):
            config = {}
        action = request.form.get("action", "")

        if action == "vk":
            token = request.form.get("access_token", "").strip()
            community_id = request.form.get("community_id", "").strip()
            user_token = request.form.get("user_token", "").strip()
            if token and community_id:
                vk_cfg = {
                    "access_token": token,
                    "community_id": community_id,
                    "enabled": True,
                }
                if user_token:
                    vk_cfg["user_token"] = user_token
                elif "user_token" in config.get("vk", {}):
                    vk_cfg["user_token"] = config["vk"]["user_token"]
                config["vk"] = vk_cfg
                write_json(CONFIG_PATH, config)
                return "<h2>OK</h2><p>VK saved. <a href='/'>Back</a>.</p>"
            return "<h2>Error</h2><p>Fill both fields. <a href='/vk-setup'>Back</a>.</p>"

        if action == "github":
            gh_token = request.form.get("gh_token", "").strip()
            gh_repo = request.form.get("gh_repo", "").strip()
            if gh_token and gh_repo:
                config["github"] = {
                    "access_token": gh_token,
                    "repo": gh_repo,
                    "enabled": True,
                }
                write_json(CONFIG_PATH, config)
                return "<h2>OK</h2><p>GitHub saved. <a href='/'>Back</a>.</p>"
            return "<h2>Error</h2><p>Fill both fields. <a href='/vk-setup'>Back</a>.</p>"

    return """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Setup</title>
<style>
body{font-family:sans-serif;max-width:650px;margin:40px auto;padding:0 20px}
h1{color:#2d3436}
h2{color:#6c5ce7;margin-top:30px}
.section{border:2px solid #e9ecef;border-radius:12px;padding:20px;margin:16px 0}
.step{background:#f8f9fa;padding:14px;border-radius:10px;margin:10px 0;border:1px solid #e9ecef;font-size:14px}
.step b{color:#6c5ce7}
input{width:100%;padding:10px;margin:6px 0;border:2px solid #dfe6e9;border-radius:8px;font-size:14px;box-sizing:border-box}
input:focus{border-color:#6c5ce7;outline:none}
.btn{background:#6c5ce7;color:white;border:none;padding:10px 20px;border-radius:10px;font-size:14px;cursor:pointer;margin-top:8px}
.btn-green{background:#00b894}
code{background:#eee;padding:2px 6px;border-radius:4px;font-size:13px}
hr{margin:24px 0;border:none;border-top:1px solid #e9ecef}
</style></head>
<body>
<h1>Setup</h1>

<div class="section">
<h2>VK</h2>
<p style="font-size:14px;color:#636e72;margin:4px 0">
Токен <b>группы</b> — для публикации постов (настройки группы → API).<br>
Токен <b>пользователя</b> — для загрузки фото (нужен, если фото не появляются в постах).
</p>
<div class="step"><b>1.</b> Create Standalone app at <a href="https://vk.com/apps?act=manage" target="_blank">vk.com/apps?act=manage</a></div>
<div class="step"><b>2.</b> Copy App ID from URL (number after /app)</div>
<div class="step"><b>3.</b> Enter App ID:<br>
<input id="appId" placeholder="App ID" oninput="updateLink()">
<br><a id="oauthLink" href="#" target="_blank">generate link</a></div>
<div class="step"><b>4.</b> Open link, click Allow, copy token from address bar</div>
<form method="post">
<input type="hidden" name="action" value="vk">
<div class="step">
<b>Токен группы</b> (для публикации):
<input name="access_token" placeholder="vk1.a...." required>
</div>
<div class="step">
<b>ID сообщества:</b>
<input name="community_id" placeholder="239607335" value="239607335" required>
</div>
<div class="step">
<b>Токен пользователя</b> (для фото, необязательно):
<input name="user_token" placeholder="vk1.a.... (из шага 4)">
</div>
<button class="btn">Save VK</button>
</form>
</div>

<div class="section">
<h2>GitHub <span style="font-weight:normal;font-size:14px;color:#636e72">(CDN для фото)</span></h2>
<p style="font-size:14px;color:#636e72">Фото загружаются на GitHub, если нет пользовательского токена VK.</p>
<div class="step"><b>1.</b> Create a <b>public</b> repo at <a href="https://github.com/new" target="_blank">github.com/new</a></div>
<div class="step"><b>2.</b> Generate a classic token at <a href="https://github.com/settings/tokens" target="_blank">github.com/settings/tokens</a> with <code>repo</code> scope</div>
<div class="step"><b>3.</b> Enter token and repo:</div>
<form method="post">
<input type="hidden" name="action" value="github">
<input name="gh_token" placeholder="github_pat_...." required>
<input name="gh_repo" placeholder="username/repo-name" required>
<button class="btn btn-green">Save GitHub</button>
</form>
</div>

<p><a href="/">Back to main</a></p>
<script>
function updateLink(){
 var id=document.getElementById('appId').value;
 var link=document.getElementById('oauthLink');
 if(id){
  link.href='https://oauth.vk.com/authorize?client_id='+id+'&scope=wall,photos,groups,offline&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token&v=5.199';
  link.textContent=link.href;
 }else{
  link.href='#';link.textContent='enter App ID first';
 }
}
updateLink();
</script>
</body></html>"""


if __name__ == "__main__":
    ssl._create_default_https_context = ssl._create_unverified_context
    app.run(debug=True)
