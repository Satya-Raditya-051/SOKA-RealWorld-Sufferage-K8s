# 🧠 MEMORY.md — Project State & Progress Tracker (SOKA Kelompok 4 Demo-3)

> **INSTRUKSI WAJIB UNTUK MANUSIA & AI CODING AGENT**:
> 1. **BACA FILE INI TERLEBIH DAHULU** setiap kali memulai sesi pengerjaan baru.
> 2. **JANGAN MENGUBAH** kontrak port (`30081`–`30084`, `8090`), nama node Kubernetes (`host-1`, `host-2`), maupun nama Pod VM (`vm-1-small` s.d. `vm-4-xlarge`) tanpa memperbarui dokumen ini.
> 3. **WAJIB UPDATE FILE INI** (ubah status `[ ]` menjadi `[x]` dan tambahkan entri di *Progress Log*) setiap kali selesai membangun, memperbaiki, atau menguji suatu fitur sebelum `git commit & push`.

---

## 📌 1. Pembagian Jobdesk Kelompok 4 & Jadwal (Senin–Rabu Coding, Kamis Testing)

| No | Anggota Tim | NRP | Jobdesk Utama | Target Hari | Status |
| :-: | :--- | :---: | :--- | :---: | :---: |
| **1** | **Hikari (`M. Hikari Reiziq R.`)** | `5027241079` | **Siapin Provider Cloud & Briefing** (`BRIEFING`, `PRD`, `MEMORY.md`) | **Senin (26 Okt)** | `[x] Selesai` |
| **2** | **Mas Satya (`I Dewa Made Satya R.`)** | `5027231051` | **Bikin GitHub & Coding Inisialisasi 1 DC, 2 Host, dan 2 VM/Host** (`k8s/`, `vm_worker/`, `scripts/`) | **Senin (26 Okt)** | `[x] Selesai` |
| **3** | **Rakha (`M. Rakha Hananditya R.`)** | `5027241015` | **Implementasi Algoritma Sufferage** (`scheduler/models.py`, `datasets.py`, `algorithms.py`, `k8s_broker.py`, `run_benchmark.py`) | **Selasa (27 Okt)** | `[x] Selesai & teruji` |
| **4** | **Aron (`Theodorus Aaron Ugraha`)** | `5027241056` | **Laporan Algoritma Sufferage** (`docs/LAPORAN_AKHIR_DEMO3_KELOMPOK4.md`, rekap `results/`) | **Rabu (28 Okt)** | `[ ] Belum` |
| **5** | **Wildan Fawwaz (`Ahmad Wildan F.`)** | `5027241001` | **Testing Kalau Ada Error & Persiapan Demo** (`tests/`, `dashboard/`, End-to-End K8s Verification) | **Rabu & Kamis (29 Okt — Full Testing)** | `[ ] Belum` |

---

## 📌 2. Ringkasan Kontrak Teknis (Single Source of Truth)
- **Nama Cluster Kind (Datacenter 1)**: `soka-datacenter` (Konteks kubectl: `kind-soka-datacenter`)
- **Namespace Kubernetes**: `soka-cloud`
- **Worker Node Logis (2 container nodes pada satu host fisik kind)**:
  - Host 1: node label `soka.its.ac.id/host-id=host-1` (`soka-host-1`)
  - Host 2: node label `soka.its.ac.id/host-id=host-2` (`soka-host-2`)
- **4 Worker Pods Terisolasi (nama `vm-*` adalah kontrak proyek; 2 Pod per node)**:
  - `vm-1-small`  (di `host-1`): CPU Limit `250m`, RAM `256Mi`, Setara `50 MIPS`, BW `100 Mbps`, Cost `0.03 INR/MI`, NodePort `30081` (`http://localhost:30081`)
  - `vm-2-medium` (di `host-1`): CPU Limit `500m`, RAM `512Mi`, Setara `100 MIPS`, BW `200 Mbps`, Cost `0.12 INR/MI`, NodePort `30082` (`http://localhost:30082`)
  - `vm-3-large`  (di `host-2`): CPU Limit `1000m`, RAM `1024Mi`, Setara `200 MIPS`, BW `250 Mbps`, Cost `0.24 INR/MI`, NodePort `30083` (`http://localhost:30083`)
  - `vm-4-xlarge` (di `host-2`): CPU Limit `1500m`, RAM `1536Mi`, Setara `300 MIPS`, BW `300 Mbps`, Cost `0.35 INR/MI`, NodePort `30084` (`http://localhost:30084`)
- **Algoritma yang Diimplementasikan (3 Inti)**:
  1. `CCTSA (Dual-Sufferage)` — Optimasi Waktu ($SVCT$) & Biaya ($SVC$)
  2. `Standard Sufferage` — Optimasi Waktu ($SVCT$) & Resolusi Konflik VM
  3. `Round Robin (Baseline)` — Penjadwalan Siklik Statis
- **Port Live Web Dashboard**: `http://localhost:8090`

---

## ✅ 3. Checklist Progres Pembangunan Komponen

### Fase 1: Siapin Provider Cloud & Briefing (PIC: Hikari — Target: Senin)
- [x] Evaluasi provider cloud (Keputusan: Full Kubernetes Multi-Node via `kind`)
- [x] Pembuatan `BRIEFING_TIM_KELOMPOK4_DEMO3.md`, `PRD_REALWORLD_SUFFERAGE_K8S.md`, dan `MEMORY.md`

