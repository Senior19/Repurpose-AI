import os
import sys
from pathlib import Path

import streamlit as st

# Make backend modules importable and expose Streamlit secrets as env vars (API keys)
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    for k, v in st.secrets.items():
        if isinstance(v, str):
            os.environ.setdefault(k, v)
except Exception:
    pass

st.set_page_config(page_title="RepurposeAI", page_icon="💊", layout="wide")
st.title("💊 RepurposeAI")
st.caption("AI-assisted drug repurposing research dashboard")

try:
    import main as backend
    import db
    from schemas import ResearchRun, new_id
except Exception as e:
    st.error(f"Backend failed to import: {e}")
    st.stop()


def friendly(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        st.error(getattr(e, "detail", None) or str(e))
        return None


tab1, tab2, tab3, tab4 = st.tabs(["🧬 Disease", "💊 Drug", "📚 Literature", "🔬 Investigate"])

with tab1:
    q = st.text_input("Disease", placeholder="e.g. Parkinson's disease", key="d")
    if st.button("Explore disease") and q:
        with st.spinner("Fetching..."):
            r = friendly(backend.disease_explorer, q)
        if r:
            st.subheader(r["disease"])
            st.write(r["overview"])
            st.caption(f"Source: {r['overview_source']}")
            if r.get("overview_url"):
                st.markdown(f"[Read more]({r['overview_url']})")
            if r["targets"]:
                st.markdown("**Associated targets**")
                st.dataframe(r["targets"], use_container_width=True)
            for g in r["gaps"]:
                st.info(g)

with tab2:
    q = st.text_input("Drug", placeholder="e.g. metformin", key="g")
    if st.button("Explore drug") and q:
        with st.spinner("Fetching..."):
            r = friendly(backend.drug_explorer, q)
        if r:
            st.subheader(r.get("name", q))
            for key in ["description", "mechanisms", "safety", "clinical_trials", "publications"]:
                if r.get(key):
                    with st.expander(key.replace("_", " ").title(), expanded=key == "description"):
                        st.write(r[key])
            for g in r.get("gaps", []):
                st.info(g)

with tab3:
    q = st.text_input("Literature query", placeholder="e.g. metformin alzheimer", key="l")
    if st.button("Search literature") and q:
        with st.spinner("Searching PubMed..."):
            r = friendly(backend.literature_explorer, q)
        if r:
            if r.get("ai_summary"):
                st.write(r["ai_summary"])
            for a in r.get("articles", []):
                st.markdown(f"- [{a.get('title')}]({a.get('url')}) ({a.get('pubdate')})")

with tab4:
    d = st.text_input("Disease to investigate", placeholder="e.g. Alzheimer's disease", key="i")
    if st.button("Run full investigation") and d:
        with st.spinner("Running multi-agent pipeline (this can take a few minutes)..."):
            run = ResearchRun(id=new_id("run"), disease=d.strip())
            db.save_run(run)
            backend.run_pipeline(run.id)
            result = db.get_run(run.id).to_dict()
        if result.get("status") == "error":
            st.error(result.get("error"))
        else:
            st.success("Done")
            st.write(result.get("report"))
            with st.expander("Candidates (raw)"):
                st.json(result.get("candidates"))