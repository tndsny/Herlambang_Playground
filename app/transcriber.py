import os
import subprocess
import uuid
from deepgram import DeepgramClient
from dotenv import load_dotenv
from app.storage import r2_client, BUCKET_NAME, dapatkan_url_durasi_terbatas

load_dotenv()

TEMP_DIR = "temp"

def dapatkan_transkrip_kata_cloud(audio_stream_url: str):
    print("====== [STEP 2] Memulai Transkripsi Cloud via Deepgram ======")

    deepgram = DeepgramClient()

    os.makedirs(TEMP_DIR, exist_ok=True)
    tmp_audio = os.path.join(TEMP_DIR, f"temp_audio_{uuid.uuid4().hex[:8]}.mp3")
    r2_audio_key = f"temp/{os.path.basename(tmp_audio)}"

    print("Mengekstrak audio via FFmpeg dan upload ke R2 sebagai relay...")

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", audio_stream_url,
        "-vn",          # no video
        "-ar", "16000", # sample rate 16kHz (optimal untuk speech recognition)
        "-ac", "1",     # mono
        "-b:a", "64k",  # bitrate rendah, cukup untuk speech
        "-f", "mp3",
        tmp_audio
    ]

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg gagal: {result.stderr[-300:]}")

    try:
        r2_client.upload_file(tmp_audio, BUCKET_NAME, r2_audio_key)

        audio_r2_url = dapatkan_url_durasi_terbatas(r2_audio_key, expires_in=600)

        print(f"Audio relay URL via R2 siap, mengirim ke Deepgram...")

        # Deepgram SDK v7.x — tanpa words=True, sudah otomatis included
        response = deepgram.listen.v1.media.transcribe_url(
            url=audio_r2_url,
            model="nova-2",
            language="id",
            smart_format=True,
            utterances=True,
        )

        words = response.results.channels[0].alternatives[0].words

        word_data = []
        for w in words:
            word_data.append({
                "word": w.word,
                "start": round(w.start, 2),
                "end": round(w.end, 2)
            })

        print(f"Transkripsi selesai. Berhasil mengekstrak {len(word_data)} kata.")
        return word_data

    finally:
        if os.path.exists(tmp_audio):
            os.remove(tmp_audio)
        try:
            r2_client.delete_object(Bucket=BUCKET_NAME, Key=r2_audio_key)
            print("File audio temp di R2 dihapus.")
        except Exception:
            pass