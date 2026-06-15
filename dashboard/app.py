"""Streamlit Pipeline Dashboard for deez-forex-ai.

v0.8.0 M5 — 6-page pipeline monitoring dashboard.
"""
import os
import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE_URL", "http://backend:8000")

st.set_page_config(
    page_title="Deez Forex AI — Pipeline Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("📊 Pipeline Dashboard")

API_BASE = st.sidebar.text_input("Backend API URL", value=API_BASE)

def _get(path: str, params=None):
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def _post(path: str, json=None):
    try:
        resp = requests.post(f"{API_BASE}{path}", json=json, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


# Cache API responses for 30 seconds
@st.cache_data(ttl=30)
def fetch_health():
    return _get("/health")


@st.cache_data(ttl=30)
def fetch_pipeline_summary():
    return _get("/api/v1/data/pipeline/summary")


@st.cache_data(ttl=30)
def fetch_pipeline_jobs(status=None, source=None, limit=100):
    params = {}
    if status:
        params["status"] = status
    if source:
        params["source"] = source
    params["limit"] = limit
    return _get("/api/v1/data/pipeline/jobs", params=params)


@st.cache_data(ttl=30)
def fetch_dead_letter(limit=100):
    return _get("/api/v1/data/pipeline/dead-letter", params={"limit": limit})


@st.cache_data(ttl=60)
def fetch_ingestion_state():
    return _get("/api/v1/data/ingestion-state")


@st.cache_data(ttl=60)
def fetch_gaps(symbol, days=7):
    return _get(f"/api/v1/data/gaps/{symbol}", params={"days": days})


@st.cache_data(ttl=60)
def fetch_pipeline_status():
    return _get("/api/v1/data/pipeline-status")


# ------------------------------------------------------------------
# Sidebar navigation
# ------------------------------------------------------------------
page = st.sidebar.radio(
    "Navigate",
    [
        "🏠 Overview",
        "📥 Ingestion Jobs",
        "💀 Dead Letter",
        "🔍 Gap Analysis",
        "📈 Data Quality",
        "🖥️ System Health",
    ]
)

# ------------------------------------------------------------------
# Page: Overview
# ------------------------------------------------------------------
if page == "🏠 Overview":
    st.title("🏠 Pipeline Overview")
    st.markdown("Real-time status of the tick data ingestion pipeline.")

    col1, col2, col3, col4 = st.columns(4)

    summary = fetch_pipeline_summary() or {}
    breakdown = summary.get("status_breakdown", {})

    col1.metric("Total Jobs", summary.get("total_jobs", 0))
    col2.metric("Running", breakdown.get("running", 0), delta_color="off")
    col3.metric("Completed", breakdown.get("completed", 0), delta_color="off")
    col4.metric("Dead Letter", breakdown.get("dead_letter", 0), delta_color="off")

    st.divider()

    health = fetch_health()
    if health:
        st.success(f"Backend health: {health.get('status', 'unknown')}")
    else:
        st.warning("Backend health check failed")

    st.subheader("Recent Pipeline Activity")
    jobs = fetch_pipeline_jobs(limit=20) or []
    if jobs:
        import pandas as pd
        df = pd.DataFrame(jobs)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No recent jobs found.")

# ------------------------------------------------------------------
# Page: Ingestion Jobs
# ------------------------------------------------------------------
elif page == "📥 Ingestion Jobs":
    st.title("📥 Ingestion Jobs")
    st.markdown("Browse, filter, and manage ingestion jobs.")

    c1, c2 = st.columns(2)
    status_filter = c1.selectbox(
        "Status",
        ["All", "queued", "running", "completed", "failed", "retrying", "dead_letter"],
    )
    source_filter = c2.selectbox("Source", ["All", "dukascopy", "mt5_zmq"])

    params = {"limit": 200}
    if status_filter != "All":
        params["status"] = status_filter
    if source_filter != "All":
        params["source"] = source_filter

    jobs = fetch_pipeline_jobs(**params) or []
    if jobs:
        import pandas as pd
        df = pd.DataFrame(jobs)
        st.dataframe(df, use_container_width=True)
        st.caption(f"Showing {len(jobs)} jobs")
    else:
        st.info("No jobs match the selected filters.")

    st.divider()
    st.subheader("Manual Actions")
    col1, col2 = st.columns(2)
    with col1:
        sym = st.text_input("Symbol", value="EURUSD", key="retry_sym")
        src = st.selectbox("Source", ["dukascopy", "mt5_zmq"], key="retry_src")
        if st.button("🔄 Retry Job"):
            result = _post(f"/api/v1/data/pipeline/jobs/{sym}/retry", json={"source": src})
            if result:
                st.success(f"Retry queued: {result}")
    with col2:
        sym2 = st.text_input("Symbol", value="EURUSD", key="backfill_sym")
        if st.button("🔙 Trigger Backfill"):
            result = _post(f"/api/v1/data/backfill/{sym2}")
            if result:
                st.success(f"Backfill queued: {result}")

# ------------------------------------------------------------------
# Page: Dead Letter
# ------------------------------------------------------------------
elif page == "💀 Dead Letter":
    st.title("💀 Dead Letter Queue")
    st.markdown("Jobs that failed after max retries. You can retry them manually.")

    dl_jobs = fetch_dead_letter(limit=100) or []
    if dl_jobs:
        import pandas as pd
        df = pd.DataFrame(dl_jobs)
        st.dataframe(df, use_container_width=True)
        st.caption(f"{len(dl_jobs)} dead-letter jobs")
    else:
        st.success("No dead-letter jobs — pipeline is healthy!")

    st.divider()
    st.subheader("Bulk Retry")
    if dl_jobs and st.button("🔄 Retry All Dead-Letter Jobs"):
        for job in dl_jobs:
            _post(
                f"/api/v1/data/pipeline/jobs/{job['symbol']}/retry",
                json={"source": job["source"]},
            )
        st.success("Retry requests submitted.")

# ------------------------------------------------------------------
# Page: Gap Analysis
# ------------------------------------------------------------------
elif page == "🔍 Gap Analysis":
    st.title("🔍 Gap Analysis")
    st.markdown("Detect missing data periods per symbol.")

    symbol = st.selectbox(
        "Symbol",
        ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"],
    )
    days = st.slider("Lookback (days)", 1, 30, 7)

    gaps = fetch_gaps(symbol, days) or {}
    gap_list = gaps.get("gaps", [])

    st.metric("Gap Count", gaps.get("gap_count", 0))
    if gap_list:
        import pandas as pd
        df = pd.DataFrame(gap_list)
        st.dataframe(df, use_container_width=True)
    else:
        st.success("No gaps detected for this symbol/period.")

    if st.button("🔙 Backfill Gaps for This Symbol"):
        result = _post(f"/api/v1/data/backfill/{symbol}")
        if result:
            st.success(f"Backfill queued: {result}")

# ------------------------------------------------------------------
# Page: Data Quality
# ------------------------------------------------------------------
elif page == "📈 Data Quality":
    st.title("📈 Data Quality")
    st.markdown("Coverage, tick volume, and source distribution.")

    states = fetch_ingestion_state() or []
    if states:
        import pandas as pd
        df = pd.DataFrame(states)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Ticks Ingested by Symbol")
            chart_df = df.groupby("symbol")["total_ticks"].sum().reset_index()
            st.bar_chart(chart_df.set_index("symbol"))
        with col2:
            st.subheader("Status Distribution")
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            st.bar_chart(status_counts.set_index("status"))

        st.subheader("Source Distribution")
        source_counts = df["source"].value_counts().reset_index()
        source_counts.columns = ["source", "count"]
        st.bar_chart(source_counts.set_index("source"))

        st.subheader("Raw Data")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No ingestion state available yet.")

# ------------------------------------------------------------------
# Page: System Health
# ------------------------------------------------------------------
elif page == "🖥️ System Health":
    st.title("🖥️ System Health")
    st.markdown("Container and database health status.")

    health = fetch_health()
    if health:
        st.json(health)
    else:
        st.error("Cannot reach backend health endpoint.")

    st.divider()
    st.subheader("Quick Actions")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Kill Stale Jobs"):
            result = _post("/api/v1/data/pipeline/kill-stale")
            if result:
                st.success(f"Stale job cleanup queued: {result}")
    with col2:
        if st.button("🔄 Refresh All Data"):
            st.cache_data.clear()
            st.rerun()
