"""
This script demonstrates how to interact with an Ollama model using the
`fastmcp` client, call native tools, and forward tool calls to the MCP server.
It is organized into three logical sections:

1. **Configuration** – constants and helper functions.
2. **Tool definitions** – native tools that the model can invoke.
3. **Main execution** – orchestration of the client, tool discovery, and the
   recursive chat loop.

**Note:** To run this project with Python 3, activate the virtual environment first:
```bash
source .venv/bin/activate
```
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Callable

from ollama import AsyncClient, ChatResponse, Message, ShowResponse

from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult

LLM_PORT: int = 8080
LLM_HOST: str = f"http://localhost:{LLM_PORT}"
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
        self.llm_client: AsyncClient = llm_client
        self.mcp_client = mcp_client
        self.llm_config = llm_config
        self.mcp_tools = mcp_tools
        self.native_tools = native_tools
        self.messages = messages
        self.model_capabilities: List[str] = []
        # Track which configuration options are supported by the current model
        self.allowed_config: Dict[str, bool] = {
            "streaming": True,
            "thinking": True,
        }

    def _update_allowed_config(self) -> None:
        """Update allowed_config based on model_capabilities.

        Ollama model capabilities may include strings like "stream", "think",
        or more specific names. We map known capability identifiers to the
        configuration flags used by this script.
        """
        # Reset to defaults before applying
        self.allowed_config["thinking"] = True
        caps = {c.lower() for c in self.model_capabilities}
        # Mapping of capability keywords to config flags
        if "think" not in caps and "thinking" not in caps:
            self.allowed_config["thinking"] = False
            # Ensure flag is off if not supported
            if self.llm_config.isThinking:
                print(f"{self.llm_config.model} does not support thinking")
                print(f"Thinking set to off")
                self.llm_config.isThinking = False

    async def load_model_capabilities(self) -> None:
        """Retrieve model capabilities from Ollama and store them.

        Args:
            model_name: The name of the model to query.
        """
        try:
            # Ollama's AsyncClient has a `show` method that returns model info.
            model_name = self.llm_config.model
            info : ShowResponse = await self.llm_client.show(model=model_name)
            self.model_capabilities = info.capabilities
            self._update_allowed_config()

            print(f"{model_name} has capabilites: {self.model_capabilities}") 
        except Exception as e:
            print(f"Failed to retrieve capabilities for model '{model_name}': {e}")
            self.model_capabilities = []

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

async def get_mcp_tools(mcp_client) ->Dict[str, dict]:
    tools_res: ListToolsResult = await mcp_client.list_tools_mcp()
    raw_tools = tools_res.model_dump(mode="json")["tools"]

    # Convert each MCP tool description to the Ollama schema.
    ollama_tools = [mcp_tool_to_schema(t) for t in raw_tools]
    mcp_tool_map: Dict[str, dict] = {t["function"]["name"]: t for t in ollama_tools}
    return mcp_tool_map

def get_native_tools() ->Dict[str, Callable]:
    return {"hello_tool": hello_tool}

async def consume_command_config_model(agent_context: AgentContext, cmd_parts: List[str]) -> bool:
    if len(cmd_parts) == 1 or cmd_parts[1].strip().lower() == 'model':
        selected_model = await configure_model(agent_context.llm_client)
        if selected_model:
            agent_context.llm_config.model = selected_model
            # Load capabilities for the new model
            await agent_context.load_model_capabilities()
            print(f"Model set to: {agent_context.llm_config.model}")
        return True
    return False

def consume_command_config_streaming(
        agent_context: AgentContext,
        sub_cmd: str,
        value: str,
        len_parts: int
) -> bool:
    if not sub_cmd == "streaming":
        return False
    
    error = False
    if value in ("on", "off"):
        agent_context.llm_config.isStreaming = (value == "on")
    elif len_parts == 2:
        agent_context.llm_config.isStreaming = not agent_context.llm_config.isStreaming
    else:
        error = True
    if error:
        print("Usage: /config streaming [on|off]")
    else:
        new_value = 'on' if agent_context.llm_config.isStreaming else 'off'
    print(f"Streaming set to {new_value}")
    return True
    

def consume_command_config_thinking(
        agent_context: AgentContext,
        sub_cmd: str,
        value: str,
        len_parts: int
) -> bool:
    if not sub_cmd == "thinking":
        False

    error = False
    if not agent_context.allowed_config['thinking']:
        print(f"{agent_context.llm_config.model} does not have thinking capabilities")
        agent_context.llm_config.isThinking = False
    elif value in ("on", "off"):
        agent_context.llm_config.isThinking = (value == "on")
    elif len_parts == 2:
        agent_context.llm_config.isThinking = not agent_context.llm_config.isThinking
    else:
        error = True

    if error:
        print("Usage: /config thinking [on|off]")
    else:
        new_value = 'on' if agent_context.llm_config.isThinking else 'off'
        print(f"Thinking set to {new_value}")
    return True

async def consume_command_config(agent_context: AgentContext, cmd: str) -> bool:
    if not cmd.startswith("/config"):
        return False
    parts = cmd.split()

    if await consume_command_config_model(agent_context, parts):
        return True
    
    len_parts = len(parts)
    # len_parts is expected >= 2 at this point
    sub_cmd = parts[1].strip().lower()
    if (len_parts >= 3):
        value = parts[2].strip().lower()
    else:
        value = ''

    if consume_command_config_streaming(agent_context, sub_cmd, value, len_parts):
        return True
    elif consume_command_config_thinking(agent_context, sub_cmd, value, len_parts):
        return True
    print("Unknown /config command. Available: /config [model], /config streaming [on|off], /config thinking [on|off]")
    return True

async def consume_command(agent_context: AgentContext, cmd: str) -> bool:
    if await consume_command_config(agent_context, cmd):
        return True
    if cmd == "/clear":
        agent_context.messages = []
        print("Context cleared:")
        return True
    return False

async def llm_call(agent_context: AgentContext):
    print("Calling llm:")
    all_tools = agent_context.get_all_tools()
    
    thinking: str = ""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = []

    if agent_context.llm_config.isStreaming:
        stream: AsyncGenerator[ChatResponse, None] = await agent_context.llm_client.chat(
            model = agent_context.llm_config.model,
            messages = agent_context.messages,
            stream = agent_context.llm_config.isStreaming,
            think = agent_context.llm_config.isThinking,
            tools = all_tools.values()
        )
        
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
    else:
        response: ChatResponse = await agent_context.llm_client.chat(
            model = agent_context.llm_config.model,
            messages = agent_context.messages,
            stream = agent_context.llm_config.isStreaming,
            think = agent_context.llm_config.isThinking,
            tools = all_tools.values()
        )
        msg: Message = response.message
        if msg.thinking:
            print("Thinking:\n")
            print(msg.thinking, end="", flush=True)
            thinking += msg.thinking
        if msg.content:
            print("\n\nAnswer:\n")
            print(msg.content, end="", flush=True)
            content += msg.content
        if msg.tool_calls:
            print("\nTool_Call: ", end="")
            print(msg.tool_calls)
            tool_calls.extend(msg.tool_calls)
        
    print("\n")
    return {
        'role': 'assistant',
        'thinking': thinking,
        'content': content,
        'tool_calls': tool_calls
    }

async def llm_interaction(agent_context: AgentContext) -> None:
    """Run a single round of the chat, handling streaming responses.

    The function streams the model's reply, prints thinking/content to the
    console, and processes any tool calls. After handling tool calls it recurses
    to continue the conversation.
    """
    all_tools = agent_context.get_all_tools()

    llm_response = await llm_call(agent_context)
    agent_context.messages.append(llm_response)

    # handle tool calling
    for call in llm_response['tool_calls']:
        result: str = ""
        fun_name = call.function.name
        fun_args = call.function.arguments or {}
        result = await agent_context.call_tool(fun_name, fun_args)
        print(result)
        if result:
            agent_context.messages.append(
                {"role": "tool", "tool_name": fun_name, "content": result})

    # If any tools were invoked we call llm again with tool result on context
    if llm_response['tool_calls']:
        await llm_interaction(agent_context)

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

        await agent_context.load_model_capabilities()

        while True:
            print("You:")
            user_input: str = read_multiline()
            cmd: str = user_input.strip().lower()
            if cmd == "/bye" or cmd == "/exit" or cmd == "/quit":
                print("Goodbye!")
                break
            if await consume_command(agent_context, cmd):
                continue
            prompt: str = user_input
            agent_context.messages.append({"role": "user", "content": prompt})
            await llm_interaction(agent_context)


# ---------------------------------------------------------------------------
# Run the script when executed directly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
