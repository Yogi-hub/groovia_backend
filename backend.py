import os
from typing import Annotated, TypedDict, List, Optional
from dotenv import load_dotenv

# Environment initialization
load_dotenv(override=True)

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from utils import extract_resume_tool, career_market_search, neural_research_tool
from prompts import SYSTEM_PROMPT, REVIEWER_PROMPT

# Critical parameter
MODEL_NAME = "openai/gpt-oss-120b"

# Critical parameter
TEMPERATURE = 0.0

# General parameter
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

llm = ChatGroq(model=MODEL_NAME, temperature=TEMPERATURE, api_key=GROQ_API_KEY)

# Tool registry
tools = [
    extract_resume_tool, 
    career_market_search, 
    neural_research_tool
]
llm_with_tools = llm.bind_tools(tools)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    resume_path: Optional[str]
    critique: Optional[str]
    revision_count: int

def call_model(state: AgentState):
    messages = state['messages']
    resume_path = state.get('resume_path')
    critique = state.get('critique')
    
    prompt = SYSTEM_PROMPT
    
    # Path normalization
    if resume_path:
        normalized_path = resume_path.replace("\\", "/")
        prompt += f"\n\nCOMMAND: You must now call 'extract_resume_tool' with file_path='{normalized_path}' to parse the user's resume."
    
    # Feedback injection
    if critique and critique != "PASSED":
        prompt += f"\n\n### CRITICAL FEEDBACK FROM AUDITOR ###\n{critique}\n"
        prompt += "Please revise your previous draft to address the feedback above."
        
    filtered_messages = [m for m in messages if not isinstance(m, SystemMessage)]
    messages = [SystemMessage(content=prompt)] + filtered_messages
        
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def reviewer_node(state: AgentState):
    last_msg = state['messages'][-1]
    review_input = [SystemMessage(content=REVIEWER_PROMPT), HumanMessage(content=last_msg.content)]
    critique = llm.invoke(review_input)
    return {"critique": critique.content, "revision_count": state.get("revision_count", 0) + 1}

def should_revise(state: AgentState):
    if state.get("revision_count", 0) >= 2 or "PASSED" in state.get("critique", ""):
        return END
    return "agent"

def should_continue(state: AgentState):
    last_message = state['messages'][-1]
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    
    content = str(last_message.content).lower()
    if "top 5" not in content and any(x in content for x in ["work", "study", "expectations"]):
        return END
        
    return "reviewer"

# Graph orchestration
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("reviewer", reviewer_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "reviewer": "reviewer", END: END})
workflow.add_conditional_edges("reviewer", should_revise, {"agent": "agent", END: END})
workflow.add_edge("tools", "agent")

memory = MemorySaver()
app = workflow.compile(checkpointer=memory)