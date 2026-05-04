# RadonNET Streamlit Dashboards

This folder contains two independent Streamlit dashboards optimized for the new RadonNET architecture.

## Files

```text
app_local_sqlite.py
app_cloud_turso.py
requirements_streamlit.txt
.env.example
```

## 1. Architecture

The dashboards are intentionally separated.

### Local dashboard

```text
app_local_sqlite.py
```

Reads:

```text
SQLite -> raw_measurements
```

Purpose:

- full-resolution raw data;
- 10-minute measurements;
- troubleshooting;
- detector diagnostics;
- detailed CSV/Excel export;
- local laboratory use.

### Cloud dashboard

```text
app_cloud_turso.py
```

Reads:

```text
Turso -> hourly_room_measurements
Turso -> hourly_detector_measurements
Turso -> rooms
Turso -> detectors
```

Purpose:

- fast remote visualization;
- Streamlit Cloud deployment;
- room-level monitoring;
- hourly dashboard;
- lightweight cloud usage.

The cloud dashboard does not read raw 10-minute data. This is deliberate.

---

## 2. Install requirements

Create or activate your Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements_streamlit.txt
```

---

## 3. Local SQLite dashboard

### 3.1 Configure

The app looks for the SQLite database in:

```text
data/radonnet_local.sqlite
```

You can override this with an environment variable:

```bash
export SQLITE_PATH=/absolute/path/to/radonnet_local.sqlite
```

Or create a `.env` file:

```bash
SQLITE_PATH=/absolute/path/to/radonnet_local.sqlite
APP_PASSWORD=optional_password
```

### 3.2 Run locally

```bash
streamlit run app_local_sqlite.py
```

To make it visible from other computers on the lab network:

```bash
streamlit run app_local_sqlite.py --server.address 0.0.0.0 --server.port 8501
```

Then open from another lab computer:

```text
http://SERVER_LAB_IP:8501
```

### 3.3 What it shows

The local dashboard has three sections:

1. Dashboard
   - raw time series;
   - filters by variable, room, detector type, detector;
   - latest values;
   - CSV export.

2. Diagnostics
   - total rows;
   - last time by detector;
   - inactive detector detection;
   - measurements without room assignment;
   - timestamp quality;
   - metadata tables.

3. Raw export
   - custom time interval;
   - variable selection;
   - detector/room selection;
   - CSV and Excel download.

---

## 4. Cloud Turso dashboard

### 4.1 Turso tables required

Before using the cloud dashboard, Turso must contain:

```text
rooms
detectors
hourly_room_measurements
hourly_detector_measurements
```

The uploader must have been run successfully:

```bash
python3 run_collector.py upload-turso
```

### 4.2 Configure for local test

Create `.env`:

```bash
TURSO_DATABASE_URL=https://your-db.aws-eu-west-1.turso.io
TURSO_AUTH_TOKEN=your_token
APP_PASSWORD=optional_password
```

`TURSO_DB_URL` is also accepted.

Important:

Prefer:

```text
https://...
```

instead of:

```text
libsql://...
```

because the app normalizes the URL to HTTP mode for better Streamlit compatibility.

### 4.3 Run locally

```bash
streamlit run app_cloud_turso.py
```

### 4.4 Deploy on Streamlit Cloud

In Streamlit Cloud secrets, set:

```toml
TURSO_DATABASE_URL = "https://your-db.aws-eu-west-1.turso.io"
TURSO_AUTH_TOKEN = "your_token"
APP_PASSWORD = "optional_password"
```

The cloud app does not need SQLite, PostgreSQL, or Supabase.

### 4.5 What it shows

The cloud dashboard has four sections:

1. Dashboard
   - room-level hourly trends;
   - multi-room and multi-variable filters;
   - latest room values;
   - reference lines for radon, CO2, PM.

2. Detector comparison
   - detector-level hourly aggregates;
   - comparison of detectors in the same room.

3. Cloud diagnostics
   - table counts;
   - last uploaded hour;
   - last hour by room and variable;
   - rooms and detectors tables.

4. Export
   - hourly cloud data export to CSV/Excel.

---

## 5. Recommended usage

### Daily local workflow

Use the local dashboard when you are physically in the laboratory and need to inspect full-resolution data:

```bash
streamlit run app_local_sqlite.py --server.address 0.0.0.0 --server.port 8501
```

### Remote/cloud workflow

Use the cloud dashboard for routine visualization from outside the laboratory:

```bash
streamlit run app_cloud_turso.py
```

or deploy it on Streamlit Cloud.

---

## 6. Why two dashboards?

The local and cloud apps serve different technical needs.

### Local app

Uses raw data:

```text
raw_measurements
```

Advantages:

- complete information;
- full temporal resolution;
- debugging capability;
- no cloud storage limit problem.

Disadvantages:

- can be heavy;
- not ideal for public remote dashboard.

### Cloud app

Uses hourly data:

```text
hourly_room_measurements
hourly_detector_measurements
```

Advantages:

- fast;
- light;
- cheap/free-tier friendly;
- ideal for Streamlit Cloud.

Disadvantages:

- no raw 10-minute data;
- less suited for detailed debugging.

This separation is intentional and recommended.

---

## 7. Troubleshooting

### Local dashboard says SQLite database not found

Check:

```bash
echo $SQLITE_PATH
ls -lh data/radonnet_local.sqlite
```

Or set:

```bash
export SQLITE_PATH=/absolute/path/to/radonnet_local.sqlite
```

### Local dashboard has no raw_measurements table

The collector has not initialized or written to SQLite.

Check:

```bash
sqlite3 data/radonnet_local.sqlite ".tables"
```

### Cloud dashboard says no variables found

Turso has no hourly data. Run:

```bash
python3 run_collector.py aggregate-hourly
python3 run_collector.py upload-turso
```

### Cloud dashboard cannot connect to Turso

Check Streamlit secrets:

```toml
TURSO_DATABASE_URL = "https://..."
TURSO_AUTH_TOKEN = "..."
```

### Cloud dashboard has rooms/detectors but no hourly data

Check PostgreSQL before upload:

```sql
SELECT COUNT(*) FROM hourly_room_measurements;
SELECT COUNT(*) FROM hourly_detector_measurements;
```

Then upload:

```bash
python3 run_collector.py upload-turso
```

---

## 8. Required Python packages

```text
streamlit
pandas
plotly
matplotlib
python-dotenv
libsql-client
openpyxl
```
