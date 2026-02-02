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
from typing import Any, AsyncGenerator, Dict, List, Callable

from ollama import AsyncClient, ChatResponse, Message

from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult

LLM_PORT: int = 8080
LLM_HOST: str = f"http://localhost:{LLM_PORT}"

# Default model – will be mutable at runtime via /configure menu.
DEFAULT_MODEL: str = "qwen3:4b"

class LlmConfig:
    def __init__(self, model):
        self.model = model
        self.isThinking = True
        self.isStreaming = True

DEFAULT_CONFIG: LlmConfig = LlmConfig(DEFAULT_MODEL)

def hello_tool(model_name: str = "Llm Assistant") -> str:
    """Return a friendly greeting that includes the assistent model name, so that
    the user knows what is the model name

    Args:
        model_name: Name of the model that invoked the tool.

    Returns:
        A greeting string.
    """
    return f"Hello from hello_tool by {model_name}"


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


def mcp_tool_to_schema(tool: dict) -> dict:
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


class AgentContext:
    def __init__(self,
                 llm_client: AsyncClient,
                 mcp_client: McpClient,
                 llm_config: LlmConfig = DEFAULT_CONFIG,
                 mcp_tools: Dict[str, dict] = {},
                 native_tools: Dict[str, Callable] = {},
                 messages: List[Dict[str, any]] = [],
                 ):
        self.llm_client = llm_client
        self.mcp_client = mcp_client
        self.llm_config = DEFAULT_CONFIG
        self.mcp_tools = mcp_tools
        self.native_tools = native_tools
        self.messages = messages

    def get_all_tools(self):
        return {**self.native_tools, **self.mcp_tools}

    async def call_tool(self, fun_name: str, fun_args):
        if fun_name in self.native_tools:
            return self.native_tools[fun_name](**fun_args)
        elif fun_name in self.mcp_tools:
            # Forward the call to the MCP server.
            tool_res: CallToolResult = await self.mcp_client.call_tool_mcp(
                fun_name, fun_args)
            if tool_res.isError:
                return f"Tool call {fn_name} failed"
            else:
                return tool_res.structuredContent.get("result", "")
        else:
            return f"Unknown tool: {fn_name}"


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


async def llm_interaction(
    agent_context: AgentContext
) -> None:
    """Run a single round of the chat, handling streaming responses.

    The function streams the model's reply, prints thinking/content to the
    console, and processes any tool calls. After handling tool calls it recurses
    to continue the conversation.
    """
    print("Calling llm:")
    # Combine native tools with dynamically discovered MCP tools.

    all_tools = agent_context.get_all_tools()

    stream: AsyncGenerator[ChatResponse, None] = await agent_context.llm_client.chat(
        model = agent_context.llm_config.model,
        messages = agent_context.messages,
        stream = agent_context.llm_config.isStreaming,
        think = agent_context.llm_config.isThinking,
        tools = all_tools.values()
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
    agent_context.messages.append(
        {"role": "assistant",
         "thinking": thinking,
         "content": content,
         "tool_calls": tool_calls}
    )

    # Resolve each tool call sequentially.
    for call in tool_calls:
        result: str = ""
        fun_name = call.function.name
        fun_args = call.function.arguments or {}
        result = await agent_context.call_tool(fun_name, fun_args)
        print(result)
        if result:
            agent_context.messages.append(
                {"role": "tool", "tool_name": fun_name, "content": result})

    # If any tools were invoked we continue the conversation recursively.
    if tool_calls:
        await llm_interaction(agent_context)

async def get_mcp_tools(mcp_client) ->Dict[str, dict]:
    tools_res: ListToolsResult = await mcp_client.list_tools_mcp()
    raw_tools = tools_res.model_dump(mode="json")["tools"]

    # Convert each MCP tool description to the Ollama schema.
    ollama_tools = [mcp_tool_to_schema(t) for t in raw_tools]
    mcp_tool_map: Dict[str, dict] = {t["function"]["name"]: t for t in ollama_tools}
    return mcp_tool_map

def get_native_tools() ->Dict[str, Callable]:
    return {"hello_tool": hello_tool}

async def main() -> None:
    """Initialise clients, discover tools, and start the chat loop."""
    llm_client = AsyncClient(host=LLM_HOST)
    async with MpcClient("http://localhost:8081/mcp") as mcp_client:
        mcp_tools: Dict[str, dict] = await get_mcp_tools(mcp_client)
        native_tools: Dict[str, Callable] = get_native_tools()
        agent_context = AgentContext(
            llm_client,
            mcp_client,
            mcp_tools=mcp_tools,
            native_tools=native_tools
        )

        while True:
            print("You:")
            user_input: str = read_multiline()
            cmd: str = user_input.strip()
            if cmd == "/bye":
                print("Goodbye!")
                break
            if cmd == "/config":
                selected_model = await configure_model(agent_context.llm_client)
                if selected_model:
                    agent_context.llm_config.model = selected_model
                    print(f"Model set to: {agent_context.llm_config.model}")
                continue
            if cmd == "/clear":
                agent_context.messages = []
                print("Context cleared:")
                continue
            prompt: str = user_input
            agent_context.messages.append({"role": "user", "content": prompt})
            await llm_interaction(agent_context)


# ---------------------------------------------------------------------------
# Run the script when executed directly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
