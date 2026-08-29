import os
import json
import datetime
from functools import wraps

import pytz
from google import genai
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, flash, session
)
from werkzeug.security import check_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import db

WIB = pytz.timezone('Asia/Jakarta')

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-ganti-nanti")
app.permanent_session_lifetime = datetime.timedelta(days=7)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

# File cache lokal (hanya untuk rekomendasi AI, BUKAN status warung)
CACHE_FILE = "ai_cache_data.json"

KATEGORI = [
    "Cemilan & Gorengan",
    "Makanan Kering / Keripik",
    "Makanan Berat",
    "Pre-Order",
]

PROMPT_DEFAULT = """Kamu adalah seorang kasir warung makan yang ramah, asyik, dan jago jualan.

Berikut adalah DAFTAR MENU ASLI yang tersedia hari ini:
{menu}

ATURAN MUTLAK:
1. Kamu HANYA boleh menyebut item yang BENAR-BENAR tertulis di DAFTAR MENU ASLI di atas.
2. DILARANG KERAS mengarang atau menyebut item apa pun yang tidak ada di daftar, termasuk kategori umum seperti 'minuman dingin', 'es teh', 'air putih', dll.
3. JANGAN menyebut, menyinggung, atau meminta maaf soal item yang tidak tersedia. Cukup fokus pada apa yang ADA.

TUGAS:
Rekomendasikan kombinasi atau satu item andalan HANYA dari daftar di atas, dengan alasan singkat yang menggugah selera. Maksimal 3 kalimat."""

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def get_pengaturan():
    return db.fetch_one("select * from pengaturan order by id limit 1")


def hapus_cache():
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        return True
    return False


def butuh_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def ambil_pesanan_terakhir(limit=20):
    pesanan = db.fetch_all(
        "select *, created_at at time zone 'Asia/Jakarta' as waktu_wib"
        " from pesanan order by created_at desc limit %s",
        (limit,),
    )
    if not pesanan:
        return []

    rows = db.fetch_all(
        "select pesanan_id, nama_menu, qty, harga from pesanan_item"
        " where pesanan_id = any(%s) order by id",
        ([p["id"] for p in pesanan],),
    )
    per_pesanan = {}
    for r in rows:
        per_pesanan.setdefault(r["pesanan_id"], []).append(r)
    for p in pesanan:
        p["daftar_item"] = per_pesanan.get(p["id"], [])
    return pesanan


def dapatkan_rekomendasi_cache_atau_api(daftar_menu, prompt_template=None):
    waktu_sekarang = datetime.datetime.now(WIB)
    target_jam_7_hari_ini = waktu_sekarang.replace(hour=7, minute=0, second=0, microsecond=0)

    if waktu_sekarang < target_jam_7_hari_ini:
        waktu_mulai_berlaku = target_jam_7_hari_ini - datetime.timedelta(days=1)
    else:
        waktu_mulai_berlaku = target_jam_7_hari_ini

    cache_valid = False
    rekomendasi_teks = ""

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data_cache = json.load(f)
            waktu_cache_dibuat = WIB.localize(
                datetime.datetime.strptime(data_cache["timestamp"], "%Y-%m-%d %H:%M:%S")
            )
            if waktu_cache_dibuat >= waktu_mulai_berlaku:
                cache_valid = True
                rekomendasi_teks = data_cache["rekomendasi"]
                print("--> [CACHE HIT] Pakai rekomendasi hari ini (hemat kuota API).")
        except Exception as cache_err:
            print(f"Gagal baca cache lokal, hit API ulang: {str(cache_err)}")

    if not cache_valid:
        print("--> [CACHE MISS] Menembak API Gemini...")
        try:
            menu_text = "".join(
                [f"- {m['nama']} (Kategori: {m['kategori']}, Harga: {m['harga']})" for m in daftar_menu]
            )
            prompt = (prompt_template or PROMPT_DEFAULT).replace("{menu}", menu_text)
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            rekomendasi_teks = response.text
            with open(CACHE_FILE, "w") as f:
                json.dump({
                    "timestamp": waktu_sekarang.strftime("%Y-%m-%d %H:%M:%S"),
                    "rekomendasi": rekomendasi_teks
                }, f)
        except Exception as ai_err:
            print(f"Gemini API Error (pakai fallback): {str(ai_err)}")
            rekomendasi_teks = (
                "Halo Kak! Nikmati pilihan menu katering terbaik kami hari ini yang dibuat "
                "dengan bahan segar dan higienis."
            )

    return rekomendasi_teks


