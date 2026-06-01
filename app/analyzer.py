import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ──────────────────────────────────────────────
# SNAP UTILITIES
# ──────────────────────────────────────────────

def _snap_ke_jeda_natural(
    end_time: float,
    transkrip_kata: list,
    toleransi: float = 4.0,
    min_jeda: float = 0.4
) -> float:
    window_start = end_time - toleransi
    window_end   = end_time + toleransi

    kata_window = [
        (i, w) for i, w in enumerate(transkrip_kata)
        if window_start <= w["end"] <= window_end
    ]
    if not kata_window:
        return end_time

    kandidat = []
    for _, (i, kata) in enumerate(kata_window):
        if i + 1 < len(transkrip_kata):
            jeda = transkrip_kata[i + 1]["start"] - kata["end"]
        else:
            jeda = 999
        kandidat.append({
            "end_kata": kata["end"],
            "jeda":     jeda,
            "jarak":    abs(kata["end"] - end_time)
        })

    jeda_natural = [k for k in kandidat if k["jeda"] >= min_jeda]
    if jeda_natural:
        pilihan = max(jeda_natural, key=lambda k: k["jeda"])
        print(f"   [SnapCut] end {end_time:.2f}s → {pilihan['end_kata']:.2f}s "
              f"(jeda {pilihan['jeda']:.2f}s)")
        return pilihan["end_kata"]

    terdekat = min(kandidat, key=lambda k: k["jarak"])
    print(f"   [SnapCut] snap ke kata terdekat: {end_time:.2f}s → {terdekat['end_kata']:.2f}s")
    return terdekat["end_kata"]


def _snap_ke_awal_kalimat(
    start_time: float,
    transkrip_kata: list,
    toleransi: float = 2.0,
    min_jeda: float = 0.3
) -> float:
    window_start = start_time - toleransi
    window_end   = start_time + toleransi

    kata_window = [
        (i, w) for i, w in enumerate(transkrip_kata)
        if window_start <= w["start"] <= window_end and i > 0
    ]
    if not kata_window:
        return start_time

    kandidat = []
    for i, kata in kata_window:
        jeda_sebelum = kata["start"] - transkrip_kata[i - 1]["end"]
        kandidat.append({
            "start_kata": kata["start"],
            "jeda":       jeda_sebelum,
            "jarak":      abs(kata["start"] - start_time)
        })

    jeda_natural = [k for k in kandidat if k["jeda"] >= min_jeda]
    if jeda_natural:
        pilihan = max(jeda_natural, key=lambda k: k["jeda"])
        print(f"   [SnapCut] start {start_time:.2f}s → {pilihan['start_kata']:.2f}s "
              f"(jeda {pilihan['jeda']:.2f}s)")
        return pilihan["start_kata"]

    return start_time


# ──────────────────────────────────────────────
# KOMPRES TRANSKRIP
# Ubah list kata+timestamp → teks ringkas per kalimat
# Format: [mm:ss] kalimat pendek...
# Jauh lebih kecil dari json.dumps(transkrip_kata)
# ──────────────────────────────────────────────

