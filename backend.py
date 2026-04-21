# backend.py
import groq
from typing import Annotated, TypedDict, Optional
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

import config
from utils import career_market_search, neural_research_tool
from prompts import SYSTEM_PROMPT, REVIEWER_PROMPT, ROUTER_PROMPT, COMPRESSION_PROMPT
from config import GROQ_API_KEY, MAIN_MODEL_NAME, FALLBACK_MODEL_NAME, TEMPERATURE, MAX_REVISION

system_prompt = SYSTEM_PROMPT.format(num_countries=config.NUM_COUNTRIES)
reviewer_prompt = REVIEWER_PROMPT.format(num_countries=config.NUM_COUNTRIES)

# initialize the primary reasoning and fallback models
primary_llm = ChatGroq(model=MAIN_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
fallback_llm = ChatGroq(model=FALLBACK_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)
router_llm_base = ChatGroq(model=config.ROUTER_MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)

class AgentState(TypedDict):
    # state schema defining the keys for the agentic workflow
    messages: Annotated[list, add_messages]
    resume_text: Optional[str]
    resume_processed: bool 
    track: Optional[str] 
    revision_count: int
    search_route: Optional[str]
    critique: Optional[str]

def router_node(state: AgentState):
    # uses the router model to classify search intent
    last_message = state['messages'][-1].content
    prompt = [SystemMessage(content=ROUTER_PROMPT.format(query=last_message))]
    try:
        response = router_llm_base.invoke(prompt)
    except Exception:
        response = fallback_llm.invoke(prompt)
    return {"search_route": "EXA" if "EXA" in response.content.upper() else "TAVILY"}

def compressor_node(state: AgentState):
    # uses the compressor model to generate a high-density summary
    if state.get("resume_processed"):
        return state
        
    raw_text = state.get("resume_text")
    if not raw_text:
        return state
        
    summary = fallback_llm.invoke([SystemMessage(content=COMPRESSION_PROMPT), HumanMessage(content=raw_text)]).content
    return {"resume_text": summary, "resume_processed": True}

def call_model(state: AgentState):
    # uses the drafter model to generate career recommendations
    messages = state['messages']
    resume_summary = state.get('resume_text', 'No resume available.')
    track = state.get('track', 'Not yet determined')
    critique = state.get('critique', 'None')
    
    if track == 'Not yet determined' and len(messages) > 1:
        text = messages[-1].content.lower()
        if any(w in text for w in ["study", "education"]): track = "STUDY"
        elif any(w in text for w in ["work", "job", "career"]): track = "WORK"

    # implements a sliding window to keep the context under token limits
    truncated_history = messages[-6:] if len(messages) > 6 else messages
    
    instruction = system_prompt + f"\n\n[LOCKED_CONTEXT]\nTRACK: {track}\nRESUME_SUMMARY: {resume_summary}\nFEEDBACK: {critique}"
    
    # combines the system instruction with the truncated message history
    payload = [SystemMessage(content=instruction)] + truncated_history
    search_tool = neural_research_tool if state.get('search_route') == "EXA" else career_market_search
    
    try:
        response = primary_llm.bind_tools([search_tool]).invoke(payload)
    except Exception:
        response = fallback_llm.bind_tools([search_tool]).invoke(payload)

    return {"messages": [response], "track": track}

def reviewer_node(state: AgentState):
    # uses the reviewer model to audit the report against quality standards
    last_msg = state['messages'][-1]
    if len(last_msg.content) < 500:
        return {"critique": "PASSED", "revision_count": state.get("revision_count", 0)}
    prompt = [SystemMessage(content=reviewer_prompt), HumanMessage(content=last_msg.content)]
    try:
        critique = primary_llm.invoke(prompt)
    except Exception:
        critique = fallback_llm.invoke(prompt)
    return {"critique": critique.content, "revision_count": state.get("revision_count", 0) + 1}

def should_revise(state: AgentState):
    # logic to terminate the reflection cycle or return to the drafter
    if state.get("revision_count", 0) >= config.MAX_REVISION or "PASSED" in state.get("critique", ""):
        return END
    return "agent"

def should_continue(state: AgentState):
    # determines if the graph should execute tool calls or proceed to review
    last_message = state['messages'][-1]
    return "tools" if (hasattr(last_message, 'tool_calls') and last_message.tool_calls) else "reviewer"

# defines the topology of the agentic graph
workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)
workflow.add_node("compressor", compressor_node)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode([career_market_search, neural_research_tool]))
workflow.add_node("reviewer", reviewer_node)

workflow.add_edge(START, "router")
workflow.add_edge("router", "compressor")
workflow.add_edge("compressor", "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "reviewer": "reviewer"})
workflow.add_conditional_edges("reviewer", should_revise, {"agent": "agent", END: END})
workflow.add_edge("tools", "agent")

app = workflow.compile(checkpointer=MemorySaver())

# try:
#     # generates a mermaid-style png if the required libraries are installed
#     png_data = app.get_graph().draw_mermaid_png()
#     with open("graph_visualization.png", "wb") as f:
#         f.write(png_data)
#     print("# [INFO] Graph visualization saved as graph_visualization.png")
# except Exception as e:
#     print(f"# [INFO] Visualization failed: {e}. Ensure pygraphviz or similar is installed.")