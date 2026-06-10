# generate_architecture.py
# Dev-only script. Produces system_architecture.png using the `diagrams` library.
# Run locally:  pip install diagrams  &&  python generate_architecture.py
# (Note: `diagrams` requires Graphviz installed on PATH.)
# The script renders the full Slice 0 architecture: browser, Vercel frontend,
# Render backend, Supabase Postgres + Auth, and all third-party services.

from diagrams import Diagram, Cluster, Edge
from diagrams.programming.framework import React, FastAPI
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Postgresql
from diagrams.onprem.network import Internet

graph_attr = {
    "fontsize": "16",
    "bgcolor": "#FAFBFD",
    "splines": "ortho",
    "nodesep": "0.7",
    "ranksep": "1.0",
    "pad": "0.6",
    "labelloc": "t",
}

node_attr = {"fontsize": "12"}

with Diagram(
    "Groovia by Immigroov — System Architecture (Slice 0)",
    show=False,
    filename="system_architecture",
    direction="TB",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = Server("Candidate\n(browser)")

    # FRONTEND — Vercel (Next.js)
    with Cluster("Frontend  •  Vercel  •  Next.js 16 App Router"):
        with Cluster("SSR pages (Server Components)"):
            chat_page = React("/chat\n(intro + ChatInterface)")
            mentors_page = React("/mentors\n/mentors/[slug]")
            auth_pages = React("/login  /signup\n/verify-email\n/forgot-password")

        with Cluster("Client components"):
            sidebar = React("Sidebar\n+ HistoryList")
            chat_ui = React("ChatInterface\n+ AuthGate modal")

        with Cluster("BFF proxy routes  /api/*"):
            bff_chat = Server("/api/chat\n(forwards JWT)")
            bff_threads = Server("/api/chat/threads/*\n(list / messages / claim)")
            bff_check = Server("/api/auth/check-email")

        sb_client_browser = Server("Supabase JS\n(anon key + cookies)")

    # BACKEND — Render (FastAPI + LangGraph)
    with Cluster("Backend  •  Render  •  FastAPI + LangGraph"):
        with Cluster("Routers"):
            r_auth = FastAPI("routers/auth.py\n/auth/check-email")
            r_chat = FastAPI("routers/chat.py\n/chat\n/chat/threads + claim/messages")
            r_mentors = FastAPI("routers/mentors.py\n/mentors\n/mentors/{slug}")

        auth_dep = Server("auth.py\nJWT verify (HS256, local)")
        db_layer = Server("db.py\nSupabase service-role client")

        with Cluster("LangGraph Agent"):
            graph_engine = Server("StateGraph\ncompressor → agent → tools → reviewer\n(AsyncPostgresSaver)")
            tools_node = Server("Tools\n• general_search  (Tavily)\n• precise_search  (Exa)\n• retrieve_mentors  (Supabase)")

    # DATA TIER — Supabase
    with Cluster("Supabase  •  Postgres + Auth  •  EU West"):
        with Cluster("auth schema (managed by Supabase)"):
            sb_auth = Server("auth.users\n+ Supabase Auth\n(email/password, Google OAuth)")

        with Cluster("public schema — application tables"):
            t_profiles = Postgresql("profiles\n(extends auth.users:\nrole, country, credits,\nattribution)")
            t_mentors = Postgresql("mentors\n(slug, expertise arrays,\nbooking_url, status)")
            t_threads = Postgresql("chat_threads\n(thread metadata,\nuser_id, title)")
            t_consent = Postgresql("consent_log\n(GDPR audit trail)")

        with Cluster("public schema — LangGraph checkpoints"):
            t_ckpt = Postgresql("checkpoints\ncheckpoint_writes\ncheckpoint_blobs")

    # EXTERNAL SERVICES
    with Cluster("External services"):
        groq = Internet("Groq Cloud\nLlama-3.3-70b\n+ Llama-3.1-8b")
        tavily = Internet("Tavily AI\nweb search")
        exa = Internet("Exa\nneural search")
        google = Internet("Google OAuth")
        cal = Internet("Cal.com\n(mentor booking)")

    # USER → FRONTEND
    user >> Edge(color="#1D4ED8") >> chat_page

    # FRONTEND internal wiring
    chat_page >> Edge(color="#94a3b8") >> chat_ui
    chat_page >> Edge(color="#94a3b8") >> sidebar
    mentors_page >> Edge(color="#94a3b8") >> sb_client_browser
    auth_pages >> Edge(color="#94a3b8") >> sb_client_browser
    chat_ui >> Edge(color="#94a3b8") >> sb_client_browser
    chat_ui >> Edge(label="POST", color="#1D4ED8") >> bff_chat
    chat_ui >> Edge(color="#1D4ED8") >> bff_threads
    sidebar >> Edge(color="#1D4ED8") >> bff_threads
    auth_pages >> Edge(color="#1D4ED8") >> bff_check

    # SUPABASE AUTH (browser side)
    sb_client_browser >> Edge(label="sign in / signUp /\nOAuth code exchange", color="#F59E0B", style="dashed") >> sb_auth
    sb_auth >> Edge(label="JWT (HS256)\nstored in cookies", color="#F59E0B", style="dashed") >> sb_client_browser

    # FRONTEND BFF → BACKEND
    bff_chat >> Edge(label="HTTPS + JWT", color="#0F2C6B") >> r_chat
    bff_threads >> Edge(label="HTTPS + JWT", color="#0F2C6B") >> r_chat
    bff_check >> Edge(label="HTTPS", color="#0F2C6B") >> r_auth

    # BACKEND internal wiring
    r_chat >> Edge(label="Depends()", color="#94a3b8") >> auth_dep
    r_chat >> Edge(color="#94a3b8") >> db_layer
    r_mentors >> Edge(color="#94a3b8") >> db_layer
    r_chat >> Edge(label="ainvoke()", color="#10b981") >> graph_engine
    graph_engine >> Edge(color="#10b981") >> tools_node
    tools_node >> Edge(color="#94a3b8") >> db_layer

    # BACKEND → SUPABASE
    db_layer >> Edge(label="service_role\n(bypasses RLS)", color="#dc2626") >> t_profiles
    db_layer >> Edge(color="#dc2626") >> t_mentors
    db_layer >> Edge(color="#dc2626") >> t_threads
    db_layer >> Edge(color="#dc2626") >> t_consent
    graph_engine >> Edge(label="checkpoint write/read", color="#dc2626") >> t_ckpt

    # LLM + tools traffic
    graph_engine >> Edge(label="prompts / tool calls", color="#7c3aed") >> groq
    tools_node >> Edge(label="search queries", color="#059669") >> tavily
    tools_node >> Edge(color="#059669") >> exa

    # OAuth flow
    sb_client_browser >> Edge(label="OAuth", color="#F59E0B", style="dashed") >> google
    google >> Edge(style="dashed", color="#F59E0B") >> sb_auth

    # Mentor booking opens Cal.com in a new tab
    mentors_page >> Edge(label="external link", color="#ea580c") >> cal

    # Trigger creates profile row on new auth.users
    sb_auth >> Edge(label="trigger\nhandle_new_user()", color="#dc2626") >> t_profiles
