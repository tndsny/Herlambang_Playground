import yt_dlp

def ambil_direct_url_youtube(youtube_url: str) -> str:
    """Ambil URL video stream (untuk FFmpeg clipping)."""
    print(f"====== Mengekstrak Direct URL dari YouTube: {youtube_url} ======")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        if 'requested_formats' in info:
            video_url = info['requested_formats'][0]['url']   # video
            audio_url = info['requested_formats'][1]['url']   # audio
        else:
            video_url = info['url']
            audio_url = info['url']

    print("Direct URL berhasil didapat.")
    return video_url, audio_url  # return keduanya