### Fase 2: Bikin GitHub & Coding Inisialisasi 1 DC, 2 Host, dan 2 VM/Host (PIC: Mas Satya — Target: Senin)
- [x] Repository GitHub `Satya-Raditya-051/SOKA-RealWorld-Sufferage-K8s` tersedia sebagai `origin`
- [x] Pembuatan `k8s/kind-cluster.yaml` (1 Control Plane + 2 Worker Host Nodes + Port Mapping 30081–30084)
- [x] Pembuatan `k8s/vm-pods.yaml` (Namespace `soka-cloud`, 4 VM Pods dengan `nodeSelector` & `resources.limits.cpu` + NodePort Services)
- [x] Pembuatan `vm_worker/worker_server.py` & `vm_worker/Dockerfile`
- [x] Pembuatan `scripts/install_k8s_tools.sh` & `scripts/setup_cluster.sh` serta verifikasi cluster `Running`

### Fase 3: Implementasi Algoritma Sufferage (PIC: Rakha — Target: Selasa)
- [x] Pembuatan `scheduler/models.py` (model task, worker, calibration, allocation, benchmark)
- [x] Pembuatan `scheduler/datasets.py` (10 task paper dan 24 task pertama dataset GoCJ resmi)
- [x] Pembuatan `scheduler/algorithms.py` (CCTSA paper-faithful, Standard Sufferage Figure 2, Round Robin)
- [x] Pembuatan `scheduler/k8s_broker.py` & `run_benchmark.py` (kalibrasi, empat antrean paralel, raw trial, metrik lengkap)

### Fase 4: Laporan Akhir Algoritma Sufferage (PIC: Aron — Target: Rabu)
- [ ] Eksekusi eksperimen 5 trial berotasi & rekap lokal di `results/realworld_summary.json`
- [ ] Pengambilan screenshot bukti `kubectl get nodes -o wide` dan `kubectl get pods -n soka-cloud -o wide`
- [ ] Penyusunan `docs/LAPORAN_AKHIR_DEMO3_KELOMPOK4.md`
- [ ] Penyusunan `README.md` utama dengan metode, batasan, penggunaan, dan hasil median

### Fase 5: Testing Kalau Ada Error & Persiapan Demo (PIC: Wildan Fawwaz — Target: Rabu & Kamis Full Testing)
- [x] Pembuatan `dashboard/server.py` & `dashboard/index.html` untuk visualisasi Live Demo (port `8090`; API: `/api/status`, `/api/summary`, `/api/results`, `POST /api/run`, `/api/run/status`, `/api/run/stop`, `/api/export/csv`; lihat `dashboard/README.md`)
- [ ] Pembuatan suite `tests/` untuk algoritma, dataset, broker, worker HTTP, kontrak manifest, dan K8s end-to-end
- [ ] Uji end-to-end cluster serta 5 trial kedua skenario tanpa error; gladi bersih presentasi tetap tugas tim

---

## 📝 4. Log Riwayat Sesi Pengerjaan (Diisi oleh Tim / AI Agent)

| Tanggal & Waktu | Anggota Tim / AI Agent | Komponen yang Dikerjakan | Status & Catatan Penting untuk Sesi Berikutnya |
| :--- | :--- | :--- | :--- |
| 2026-10-26 | Hikari (via Antigravity) | Penyiapan Provider Cloud, `BRIEFING_TIM_KELOMPOK4_DEMO3.md`, `PRD_REALWORLD_SUFFERAGE_K8S.md`, dan `MEMORY.md` | `[x] Selesai`. Selanjutnya giliran **Mas Satya** membuat repo GitHub baru dan membangun inisialisasi 1 DC, 2 Host, dan 2 VM/Host (Fase 2). |
| 2026-10-27 | Mas Satya (via Copilot SDK) | Membangun `k8s/`, `vm_worker/`, dan `scripts/`; memasang `kubectl`/`kind`; membuat cluster `soka-datacenter` dengan 1 control plane, 2 host, dan 4 VM Pod | `[x]` Node control-plane, host-1, dan host-2 `Ready`; `vm-1-small`/`vm-2-medium` Running di host-1 dan `vm-3-large`/`vm-4-xlarge` Running di host-2. Keempat `/health` `Ready` dan POST `/execute` menghasilkan checksum SHA-256. Siap dilanjutkan **Rakha (Fase 3: Implementasi Algoritma Sufferage)** pada Selasa. Push GitHub menunggu URL repository baru. |
| 2026-10-28 | Codex | Implementasi Phase 3, koreksi worker/K8s/setup, dataset GoCJ resmi, kalibrasi real, benchmark, dokumentasi, dan testing | `[x]` 20 unit/integration tests lulus, 2 live K8s E2E tests lulus, cluster v1.37.0 sehat. Lima trial berotasi selesai untuk paper dan GoCJ. Median makespan paper: CCTSA 2.814 s, Sufferage 2.922 s, RR 12.014 s; GoCJ: CCTSA 7.647 s, Sufferage 7.278 s, RR 15.452 s. Modeled cost dilaporkan apa adanya dan bukan real spend. |
| 2026-10-29 | AI Agent (OpenCode) | Membangun `dashboard/server.py` + `dashboard/index.html` + `dashboard/README.md` (Fase 5, item dashboard) | `[x]` Dashboard live di `http://localhost:8090` terhubung ke `kubectl` + `/health` 4 worker + `results/realworld_summary.json`; dapat menjalankan benchmark langsung dari browser (`POST /api/run` teruji end-to-end, `returncode 0`, log streaming sampai selesai) dan ekspor CSV. Smoke test jsdom (19 asersi + uji ganti skenario/trial) lulus tanpa error runtime; deadlock pada job runner sudah diperbaiki. Data hasil tim (GoCJ 5 trial) dipertahankan. Item Fase 5 lainnya (suite tests & gladi bersih) tetap milik PIC. |