@app.route('/ping')
def ping():
    return "pong", 200


@app.route('/')
def index():
    try:
        p = get_pengaturan()
        warung_buka = bool(p["warung_buka"])

        daftar_menu = db.fetch_all(
            "select * from menu where aktif = true order by urutan, nama"
        )

        menu_per_kategori = {}
        for m in daftar_menu:
            kat = (m.get("kategori") or "Lainnya").strip()
            menu_per_kategori.setdefault(kat, []).append(m)

        if not warung_buka:
            rekomendasi_ai = p["pesan_tutup"] or "Maaf Kak, Linda Catering sedang tutup."
        elif daftar_menu:
            rekomendasi_ai = dapatkan_rekomendasi_cache_atau_api(
                daftar_menu, p["prompt_template"]
            )
        else:
            rekomendasi_ai = "Belum ada menu untuk hari ini."

        return render_template(
            'index.html',
            menu=daftar_menu,
            menu_per_kategori=menu_per_kategori,
            ai_suggestion=rekomendasi_ai,
            warung_buka=warung_buka
        )
    except Exception as e:
        return f"Terjadi kesalahan koneksi data: {str(e)}"


@app.route('/pesan', methods=['POST'])
def simpan_pesanan():
    try:
        p = get_pengaturan()
        if not p["warung_buka"]:
            return jsonify({"status": "error", "message": "Maaf, warung sedang tutup."})

        data = request.get_json(silent=True) or {}
        nama = (data.get("nama") or "").strip()
        catatan = (data.get("catatan") or "").strip() or None
        items = data.get("items") or []

        if not nama:
            return jsonify({"status": "error", "message": "Nama tidak boleh kosong!"})
        if not items:
            return jsonify({"status": "error", "message": "Pilih minimal 1 item menu."})

        ids = [int(i["menu_id"]) for i in items]
        rows = db.fetch_all(
            "select id, nama, harga from menu"
            " where id = any(%s) and aktif = true and habis = false",
            (ids,),
        )
        tersedia = {r["id"]: r for r in rows}

        baris = []
        total = 0
        for i in items:
            mid, qty = int(i["menu_id"]), int(i["qty"])
            if qty < 1 or mid not in tersedia:
                return jsonify({
                    "status": "error",
                    "message": "Ada item yang sudah tidak tersedia. Silakan refresh halaman."
                })
            m = tersedia[mid]
            total += m["harga"] * qty
            baris.append((mid, m["nama"], qty, m["harga"]))

        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into pesanan (nama_pembeli, catatan, total)"
                " values (%s, %s, %s) returning id",
                (nama, catatan, total),
            )
            pesanan_id = cur.fetchone()["id"]
            for mid, nama_menu, qty, harga in baris:
                cur.execute(
                    "insert into pesanan_item (pesanan_id, menu_id, nama_menu, qty, harga)"
                    " values (%s, %s, %s, %s, %s)",
                    (pesanan_id, mid, nama_menu, qty, harga),
                )

        total_fmt = f"{total:,}".replace(",", ".")
        return jsonify({
            "status": "success",
            "message": f"Pesanan {nama} berhasil dibuat! Total Rp {total_fmt}"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ============================================================
# AUTH
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if ADMIN_PASSWORD_HASH and check_password_hash(
            ADMIN_PASSWORD_HASH, request.form.get("password", "")
        ):
            session["admin"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("admin_menu"))
        flash("Password salah")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ============================================================
# ADMIN
# ============================================================
@app.route("/admin")
@butuh_login
def admin_menu():
    items = db.fetch_all("select * from menu order by aktif desc, urutan, nama")
    return render_template(
        "admin_menu.html",
        items=items,
        kategori=KATEGORI,
        p=get_pengaturan(),
        pesanan=ambil_pesanan_terakhir(),
    )


@app.post("/admin/menu/tambah")
@butuh_login
def admin_menu_tambah():
    nama = request.form.get("nama", "").strip()
    kategori = request.form.get("kategori") or None
    harga = int(request.form.get("harga", "").replace(".", "").replace(",", "") or 0)

    if not nama:
        flash("Nama menu wajib diisi")
        return redirect(url_for("admin_menu"))

    if kategori and kategori not in KATEGORI:
        flash("Kategori tidak valid")
        return redirect(url_for("admin_menu"))

    urutan = db.fetch_one("select coalesce(max(urutan), 0) + 1 as n from menu")["n"]

    db.execute(
        "insert into menu (nama, kategori, harga, is_default, aktif, habis, urutan)"
        " values (%s, %s, %s, false, true, false, %s)",
        (nama, kategori, harga, urutan),
    )
    flash(f"Menu '{nama}' ditambahkan")
    return redirect(url_for("admin_menu"))


@app.post("/admin/menu/<int:menu_id>/toggle/<field>")
@butuh_login
def admin_menu_toggle(menu_id, field):
    if field not in ("aktif",):
        return redirect(url_for("admin_menu"))
    db.execute(f"update menu set {field} = not {field} where id = %s", (menu_id,))
    return redirect(url_for("admin_menu"))


@app.post("/admin/menu/<int:menu_id>/pindah/<arah>")
@butuh_login
def admin_menu_pindah(menu_id, arah):
    if arah not in ("naik", "turun"):
        return redirect(url_for("admin_menu"))

    m = db.fetch_one("select id, urutan, aktif from menu where id = %s", (menu_id,))
    if not m:
        return redirect(url_for("admin_menu"))

    if arah == "naik":
        t = db.fetch_one(
            "select id, urutan from menu where aktif = %s and urutan < %s"
            " order by urutan desc limit 1",
            (m["aktif"], m["urutan"]),
        )
    else:
        t = db.fetch_one(
            "select id, urutan from menu where aktif = %s and urutan > %s"
            " order by urutan asc limit 1",
            (m["aktif"], m["urutan"]),
        )

    if t:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("update menu set urutan = %s where id = %s", (t["urutan"], m["id"]))
            cur.execute("update menu set urutan = %s where id = %s", (m["urutan"], t["id"]))

    return redirect(url_for("admin_menu"))


@app.post("/admin/warung/toggle")
@butuh_login
def admin_warung_toggle():
    p = get_pengaturan()
    db.execute(
        "update pengaturan set warung_buka = not warung_buka, updated_at = now() where id = %s",
        (p["id"],),
    )
    return redirect(url_for("admin_menu"))


@app.post("/admin/warung/pesan")
@butuh_login
def admin_warung_pesan():
    p = get_pengaturan()
    db.execute(
        "update pengaturan set pesan_tutup = %s, updated_at = now() where id = %s",
        (request.form.get("pesan_tutup", "").strip(), p["id"]),
    )
    flash("Pesan tutup disimpan")
    return redirect(url_for("admin_menu"))


@app.post("/admin/prompt")
@butuh_login
def admin_prompt_simpan():
    p = get_pengaturan()
    db.execute(
        "update pengaturan set prompt_template = %s, updated_at = now() where id = %s",
        (request.form.get("prompt_template", "").strip() or None, p["id"]),
    )
    hapus_cache()
    flash("Prompt template disimpan, cache dibersihkan")
    return redirect(url_for("admin_menu"))


@app.post("/admin/cache/refresh")
@butuh_login
def admin_cache_refresh():
    flash("Cache dihapus" if hapus_cache() else "Cache sudah kosong")
    return redirect(url_for("admin_menu"))


if __name__ == '__main__':
    app.run(debug=True)