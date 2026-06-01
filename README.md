# 🚀 Panduan Deploy Linda Catering ke Render

## Struktur File yang Dibutuhkan

```
linda-catering/
├── app.py
├── requirements.txt
├── render.yaml          ← BARU
├── .gitignore           ← BARU (ganti yang lama)
├── templates/
│   └── index.html       ← PINDAHKAN ke folder ini
└── service_account.json ← BARU (dari Google Cloud Console)
```

---

## LANGKAH 1 — Siapkan Google Service Account

Karena Render adalah server cloud, OAuth login via browser (`token.json`) tidak bisa dipakai.
Kamu harus beralih ke **Service Account**.

### Cara buat Service Account:

1. Buka [console.cloud.google.com](https://console.cloud.google.com)
2. Pilih project kamu (`project-ab41daf0-279c-458f-bfe`)
3. Pergi ke **IAM & Admin → Service Accounts**
4. Klik **Create Service Account**
   - Name: `linda-catering-bot`
   - Klik **Create and Continue** → **Done**
5. Klik service account yang baru dibuat
6. Tab **Keys** → **Add Key** → **Create new key** → pilih **JSON**
7. File JSON akan otomatis terdownload — **simpan baik-baik, jangan di-share!**
8. Rename file tersebut menjadi `service_account.json`

### Share Google Sheets ke Service Account:

1. Buka file `service_account.json`, cari field `"client_email"` (contoh: `linda-catering-bot@project-xxx.iam.gserviceaccount.com`)
2. Buka Google Sheets **"Data Warung Digital"**
3. Klik tombol **Share** di pojok kanan atas
4. Paste `client_email` tadi, berikan akses **Editor**
5. Klik **Send**

---

## LANGKAH 2 — Update app.py

Ganti fungsi `get_sheets_client()` di `app.py` dengan versi Service Account (lihat file `app_updated.py` yang sudah disiapkan).

---

## LANGKAH 3 — Pindahkan index.html ke folder templates/

Render/Flask membutuhkan file HTML di dalam folder `templates/`:

```bash
mkdir templates
mv index.html templates/
```

---

## LANGKAH 4 — Push ke GitHub

```bash
# Inisialisasi repo (jika belum)
git init
git add .
git commit -m "Initial commit - Linda Catering"

# Buat repo baru di github.com, lalu:
git remote add origin https://github.com/USERNAME/linda-catering.git
git branch -M main
git push -u origin main
```

> ⚠️ Pastikan `.gitignore` sudah benar agar `service_account.json` dan `token.json` TIDAK ikut ter-upload ke GitHub!

---

## LANGKAH 5 — Deploy di Render

1. Buka [render.com](https://render.com) dan login/daftar
2. Klik **New +** → **Web Service**
3. Pilih **Connect a repository** → pilih repo GitHub kamu
4. Isi konfigurasi:
   - **Name**: `linda-catering`
   - **Region**: Singapore (terdekat dari Indonesia)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. Klik **Advanced** → **Add Environment Variable**:

   | Key | Value |
   |-----|-------|
   | `GEMINI_API_KEY` | API key Gemini kamu |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | *(isi di langkah berikutnya)* |

6. Untuk `GOOGLE_SERVICE_ACCOUNT_JSON`: buka file `service_account.json`, copy **seluruh isinya** (format JSON), paste sebagai value environment variable tersebut.

7. Klik **Create Web Service** — Render akan mulai build otomatis!

---

## LANGKAH 6 — Verifikasi

Setelah deploy selesai (biasanya 2-5 menit), Render akan memberi URL seperti:
`https://linda-catering.onrender.com`

Buka URL tersebut dan cek apakah aplikasi berjalan normal.

---

## ⚠️ Catatan Penting

- **Free tier Render**: server akan "tidur" setelah 15 menit tidak ada request, dan butuh ~30 detik untuk "bangun" lagi. Untuk produksi, upgrade ke plan berbayar atau gunakan UptimeRobot untuk ping otomatis.
- **Cache rekomendasi AI**: karena Render pakai ephemeral storage, file `ai_cache_data.json` akan reset setiap deploy. Ini tidak masalah — hanya berarti API Gemini akan dipanggil sekali lagi setelah deploy.
- **Jangan pernah commit** `service_account.json`, `token.json`, atau `credentials.json` ke GitHub publik!