def _kompres_transkrip(transkrip_kata: list, kata_per_kalimat: int = 12) -> str:
    """
    Gabungkan transkrip kata menjadi kalimat-kalimat pendek dengan
    timestamp awal per kalimat. Format output:

      [00:10] ini adalah contoh kalimat pertama yang cukup panjang
      [00:18] lanjutan kalimat berikutnya dalam transkrip ini
      ...

    Ini jauh lebih kecil dari JSON per-kata, tapi tetap memberi Gemini
    informasi waktu yang cukup untuk menentukan start_time dan end_time.
    """
    if not transkrip_kata:
        return ""

    baris = []
    i = 0
    while i < len(transkrip_kata):
        grup   = transkrip_kata[i : i + kata_per_kalimat]
        t      = grup[0]["start"]
        menit  = int(t // 60)
        detik  = int(t % 60)
        teks   = " ".join(w["word"] for w in grup)
        baris.append(f"[{menit:02d}:{detik:02d}] {teks}")
        i += kata_per_kalimat

    return "\n".join(baris)


# ──────────────────────────────────────────────
# MAIN ANALYZER
# ──────────────────────────────────────────────

def cari_segmen_hook(transkrip_kata: list) -> list[dict]:
    """
    Analisis transkrip dan minta Gemini menentukan sendiri berapa clip
    yang layak dibuat. Transkrip dikirim dalam format ringkas (teks + timestamp
    per kalimat) bukan JSON per-kata, agar Gemini jauh lebih cepat.
    Timestamp detail tetap dipakai untuk snap ke titik potong natural.
    """
    print("====== [STEP 2] Menganalisis Potensi Viral dengan Gemini ======")

    durasi_video  = transkrip_kata[-1]["end"] if transkrip_kata else 0
    durasi_menit  = durasi_video / 60

    print(f"   Durasi video   : {durasi_menit:.1f} menit ({durasi_video:.0f} detik)")
    print(f"   Total kata     : {len(transkrip_kata)}")

    # Kompres transkrip sebelum kirim ke Gemini
    transkrip_ringkas = _kompres_transkrip(transkrip_kata, kata_per_kalimat=12)
    ukuran_kb = len(transkrip_ringkas.encode()) / 1024
    print(f"   Payload Gemini : {ukuran_kb:.1f} KB "
          f"(dari ~{len(json.dumps(transkrip_kata).encode())//1024} KB raw)")

    prompt = f"""Anda adalah video editor profesional khusus konten viral TikTok, Instagram Reels, dan YouTube Shorts.

Video berdurasi {durasi_menit:.1f} menit. Tentukan sendiri berapa clip pendek yang layak dibuat.

ATURAN:
1. Durasi setiap clip: 25–45 detik
2. Tidak boleh overlap antar clip
3. Mulai dan akhiri di batas kalimat yang natural
4. Pilih HANYA yang berpotensi viral — jangan paksa jika konten biasa saja
5. Video >30 menit: target 3–8 clip. Video <10 menit: 1–3 clip
6. Urutkan berdasarkan start_time ascending
7. start_time dan end_time dalam satuan DETIK (bukan mm:ss)

TRANSKRIP (format [mm:ss] teks):
{transkrip_ringkas}

Balas HANYA JSON array, tanpa teks lain:
[{{"start_time": 10.0, "end_time": 48.0, "hook_title": "...", "reason": "..."}}]"""

    print("   Mengirim ke Gemini...")

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=8192
            )
        )
        try:
            response = future.result(timeout=90)  # 90 detik timeout
        except concurrent.futures.TimeoutError:
            raise RuntimeError("Gemini timeout setelah 90 detik — coba lagi.")

    # Robust JSON parsing
    raw = response.text.strip()

    # Buang markdown fence jika ada
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Ambil dari karakter '[' pertama
    start_idx = raw.find("[")
    if start_idx == -1:
        raise RuntimeError(f"Gemini tidak return JSON array.\nRaw: {raw[:300]}")
    raw = raw[start_idx:]

    # Coba parse langsung
    try:
        hasil = json.loads(raw)
    except json.JSONDecodeError:
        # JSON terpotong — repair: buang objek terakhir yang tidak lengkap
        # lalu tutup array dengan ']'
        last_complete = raw.rfind("},")
        if last_complete == -1:
            last_complete = raw.rfind("}")
        if last_complete != -1:
            raw_repaired = raw[:last_complete + 1] + "\n]"
            try:
                hasil = json.loads(raw_repaired)
                print(f"   ⚠️  JSON terpotong, berhasil di-repair ({len(hasil)} item).")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"JSON tidak bisa di-repair: {e}\nRaw: {raw[:300]}")
        else:
            raise RuntimeError(f"JSON tidak valid dan tidak bisa di-repair.\nRaw: {raw[:300]}")

    if isinstance(hasil, dict):
        hasil = [hasil]

    print(f"   Gemini return {len(hasil)} segmen, memvalidasi...")

    valid    = []
    last_end = 0.0

    for i, seg in enumerate(hasil):
        start  = float(seg.get("start_time", 0))
        end    = float(seg.get("end_time", 0))

        # Snap ke titik bicara natural menggunakan timestamp detail
        start = _snap_ke_awal_kalimat(start, transkrip_kata)
        end   = _snap_ke_jeda_natural(end,   transkrip_kata)

        durasi = end - start

        if start < last_end:
            print(f"   ⚠️  Clip {i+1} overlap, dilewati.")
            continue
        if durasi < 20:
            print(f"   ⚠️  Clip {i+1} terlalu pendek ({durasi:.1f}s), dilewati.")
            continue
        if durasi > 60:
            end    = _snap_ke_jeda_natural(start + 45, transkrip_kata, toleransi=3.0)
            durasi = end - start
            print(f"   ⚠️  Clip {i+1} terlalu panjang, dipotong ke {durasi:.1f}s")

        valid.append({
            "start_time": round(start, 2),
            "end_time":   round(end,   2),
            "hook_title": seg.get("hook_title", f"Clip {i+1}"),
            "reason":     seg.get("reason", "")
        })
        last_end = end

    print(f"\n   ✅ {len(valid)} clip siap diproses")
    for i, v in enumerate(valid):
        dur = v["end_time"] - v["start_time"]
        print(f"      Clip {i+1}: [{v['start_time']:.1f}s → {v['end_time']:.1f}s] "
              f"({dur:.1f}s) — {v['hook_title']}")

    return valid