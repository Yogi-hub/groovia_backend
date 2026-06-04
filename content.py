# content.py
# All user-facing strings. Edit here to change the wording without touching logic files.
# These are the phrases the LLM is instructed to echo verbatim plus any reusable links.

# ---- Required exact phrases ----
MSG_ASK_FOR_RESUME       = "Please attach your resume or profile to begin."
MSG_RESUME_UPLOADED      = "Your profile has been successfully uploaded. Please select an option below to proceed."
MSG_ASK_TRACK_AND_PREFS  = "To generate your personalized report, are you looking for **Work** or **Study** opportunities? And do you have any specific preferences (e.g., climate, salary expectations, company size)?"
MSG_ASK_TARGET_COUNTRY   = "Which country are you looking to find a mentor in?"

# ---- Reusable links ----
MENTOR_DISCOVERY_URL    = "https://immigroov.com/mentor-profiles-discovery"
MSG_MENTOR_DISCOVERY    = f"To explore other mentors, please visit our [Mentor Discovery Page]({MENTOR_DISCOVERY_URL})."
MSG_MENTOR_DISCOVERY_REPORT = f"  To explore other options, please visit our [Mentor Discovery Page]({MENTOR_DISCOVERY_URL})."
