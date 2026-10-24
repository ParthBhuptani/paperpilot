from dotenv import load_dotenv
load_dotenv()

import os
import re
import time
import requests
import streamlit as st
import xml.etree.ElementTree as ET
from google import genai

NS = {"a": "http://www.w3.org/2005/Atom"}
MODELS = ["gemma-4-26b-a4b-it", "gemma-4-31b-it"]

st.set_page_config(page_title="PaperPilot", page_icon="📄", layout="wide")


def get_secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


GEMINI_KEY = get_secret("GEMINI_API_KEY")
if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY. Add it in the app's Secrets settings.")
    st.stop()

client = genai.Client(api_key=GEMINI_KEY)

GH_HEADERS = {"Accept": "application/vnd.github+json"}
if get_secret("GITHUB_TOKEN"):
    GH_HEADERS["Authorization"] = f"Bearer {get_secret('GITHUB_TOKEN')}"

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
.hero {
    background: linear-gradient(135deg, #6C63FF 0%, #00C9A7 100%);
    padding: 28px 32px; border-radius: 16px; margin-bottom: 18px;
}
.hero h1 {color: #ffffff; margin: 0; font-size: 2.4rem;}
.hero p {color: #f0f0ff; margin: 6px 0 0; font-size: 1.05rem;}
h2, h3 {color: #8F88FF !important;}
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    background: linear-gradient(135deg, #6C63FF, #00C9A7);
    color: #ffffff; border: 0; border-radius: 10px; font-weight: 600;
}
.stButton > button:hover, .stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {filter: brightness(1.12); color: #ffffff;}
button[data-baseweb="tab"] {font-weight: 600; font-size: 1rem;}
a {color: #00C9A7 !important;}
</style>
""", unsafe_allow_html=True)


def ask(prompt):
    last_err = None
    for model in MODELS:
        for attempt in range(3):
            try:
                return client.models.generate_content(model=model, contents=prompt).text
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
    return ("The model is temporarily busy. Please click the button again in a few "
            f"seconds. ({last_err})")


@st.cache_data(ttl=600)
def search_arxiv(topic, latest, n=8):
    terms = " AND ".join(f"all:{w}" for w in topic.split())
    params = {
        "search_query": terms,
        "start": 0,
        "max_results": n,
        "sortBy": "submittedDate" if latest else "relevance",
        "sortOrder": "descending",
    }
    r = requests.get("https://export.arxiv.org/api/query", params=params, timeout=20)
    root = ET.fromstring(r.text)
    papers = []
    for e in root.findall("a:entry", NS):
        papers.append({
            "title": " ".join(e.find("a:title", NS).text.split()),
            "abstract": " ".join(e.find("a:summary", NS).text.split()),
            "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)],
            "date": e.find("a:published", NS).text[:10],
            "link": e.find("a:id", NS).text,
        })
    return papers


def looks_like_list(repo):
    text = f"{repo['name']} {repo.get('description') or ''}".lower()
    junk = ("awesome", "daily", "digest", "paper-list", "papers", "arxiv-", "news", "curated")
    return any(j in text for j in junk)


@st.cache_data(ttl=600)
def find_repos(title, link):
    arxiv_id = re.sub(r"v\d+$", "", link.split("/abs/")[-1])
    stop = {"the", "and", "for", "with", "from", "towards", "toward", "using", "via",
            "into", "based", "through", "that", "this", "are", "its", "survey"}
    words = [w for w in title.replace(":", " ").replace("-", " ").replace(",", " ").split()
             if len(w) > 3 and w.lower() not in stop]
    queries = [f'"{arxiv_id}" in:readme']
    for n in (5, 4, 3):
        queries.append(" ".join(words[:n]) + " in:name,description stars:>3")
    for q in queries:
        try:
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": q, "per_page": 8},
                headers=GH_HEADERS,
                timeout=15,
            )
            items = [i for i in r.json().get("items", []) if not looks_like_list(i)][:5]
        except Exception:
            items = []
        if items:
            return items
    return []


def paper_context(p):
    return (f"Title: {p['title']}\nAuthors: {', '.join(p['authors'][:6])}\n"
            f"Date: {p['date']}\nAbstract: {p['abstract']}")


# ---------- UI ----------
st.markdown("""
<div class="hero">
  <h1>📄 PaperPilot</h1>
  <p>From research paper to open-source contribution. Find the latest papers, get instant
  summaries, ask follow-ups, generate project ideas and discover related code,
  powered by open-weight Gemma 4.</p>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns([3, 2, 1])
topic = c1.text_input("Research topic", "retrieval augmented generation")
mode = c2.radio("Sort by", ["Latest", "Most relevant"], horizontal=True)
go = c3.button("Search", use_container_width=True)

level = st.radio("Explain summaries at", ["Beginner", "Student", "Expert"],
                 index=1, horizontal=True)

if go and topic.strip():
    try:
        st.session_state.papers = search_arxiv(topic.strip(), mode == "Latest")
    except Exception as e:
        st.error(f"Search failed: {e}")
        st.session_state.papers = []
    st.session_state.sel = None

papers = st.session_state.get("papers", [])

if go and not papers:
    st.warning("No papers found. Try a different topic.")

if papers:
    left, right = st.columns([1, 2])

    with left:
        st.subheader("Results")
        for i, p in enumerate(papers):
            with st.container(border=True):
                st.markdown(f"**{p['title']}**")
                st.caption(f"{p['date']} · {', '.join(p['authors'][:2])}"
                           f"{' et al.' if len(p['authors']) > 2 else ''}")
                if st.button("Analyze", key=f"analyze_{i}"):
                    st.session_state.sel = i
                    st.session_state.chat = []
                    st.session_state.ideas = None
                    with st.spinner("Gemma 4 is reading the paper..."):
                        st.session_state.summary = ask(
                            f"Summarize this research paper for a {level.lower()}-level reader.\n"
                            "Give: 1) TL;DR in one line, 2) the problem, 3) the approach, "
                            "4) key findings, 5) limitations. Use only the information given; "
                            "if something is not stated, say so.\n\n" + paper_context(p))

    with right:
        sel = st.session_state.get("sel")
        if sel is None:
            st.info("👈 Pick a paper and click **Analyze**.")
        else:
            p = papers[sel]
            st.subheader(p["title"])
            st.caption(f"{p['date']} · {', '.join(p['authors'][:5])}")
            pdf = p["link"].replace("/abs/", "/pdf/")
            st.markdown(f"[Open on arXiv]({p['link']}) · [PDF]({pdf})")

            tab1, tab2, tab3, tab4 = st.tabs(
                ["📝 Summary", "💬 Ask follow-ups", "💡 Project ideas", "🔗 Open-source code"])

            with tab1:
                st.markdown(st.session_state.get("summary", ""))
                if st.session_state.get("summary"):
                    st.download_button("⬇ Download summary", st.session_state.summary,
                                       file_name="summary.md")

            with tab2:
                for m in st.session_state.get("chat", []):
                    with st.chat_message(m["role"]):
                        st.markdown(m["content"])
                with st.form("qa", clear_on_submit=True):
                    q = st.text_input("Ask anything about this paper")
                    sent = st.form_submit_button("Ask")
                if sent and q.strip():
                    history = "\n".join(
                        f"{m['role']}: {m['content']}" for m in st.session_state.chat[-6:])
                    with st.spinner("Thinking..."):
                        a = ask(
                            "You are a research assistant. Answer the question about this "
                            "paper using the information below. If the answer is not in it, "
                            "say so and give a careful general explanation.\n\n"
                            f"{paper_context(p)}\n\nConversation so far:\n{history}\n\n"
                            f"Question: {q}")
                    st.session_state.chat.append({"role": "user", "content": q})
                    st.session_state.chat.append({"role": "assistant", "content": a})
                    st.rerun()

            with tab3:
                if st.button("Generate project ideas"):
                    with st.spinner("Brainstorming..."):
                        st.session_state.ideas = ask(
                            "Based on this paper, suggest 3 project ideas a student can build "
                            "in a weekend. For each: name, what it does, tech stack, and the "
                            "first 3 steps.\n\n" + paper_context(p))
                if st.session_state.get("ideas"):
                    st.markdown(st.session_state.ideas)

            with tab4:
                st.caption("Repos that cite this paper, or the closest open-source projects. "
                           "Open the issues link to start contributing.")
                repos = find_repos(p["title"], p["link"])
                if not repos:
                    st.info("No open-source code found for this paper yet. It may be too new. "
                            "Try an established topic like RAG or LoRA.")
                for repo in repos:
                    st.markdown(f"**[{repo['full_name']}]({repo['html_url']})** "
                                f"⭐ {repo['stargazers_count']}")
                    st.write(repo["description"] or "No description")
                    st.markdown(f"[Good first issues]({repo['html_url']}/issues?q=is%3Aopen"
                                f"+label%3A%22good+first+issue%22)")
                    st.divider()