from diagrams import Diagram, Cluster, Edge
from diagrams.programming.framework import React, FastAPI
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Postgresql
from diagrams.onprem.network import Internet

graph_attr = {
    "fontsize": "20",
    "bgcolor": "#ffffff",
    "splines": "ortho",
    "nodesep": "1.0",
    "ranksep": "1.2",
    "pad": "0.5",
}

node_attr = {
    "fontsize": "18",
}

with Diagram(
    "Groovia — System Architecture",
    show=False,
    filename="system_architecture.png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):

    # Frontend presentation tier
    with Cluster("Frontend Tier (Vercel)"):
        ui = React("Next.js UI Component")
        proxy = Server("API Edge Route\n/api/chat")
        ui >> Edge(dir="both", color="#94a3b8") >> proxy

    # Backend computation tier
    with Cluster("Backend Compute Tier (Render)"):
        api = FastAPI("FastAPI Gateway")
        orchestrator = Server("LangGraph Engine")
        api >> Edge(dir="both", color="#10b981") >> orchestrator

    # Database storage tier
    with Cluster("Database Tier (Supabase)"):
        db = Postgresql("PostgreSQL Engine\n(Mentors DB)")

    # Third party external integrations
    with Cluster("External Integrations Layer"):
        groq = Internet("Groq Cloud\n(LLM Inference)")
        tavily = Internet("Tavily AI\n(General Search)")
        exa = Internet("Exa API\n(Precise Search)")
        cal = Internet("Cal.com\n(Scheduling Interface)")

    # Client application transport channel
    proxy >> Edge(label="HTTPS POST /chat", dir="both", color="#2563eb") >> api

    # State engine persistence routing
    orchestrator >> Edge(label="SQL Read/Write", dir="both", color="#dc2626") >> db

    # Cognitive processing and auxiliary tool loops
    orchestrator >> Edge(label="Payload Loop", dir="both", color="#7c3aed") >> groq
    orchestrator >> Edge(label="Context Queries", dir="both", color="#059669") >> [tavily, exa]
    orchestrator >> Edge(label="Delivery Links", color="#ea580c") >> cal