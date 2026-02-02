"""
This script demonstrates how to interact with an Ollama model using the
`fastmcp` client, call native tools, and forward tool calls to the MCP server.
It is organized into three logical sections:

1. **Configuration** – constants and helper functions.
2. **Tool definitions** – native tools that the model can invoke.
3. **Main execution** – orchestration of the client, tool discovery, and the
   recursive chat loop.

"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict, List

from ollama import AsyncClient, ChatResponse, Message

from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Ollama server configuration – adjust the port if your instance runs on a
# different port.
LLM_PORT: int = 8080
LLM_HOST: str = f"http://localhost:{LLM_PORT}"

# Default model – will be mutable at runtime via /configure menu.
DEFAULT_MODEL: str = "qwen3:4b"

# ---------------------------------------------------------------------------
# Native tool definitions
# ---------------------------------------------------------------------------

def hello_tool(model_name: str = "Llm Assistant") -> str:
    """Return a friendly greeting that includes the assistent model name, so that
    the user knows what is the model name

    Args:
        model_name: Name of the model that invoked the tool.

    Returns:
        A greeting string.
    """
    return f"Hello from hello_tool by {model_name}"

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def read_multiline() -> str:
    """Read user input until an empty line (two consecutive newlines) is entered.

            Returns the collected text as a single string, preserving internal newlines.
    """
    lines: List[str] = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def mcp_tool_to_ollama(tool: dict) -> dict:
    """Convert an MCP tool description to the JSON schema expected by Ollama.
    """

    parameters: dict = tool.get(
        "inputSchema",
        {"type": "object", "properties": {}, "required": []},
    )

    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": parameters,
        },
    }


async def configure_model(llm_client: AsyncClient) -> str | None:
    """Fetch available models from the Ollama client and let the user select one.

    Returns the chosen model name or ``None`` if the selection is invalid or cancelled.
    """
    try:

        models_resp = await llm_client.list()
        models = [m.model for m in models_resp.models]
    except Exception as e:
        print(f"Failed to retrieve models: {e}")
        return None

    if not models:
        print("No models available.")
        return None

    print("Available models:")
    for idx, name in enumerate(models, 1):
        print(f"  {idx}. {name}")
    choice = input("Select model number (or press Enter to cancel): ").strip()
    if not choice:
        return None
    if not choice.isdigit() or not (1 <= int(choice) <= len(models)):
        print("Invalid selection.")
        return None
    return models[int(choice) - 1]

# ---------------------------------------------------------------------------
# Core chat logic
# ---------------------------------------------------------------------------
async def llm_interaction(
    model: str,
    llm_client: AsyncClient,
    mcp_client: MpcClient,
    mcp_tools: Dict[str, dict],
    messages: List[Dict[str, Any]],
) -> None:
    """Run a single round of the chat, handling streaming responses.

    The function streams the model's reply, prints thinking/content to the
    console, and processes any tool calls. After handling tool calls it recurses
    to continue the conversation.
    """
    print("Calling llm:")
    # Combine native tools with dynamically discovered MCP tools.
    native_tools = {"hello_tool": hello_tool}
    all_tools = {**native_tools, **mcp_tools}

    # ``llm_client.chat`` returns an async generator yielding ``ChatResponse``
    # objects. We enable ``stream=True`` and ``think=True`` to receive both
    # thinking and content chunks.
    stream: AsyncGenerator[ChatResponse, None] = await llm_client.chat(
        model=model,
        messages=messages,
        stream=True,
        tools=all_tools.values(),
        think=True,
    )

    thinking: str = ""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = []

    async for chunk in stream:
        msg: Message = chunk.message
        if msg.thinking:
            if not thinking:
                print("Thinking:\n")
            print(msg.thinking, end="", flush=True)
            thinking += msg.thinking
        elif msg.content:
            if not content:
                print("\n\nAnswer:\n")
            print(msg.content, end="", flush=True)
            content += msg.content
        elif msg.tool_calls:
            print("\nTool_Call: ", end="")
            print(msg.tool_calls)
            tool_calls.extend(msg.tool_calls)

    print("\n")

    # Append the assistant's full reply to the message history.
    messages.append(
        {"role": "assistant", "thinking": thinking, "content": content, "tool_calls": tool_calls}
    )

    # Resolve each tool call sequentially.
    for call in tool_calls:
        result: str = ""
        fn_name = call.function.name
        fn_args = call.function.arguments or {}
        if fn_name in native_tools:
            result = native_tools[fn_name](**fn_args)
        elif fn_name in mcp_tools:
            # Forward the call to the MCP server.
            tool_res: CallToolResult = await mcp_client.call_tool_mcp(fn_name, fn_args)
            if tool_res.isError:
                result = f"Tool call {fn_name} failed"
            else:
                # The structured content is expected to contain a ``result`` field.
                result = tool_res.structuredContent.get("result", "")
        else:
            result = f"Unknown tool: {fn_name}"

        print(result)
        if result:
            messages.append({"role": "tool", "tool_name": fn_name, "content": result})

    # If any tools were invoked we continue the conversation recursively.
    if tool_calls:
        await llm_interaction(model, llm_client, mcp_client, mcp_tools, messages)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    """Initialise clients, discover tools, and start the chat loop."""
    llm_client = AsyncClient(host=LLM_HOST)
    current_model: str = DEFAULT_MODEL
    # Initialise the MCP client – this connects to the local MCP server.
    async with MpcClient("http://localhost:8081/mcp") as mcp_client:

        # Retrieve the list of tools available via MCP.
        tools_res: ListToolsResult = await mcp_client.list_tools_mcp()
        raw_tools = tools_res.model_dump(mode="json")["tools"]

        # Convert each MCP tool description to the Ollama schema.
        ollama_tools = [mcp_tool_to_ollama(t) for t in raw_tools]
        mcp_tool_map: Dict[str, dict] = {t["function"]["name"]: t for t in ollama_tools}

        # Conversation history persists across iterations.
        messages: List[Dict[str, Any]] = []

        while True:
            print("You:")
            user_input = read_multiline()
            cmd = user_input.strip()
            if cmd == "/bye":
                print("Goodbye!")
                break
            if cmd == "/configure":
                # Fetch available models and let user select one
                selected = await configure_model(llm_client)
                if selected:
                    current_model = selected
                    print(f"Model set to: {current_model}")
                continue
            if cmd == "/clear":
                messages = []
                print("Context cleared:")
                continue
            messages.append({"role": "user", "content": user_input})
            await llm_interaction(current_model, llm_client, mcp_client, mcp_tool_map, messages)


# ---------------------------------------------------------------------------
# Run the script when executed directly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
