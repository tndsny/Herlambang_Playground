import subprocess
import os
import uuid
import cv2
import mediapipe as mp
import numpy as np

TEMP_DIR = "temp"

# ──────────────────────────────────────────────
# FACE TRACKING — MediaPipe
# Crop 9:16 dinamis mengikuti aspect ratio sumber
# ──────────────────────────────────────────────

def _hitung_crop_916(frame_w: int, frame_h: int) -> tuple:
    """
    Hitung dimensi crop 9:16 secara dinamis dari resolusi video sumber.

    Tiga skenario:
      1. Portrait / square (h >= w)  → crop lebar ke 9:16, full tinggi
      2. Landscape normal AR <= 1.8  → full tinggi, lebar = h * 9/16
         (16:9, 4:3, 3:2, 1280x720, dll)
      3. Ultrawide AR > 1.8          → ambil separuh lebar, hitung tinggi 9:16
         (2:1 seperti 1280x640, 21:9, dll)

    Return: (crop_w, crop_h, crop_y, label)
      crop_y = offset vertikal bila crop area lebih pendek dari frame_h
    """
    ar = frame_w / frame_h

    if frame_h >= frame_w:
        # Portrait atau square
        crop_h = frame_h
        crop_w = min(int(frame_h * 9 / 16), frame_w)
        crop_y = 0
        label  = f"portrait ({frame_w}x{frame_h})"

    elif ar <= 1.8:
        # Landscape normal: 16:9, 4:3, 3:2
        crop_h = frame_h
        crop_w = min(int(frame_h * 9 / 16), frame_w)
        crop_y = 0
        label  = f"landscape ({frame_w}x{frame_h}, AR={ar:.2f})"

    else:
        # Ultrawide: 2:1, 21:9, dsb — contoh: 1280x640
        # Pakai separuh lebar frame sebagai crop_w
        crop_w = frame_w // 2
        crop_h = int(crop_w * 16 / 9)
        if crop_h > frame_h:
            # Tinggi melebihi frame, clamp dan sesuaikan lebar
            crop_h = frame_h
            crop_w = int(frame_h * 9 / 16)
        # Vertikal center
        crop_y = (frame_h - crop_h) // 2
        label  = f"ultrawide ({frame_w}x{frame_h}, AR={ar:.2f})"

    return crop_w, crop_h, crop_y, label


def _cari_crop_x_wajah(video_path: str, max_samples: int = 30) -> dict | None:
    """
    Scan sejumlah frame secara merata, deteksi wajah dengan MediaPipe,
    kembalikan dict parameter crop siap pakai FFmpeg.
    Semua dimensi dihitung dinamis dari resolusi video sumber.
    """
    print("   [FaceTrack] Membuka video untuk analisis wajah...")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"[FaceTrack] Tidak bisa membuka video: {video_path}")

    frame_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    crop_w, crop_h, crop_y, ar_label = _hitung_crop_916(frame_w, frame_h)

    print(f"   [FaceTrack] Resolusi sumber  : {frame_w}x{frame_h} (AR {frame_w/frame_h:.2f}:1)")
    print(f"   [FaceTrack] Layout terdeteksi: {ar_label}")
    print(f"   [FaceTrack] Target crop      : {crop_w}x{crop_h} y={crop_y} → scale 1080x1920")
    print(f"   [FaceTrack] Total frame      : {total_frames}")

    # Pilih indeks frame tersebar merata
    if total_frames <= max_samples:
        sample_indices = list(range(total_frames))
    else:
        step = total_frames / max_samples
        sample_indices = [int(i * step) for i in range(max_samples)]

    mp_face  = mp.solutions.face_detection
    detector = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.4)

    cx_list = []

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue

        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hasil = detector.process(rgb)

        if hasil.detections:
            # Pilih wajah terbesar bila ada lebih dari 1
            best = max(
                hasil.detections,
                key=lambda d: (
                    d.location_data.relative_bounding_box.width *
                    d.location_data.relative_bounding_box.height
                )
            )
            bb = best.location_data.relative_bounding_box
            # cx dalam piksel absolut
            cx = (bb.xmin + bb.width / 2) * frame_w
            cx_list.append(cx)

    cap.release()
    detector.close()

    if not cx_list:
        print("   [FaceTrack] Wajah tidak terdeteksi di semua frame sample.")
        return None

    # Median cx — tahan outlier
    cx_median = float(np.median(cx_list))

    # Hitung crop_x, clamp agar tidak keluar batas frame
    crop_x = cx_median - crop_w / 2
    crop_x = max(0.0, min(float(frame_w - crop_w), crop_x))
    crop_x = int(round(crop_x))

    detected_pct = int(100 * len(cx_list) / len(sample_indices))
    print(f"   [FaceTrack] Deteksi wajah   : {len(cx_list)}/{len(sample_indices)} frame ({detected_pct}%)")
    print(f"   [FaceTrack] Posisi wajah cx : {cx_median:.0f}px dari {frame_w}px total lebar")
    print(f"   [FaceTrack] Crop final      : x={crop_x}, y={crop_y}, w={crop_w}, h={crop_h}")

    return {
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "frame_w": frame_w,
        "frame_h": frame_h,
    }


# ──────────────────────────────────────────────
# FUNGSI UTAMA CLIPPER
# ──────────────────────────────────────────────

