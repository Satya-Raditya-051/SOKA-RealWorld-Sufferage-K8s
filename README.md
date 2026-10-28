# SOKA: Real-World Sufferage di Kubernetes

Proyek ini menjalankan tugas pemrosesan CPU dan payload yang saling independen
pada empat Pod worker Kubernetes yang heterogen. Proyek ini membandingkan
heuristik Sufferage dynamic-batch tahun 1999, heuristik CCTSA tahun 2019, dan
Round Robin tanpa CloudSim, jeda buatan, pembatasan payload, atau waktu
penyelesaian yang direkayasa.

## Topologi

Kind membuat satu node control-plane dan dua node worker logis. Empat Pod
worker ditempatkan secara tetap, masing-masing dua Pod per node worker:

| Worker | Node logis | Batas CPU | NodePort |
| --- | --- | ---: | ---: |
| `vm-1-small` | `host-1` | 250m | 30081 |
| `vm-2-medium` | `host-1` | 500m | 30082 |
| `vm-3-large` | `host-2` | 1000m | 30083 |
| `vm-4-xlarge` | `host-2` | 1500m | 30084 |

Node Kind merupakan container yang berjalan pada satu mesin fisik. Nama
`host-*` dan `vm-*` adalah kontrak proyek, bukan pernyataan bahwa keduanya
merupakan host fisik atau mesin virtual perangkat keras yang terpisah.
Manifes tetap portabel untuk cluster Kubernetes dengan banyak host.

## Persiapan

Prasyaratnya adalah Linux, Docker Engine atau Docker Desktop dengan daemon
Docker yang berfungsi, minimal empat CPU logis, RAM 4 GiB, cgroup v2, dan
`curl`.

Pasang alat Kubernetes yang versinya dikunci dan checksum-nya telah
diverifikasi:

```bash
./scripts/install_k8s_tools.sh
export PATH="$HOME/.local/bin:$PATH"
```

Buat cluster, bangun image worker, dan terapkan keempat Pod:

```bash
./scripts/setup_cluster.sh
```

Proses persiapan menggunakan kind v0.33.0, Kubernetes v1.37.0 beserta digest
rilisnya, dan kubectl v1.37.1. Gunakan `--recreate` hanya ketika cluster proyek
perlu dihapus dan dibuat ulang menggunakan image node yang telah dikunci.

## Tolok ukur

Jalankan tiga percobaan untuk kedua dataset:

```bash
python3 run_benchmark.py
```

Untuk demonstrasi singkat:

```bash
python3 run_benchmark.py --scenario paper --trials 1
```

Runner melakukan pemanasan dan kalibrasi tersinkronisasi, merotasi urutan
algoritma di antara percobaan, mengirim satu antrean serial per worker secara
bersamaan, serta menulis alokasi mentah dan ringkasan statistik ke
`results/realworld_summary.json`.

Opsi yang berguna:

```bash
python3 run_benchmark.py --scenario gocj --trials 5
python3 run_benchmark.py --algorithms sufferage round-robin --trials 5
python3 run_benchmark.py --help
```

Tidak ada percobaan ulang otomatis selama percobaan yang diukur. Kegagalan
worker atau checksum membatalkan percobaan sehingga kegagalan tersebut tidak
tersembunyi di dalam hasil pengukuran waktunya.

## Beban kerja dan prediksi

Skenario paper menggunakan dataset sepuluh tugas yang sama persis dengan Tabel
II dari Krishnaveni dkk., termasuk ukuran data dalam megabit. Broker mentransfer
payload tersebut secara utuh sebagai badan permintaan HTTP.

Skenario GoCJ menggunakan 24 baris pertama dari `GoCJ_Dataset_100.txt` yang
telah dipublikasikan, sesuai urutan pada sumber. GoCJ memuat nilai MI pekerjaan,
tetapi tidak memuat ukuran data per pekerjaan sehingga tugasnya hanya
menggunakan CPU. Rincian atribusi dan lisensi tersedia di `data/README.md`.

MI sumber tetap digunakan sebagai metadata penelitian. Setiap skenario
memetakan MI secara proporsional ke jumlah iterasi PBKDF2 yang telah ditentukan.
Dua thread worker PBKDF2 OpenSSL memungkinkan Pod 1500m menggunakan lebih dari
satu core CPU. Hal ini diperlukan karena kedua paper menggunakan skala MI yang
tidak kompatibel; mekanisme ini bukan pembatas saat runtime. Seluruh iterasi
terjadwal dan seluruh byte payload tetap diproses. Tugas executable yang sama
digunakan oleh ketiga algoritma.

Sebelum penjadwalan, setiap Pod diukur berulang kali. Median laju kerja CPU dan
laju payload efektif menentukan:

