const express = require('express');
const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

app.get('/download', (req, res) => {
    const videoUrl = req.query.url;

    if (!videoUrl) {
        return res.status(400).send('URL YouTube tidak boleh kosong.');
    }

    console.log(`[Cloud Engine] Memproses URL di Server: ${videoUrl}`);

    // Generate ID unik berbasis timestamp acak untuk mengisolasi proses I/O file temporer
    const uniqueJobId = `${Date.now()}_${Math.floor(Math.random() * 1000)}`;
    
    // Pola nama file: menaruh unique ID di depan nama file agar tidak bentrok di folder /tmp
    const outputTemplate = path.join('/tmp', `${uniqueJobId}_%(title)s.%(ext)s`);

    // Tambahkan flag --no-part untuk meminimalkan proses rename di Linux kontainer
    const command = `yt-dlp --extract-audio --audio-format mp3 --audio-quality 0 --embed-thumbnail --embed-metadata --no-part -o "${outputTemplate}" "${videoUrl}"`;

    exec(command, (error, stdout, stderr) => {
        if (error) {
            console.error('[Cloud Engine Error]:', error.message);
            // Tetap pastikan jika ada sisa file corrupt dengan prefix ID tersebut, langsung disapu bersih
            cleanUpFiles(uniqueJobId);
            return res.status(500).send('Server Cloud gagal memproses audio akibat benturan request.');
        }

        // Cari file asli hasil keluaran yt-dlp lewat log stdout
        const match = stdout.match(/Destination:\s(.*\.mp3)/);
        
        if (match && match[1]) {
            const filePath = match[1].trim();
            
            // Bersihkan nama file dari unique ID sebelum dilempar ke client agar namanya tetap rapi di lokal komputer user
            const rawFileName = path.basename(filePath);
            const cleanFileName = rawFileName.replace(`${uniqueJobId}_`, '');

            console.log(`[Cloud Sukses] File siap dikirim ke lokal Anda: ${cleanFileName}`);

            res.download(filePath, cleanFileName, (downloadErr) => {
                if (downloadErr) {
                    console.error('Koneksi download terputus (Client Aborted):', downloadErr.message);
                }
                // Hapus file matang di server kontainer setelah selesai dilempar
                if (fs.existsSync(filePath)) {
                    fs.unlink(filePath, (err) => { if (err) console.error(err); });
                }
            });
        } else {
            console.error('Gagal mendeteksi output file di stdout Cloud.');
            cleanUpFiles(uniqueJobId);
            res.status(500).send('Proses Cloud selesai, namun penulisan file terhambat.');
        }
    });
});

// Helper function untuk membersihkan file sampah jika proses di tengah jalan gagal/crash
function cleanUpFiles(jobId) {
    try {
        const files = fs.readdirSync('/tmp');
        files.forEach(file => {
            if (file.startsWith(jobId)) {
                fs.unlinkSync(path.join('/tmp', file));
            }
        });
    } catch (err) {
        console.error('Gagal menjalankan cleanup routine:', err.message);
    }
}

app.listen(PORT, () => {
    console.log(`🚀 Server Cloud aktif pada port ${PORT}`);
});