def proses_potong_video_cloud(
    video_stream_url: str,
    audio_stream_url: str,
    output_filename: str,
    start_time: float,
    end_time: float,
    subtitle_path: str = None,
    face_tracking: bool = True,
    max_samples: int = 30
):
    print(f"====== [STEP 3] Memotong Video dari Detik {start_time} ke {end_time} ======")
    print(f"   Mode: {'Face Tracking — MediaPipe ✓' if face_tracking else 'Static Center Crop'}")

    os.makedirs(TEMP_DIR, exist_ok=True)

    durasi    = end_time - start_time
    uid       = uuid.uuid4().hex[:8]
    tmp_video = os.path.join(TEMP_DIR, f"tmp_video_{uid}.mp4")
    tmp_audio = os.path.join(TEMP_DIR, f"tmp_audio_{uid}.m4a")

    try:
        # ── STEP A: Download segmen video ──────────────────────────────
        buffer = 2
        print(f"Mendownload segmen video lokal ke {tmp_video} ...")
        dl_video = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", video_stream_url,
            "-t", str(durasi + buffer),
            "-c", "copy",
            tmp_video
        ], capture_output=True, text=True)

        if dl_video.returncode != 0:
            print(f"[FFmpeg download video stderr]\n{dl_video.stderr[-1000:]}")
            raise RuntimeError(f"Download video gagal: {dl_video.stderr[-300:]}")

        # ── STEP B: Download segmen audio ──────────────────────────────
        print(f"Mendownload segmen audio lokal ke {tmp_audio} ...")
        dl_audio = subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", audio_stream_url,
            "-t", str(durasi + buffer),
            "-c", "copy",
            tmp_audio
        ], capture_output=True, text=True)

        if dl_audio.returncode != 0:
            print(f"[FFmpeg download audio stderr]\n{dl_audio.stderr[-1000:]}")
            raise RuntimeError(f"Download audio gagal: {dl_audio.stderr[-300:]}")

        # ── STEP C: Tentukan crop filter ───────────────────────────────
        crop_filter = None

        if face_tracking:
            print("\n   [FaceTrack] Memulai analisis posisi wajah...")
            try:
                hasil = _cari_crop_x_wajah(tmp_video, max_samples)
                if hasil:
                    cx = hasil["crop_x"]
                    cy = hasil["crop_y"]
                    cw = hasil["crop_w"]
                    ch = hasil["crop_h"]
                    # crop=w:h:x:y lalu scale ke 1080x1920
                    crop_filter = f"crop={cw}:{ch}:{cx}:{cy},scale=1080:1920"
                    print(f"   [FaceTrack] ✓ Filter: {crop_filter}")
                else:
                    print("   [FaceTrack] Fallback ke center crop dinamis.")
            except Exception as e:
                print(f"   [FaceTrack] WARNING: {e} — fallback ke center crop dinamis.")

        if crop_filter is None:
            # Fallback: center crop dinamis menggunakan ekspresi FFmpeg
            # iw/ih = lebar/tinggi frame asli, dihitung otomatis oleh FFmpeg
            # Untuk semua aspect ratio: ambil area 9:16 dari tengah frame
            crop_filter = (
                "crop=if(gt(iw/ih\\,1.8)\\,iw/2\\,ih*9/16)"
                ":if(gt(iw/ih\\,1.8)\\,ih*8/9\\,ih)"
                ":if(gt(iw/ih\\,1.8)\\,(iw-iw/2)/2\\,(iw-ih*9/16)/2)"
                ":if(gt(iw/ih\\,1.8)\\,(ih-ih*8/9)/2\\,0)"
                ",scale=1080:1920"
            )
            print(f"   Center crop filter (dinamis): {crop_filter}")

        # ── STEP D: Tambahkan subtitle bila ada ────────────────────────
        if subtitle_path and os.path.exists(subtitle_path):
            sub_path  = subtitle_path.replace("\\", "/").replace(":", "\\:")
            vf_filter = f"{crop_filter},subtitles={sub_path}"
            print(f"Subtitle akan di-burn dari: {subtitle_path}")
        else:
            vf_filter = crop_filter

        # ── STEP E: Encode final via FFmpeg ────────────────────────────
        # Fade out video + audio di 1.5 detik terakhir
        # agar clip terasa selesai natural, tidak terpotong tiba-tiba
        fade_durasi = 1.5
        fade_start  = max(0.0, durasi - fade_durasi)
        vf_filter_final = f"{vf_filter},fade=t=out:st={fade_start:.2f}:d={fade_durasi}"
        af_filter       = f"afade=t=out:st={fade_start:.2f}:d={fade_durasi}"

        print("\nMemotong dan encode dari file lokal...")
        print(f"   Fade out: mulai {fade_start:.1f}s, durasi {fade_durasi}s")
        command = [
            "ffmpeg", "-y",
            "-i", tmp_video,
            "-i", tmp_audio,
            "-t", str(durasi),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", vf_filter_final,
            "-af", af_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-threads", "4",
            output_filename
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        print(f"[FFmpeg encode stderr]\n{result.stderr[-1000:]}")

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg encode gagal dengan kode {result.returncode}:\n{result.stderr[-500:]}"
            )

        if os.path.exists(output_filename):
            size = os.path.getsize(output_filename)
            print(f"Output file: {output_filename} | Ukuran: {size} bytes")
            if size < 10000:
                raise RuntimeError(
                    f"Output file terlalu kecil ({size} bytes) — video stream gagal dibaca."
                )
        else:
            raise RuntimeError("Output file tidak ditemukan setelah FFmpeg selesai.")

        print(f"====== Pemotongan Klip Video Selesai: {output_filename} ======")

    finally:
        for f in [tmp_video, tmp_audio]:
            if f and os.path.exists(f):
                os.remove(f)
                print(f"File temp '{f}' dihapus.")