```text
ETC(task, worker) = cpu_work / measured_cpu_rate
                  + input_mbit / measured_payload_rate
```

Nilai MIPS dan Mbps yang dikonfigurasi tetap menjadi metadata paper. Batas CPU
Kubernetes merupakan batas cgroup yang nyata; field bandwidth nominal tidak
disajikan secara keliru sebagai pembatasan jaringan yang benar-benar diterapkan.

## Algoritma

- Standard Sufferage mengikuti Gambar 2 dari Maheswaran dkk. Setiap putaran
  dapat menetapkan satu pemenang untuk setiap worker yang tersedia. Worker yang
  diperebutkan mempertahankan tugas dengan nilai completion-time sufferage yang
  lebih besar; jika nilainya sama, tugas yang telah terpilih dipertahankan.
- CCTSA mengikuti pemindaian tugas menurun dan predikat `SVCT`/`SVC` yang
  dipublikasikan. Tugas terpilih diberikan kepada worker dengan waktu
  penyelesaian minimum. Biaya penyelesaian hanya memecahkan kondisi waktu yang
  benar-benar sama karena paper tidak mendefinisikan frasa "cost suitable."
- Round Robin menetapkan tugas secara siklik sesuai urutan dataset.

Skor VM berbobot yang dinormalisasi dan fallback combined-sufferage dari
rancangan PRD lama sengaja tidak digunakan karena tidak terdapat dalam paper
CCTSA. Biaya 21,30 yang dilaporkan paper tersebut juga tidak dapat direproduksi
dari rumus `MI * cost_rate` yang dinyatakan; keluaran tolok ukur melabeli nilai
ini sebagai biaya termodelkan, bukan pengeluaran infrastruktur yang sebenarnya.

## Metrik

Setiap percobaan mencatat makespan prediksi dan aktual, throughput tugas,
throughput payload efektif, biaya termodelkan, waktu tunggu antrean broker,
waktu tunggu worker, okupansi antrean logis, utilisasi kapasitas CPU cgroup,
throttling cgroup, derajat ketidakseimbangan, MAE/RMSE prediksi, sampel kalibrasi
mentah, checksum tugas, dan metadata lingkungan.

Heuristik tidak harus mengungguli Round Robin pada setiap metrik. Worker yang
lebih cepat juga memiliki tarif biaya paper yang lebih tinggi, sehingga
makespan yang lebih rendah dapat secara wajar memiliki biaya termodelkan yang
lebih tinggi.

## Pengujian

Jalankan rangkaian pengujian unit dan integrasi loopback yang tidak memerlukan
dependensi tambahan:

```bash
python3 -m unittest discover -s tests -v
```

Saat cluster sedang berjalan, sertakan pemeriksaan topologi dan eksekusi nyata:

```bash
SOKA_RUN_K8S_TESTS=1 python3 -m unittest tests.test_k8s_end_to_end -v
```

Rangkaian pengujian algoritma mencakup matriks asli Tabel 3 Maheswaran dan
memverifikasi pemetaan Sufferage yang dipublikasikan dengan makespan 78.

## Eksekusi terverifikasi

Lima percobaan dengan urutan yang dirotasi telah diselesaikan pada 28 Oktober
2026. Hasil median:

| Skenario | Algoritma | Makespan (dtk) | Tugas/dtk | Biaya termodelkan | Kapasitas CPU | Ketidakseimbangan |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Paper 10 | CCTSA | 2.814 | 3.554 | 290.65 | 86.43% | 0.666 |
| Paper 10 | Standard Sufferage | 2.922 | 3.422 | 280.39 | 84.73% | 1.042 |
| Paper 10 | Round Robin | 12.014 | 0.832 | 167.17 | 19.96% | 2.470 |
| GoCJ 24 | CCTSA | 7.647 | 3.138 | 761025 | 90.74% | 0.307 |
| GoCJ 24 | Standard Sufferage | 7.278 | 3.297 | 762130 | 95.63% | 0.250 |
| GoCJ 24 | Round Robin | 15.452 | 1.553 | 596200 | 44.21% | 1.256 |

Hasil dapat berbeda tergantung pada mesin dan beban proses latar belakang. File
hasil lokal mentah merupakan keluaran yang dihasilkan dan sengaja diabaikan
oleh Git.

## Referensi utama

- Maheswaran et al., *Dynamic Mapping of a Class of Independent Tasks onto
  Heterogeneous Computing Systems*, JPDC 1999.
- Krishnaveni et al., *Cost and Completion Time based Sufferage Algorithm for
  Task Scheduling in Cloud Environment*, IJRECE 2019.
- Hussain and Aleem, *GoCJ: Google Cloud Jobs Dataset for Distributed and Cloud
  Computing Infrastructures*, Data 2018, DOI 10.3390/data3040038.
