import streamlit as st
import uuid
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage
from backend import app

# Setup
st.set_page_config(page_title="Groovia", layout="centered")

# CSS
st.markdown("""
    <style>
    /* Remove background from all chat avatar containers */
    div[data-testid^="stChatMessageAvatar"] {
        background-color: transparent !important;
        border: none !important;
    }
    
    /* Remove background from inner avatar elements */
    div[data-testid^="stChatMessageAvatar"] > div {
        background-color: transparent !important;
    }

    /* Increase icon size */
    div[data-testid^="stChatMessageAvatar"] span, 
    div[data-testid^="stChatMessageAvatar"] img {
        font-size: 2.5rem !important;
        width: 45px !important;
        height: 45px !important;
    }
    </style>
""", unsafe_allow_html=True)

# Assets
LOGO_PATH = r"assets/Immigroov_Transparent_Logo.png"
USER_ICON = "👤"
BOT_ICON = "🤖"

# Sidebar
with st.sidebar:
    if Path(LOGO_PATH).exists():
        # Updated width parameter for 2026
        st.image(LOGO_PATH, width='stretch')
    else:
        st.error(f"Logo not found at: {LOGO_PATH}")
    
    st.markdown("---")
    st.write("### Session Controls")
    if st.button("Clear Chat & Restart"):
        st.session_state.clear()
        st.rerun()

# Titles
st.title("Groovia")
st.subheader("Immigroov's Virtual Intelligent Assistant")

# State
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Welcome! Please attach your resume using the button below so I can begin your global career analysis."}]
if "resume_uploaded" not in st.session_state:
    st.session_state.resume_uploaded = False

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# UI
col1, col2 = st.columns([1, 4])
with col1:
    with st.popover("📎 Attach"):
        uploaded_file = st.file_uploader("Upload Resume", type=["pdf", "docx"])

# Logic
if uploaded_file and not st.session_state.resume_uploaded:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    file_path = data_dir / uploaded_file.name
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    inputs = {
        "messages": [HumanMessage(content="Analyze my resume.")],
        "resume_path": str(file_path),
        "revision_count": 0
    }
    
    with st.spinner("Analyzing..."):
        for event in app.stream(inputs, config):
            pass 
        state = app.get_state(config)
        last_msg = state.values["messages"][-1]
        st.session_state.messages.append({"role": "assistant", "content": last_msg.content})
        st.session_state.resume_uploaded = True
        st.rerun()

# Chat
for msg in st.session_state.messages:
    icon = BOT_ICON if msg["role"] == "assistant" else USER_ICON
    with st.chat_message(msg["role"], avatar=icon):
        st.markdown(msg.get("content", ""))

# Input
if prompt := st.chat_input("Ask about your career..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=BOT_ICON):
        with st.spinner("Consulting..."):
            user_input = {"messages": [HumanMessage(content=prompt)]}
            for event in app.stream(user_input, config):
                pass
            state = app.get_state(config)
            final_msg = state.values["messages"][-1].content
            
            if not final_msg:
                final_msg = "Error: Please try again."
                
            st.markdown(final_msg)
            st.session_state.messages.append({"role": "assistant", "content": final_msg})
