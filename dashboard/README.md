# Dashboard Web Live (Demo 3)

Dashboard visual untuk *live demo* Kelompok 4 — menjembatani hasil benchmark
nyata di cluster `soka-datacenter` dengan tampilan web pada
**`http://localhost:8090`** (kontrak port di `MEMORY.md` §2 dan PRD §8.6).

Dibangun **hanya dengan Python stdlib + HTML/JS murni** (Chart.js via CDN),
tanpa Flask/FastAPI/pip, mengikuti konvensi repo ini.

## Menjalankan

```bash
./scripts/setup_cluster.sh          # sekali saja: cluster + 4 Pod worker
python3 dashboard/server.py          # buka http://localhost:8090
```

Prasyarat: cluster `soka-datacenter` hidup dan keempat worker
`http://127.0.0.1:30081`–`30084/health` `ready` (tanpa cluster pun dashboard
tetap terbuka — bagian topologi akan menampilkan status error).

## Endpoint API

| Method | Endpoint | Fungsi |
| --- | --- | --- |
| `GET` | `/` | Menyajikan `dashboard/index.html` |
| `GET` | `/api/status` | Real-time: `kubectl get nodes/pods` + `GET /health` ke 4 worker (paralel, timeout 3 dtk) |
| `GET` | `/api/results` | File mentah `results/realworld_summary.json` |
| `GET` | `/api/summary` | Ringkasan untuk chart: median 20 metrik per skenario × algoritma + alokasi Gantt per trial |
| `POST` | `/api/run?scenario=paper\|gocj\|all&trials=N` | Menjalankan `run_benchmark.py` **di background** (worker hanya boleh 1 job; balasan `409` jika masih berjalan) |
| `GET` | `/api/run/status` | Status job + **log streaming** (polling ~0,7 dtk dari frontend) |
| `POST` | `/api/run/stop` | Menghentikan job yang sedang berjalan (`SIGTERM`) |
| `GET` | `/api/export/csv?type=summary\|allocations` | Unduhan CSV (ringkasan metrik / detail alokasi per tugas) |

## Isi halaman

1. **Topologi langsung** — 1 DC → 2 host (`soka-host-1/2`) → 4 VM Pod, dengan
   status Ready/Down, CPU limit, cost/MI, antrean, dan jumlah tugas selesai
   dari tiap worker; auto-refresh tiap 15 detik.
2. **Konsol benchmark** — tombol `Run All` / `Paper 10` / `GoCJ 24` + jumlah
   trial; log benchmark ditampilkan real-time (kalibrasi → dispatch → metrik),
   lalu dashboard memuat ulang hasil secara otomatis.
3. **Tab skenario** (`paper_10`, `gocj_first_24`) → **5 KPI** (makespan nyata
   terbaik, biaya model + penghematan vs RR, utilisasi, DI, skala uji).
4. **4 chart Chart.js** — makespan nyata vs prediksi, biaya model, utilisasi
   vs degree of imbalance (sumbu ganda), distribusi tugas per host.
5. **Gantt eksekusi nyata** per tugas (pilih algoritma + trial), diwarnai per
   host, dengan tooltip nyata vs prediksi.
6. **Tabel peringkat** + ekspor CSV + info reproduksi (commit git, platform,
   metode kalibrasi).

## Struktur

```
dashboard/
├── server.py    # ThreadingHTTPServer stdlib: routing, kubectl, worker health,
│                #   job runner background, generator CSV
├── index.html   # SPA frontend (Chart.js CDN, Google Fonts), memanggil API di atas
└── README.md
```

Sumber data satu-satunya adalah `results/realworld_summary.json` (dihasilkan
`run_benchmark.py`); tidak ada angka yang di-hardcode di frontend.
