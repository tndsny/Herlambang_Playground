from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import uuid

from app.downloader import ambil_direct_url_youtube
from app.storage import dapatkan_url_durasi_terbatas, upload_file_ke_r2
from app.transcriber import dapatkan_transkrip_kata_cloud
from app.analyzer import cari_segmen_hook
from app.clipper import proses_potong_video_cloud
from app.subtitler import buat_file_ass

app = FastAPI(
    title="KawanTech AI Video Clipper",
    description="Paste URL YouTube → Clip vertikal siap posting secara otomatis.",
    version="2.0.0"
)

class YouTubeClipRequest(BaseModel):
    youtube_url: str

class CloudClipRequest(BaseModel):
    r2_video_key: str


@app.post("/api/v1/clip-from-youtube")
async def clip_from_youtube(payload: YouTubeClipRequest):
    output_filename = f"clip_{uuid.uuid4().hex[:8]}.mp4"
    r2_output_key = f"shorts/{output_filename}"
    subtitle_filename = f"sub_{uuid.uuid4().hex[:8]}.ass"

    try:
        print("\n[1/5] Mengekstrak URL stream dari YouTube...")
        video_stream_url, audio_stream_url = ambil_direct_url_youtube(payload.youtube_url)

        print("\n[2/5] Transkripsi audio via Deepgram...")
        transkrip = dapatkan_transkrip_kata_cloud(audio_stream_url)

        if not transkrip:
            raise HTTPException(
                status_code=422,
                detail="Transkripsi gagal atau video tidak memiliki audio yang bisa dideteksi."
            )

        print("\n[3/5] Analisis hook viral via Gemini AI...")
        ai_analysis = cari_segmen_hook(transkrip)  # kirim transkrip penuh

        print("\n[3.5/5] Membuat file subtitle ASS...")
        buat_file_ass(
            words=transkrip,
            start_offset=ai_analysis["start_time"],
            output_path=subtitle_filename
        )

        print("\n[4/5] Memotong, crop, dan burn subtitle via FFmpeg...")
        proses_potong_video_cloud(
            video_stream_url=video_stream_url,
            audio_stream_url=audio_stream_url,
            output_filename=output_filename,
            start_time=ai_analysis["start_time"],
            end_time=ai_analysis["end_time"],
            subtitle_path=subtitle_filename
        )

        print("\n[5/5] Upload hasil ke Cloudflare R2...")
        cloud_download_url = upload_file_ke_r2(output_filename, r2_output_key)

        return {
            "status": "success",
            "message": "Clip berhasil dibuat dan siap diposting!",
            "ai_insights": {
                "hook_title": ai_analysis.get("hook_title"),
                "reason": ai_analysis.get("reason"),
                "start_time": ai_analysis.get("start_time"),
                "end_time": ai_analysis.get("end_time"),
                "duration_seconds": round(ai_analysis["end_time"] - ai_analysis["start_time"], 1)
            },
            "cloud_download_url": cloud_download_url
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(output_filename):
            os.remove(output_filename)
            print(f"File sementara '{output_filename}' dihapus.")
        if os.path.exists(subtitle_filename):
            os.remove(subtitle_filename)
            print(f"File subtitle '{subtitle_filename}' dihapus.")


@app.post("/api/v1/generate-clip-cloud")
async def generate_clip_cloud(payload: CloudClipRequest):
    output_filename = f"short_{uuid.uuid4().hex[:8]}.mp4"
    r2_output_key = f"shorts/hasil_{payload.r2_video_key}"

    try:
        video_url = dapatkan_url_durasi_terbatas(payload.r2_video_key)
        transkrip = dapatkan_transkrip_kata_cloud(video_url)
        ai_analysis = cari_segmen_hook(transkrip)

        proses_potong_video_cloud(
            video_stream_url=video_url,
            audio_stream_url=video_url,
            output_filename=output_filename,
            start_time=ai_analysis["start_time"],
            end_time=ai_analysis["end_time"]
        )

        cloud_short_url = upload_file_ke_r2(output_filename, r2_output_key)

        return {
            "status": "success",
            "message": "Pemrosesan cloud selesai dengan sukses!",
            "ai_insights": ai_analysis,
            "cloud_download_url": cloud_short_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(output_filename):
            os.remove(output_filename)


@app.get("/")
def root():
    return {"status": "online", "app": "KawanTech AI Video Clipper v2.0"}