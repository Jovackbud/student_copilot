# agent_core.py — Sovereign tool-calling agent (zero framework dependency)
# All langchain agent factories (create_agent, create_tool_calling_agent,
# create_react_agent) now internally produce LangGraph CompiledStateGraphs
# that expect {"messages": [...]} input. This is fundamentally incompatible
# with the RunnableWithMessageHistory wrapping that passes dict-based inputs
# {"input", "chat_history", "user_profile", "file_summaries"}.
#
# Solution: Manual tool-calling loop via RunnableLambda. Full control,
# zero volatility, proper prompt rendering, complete tool execution.

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.messages import ToolMessage

from typing import Dict, Any

from llm_setup import llm
from tools_setup import tools
from session_manager import get_conversation_history, SESSIONS
from config import logger

# ─── SYSTEM PROMPT ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a friendly and knowledgeable AI tutor designed to answer children's questions appropriately for their age, country, and school grade.

**How to Answer:**
1.  **Student Context:** Tailor your language, examples, and depth to the `user_profile` (age, country, class). Default to an elementary school level if no profile is provided.
2.  **File Summaries:** If the user references an uploaded document, prioritize its summary from `{file_summaries}`. Cite the filename when relevant.
3.  **Web Search:** If you lack information, need current data, or the topic is time-sensitive, use the `tavily_search` tool. Synthesize results into a clear, child-friendly answer and include relevant source URLs.
4.  **Direct Answer:** Otherwise, answer directly from your knowledge base or conversation history.
5.  **Clarity & Conciseness:** Use simple words and concepts. Avoid jargon or explain it clearly. Be concise, but expand if a deeper explanation genuinely aids understanding.
6.  **Safety:** Ensure all answers are safe, appropriate for children, and avoid harmful/inappropriate content. You may recommend further safe reading or resources.

**Current Context:**
- User Profile: `{user_profile}`
- Uploaded Summaries: `{file_summaries}`\
"""

# Prompt template: system + history + user input (no agent_scratchpad needed)
_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("user", "{input}"),
])

# ─── SOVEREIGN TOOL-CALLING LOOP ───────────────────────────────────────────
_llm_with_tools = llm.bind_tools(tools) if tools else llm
_tool_map: Dict[str, Any] = {t.name: t for t in tools} if tools else {}
_MAX_TOOL_ITERATIONS = 5


async def _sovereign_agent(input_dict: dict, config=None) -> dict:
    """
    Manual tool-calling agent loop.
    Renders prompt → calls LLM → executes any tool calls → loops until text response.
    Fully compatible with RunnableWithMessageHistory's dict-based input.
    """
    # 1. Render the prompt template into messages
    rendered = _prompt.invoke({
        "input": input_dict.get("input", ""),
        "chat_history": input_dict.get("chat_history", []),
        "user_profile": input_dict.get("user_profile", "no profile provided"),
        "file_summaries": input_dict.get("file_summaries", "no uploaded file summaries"),
    })
    messages = list(rendered.to_messages())

    # 2. Tool-calling loop (bounded)
    response = None
    for iteration in range(_MAX_TOOL_ITERATIONS):
        response = await _llm_with_tools.ainvoke(messages, config=config)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            break  # No tool calls — we have the final text response

        logger.info(f"[agent_core] Iteration {iteration + 1}: executing {len(tool_calls)} tool call(s).")
        for tc in tool_calls:
            tool_fn = _tool_map.get(tc["name"])
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    logger.error(f"[agent_core] Tool '{tc['name']}' error: {e}")
                    result = f"Tool execution failed: {e}"
            else:
                logger.warning(f"[agent_core] Unknown tool requested: {tc['name']}")
                result = f"Unknown tool: {tc['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    # 3. Extract final text output
    output = ""
    if response is not None:
        output = getattr(response, "content", "") or ""
    if not output:
        output = "I couldn't generate a response. Please try again."

    return {"output": output}


agent_executor = RunnableLambda(_sovereign_agent)
logger.info("[agent_core] Sovereign agent initialized (manual tool loop, zero agent-factory deps).")


# --- FIX C1: Direct O(1) lookup instead of O(n) linear scan ---
# The user_id is passed via the LangChain config["configurable"]["user_id"]
# and extracted here to avoid scanning all SESSIONS.
def get_session_history(session_id: str, user_id: str):
    """
    Get session history for a given session_id (conversation_id).
    """

    if not user_id:
        logger.error(f"[agent_core] Could not resolve user_id for session_id {session_id}.")
        raise RuntimeError(f"Session owner not found for conversation {session_id}")

    logger.info(f"[agent_core] Resolved user_id={user_id} for session_id={session_id}")
    return get_conversation_history(user_id, session_id)


# Create the RunnableWithMessageHistory instance with user_id passthrough
with_message_history = RunnableWithMessageHistory(
    agent_executor,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    history_factory_config=[
        {
            "id": "session_id",
            "annotation": str,
            "is_shared": True,
        },
        {
            "id": "user_id",
            "annotation": str,
            "is_shared": True,
        },
    ],
)
