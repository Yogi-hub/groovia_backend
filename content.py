from config import FRONTEND_URL

# Exact phrases the agent echoes verbatim (no LLM call) at clarification gates.
MSG_ASK_FOR_RESUME       = "Please attach your resume or profile to begin."
MSG_RESUME_UPLOADED      = "Your profile has been successfully uploaded. Please select an option below to proceed."
MSG_ASK_TRACK_AND_PREFS  = "To generate your personalized report, are you looking for **Work** or **Study** opportunities? And do you have any specific preferences (e.g., climate, salary expectations, company size)?"
MSG_ASK_TARGET_COUNTRY   = "Which country are you looking to find a mentor in?"
MSG_ASK_FOR_QUESTION     = "Sure — what would you like to know?"
MSG_ACK                  = "Great! Is there anything else you'd like to know? You can also ask for mentors or a fresh career report anytime."


# Prefix kept stable so backend.should_continue can recognise the dynamic message.
NO_MENTORS_PREFIX = "We don't have mentors based in"


def msg_no_mentors_for_country(country_display: str) -> str:
    return (
        f"{NO_MENTORS_PREFIX} **{country_display}** just yet — our network is "
        f"actively expanding there. In the meantime, would you like to explore mentors in "
        f"a nearby country, or browse the full [Mentor Directory]({MENTOR_DISCOVERY_URL})?"
    )

# Frontend INTENT_OPTIONS messages. Keep in sync with groovia-frontend/lib/content.ts.
# Backend uses these for deterministic intent routing.
INTENT_REPORT_PHRASE = "i want to generate a career report."
INTENT_MENTOR_PHRASE = "i want to find a mentor."
INTENT_QNA_PHRASE    = "i just want to ask some questions."

# Reusable links to our own frontend.
MENTOR_DISCOVERY_URL        = f"{FRONTEND_URL}/mentors"
MSG_MENTOR_DISCOVERY        = f"To explore other mentors, please visit the [Mentor Directory]({MENTOR_DISCOVERY_URL})."
MSG_MENTOR_DISCOVERY_REPORT = f"  To explore other options, please visit the [Mentor Directory]({MENTOR_DISCOVERY_URL})."
