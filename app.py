import os
import datetime
import json
import pytz

WIB = pytz.timezone('Asia/Jakarta')
from flask import Flask, render_template, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
from google import genai

app = Flask(__name__)

# FILE DATA CACHE LOKAL
CACHE_FILE = "ai_cache_data.json"

# 1. KONFIGURASI GOOGLE SHEETS API (SERVICE ACCOUNT)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_sheets_client():
    """
    Mendukung dua cara autentikasi:
    - Di Render (production): baca dari environment variable GOOGLE_SERVICE_ACCOUNT_JSON
    - Di lokal (development): baca dari file service_account.json
    """
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if service_account_json:
        # Production: baca dari env variable (value-nya adalah string JSON)
        service_account_info = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    else:
        # Local development: baca dari file
        creds = Credentials.from_service_account_file('service_account.json', scopes=SCOPES)
    
    return gspread.authorize(creds)


# 2. KONFIGURASI GEMINI AI SDK
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def dapatkan_rekomendasi_cache_atau_api(daftar_menu):
    """
    Fungsi pintar untuk mengontrol hit ke API Gemini hanya sekali dalam sehari.
    Siklus akan diperbarui (expired) setiap memasuki jam 7 pagi di hari baru.
    """
    waktu_sekarang = datetime.datetime.now(WIB)
    
    target_jam_7_hari_ini = waktu_sekarang.replace(hour=7, minute=0, second=0, microsecond=0)
    
    if waktu_sekarang < target_jam_7_hari_ini:
        waktu_mulai_berlaku = target_jam_7_hari_ini - datetime.timedelta(days=1)
    else:
        waktu_mulai_berlaku = target_jam_7_hari_ini

    cache_valid = False
    rekomendasi_teks = ""
    
    # Skenario A: Cek file JSON cache lokal dulu
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data_cache = json.load(f)
                
            waktu_cache_dibuat = WIB.localize(datetime.datetime.strptime(data_cache["timestamp"], "%Y-%m-%d %H:%M:%S"))
            
            if waktu_cache_dibuat >= waktu_mulai_berlaku:
                cache_valid = True
                rekomendasi_teks = data_cache["rekomendasi"]
                print("--> [CACHE HIT] Menggunakan rekomendasi statis hari ini (Hemat Kuota API).")
        except Exception as cache_err:
            print(f"Gagal membaca cache lokal, terpaksa hit API ulang: {str(cache_err)}")

    # Skenario B: Cache kedaluwarsa atau belum ada
    if not cache_valid:
        print("--> [CACHE EXPIRED / MISS] Menembak API Gemini untuk siklus hari baru...")
        try:
            menu_text = "\n".join([f"- {m['nama']} (Kategori: {m['kategori']}, Harga: {m['harga']})" for m in daftar_menu])

            prompt = (
                f"Kamu adalah seorang kasir warung makan yang ramah, asyik, dan jago jualan.\n\n"
                f"Berikut adalah DAFTAR MENU ASLI yang tersedia hari ini:\n"
                f"{menu_text}\n\n"
                f"TUGAS UTAMA:\n"
                f"PILIHLAH 1 kombinasi (makanan/cemilan + minuman) yang WAJIB diambil HANYA dari DAFTAR MENU ASLI di atas! "
                f"DILARANG KERAS mengarang atau menyebutkan nama makanan/minuman lain yang tidak tertulis di daftar tersebut.\n\n"
                f"Berikan rekomendasi pasangannya dengan alasan singkat yang menggugah selera pelanggan! "
                f"Maksimal 3 kalimat."
            )
            
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            rekomendasi_teks = response.text
            
            # Simpan hasil ke cache
            data_baru_cache = {
                "timestamp": waktu_sekarang.strftime("%Y-%m-%d %H:%M:%S"),
                "rekomendasi": rekomendasi_teks
            }
            with open(CACHE_FILE, "w") as f:
                json.dump(data_baru_cache, f)
                
        except Exception as ai_err:
            print(f"Gemini API Error (Menggunakan Fallback Default): {str(ai_err)}")
            rekomendasi_teks = "Halo Kak! Nikmati pilihan menu katering terbaik kami hari ini yang dibuat dengan bahan segar dan higienis. Padukan cemilan favoritmu dengan menu utama pilihan untuk penambah semangat!"

    return rekomendasi_teks


@app.route('/ping')
def ping():
    return "pong", 200

@app.route('/')
def index():
    try:
        client = get_sheets_client()
        sheet = client.open("Data Warung Digital")
        
        menu_sheet = sheet.worksheet("Menu")
        daftar_menu = menu_sheet.get_all_records()
        
        rekomendasi_ai = "Belum ada rekomendasi menu untuk saat ini."
        
        if daftar_menu:
            rekomendasi_ai = dapatkan_rekomendasi_cache_atau_api(daftar_menu)

        return render_template('index.html', menu=daftar_menu, ai_suggestion=rekomendasi_ai)
        
    except Exception as e:
        return f"Terjadi kesalahan koneksi data: {str(e)}"

@app.route('/pesan', methods=['POST'])
def simpan_pesanan():
    try:
        nama = request.form.get('nama')
        item = request.form.get('item')
        jumlah = request.form.get('jumlah')
        waktu_sekarang = datetime.datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
        
        client = get_sheets_client()
        sheet = client.open("Data Warung Digital").worksheet("Pesanan")
        sheet.append_row([waktu_sekarang, nama, item, jumlah])
        
        return jsonify({"status": "success", "message": f"Pesanan {nama} berhasil dibuat!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)