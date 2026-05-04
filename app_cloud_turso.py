#!/usr/bin/env python3
"""
RadonNET Cloud Streamlit Dashboard

Purpose
-------
Cloud dashboard optimized for Turso.

Data source
-----------
Turso database containing hourly aggregates and metadata.

Main tables
-----------
rooms
detectors
hourly_room_measurements
hourly_detector_measurements

Typical use
-----------
- Streamlit Cloud deployment
- lightweight remote dashboard
- room-level monitoring
- hourly trends
"""

from __future__ import annotations

import hmac
import io
import os
import time
from datetime import datetime, timedelta, timezone

import libsql_client
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv


# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="RadonNET Cloud Dashboard",
    page_icon="☁️",
    layout="wide",
)

load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================
VARIABLE_UNITS = {
    "radon": "Bq/m³",
    "radon_error": "Bq/m³",
    "gross_counts": "counts",
    "temperature": "°C",
    "humidity": "%",
    "atmosphericpressure": "hPa",
    "pressure": "hPa",
    "battery": "V",
    "rssi": "dBm",
    "pm1": "kg/m³",
    "pm2_5": "kg/m³",
    "pm10": "kg/m³",
    "co2": "ppm",
    "voc": "ppb",
    "noise": "dB",
    "light": "lx",
}

DEFAULT_VARIABLE_ORDER = [
    "radon",
    "co2",
    "temperature",
    "humidity",
    "pressure",
    "atmosphericpressure",
    "pm1",
    "pm2_5",
    "pm10",
    "gross_counts",
    "battery",
    "rssi",
]

REFERENCE_LINES = {
    "radon": {
        "recommended": 100.0,
        "limit": 300.0,
    },
    "co2": {
        "recommended": 1000.0,
        "limit": 1500.0,
    },
    "pm2_5": {
        "recommended": 10.0e-9,
        "limit": 25.0e-9,
    },
    "pm10": {
        "recommended": 20.0e-9,
        "limit": 45.0e-9,
    },
}

MAX_CLOUD_DAYS = 90


