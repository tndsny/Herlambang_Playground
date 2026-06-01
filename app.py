import os
import datetime
import time
import json  # Ditambahkan untuk menyimpan data cache ke file fisik (.json)
from flask import Flask, render_template, request, jsonify
import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
# Menggunakan SDK google-genai terbaru
from google import genai 

app = Flask(__name__)

# FILE DATA CACHE LOKAL (Agar data tidak hilang meski Flask di-restart)
CACHE_FILE = "ai_cache_data.json"

# 1. KONFIGURASI GOOGLE SHEETS API (OAUTH2)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_sheets_client():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    return gspread.authorize(creds)

# 2. KONFIGURASI GEMINI AI SDK BARU
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6L7pagNp-NuKxL4USceNpyZeWL40sK1Au1f5o_LNQc8jQ")
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def dapatkan_rekomendasi_cache_atau_api(daftar_menu):
    """
    Fungsi pintar untuk mengontrol hit ke API Gemini hanya sekali dalam sehari.
    Siklus akan diperbarui (expired) setiap memasuki jam 7 pagi di hari baru.
    """
    waktu_sekarang = datetime.datetime.now()
    
    # Ambil titik target jam 7 pagi di hari yang berjalan sekarang
    target_jam_7_hari_ini = waktu_sekarang.replace(hour=7, minute=0, second=0, microsecond=0)
    
    # Hitung batas minimal waktu berlaku cache untuk siklus hari ini:
    # Jika saat ini BELUM jam 7 pagi, berarti masih ikut siklus rekomendasi jam 7 pagi KEMARIN.
    if waktu_sekarang < target_jam_7_hari_ini:
        waktu_mulai_berlaku = target_jam_7_hari_ini - datetime.timedelta(days=1)
    else:
        waktu_mulai_berlaku = target_jam_7_hari_ini

    cache_valid = False
    rekomendasi_teks = ""
    
    # Skenario A: Coba cek file JSON lokal dulu
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data_cache = json.load(f)
                
            waktu_cache_dibuat = datetime.datetime.strptime(data_cache["timestamp"], "%Y-%m-%d %H:%M:%S")
            
            # Jika cache dibuat SETELAH 'waktu_mulai_berlaku', tandanya data masih valid & statis
            if waktu_cache_dibuat >= waktu_mulai_berlaku:
                cache_valid = True
                rekomendasi_teks = data_cache["rekomendasi"]
                print("--> [CACHE HIT] Menggunakan rekomendasi statis hari ini (Hemat Kuota API).")
        except Exception as cache_err:
            print(f"Gagal membaca cache lokal, terpaksa hit API ulang: {str(cache_err)}")

    # Skenario B: Cache kedaluwarsa atau belum ada, saatnya tembak Gemini API sekali saja
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
            
            # Amankan hasil rekomendasi baru ke file JSON fisik
            data_baru_cache = {
                "timestamp": waktu_sekarang.strftime("%Y-%m-%d %H:%M:%S"),
                "rekomendasi": rekomendasi_teks
            }
            with open(CACHE_FILE, "w") as f:
                json.dump(data_baru_cache, f)
                
        except Exception as ai_err:
            print(f"Gemini API Error (Menggunakan Fallback Default): {str(ai_err)}")
            # Fallback teks bawaan jika sewaktu-waktu Google API mengalami gangguan/limit
            rekomendasi_teks = "Halo Kak! Nikmati pilihan menu katering terbaik kami hari ini yang dibuat dengan bahan segar dan higienis. Padukan cemilan favoritmu dengan menu utama pilihan untuk penambah semangat!"

    return rekomendasi_teks


@app.route('/')
def index():
    try:
        client = get_sheets_client()
        sheet = client.open("Data Warung Digital")
        
        # Tarik Data Menu Hari Ini
        menu_sheet = sheet.worksheet("Menu")
        daftar_menu = menu_sheet.get_all_records()
        
        rekomendasi_ai = "Belum ada rekomendasi menu untuk saat ini."
        
        if daftar_menu:
            # Menggunakan logika pembatasan jam 7 pagi
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
        waktu_sekarang = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        client = get_sheets_client()
        sheet = client.open("Data Warung Digital").worksheet("Pesanan")
        sheet.append_row([waktu_sekarang, nama, item, jumlah])
        
        return jsonify({"status": "success", "message": f"Pesanan {nama} berhasil dibuat!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)