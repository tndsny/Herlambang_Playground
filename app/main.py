from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import uuid
import time

from app.transcriber import dapatkan_transkrip_kata_cloud
from app.analyzer import cari_segmen_hook
from app.clipper import proses_potong_video_cloud
from app.subtitler import buat_file_ass

TEMP_DIR = "temp"

app = FastAPI(
    title="KawanTech AI Video Clipper",
    description="Clip video lokal → beberapa klip vertikal TikTok siap posting secara otomatis.",
    version="4.0.0"
)


class LocalClipRequest(BaseModel):
    filename: str   # nama file di dalam folder temp/, contoh: "video.mp4"


@app.post("/api/v1/clip-from-local")
async def clip_from_local(payload: LocalClipRequest):
    os.makedirs(TEMP_DIR, exist_ok=True)

    input_path = os.path.join(TEMP_DIR, payload.filename)
    if not os.path.exists(input_path):
        raise HTTPException(
            status_code=404,
            detail=f"File tidak ditemukan: {input_path}"
        )

    waktu_mulai = time.time()
    subtitle_files: list[str] = []   # track semua file subtitle untuk cleanup

    try:
        print("\n" + "="*60)
        print("🎬 MULAI PROSES GENERATE MULTI-CLIP (LOKAL)")
        print(f"   Sumber: {input_path}")
        print("="*60)

        # ── [1/3] Transkripsi (1x untuk seluruh video) ─────────────────
        t1 = time.time()
        print("\n[1/3] Transkripsi audio via Deepgram...")
        transkrip = dapatkan_transkrip_kata_cloud(input_path)
        print(f"      ✅ Selesai dalam {time.time() - t1:.1f} detik")

        if not transkrip:
            raise HTTPException(
                status_code=422,
                detail="Transkripsi gagal atau video tidak memiliki audio yang bisa dideteksi."
            )

        # ── [2/3] Analisis — AI tentukan sendiri jumlah clip ───────────
        t2 = time.time()
        print("\n[2/3] Analisis multi-clip via Gemini AI...")
        segmen_list = cari_segmen_hook(transkrip)
        print(f"      ✅ Selesai dalam {time.time() - t2:.1f} detik")

        if not segmen_list:
            raise HTTPException(
                status_code=422,
                detail="Gemini tidak menemukan segmen yang layak dijadikan clip TikTok."
            )

        # ── [3/3] Proses setiap clip ────────────────────────────────────
        print(f"\n[3/3] Memproses {len(segmen_list)} clip...")
        print("-" * 60)

        clips_hasil = []

        # Nama dasar dari file input (tanpa ekstensi), dipakai sebagai prefix output
        nama_dasar = os.path.splitext(payload.filename)[0]
        # Gunakan penomoran hanya jika clip lebih dari 1
        pakai_nomor = len(segmen_list) > 1

        for i, segmen in enumerate(segmen_list):
            clip_num     = i + 1
            start_time   = segmen["start_time"]
            end_time     = segmen["end_time"]
            durasi_clip  = round(end_time - start_time, 1)

            print(f"\n  ▶ Clip {clip_num}/{len(segmen_list)}: "
                  f"[{start_time:.1f}s → {end_time:.1f}s] ({durasi_clip}s)")
            print(f"    Hook: {segmen['hook_title']}")

            # Penamaan: namafileasli_001.mp4 jika multi-clip, namafileasli.mp4 jika hanya 1
            if pakai_nomor:
                nama_output = f"{nama_dasar}_{clip_num:03d}.mp4"
            else:
                nama_output = f"{nama_dasar}.mp4"

            output_filename   = os.path.join(TEMP_DIR, nama_output)
            subtitle_filename = os.path.join(TEMP_DIR, f"sub_{uuid.uuid4().hex[:8]}.ass")
            subtitle_files.append(subtitle_filename)

            t_clip = time.time()

            try:
                # Subtitle untuk clip ini
                buat_file_ass(
                    words=transkrip,
                    start_offset=start_time,
                    end_offset=end_time,
                    output_path=subtitle_filename
                )

                # Potong, crop face-tracking, burn subtitle
                proses_potong_video_cloud(
                    video_stream_url=input_path,
                    audio_stream_url=input_path,
                    output_filename=output_filename,
                    start_time=start_time,
                    end_time=end_time,
                    subtitle_path=subtitle_filename
                )

                durasi_proses = round(time.time() - t_clip, 1)
                ukuran_mb     = round(os.path.getsize(output_filename) / 1024 / 1024, 2)

                print(f"    ✅ Clip {clip_num} selesai dalam {durasi_proses}s | "
                      f"Ukuran: {ukuran_mb} MB | Output: {output_filename}")

                clips_hasil.append({
                    "clip_number":   clip_num,
                    "output_file":   output_filename,
                    "ukuran_mb":     ukuran_mb,
                    "durasi_detik":  durasi_clip,
                    "waktu_proses":  f"{durasi_proses} detik",
                    "hook_title":    segmen["hook_title"],
                    "reason":        segmen["reason"],
                    "start_time":    start_time,
                    "end_time":      end_time,
                })

            except Exception as e:
                # Clip gagal tidak menghentikan clip lainnya
                print(f"    ❌ Clip {clip_num} GAGAL: {e}")
                clips_hasil.append({
                    "clip_number": clip_num,
                    "status":      "gagal",
                    "error":       str(e),
                    "hook_title":  segmen["hook_title"],
                    "start_time":  start_time,
                    "end_time":    end_time,
                })

        # ── Ringkasan ───────────────────────────────────────────────────
        total       = time.time() - waktu_mulai
        menit       = int(total // 60)
        detik_sisa  = total % 60
        sukses      = [c for c in clips_hasil if "output_file" in c]
        gagal       = [c for c in clips_hasil if "status" in c and c["status"] == "gagal"]

        print("\n" + "="*60)
        print(f"✅ SELESAI — {len(sukses)} clip berhasil, {len(gagal)} gagal")
        print(f"   Total waktu: {menit} menit {detik_sisa:.1f} detik")
        print("="*60 + "\n")

        return {
            "status":          "success",
            "input_file":      input_path,
            "total_clip":      len(segmen_list),
            "clip_berhasil":   len(sukses),
            "clip_gagal":      len(gagal),
            "waktu_generate":  f"{menit} menit {detik_sisa:.1f} detik",
            "clips":           clips_hasil
        }

    except HTTPException:
        raise
    except Exception as e:
        total = time.time() - waktu_mulai
        print(f"\n❌ GAGAL setelah {total:.1f} detik — {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Bersihkan semua file subtitle
        for sf in subtitle_files:
            if os.path.exists(sf):
                os.remove(sf)
                print(f"File subtitle '{sf}' dihapus.")


@app.get("/")
def root():
    return {"status": "online", "app": "KawanTech AI Video Clipper v4.0 — Multi-Clip"}