# ============================================================
# HEADER / STYLE
# ============================================================
st.markdown(
    """
    <style>
        .hero-header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 1rem 1.5rem;
            padding: 0.25rem 0 1rem 0;
            border-bottom: 1px solid rgba(120,120,120,0.25);
            margin-bottom: 1rem;
        }
        .main-title {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .main-subtitle {
            font-size: 1rem;
            color: #555;
            margin-top: 0.25rem;
        }
        .section-note {
            background: rgba(240, 242, 246, 0.7);
            border: 1px solid rgba(120,120,120,0.18);
            border-radius: 10px;
            padding: 0.9rem 1rem;
            margin-bottom: 1rem;
        }
    </style>
    <div class="hero-header">
        <div>
            <div class="main-title">CEA/LNHB RadonNET Cloud Dashboard</div>
            <div class="main-subtitle">
                Lightweight remote visualization from Turso hourly aggregates.
            </div>
        </div>
    </div>
    <div class="section-note">
        <strong>Cloud mode.</strong> This app reads hourly aggregates from Turso.
        It is designed for fast dashboard rendering and remote access.
        Raw 10-minute data remain in the local SQLite/PostgreSQL database.
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# OPTIONAL PASSWORD
# ============================================================
def get_secret_or_env(name: str, default: str | None = None) -> str | None:
    if name in st.secrets:
        return str(st.secrets[name])
    return os.getenv(name, default)


def check_app_password() -> bool:
    expected = get_secret_or_env("APP_PASSWORD")
    if not expected:
        return True

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("Private dashboard")
    password_input = st.text_input("Password", type="password")
    if st.button("Login", use_container_width=True):
        if hmac.compare_digest(password_input, expected):
            st.session_state.authenticated = True
            st.rerun()
        st.error("Wrong password.")

    return False


if not check_app_password():
    st.stop()


# ============================================================
# TURSO CONNECTION
# ============================================================
def normalize_turso_url(url: str) -> str:
    """
    Prefer HTTP mode for Streamlit Cloud stability.
    """
    url = str(url).strip()
    if url.startswith("libsql://"):
        url = "https://" + url.replace("libsql://", "", 1)
    return url.rstrip("/")


@st.cache_resource
def get_turso_client():
    url = get_secret_or_env("TURSO_DATABASE_URL") or get_secret_or_env("TURSO_DB_URL")
    token = get_secret_or_env("TURSO_AUTH_TOKEN")

    if not url:
        raise RuntimeError("TURSO_DATABASE_URL or TURSO_DB_URL is missing.")
    if not token:
        raise RuntimeError("TURSO_AUTH_TOKEN is missing.")

    return libsql_client.create_client_sync(
        normalize_turso_url(url),
        auth_token=token,
    )


def turso_query(sql: str, args: list | tuple | None = None) -> pd.DataFrame:
    if args is None:
        args = []

    client = get_turso_client()
    result = client.execute(sql, list(args))

    columns = [col[0] if isinstance(col, (tuple, list)) else str(col) for col in result.columns]
    return pd.DataFrame(result.rows, columns=columns)


# ============================================================
# HELPERS
# ============================================================
def get_unit(variable: str) -> str:
    return VARIABLE_UNITS.get(str(variable), "")


def with_unit(label: str, variable: str) -> str:
    unit = get_unit(variable)
    return f"{label} [{unit}]" if unit else label


def format_value(value, variable: str | None = None, decimals: int = 2) -> str:
    if pd.isna(value):
        return "NA"
    value = float(value)
    abs_val = abs(value)
    if abs_val == 0:
        text = "0"
    elif abs_val < 1e-3 or abs_val >= 1e4:
        text = f"{value:.3e}"
    else:
        text = f"{value:.{decimals}f}"
    if variable:
        unit = get_unit(variable)
        return f"{text} {unit}" if unit else text
    return text


def order_variables(variables: list[str]) -> list[str]:
    order_map = {v: i for i, v in enumerate(DEFAULT_VARIABLE_ORDER)}
    return sorted(variables, key=lambda x: (order_map.get(x, 999), x))


def choose_hover_format(series: pd.Series) -> str:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return ".2f"
    max_abs = numeric.abs().max()
    if pd.isna(max_abs):
        return ".2f"
    if max_abs < 1e-3 or max_abs >= 1e4:
        return ".4e"
    return ".2f"


def choose_tick_format(series: pd.Series) -> str | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    max_abs = numeric.abs().max()
    if pd.isna(max_abs):
        return None
    if max_abs < 1e-3 or max_abs >= 1e4:
        return ".2e"
    return None


def add_reference_lines(fig, variable: str):
    ref = REFERENCE_LINES.get(variable)
    if not ref:
        return fig

    recommended = ref.get("recommended")
    limit = ref.get("limit")

    if recommended is not None:
        fig.add_hline(
            y=recommended,
            line_width=2,
            line_dash="dash",
            line_color="gold",
            annotation_text=f"Recommended: {format_value(recommended, variable)}",
            annotation_position="top left",
        )

    if limit is not None:
        fig.add_hline(
            y=limit,
            line_width=2,
            line_dash="solid",
            line_color="red",
            annotation_text=f"Reference: {format_value(limit, variable)}",
            annotation_position="top right",
        )

    return fig


def build_trace_mode(show_lines: bool, show_points: bool) -> str:
    if not show_lines and not show_points:
        show_lines = True

    if show_lines and show_points:
        return "lines+markers"
    if show_lines:
        return "lines"
    return "markers"


# ============================================================
# DATA LOADING
# ============================================================
@st.cache_data(ttl=60)
def load_rooms() -> pd.DataFrame:
    try:
        df = turso_query(
            """
            SELECT room_id, room_name, building, floor, notes, active, updated_at_utc
            FROM rooms
            ORDER BY room_id
            """
        )
    except Exception:
        return pd.DataFrame(columns=["room_id", "room_name", "building", "floor", "notes", "active", "updated_at_utc"])

    if df.empty:
        return df

    df["room_id"] = df["room_id"].astype(str)
    df["room_label"] = df.apply(
        lambda r: f"{r['room_id']} - {r['room_name']}" if pd.notna(r.get("room_name")) and str(r.get("room_name")).strip() else str(r["room_id"]),
        axis=1,
    )
    return df


@st.cache_data(ttl=60)
def load_detectors() -> pd.DataFrame:
    try:
        df = turso_query(
            """
            SELECT detector_id, detector_type, display_name, serial_number, mac_address,
                   product_number, notes, active, updated_at_utc
            FROM detectors
            ORDER BY detector_type, detector_id
            """
        )
    except Exception:
        return pd.DataFrame(columns=["detector_id", "detector_type", "display_name"])

    if df.empty:
        return df

    df["detector_id"] = df["detector_id"].astype(str)
    return df


@st.cache_data(ttl=60)
def load_available_variables() -> list[str]:
    df = turso_query(
        """
        SELECT DISTINCT variable
        FROM hourly_room_measurements
        WHERE variable IS NOT NULL
        ORDER BY variable
        """
    )
    if df.empty:
        return []
    return order_variables(df["variable"].dropna().astype(str).tolist())


@st.cache_data(ttl=60)
def load_hourly_room_data(
    variables: tuple[str, ...],
    rooms: tuple[str, ...],
    start_iso: str,
) -> pd.DataFrame:
    where = [
        "hour_utc >= ?",
    ]
    args: list = [start_iso]

    if variables:
        where.append(f"variable IN ({','.join(['?'] * len(variables))})")
        args.extend(variables)

    if rooms:
        where.append(f"room_id IN ({','.join(['?'] * len(rooms))})")
        args.extend(rooms)

    sql = f"""
        SELECT
            h.room_id,
            COALESCE(r.room_name, h.room_id) AS room_name,
            h.variable,
            h.hour_utc,
            h.mean_value,
            h.std_value,
            h.min_value,
            h.max_value,
            h.n_points,
            h.n_detectors,
            h.mean_uncertainty,
            h.uncertainty_method,
            h.unit,
            h.updated_at_utc
        FROM hourly_room_measurements h
        LEFT JOIN rooms r
            ON r.room_id = h.room_id
        WHERE {' AND '.join(where)}
        ORDER BY h.hour_utc
    """

    df = turso_query(sql, args)
    if df.empty:
        return df

    df["hour_utc"] = pd.to_datetime(df["hour_utc"], errors="coerce", utc=True)
    df["updated_at_utc"] = pd.to_datetime(df["updated_at_utc"], errors="coerce", utc=True)

    for col in ["mean_value", "std_value", "min_value", "max_value", "mean_uncertainty"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["n_points", "n_detectors"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    df = df.dropna(subset=["hour_utc", "mean_value"])
    df["room_label"] = df.apply(
        lambda r: f"{r['room_id']} - {r['room_name']}" if str(r["room_name"]) != str(r["room_id"]) else str(r["room_id"]),
        axis=1,
    )

    return df


@st.cache_data(ttl=60)
def load_hourly_detector_data(
    variables: tuple[str, ...],
    start_iso: str,
) -> pd.DataFrame:
    where = ["hour_utc >= ?"]
    args: list = [start_iso]

    if variables:
        where.append(f"variable IN ({','.join(['?'] * len(variables))})")
        args.extend(variables)

    sql = f"""
        SELECT
            h.detector_id,
            COALESCE(d.display_name, h.detector_id) AS display_name,
            COALESCE(d.detector_type, 'unknown') AS detector_type,
            h.room_id,
            h.variable,
            h.hour_utc,
            h.mean_value,
            h.std_value,
            h.min_value,
            h.max_value,
            h.n_points,
            h.mean_uncertainty,
            h.uncertainty_method,
            h.unit,
            h.updated_at_utc
        FROM hourly_detector_measurements h
        LEFT JOIN detectors d
            ON d.detector_id = h.detector_id
        WHERE {' AND '.join(where)}
        ORDER BY h.hour_utc
    """

    df = turso_query(sql, args)
    if df.empty:
        return df

    df["hour_utc"] = pd.to_datetime(df["hour_utc"], errors="coerce", utc=True)
    df["mean_value"] = pd.to_numeric(df["mean_value"], errors="coerce")
    df = df.dropna(subset=["hour_utc", "mean_value"])
    df["detector_label"] = df.apply(
        lambda r: f"{r['detector_id']} - {r['display_name']}" if str(r["display_name"]) != str(r["detector_id"]) else str(r["detector_id"]),
        axis=1,
    )
    return df


@st.cache_data(ttl=60)
def load_cloud_health() -> dict[str, pd.DataFrame]:
    out = {}

    for table in ["rooms", "detectors", "hourly_room_measurements", "hourly_detector_measurements"]:
        try:
            out[table] = turso_query(f"SELECT COUNT(*) AS n_rows FROM {table}")
        except Exception as exc:
            out[table] = pd.DataFrame({"n_rows": [None], "error": [str(exc)]})

    try:
        out["last_room"] = turso_query(
            """
            SELECT
                COUNT(*) AS n_rows,
                MIN(hour_utc) AS first_hour,
                MAX(hour_utc) AS last_hour
            FROM hourly_room_measurements
            """
        )
    except Exception as exc:
        out["last_room"] = pd.DataFrame({"error": [str(exc)]})

    try:
        out["by_room_variable"] = turso_query(
            """
            SELECT
                room_id,
                variable,
                COUNT(*) AS n_rows,
                MAX(hour_utc) AS last_hour
            FROM hourly_room_measurements
            GROUP BY room_id, variable
            ORDER BY last_hour DESC
            """
        )
    except Exception as exc:
        out["by_room_variable"] = pd.DataFrame({"error": [str(exc)]})

    return out


# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.header("Cloud data source")

try:
    client = get_turso_client()
    st.sidebar.success("Turso connected")
except Exception as exc:
    st.error(f"Unable to connect to Turso: {exc}")
    st.stop()

page_mode = st.sidebar.radio(
    "Section",
    ["Dashboard", "Detector comparison", "Cloud diagnostics", "Export"],
    index=0,
)

auto_refresh = st.sidebar.checkbox("Auto-refresh every minute", value=False)

show_lines = st.sidebar.checkbox("Show lines", value=True)
show_points = st.sidebar.checkbox("Show markers", value=False)
trace_mode = build_trace_mode(show_lines, show_points)

rooms_df = load_rooms()
detectors_df = load_detectors()
available_variables = load_available_variables()

if not available_variables:
    st.warning("No variables found in hourly_room_measurements. Has upload-turso been run?")
    st.stop()


# ============================================================
# DASHBOARD
# ============================================================
if page_mode == "Dashboard":
    st.subheader("Room-level hourly dashboard")

    days = st.sidebar.slider(
        "Range [days]",
        min_value=1,
        max_value=MAX_CLOUD_DAYS,
        value=min(7, MAX_CLOUD_DAYS),
    )

    selected_variables = st.sidebar.multiselect(
        "Variables",
        options=available_variables,
        default=available_variables[: min(4, len(available_variables))],
    )

    room_options = rooms_df["room_id"].tolist() if not rooms_df.empty else []
    selected_rooms = st.sidebar.multiselect(
        "Rooms",
        options=room_options,
        default=[],
        help="Leave empty to include all rooms.",
    )

    if not selected_variables:
        st.warning("Select at least one variable.")
        st.stop()

    start_dt = datetime.now(timezone.utc) - timedelta(days=days)

    data_df = load_hourly_room_data(
        variables=tuple(selected_variables),
        rooms=tuple(selected_rooms),
        start_iso=start_dt.isoformat(),
    )

    if data_df.empty:
        st.warning("No hourly room data found for the selected filters.")
        st.stop()

    metric_cols = st.columns(5)
    metric_cols[0].metric("Rows", f"{len(data_df):,}")
    metric_cols[1].metric("Rooms", data_df["room_id"].nunique())
    metric_cols[2].metric("Variables", data_df["variable"].nunique())
    metric_cols[3].metric("Last hour", data_df["hour_utc"].max().strftime("%Y-%m-%d %H:%M UTC"))
    metric_cols[4].metric("Points", f"{int(data_df['n_points'].sum()):,}")

    for variable in selected_variables:
        var_df = data_df[data_df["variable"] == variable].copy()
        if var_df.empty:
            continue

        st.markdown(f"### {with_unit(variable, variable)}")

        stats_cols = st.columns(5)
        stats_cols[0].metric("Rooms with data", var_df["room_id"].nunique())
        stats_cols[1].metric("Mean", format_value(var_df["mean_value"].mean(), variable))
        stats_cols[2].metric("Min", format_value(var_df["mean_value"].min(), variable))
        stats_cols[3].metric("Max", format_value(var_df["mean_value"].max(), variable))
        stats_cols[4].metric("Hourly rows", f"{len(var_df):,}")

        hover_fmt = choose_hover_format(var_df["mean_value"])
        tick_fmt = choose_tick_format(var_df["mean_value"])
        y_title = with_unit(variable, variable)

        fig = px.line(
            var_df,
            x="hour_utc",
            y="mean_value",
            color="room_label",
            labels={
                "hour_utc": "Time UTC",
                "mean_value": y_title,
                "room_label": "Room",
            },
            template="plotly_white",
        )

        fig.update_traces(
            mode=trace_mode,
            hovertemplate=(
                "<b>Time</b>: %{x|%Y-%m-%d %H:%M UTC}<br>"
                "<b>Room</b>: %{fullData.name}<br>"
                f"<b>{y_title}</b>: %{{y:{hover_fmt}}}<extra></extra>"
            ),
        )

        fig = add_reference_lines(fig, variable)

        layout_kwargs = dict(
            height=430,
            margin=dict(l=20, r=20, t=30, b=20),
            hovermode="x unified",
            xaxis_title="Time UTC",
            yaxis_title=y_title,
            legend_title="Room",
        )
        if tick_fmt:
            layout_kwargs["yaxis"] = dict(tickformat=tick_fmt)

        fig.update_layout(**layout_kwargs)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Latest room values")
    latest = (
        data_df.sort_values("hour_utc")
        .groupby(["room_id", "room_name", "variable"], dropna=False)
        .tail(1)
        .copy()
    )
    latest["display_value"] = latest.apply(
        lambda row: format_value(row["mean_value"], str(row["variable"])),
        axis=1,
    )
    st.dataframe(
        latest[
            [
                "hour_utc",
                "room_id",
                "room_name",
                "variable",
                "display_value",
                "n_points",
                "n_detectors",
                "mean_uncertainty",
                "uncertainty_method",
            ]
        ].sort_values("hour_utc", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# DETECTOR COMPARISON
# ============================================================
elif page_mode == "Detector comparison":
    st.subheader("Detector-level hourly comparison")

    days = st.sidebar.slider(
        "Range [days]",
        min_value=1,
        max_value=MAX_CLOUD_DAYS,
        value=min(7, MAX_CLOUD_DAYS),
    )

    selected_variables = st.sidebar.multiselect(
        "Variables",
        options=available_variables,
        default=["radon"] if "radon" in available_variables else available_variables[:1],
    )

    if not selected_variables:
        st.warning("Select at least one variable.")
        st.stop()

    start_dt = datetime.now(timezone.utc) - timedelta(days=days)

    det_df = load_hourly_detector_data(
        variables=tuple(selected_variables),
        start_iso=start_dt.isoformat(),
    )

    if det_df.empty:
        st.warning("No detector-level hourly data found.")
        st.stop()

    selected_room = st.sidebar.selectbox(
        "Room filter",
        options=["All"] + sorted(det_df["room_id"].dropna().astype(str).unique().tolist()),
        index=0,
    )

    if selected_room != "All":
        det_df = det_df[det_df["room_id"].astype(str) == selected_room]

    selected_detectors = st.sidebar.multiselect(
        "Detectors",
        options=sorted(det_df["detector_id"].dropna().astype(str).unique().tolist()),
        default=[],
        help="Leave empty to include all detectors.",
    )

    if selected_detectors:
        det_df = det_df[det_df["detector_id"].astype(str).isin(selected_detectors)]

    if det_df.empty:
        st.warning("No data after detector filters.")
        st.stop()

    for variable in selected_variables:
        var_df = det_df[det_df["variable"] == variable].copy()
        if var_df.empty:
            continue

        st.markdown(f"### {with_unit(variable, variable)}")

        fig = px.line(
            var_df,
            x="hour_utc",
            y="mean_value",
            color="detector_label",
            labels={
                "hour_utc": "Time UTC",
                "mean_value": with_unit(variable, variable),
                "detector_label": "Detector",
            },
            template="plotly_white",
        )
        fig.update_traces(mode=trace_mode)
        fig = add_reference_lines(fig, variable)
        fig.update_layout(height=430, hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        summary = (
            var_df.groupby(["detector_id", "detector_type", "room_id"])["mean_value"]
            .agg(n="count", mean="mean", std="std", min="min", max="max")
            .reset_index()
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)


# ============================================================
# CLOUD DIAGNOSTICS
# ============================================================
elif page_mode == "Cloud diagnostics":
    st.subheader("Cloud database diagnostics")

    health = load_cloud_health()

    st.markdown("### Table counts")
    counts = []
    for table, df in health.items():
        if table.startswith("last") or table == "by_room_variable":
            continue
        row = {"table": table}
        if not df.empty:
            row.update(df.iloc[0].to_dict())
        counts.append(row)
    st.dataframe(pd.DataFrame(counts), use_container_width=True, hide_index=True)

    st.markdown("### Hourly room aggregate status")
    st.dataframe(health["last_room"], use_container_width=True, hide_index=True)

    st.markdown("### Last hour by room and variable")
    st.dataframe(health["by_room_variable"], use_container_width=True, hide_index=True)

    with st.expander("Rooms table"):
        st.dataframe(rooms_df, use_container_width=True, hide_index=True)

    with st.expander("Detectors table"):
        st.dataframe(detectors_df, use_container_width=True, hide_index=True)


# ============================================================
# EXPORT
# ============================================================
else:
    st.subheader("Export hourly cloud data")

    days = st.slider(
        "Range [days]",
        min_value=1,
        max_value=MAX_CLOUD_DAYS,
        value=min(30, MAX_CLOUD_DAYS),
    )

    selected_variables = st.multiselect(
        "Variables",
        options=available_variables,
        default=available_variables,
    )

    room_options = rooms_df["room_id"].tolist() if not rooms_df.empty else []
    selected_rooms = st.multiselect(
        "Rooms",
        options=room_options,
        default=[],
    )

    start_dt = datetime.now(timezone.utc) - timedelta(days=days)

    export_df = load_hourly_room_data(
        variables=tuple(selected_variables),
        rooms=tuple(selected_rooms),
        start_iso=start_dt.isoformat(),
    )

    st.metric("Rows selected", f"{len(export_df):,}")

    if export_df.empty:
        st.warning("No rows selected.")
        st.stop()

    st.dataframe(export_df, use_container_width=True, hide_index=True)

    st.download_button(
        "Download hourly room CSV",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name=f"radonnet_cloud_hourly_room_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    buffer = io.BytesIO()
    export_df.to_excel(buffer, index=False)
    buffer.seek(0)
    st.download_button(
        "Download hourly room Excel",
        data=buffer.getvalue(),
        file_name=f"radonnet_cloud_hourly_room_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ============================================================
# AUTO REFRESH
# ============================================================
if auto_refresh:
    time.sleep(60)
    st.rerun()
