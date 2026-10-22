# PDF Studio

Experimental self-hosted PDF editor built with Python, FastAPI, PyMuPDF, and vanilla JavaScript.

> Work in progress. Text editing can still change layout on some PDFs. Image editing only detects separately stored raster objects. Do not use the editor as your only copy of an important document.

Repository: https://github.com/designedbyjo/pdf-studio

## License

This project uses GNU AGPL-3.0. Keep the existing LICENSE file in the repository. Third-party dependencies retain their own licenses.

## Known issues and contribution priorities

- Preserve text appearance and table alignment when replacing text with different lengths.
- Improve detection of editable raster images and explain unsupported vector or flattened content.
- Add regression fixtures using synthetic documents only.
- Improve replacement-image aspect ratio handling.

Please report your operating system, Python version, steps to reproduce, and expected versus actual output. Attach a synthetic or anonymized PDF. Never submit salary slips, identity documents, credentials, or other private files.

## Version 2.3 usage

Web-based PDF editor yang berjalan dengan backend Python lokal. Semua perubahan di halaman bisa di-export menjadi PDF baru. Tidak perlu database atau akun.

## Install pada Windows

1. Install **Python 3.12** (boleh tetap menyimpan Python 3.15). Python 3.11 atau 3.13 juga diterima oleh launcher.
2. Ekstrak ZIP sepenuhnya ke folder baru, misalnya `C:\PDF-Studio-2.3`. Jangan campur dengan folder v2.2.
3. Tutup CMD aplikasi versi sebelumnya bila masih berjalan, kemudian klik dua kali `start-windows.bat`.
4. Pada pertama kali menjalankan, tunggu pip memasang dependency dan biarkan CMD tetap terbuka.
5. Buka **http://127.0.0.1:8000** di Chrome / Edge.
6. Jika masih melihat versi lama, tekan **Ctrl + Shift + R** agar cache browser diperbarui.

## Cara menggunakan

- Klik **Coba PDF contoh** untuk membuka dokumen uji dengan teks multi-kolom dan logo raster terpisah.
- **Teks** di toolbar: klik teks di atas halaman PDF, langsung ketik. Autosave setelah berhenti mengetik sekitar 1,25 detik. Edit lagi dengan klik teks di halaman yang sama. Escape membatalkan edit yang belum disimpan.
- **Gambar** di toolbar: gambar raster terpisah diberi garis tepi ketika mode aktif. Klik objek lalu **Ganti** (pilih PNG/JPG) atau **Hapus**. Replacement menjaga posisi dan ukuran kotak gambar asli.
- **Preview**: periksa halaman tanpa objek klik.
- **Organize**: ubah urutan, rotasi, duplikasi, hapus halaman, dan ekspor pilihan.
- **Combine**: tambah beberapa file PDF dan pilih **Export PDF** setelah selesai.
- **Undo/Redo**: gunakan toolbar atau Ctrl+Z / Ctrl+Y setelah edit tersimpan.

## Apa yang diperbaiki dari v2.2?

1. Edit sekarang memilih **fragmen kecil dalam satu baris asli**, bukan satu text block PyMuPDF. Blok PDF sering memuat dua kolom sekaligus, sehingga v2.2 menghapus atau menggeser nilai tabel. Versi ini menjaga baseline dan koordinat glyph lain.
2. Redaksi hanya menyentuh glyph dalam fragmen terpilih. Bila teks baru terlalu panjang untuk jarak sebelum kolom berikutnya, penyimpanan **ditolak**, bukan merusak kolom. Baris multiline tidak direflow otomatis ke elemen lainnya.
3. Deteksi image XObject dan inline raster image dengan posisi bounding box asli. Ada penggantian dan penghapusan objek gambar.
4. Gambar yang dipakai berulang kali di berbagai halaman mendapat perlakuan terpisah agar perubahan satu halaman tidak memengaruhi yang lain.
5. Semua fitur Organize/Combine sebelumnya tetap tersedia.

## Batasan teknis

- **Penting**: aplikasi tidak bisa menjamin bahwa setiap PDF akan bisa diedit tanpa perbedaan visual. PDF menyimpan instruksi menggambar teks, bukan paragraf semantik seperti Word. Font yang tidak tersedia diganti berdasarkan pengukuran lebar sehingga tampilannya mungkin sedikit berbeda.
- Perbaikan layout diuji memakai PDF sintetis yang menyerupai baris multi-kolom. **Belum diuji menggunakan file slip gaji asli**, karena yang tersedia hanya screenshot.
- Mode Gambar hanya memilih gambar raster tersimpan sebagai objek PDF. Logo yang berbentuk vektor, hasil flatten, atau menyatu dengan satu background foto tidak bisa langsung dipilih sebagai objek terpisah. Untuk gambar overlap kompleks yang tidak bisa dihapus secara aman, aplikasi menolak perubahan.
- Gambar pengganti mengikuti kotak ukuran lama dan bisa terdistorsi jika rasio aspek berbeda. Siapkan gambar baru dengan rasio sama.
- Tidak mendukung OCR dan edit paragraf mengalir lintas baris/halaman. Halaman rotated text bisa memerlukan implementasi terpisah.
- File disimpan sementara di RAM. **Ekspor sebelum menutup CMD**.
- Server default lokal, jangan expose ke internet tanpa autentikasi dan proteksi dokumen.
- Backend memakai PyMuPDF. Periksa [lisensi AGPL atau komersial](https://pymupdf.io/licensing) sebelum menjual produk tertutup.

## Uji developer

Install dependensi pengujian melalui `python -m pip install -r requirements-dev.txt`, kemudian jalankan `python -m unittest discover -s tests -v`.
