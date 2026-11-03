# Audit teknis: bootstrap dan peta memori HMBTN

Tanggal audit: 4 November 2026
Repository: `YudhaPratamaPutra/hmbtn-decomp-4Clovers`
Branch sumber yang diaudit: `main`
HEAD sumber: `b3725735a677da0de9360b32acef1736bfd0f90e`

## Status dan jejak build

Build penuh `cmake --build build --target check` berhasil pada GitHub Actions run [41705758920](https://github.com/YudhaPratamaPutra/hmbtn-decomp-4Clovers/actions/runs/41705758920). Disc dari release `Disc` lolos pemeriksaan SHA-256 sebelum diekstrak. Run build PR reguler [41705758987](https://github.com/YudhaPratamaPutra/hmbtn-decomp-4Clovers/actions/runs/41705758987) juga berhasil.

Artefak linker di runner:
- `build/program.map`: 303.484 byte, SHA-256 `c1e04157942507555e2763724b733f654b00cd3e082b405f142b045e10a29fcd`
- `build/program.ld`: 10.538 byte, SHA-256 `f56512c7fb10713e3ddf14e850e61aa97ba4ad97291987c4d89076f9bd8dd3bd`
- `build/program.elf`: 3.347.868 byte, SHA-256 `78679eacde7e049964065cc0a44ff8901270e3bd39cf5fa826f20fa66ccd9c72`
- `build/SLUS_011.15`: 323.584 byte, SHA-256 `34e3b35dcd3fb1cd9a7d4813b8a9ef987915826e3d436f1908ecbe2d4fdf1444`
- `build/original/disc/SYSTEM.CNF`: 69 byte, SHA-256 `a35823aeec31790d68e384429a5582300c73ec2ee822e7cf64cb29ec1c799ef2`

GitHub menolak unggahan artifact pada run pertama karena kuota penyimpanan artifact repository penuh. Tidak ada artifact lama yang dihapus. Untuk menghindari kuota artifact, workflow audit berikutnya mencetak seluruh map ke job log. Peta lengkap kemudian dipulihkan dari log run [41706697213](https://github.com/YudhaPratamaPutra/hmbtn-decomp-4Clovers/actions/runs/41706697213) dan disimpan di repository sebagai [`logs/audit/program.map`](program.map).

Verifikasi file yang tersimpan:
- ukuran: 303.484 byte;
- SHA-256: `c1e04157942507555e2763724b733f654b00cd3e082b405f142b045e10a29fcd`;
- hasil round-trip setelah disimpan dan dibaca kembali: identik byte-for-byte dengan teks map dari job log.

Artifact ZIP Actions tetap tidak tersedia karena kuota repository. Namun file peta lengkap kini disimpan langsung di branch audit, dan hash-nya cocok dengan fingerprint map yang dicatat pada build penuh sebelumnya.

## SYSTEM.CNF asli

Isi yang diekstrak langsung dari disc original:

```text
BOOT = cdrom:\\SLUS_011.15;1
TCB = 4
EVENT = 10
STACK = 801fff00
```

Catatan: karakter pada BOOT setelah `cdrom:` berjumlah **dua backslash literal** pada file hasil ekstraksi (bukan satu). Jangan menormalkan atau menggantinya sebelum ada uji boot yang membuktikan perilakunya. `TCB`, `EVENT`, dan `STACK` harus dipertahankan ketika merancang bootstrap.

Nilai stack pada `SYSTEM.CNF` adalah `0x801FFF00`, sedangkan deklarasi executable di root `CMakeLists.txt` menggunakan `STACK 0x801FFFF0` untuk header PS-X EXE. Perbedaan 0xF0 ini harus ditangani secara eksplisit saat menjalankan executable original melalui BIOS `Load` + `Exec`; jangan mengasumsikan jalur tersebut identik dengan boot BIOS biasa.

## Linker map dan simbol

Alamat wilayah dari `program.map`:
- `overlay_low = 0x800B7E20`
- `overlay_high = 0x8012DDE8`

Layout ELF (`mips-linux-gnu-objdump -h`):
- `.main`: VMA `0x80010000`, ukuran `0x4E800`
- `.bss`: VMA `0x8005E374`, ukuran `0x59AAC`, berakhir tepat di `0x800B7E20`
- `.11_GF_FARM`: VMA `0x800B7E20`, ukuran hasil sektor `0x76000`, ujung hasil rounded `0x8012DE20`
- `.15_saveload`: VMA `0x8012DDE8`, ukuran `0x18000`, ujung `0x80145DE8`
- `.30_GF_swind`: VMA `0x8012DDE8`, ukuran `0x7000`, ujung `0x80134DE8`

Perbedaan `0x38` antara `overlay_high` dan ujung image FARM yang dibulatkan ke sektor adalah akibat ukuran anggota A_FILE yang dibulatkan; `farm_area.loadWindow` dihitung sesudah ukuran low overlay dibulatkan. Ini bukan ruang yang boleh otomatis dialokasikan.

Alamat simbol dari tabel linker dan `mips-linux-gnu-nm -n`:
- `main_run_frame`: `0x80011C24` (simbol lokal)
- `main_region_free_bytes`: `0x8001205C`
- `main_region_free_start`: `0x80012098`
- `main_get_region_base`: `0x800120BC`
- `farm_state_init`: `0x80021DA8`
- `farm_load_hook`: `0x800BD5A0`
- `weather_frame_update_hook`: `0x800BFEF8`
- `farm_mode_tick`: `0x800C14A0`

Alamat simbol ini berlaku untuk image/overlay yang sedang dilink pada build ini. Fungsi di overlay FARM hanya dapat dipanggil ketika overlay `11_GF_FARM` berada di `overlay_low`.

## Batas RAM yang diturunkan dari source dan map

Konstanta dan struktur aktual:
- `WORK_REGION = 0x801BE1B0`; `region_base` ditetapkan ke alamat tersebut.
- `REGION_BYTES = 0x3EE50`; frame work area mencapai `0x801FC000`.
- `FARM_IMAGE_SIZE = 0x49000`.
- Selisih `overlay_high - overlay_low = 0x75FC8`, dibulatkan ke `0x76000`.
- `farm_area.loadWindow = 0x8012DE20`.
- `farm_area.sectionBuffer = 0x80176E20`.

Tabel `farm_section_table.h` berisi 255 section. Section terbesar berukuran `0x39800` (rentang offset file `0x735800..0x76F000`). Batas akhir section sebesar itu di RAM adalah:

`0x80176E20 + 0x39800 = 0x801B0620`

Jarak dari batas tersebut ke `region_base`:

`0x801BE1B0 - 0x801B0620 = 0xDB90` (56.720 byte).

Angka `0xDB90` adalah ruang kerja sementara yang dihitung game, **bukan ruang resident yang kosong**.

Ada dua pemakai penting:
1. `event_script.c` memakai `main_region_free_start()` untuk pembacaan event script asynchronous.
2. `vram_stash_block()` menyimpan ekor data gambar VRAM di bawah `region_base`.

`InputDemo` diletakkan pada `region_base - sizeof(InputDemo)`; dengan ukuran struktur 0x1008, alamat awalnya `0x801BD1A8`. Rentang dari akhir section maksimum sampai awal InputDemo adalah `0xCB88`. Dari 451 ukuran event-script, ukuran terbesar yang memenuhi syarat `size < main_region_free_bytes()` saat ini adalah `0xC800`; masih ada margin `0x388` sebelum InputDemo. Script yang lebih besar memakai jalur buffer primitive sebagai fallback.

Untuk data VRAM:
- `vram_stash_rect = {320, 0, 128, 255}`, ukuran gambar `0xFF00` byte.
- Offset akhir tabel chunk `vram_chunk_offsets[50] = 0x120E8`.
- Ekor yang disimpan di RAM: `0x120E8 - 0xFF00 = 0x21E8`.
- Alamat awal tail maksimum: `0x801BE1B0 - 0x21E8 = 0x801BBFC8`.

`event_map_upload()` tidak menjalankan stash selama `GLOBAL_FLAG_DEMO_START` atau `GLOBAL_FLAG_INPUT_REPLAY`, dan juga mensyaratkan tidak ada request yang sibuk. Ini menunjukkan kepemilikan memori tersebut bersifat temporal. Jangan menaruh mod resident di sana tanpa allocator/hook yang mengatur ulang batas buffer dan menjaga kondisi penggunaan aslinya.

## Implikasi untuk bootstrap dan runtime mod

1. Mempertahankan byte executable `SLUS_011.15` dan anggota A_FILE original tetap merupakan arah yang layak.
2. Untuk menjalankan kode sebelum game, CD harus mem-boot executable bootstrap melalui `SYSTEM.CNF`; berarti file konfigurasi boot berubah, sementara binary game original tetap bisa dipertahankan.
3. Dokumentasi BIOS PS1 membedakan `Load` + `Exec` dari `LoadExec`: pasangan `Load`/`Exec` memuat executable dan menjalankannya, sedangkan `LoadExec` mencoba memulai ulang boot executable setelah child kembali. Untuk bootstrap yang perlu menyerahkan kontrol ke SLUS original, `Load` + `Exec` adalah jalur yang perlu diuji terlebih dahulu, bukan `LoadExec`.
4. Alamat `0x801B0620..0x801BE1B0` belum boleh ditetapkan sebagai RAM mod. Sebagian dipakai sebagai buffer event, tail VRAM, dan InputDemo. Kandidat resident harus dipilih dengan memesan blok terpisah lalu membatasi `main_region_free_start()` / `main_region_free_bytes()` atau membuat mekanisme yang setara, tanpa mengubah layout data original. Ukuran dan alamat final menunggu verifikasi seluruh jalur akses serta uji runtime.
5. Bootstrap wajib memverifikasi rentang tujuan, ukuran PS-X EXE, entry point, stack, flush cache, dan alamat yang ditulis. Linker map, alamat simbol, serta hasil binary harus dibandingkan sebelum dan sesudah patch.

Referensi:
- [CMakeLists.txt](../../CMakeLists.txt)
- [program linker rules](../../cmake/psx.cmake)
- [main runtime](../../src/main/main.c)
- [farm state layout](../../src/main/game/farm_state.h)
- [farm state initialization](../../src/main/game/farm_state.c)
- [event script memory users](../../src/overlay/11_GF_FARM/event/event_script.c)
- [farm section table](../../src/overlay/common/farm_section_table.h)
- [BIOS File Execute and Flush Cache: Load, Exec, LoadExec](https://psx-spx.consoledev.net/dev/ps1/kernelbios/file-execute-and-flush-cache/)
- [SYSTEM.CNF and PS-X EXE format](https://psx-spx.consoledev.net/dev/ps1/cdr/cdromfileformats/executables/)



## Audit lanjutan: rentang heap PSY-Q (bukti ELF)

Workflow audit run [41708709984](https://github.com/YudhaPratamaPutra/hmbtn-decomp-4Clovers/actions/runs/41708709984) berhasil membaca nilai data langsung dari `program.elf`:

```text
.data 0x8005648c:
  bytes 00 80 00 00  -> _stacksize = 0x00008000
  bytes 00 00 80 00  -> _ramsize   = 0x00800000
```

Catatan: startup `2mbyte.o` tidak mengambil ukuran RAM dari `_ramsize` pada word kedua tersebut. Disassembly menunjukkan nilai `0x00200000` dibaca dari konstanta di dalam startup stub. Nilai ini kemudian dikurangi `_stacksize` dan alamat fisik `overlay_low` untuk menentukan ukuran heap.

Input yang diberikan startup kepada `InitHeap`:
- heap base: `0x800B7E24` (`overlay_low + 4`);
- heap length: `0x00200000 - 0x00008000 - 0x000B7E20 = 0x001401E0`;
- batas nominal akhir: `0x801F8004`.

Karena `InitHeap` menginisialisasi heap BIOS, seluruh alamat di dalam rentang itu berpotensi dialokasikan oleh pemanggil `malloc/calloc/realloc/free`. Dokumentasi kernel PS1 menjelaskan `InitHeap` sebagai penetap rentang heap BIOS, sedangkan dokumentasi Psy-Q memisahkan tiga sistem `malloc`, `malloc2`, dan `malloc3` beserta fungsi inisialisasinya. Rujukan: [PS1 BIOS memory allocation](https://psx-spx.consoledev.net/ps1/kernelbios/memory-allocation/) dan [Psy-Q Run-Time Library Overview, halaman 2-23](https://psx.arthus.net/sdk/Psy-Q/DOCS/LIBOVR46.PDF).

Pemeriksaan terhadap seluruh teks `program.map` untuk simbol `malloc`, `calloc`, `realloc`, `free`, `qsort`, `InitHeap2/3`, dan `malloc2/3` hanya menemukan `InitHeap`. Ini indikasi baik bahwa binary original hanya menginisialisasi heap dan tidak menautkan konsumen alokasi yang terlihat. Namun, itu belum membuktikan semua jalur BIOS/library tidak pernah mengalokasikan memori secara tidak langsung; klaim aman tetap menunggu pemeriksaan instruksi dan uji runtime.

### Contoh skema reservasi yang sedang diuji (belum diterapkan)

Untuk menghindari akhir section FARM terbesar (`0x801B0620`) secara rapat, satu kandidat layout audit adalah:

| Batas | Alamat |
|---|---:|
| Akhir section FARM terbesar | `0x801B0620` |
| Guard | `0x9E0` |
| Awal blok runtime kandidat | `0x801B1000` |
| Akhir blok runtime 8 KiB | `0x801B3000` |
| Buffer sementara baru (calon) | `0x801B3000` |
| Awal InputDemo | `0x801BD1A8` |

Jika heap dipotong tepat di `0x801B1000`, ukuran heap baru dari `0x800B7E24` adalah `0xF91DC`. Berdasarkan formula startup, nilai `_stacksize` yang menghasilkan batas tersebut adalah `0x4F004` (dibanding nilai original `0x8000`). Perhitungan ini mengubah **batas heap saja**, bukan nilai awal SP yang berasal dari konstanta 2 MiB / header PS-X EXE.

Jika buffer sementara digeser dari `0x801B0620` ke `0x801B3000`, total pengurangan pada `main_region_free_bytes()` adalah `0x29E0` (guard + runtime block). Batas buffer sementara menjadi `0xB1B0` byte. Dari 451 ukuran event script yang tercatat di source, 391 akan tetap memenuhi syarat `size < main_region_free_bytes()`; 60 menggunakan jalur fallback. Saat ini 401 script memenuhi jalur asynchronous, sehingga contoh blok 8 KiB + guard mengubah jalur 10 script tambahan.

Angka di atas adalah simulasi aritmetika dari ELF/map dan tabel event yang ada, bukan pilihan akhir atau uji runtime. Ukuran 8 KiB hanya contoh untuk membuktikan metode reservasi; ukuran runtime final belum ditentukan.

### Dua titik patch yang harus diverifikasi sebelum implementasi

1. Startup stub membaca `_stacksize`, menghitung ukuran heap, lalu memanggil `InitHeap`. Kita harus memeriksa disassembly persis dari callsite dan delay slot. Kandidat metode adalah trampoline runtime pada pemanggilan `InitHeap` yang hanya mengurangi ukuran heap; tidak boleh menggeser `.main`, BSS, `game_state`, `farm_area`, atau overlay.
2. `main_region_free_bytes()` menentukan ukuran buffer bersama, dan `main_region_free_start()` mengembalikan awalnya. Keduanya harus diperiksa pada level instruksi sebelum memilih patch. Tujuannya hanya menggeser buffer temporary setelah blok runtime; struktur data dan buffer original tidak boleh diubah.

Workflow audit berikutnya merekam disassembly `InitHeap`, startup heap-argument calculation, `main_region_free_bytes`, dan `main_region_free_start` dari ELF build yang sama. Sampai hasil itu diperiksa dan diuji, `0x801B1000` tetap kandidat, bukan alamat runtime yang disetujui.

## Batas audit ini

Belum dilakukan:
- uji runtime bootstrap pada emulator atau hardware;
- patch BIOS/EXE;
- pengujian integrasi modul mod;
- pengukuran stack high-water mark;
- pembuktian bahwa semua jalur event/VRAM tidak mengakses blok kandidat dalam semua scene.

Tidak ada file C original, struktur data original, linker region, atau binary original yang diubah pada tahap audit ini.
