import os

# Warna ASS format: &HBBGGRR&
WARNA_PUTIH  = "&H00FFFFFF"
WARNA_KUNING = "&H0000FFFF"
WARNA_OUTLINE = "&H00000000"


def detik_ke_ass(detik: float) -> str:
    """Convert float detik ke format timestamp ASS: H:MM:SS.cc"""
    detik = max(0.0, detik)
    h  = int(detik // 3600)
    m  = int((detik % 3600) // 60)
    s  = int(detik % 60)
    cs = int((detik % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def buat_ass_header() -> str:
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 608
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def kelompokkan_kata_per_kalimat(words: list, maks_kata: int = 5) -> list:
    """
    Kelompokkan word timestamps menjadi kalimat pendek.
    Maks 5 kata per baris agar mudah dibaca.
    """
    kalimat = []
    i = 0
    while i < len(words):
        grup  = words[i:i + maks_kata]
        teks  = " ".join(w["word"] for w in grup)
        start = grup[0]["start"]
        end   = grup[-1]["end"]
        kalimat.append({"text": teks, "start": start, "end": end})
        i += maks_kata
    return kalimat


def buat_file_ass(
    words: list,
    start_offset: float,
    output_path: str,
    end_offset: float = None,
    maks_kata: int = 5
):
    """
    Buat file .ass dari word timestamps Deepgram.

    Parameter:
      words        : seluruh transkrip kata dari video asli
      start_offset : detik mulai clip di video asli
      end_offset   : detik akhir clip di video asli (opsional, untuk filter kata)
      output_path  : path file .ass output
      maks_kata    : jumlah kata per baris subtitle

    Fix utama:
      - Filter dulu hanya kata yang berada dalam rentang [start_offset, end_offset]
      - Baru normalisasi timestamp ke 0 dengan mengurangi start_offset
      - Subtitle dengan start < 0 setelah offset dibuang, bukan di-clamp ke 0
    """
    # ── Filter kata yang relevan untuk clip ini ────────────────────────
    batas_akhir = end_offset if end_offset is not None else float("inf")

    kata_clip = [
        w for w in words
        if w["end"] > start_offset and w["start"] < batas_akhir
    ]

    if not kata_clip:
        print(f"   [Subtitle] Tidak ada kata dalam rentang clip, file kosong dibuat.")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(buat_ass_header())
        return output_path

    print(f"   [Subtitle] {len(kata_clip)} kata dalam clip "
          f"[{start_offset:.1f}s → {batas_akhir:.1f}s]")

    # ── Kelompokkan kata menjadi baris subtitle ────────────────────────
    kalimat_list = kelompokkan_kata_per_kalimat(kata_clip, maks_kata)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(buat_ass_header())

        for i, kalimat in enumerate(kalimat_list):
            # Normalisasi waktu relatif ke awal clip
            start = round(kalimat["start"] - start_offset, 2)
            end   = round(kalimat["end"]   - start_offset, 2)

            # Buang subtitle yang masih bernilai negatif (seharusnya tidak ada
            # setelah filter di atas, tapi sebagai safety net)
            if end <= 0:
                continue
            start = max(0.0, start)

            # Pastikan durasi minimal 0.5 detik agar terbaca
            if end - start < 0.5:
                end = start + 0.5

            warna    = WARNA_PUTIH
            teks_ass = f"{{\\c{warna}&\\b1}}{kalimat['text']}"

            f.write(
                f"Dialogue: 0,{detik_ke_ass(start)},{detik_ke_ass(end)},"
                f"Default,,0,0,0,,{teks_ass}\n"
            )

    print(f"   [Subtitle] File ASS dibuat: {output_path} "
          f"({len(kalimat_list)} baris)")
    return output_path