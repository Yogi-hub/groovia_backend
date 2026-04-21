# app.py
import os
import streamlit as st
import requests
import uuid
from pathlib import Path

st.set_page_config(page_title="Groovia", layout="centered")

LOGO_PATH = r"assets/Immigroov_Transparent_Logo.png"
API_URL = os.getenv("BACKEND_URL", "http://localhost:8000") + "/chat"

with st.sidebar:
    if Path(LOGO_PATH).exists():
        st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    if st.button("Clear Chat & Restart"):
        st.session_state.clear()
        st.rerun()

st.title("Groovia")
st.subheader("Immigroov's Virtual Assistant")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Welcome! Please attach your resume to begin."}]
if "resume_uploaded" not in st.session_state:
    st.session_state.resume_uploaded = False

col1, col2 = st.columns([1, 4])
with col1:
    with st.popover("📎 Attach"):
        uploaded_file = st.file_uploader("Upload Resume", type=["pdf", "docx"])

if uploaded_file and not st.session_state.resume_uploaded:
    with st.spinner("Analyzing resume..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        data = {"message": "Analyze my resume.", "thread_id": st.session_state.thread_id}
        response = requests.post(API_URL, files=files, data=data)

        if response.status_code == 200:
            res_content = response.json().get("response", "")
            st.session_state.messages.append({"role": "assistant", "content": res_content})
            st.session_state.resume_uploaded = True
            st.rerun()
        else:
            st.error("Error communicating with backend server")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about your career..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Consulting..."):
            payload = {"message": prompt, "thread_id": st.session_state.thread_id}
            chat_res = requests.post(API_URL, data=payload)

            if chat_res.status_code == 200:
                ans = chat_res.json().get("response", "")
                st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})
            else:
                st.error("Failed to receive response from backend")
