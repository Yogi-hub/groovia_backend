# app.py
import streamlit as st
import requests
import uuid
from pathlib import Path

# set page configuration
st.set_page_config(page_title="Groovia", layout="centered")

# define local asset path
LOGO_PATH = r"assets/Immigroov_Transparent_Logo.png"

# define the backend api endpoint
API_URL = "http://localhost:8000/chat"

# create sidebar layout
with st.sidebar:
    # display logo if file exists
    if Path(LOGO_PATH).exists():
        st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    # reset session state variables
    if st.button("Clear Chat & Restart"):
        st.session_state.clear()
        st.rerun()

# set application titles
st.title("Groovia")
st.subheader("Immigroov's Virtual Assistant")

# initialize persistent thread id
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
# initialize message history
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Welcome! Please attach your resume to begin."}]
# track resume upload status
if "resume_uploaded" not in st.session_state:
    st.session_state.resume_uploaded = False

# create layout columns for attachment
col1, col2 = st.columns([1, 4])
with col1:
    # define file uploader in popover
    with st.popover("📎 Attach"):
        uploaded_file = st.file_uploader("Upload Resume", type=["pdf", "docx"])

# handle initial resume submission to backend
if uploaded_file and not st.session_state.resume_uploaded:
    with st.spinner("Analyzing resume..."):
        # prepare multi-part form data
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        data = {"message": "Analyze my resume.", "thread_id": st.session_state.thread_id}
        # send post request to fastapi handler
        response = requests.post(API_URL, files=files, data=data)
        
        if response.status_code == 200:
            # extract response and update state
            res_content = response.json().get("response", "")
            st.session_state.messages.append({"role": "assistant", "content": res_content})
            st.session_state.resume_uploaded = True
            st.rerun()
        else:
            st.error("Error communicating with backend server")

# render message history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# handle user chat input
if prompt := st.chat_input("Ask about your career..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Consulting..."):
            # prepare payload for chat request
            payload = {"message": prompt, "thread_id": st.session_state.thread_id}
            # send request to api endpoint
            chat_res = requests.post(API_URL, data=payload)
            
            if chat_res.status_code == 200:
                # display and store backend response
                ans = chat_res.json().get("response", "")
                st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})
            else:
                st.error("Failed to receive response from backend")