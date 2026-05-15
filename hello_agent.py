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
import shlex
import signal
from typing import Any, AsyncGenerator, Dict, List, Callable, Optional

from ollama import AsyncClient, ChatResponse, Message, ShowResponse

from fastmcp import Client as MpcClient
from fastmcp.client.transports import StdioTransport
from mcp.types import CallToolResult, ListToolsResult

DEFAULT_LLM_PORT: int = 8080
DEFAULT_LLM_HOST: str = f"http://localhost:{DEFAULT_LLM_PORT}"
DEFAULT_MODEL: str = "qwen3:4b"

class LlmConfig:
    def __init__(self, model, llm_host):
        self.model = model
        self.isThinking = True
        self.isStreaming = True
        self.llm_host = llm_host

DEFAULT_CONFIG: LlmConfig = LlmConfig(DEFAULT_MODEL, DEFAULT_LLM_HOST)

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
                 llm_config: LlmConfig = DEFAULT_CONFIG,
                 native_tools: Dict[str, Callable] = {},
                 messages: List[Dict[str, Any]] = [],
                 ):
        self.llm_client: AsyncClient = llm_client
        self.llm_config = llm_config
        self.native_tools = native_tools
        self.messages = messages
        self.model_capabilities: List[str] = []
        self.is_connected: bool = False
        self.mcp_servers: Dict[str, MpcClient] = {}
        self.server_tools: Dict[str, Dict[str, dict]] = {}
        self.tool_to_server: Dict[str, str] = {}
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
        all_mcp: Dict[str, dict] = {}
        for tools in self.server_tools.values():
            all_mcp.update(tools)
        return {**self.native_tools, **all_mcp}

    async def call_tool(self, fun_name: str, fun_args: Dict[str, Any]) -> Any:
        if fun_name in self.native_tools:
            return self.native_tools[fun_name](**fun_args)
        elif fun_name in self.tool_to_server:
            server_url = self.tool_to_server[fun_name]
            client = self.mcp_servers[server_url]
            tool_res: CallToolResult = await client.call_tool_mcp(fun_name, fun_args)
            # Extract text from content blocks (standard MCP format used by all servers)
            text_parts = [
                block.text for block in tool_res.content
                if hasattr(block, "text")
            ]
            text_content = "\n".join(text_parts)
            if tool_res.isError:
                return f"Tool call {fun_name} failed: {text_content}"
            # fastmcp servers populate structuredContent with a "result" key;
            # prefer that when available, otherwise fall back to text blocks.
            if tool_res.structuredContent:
                return tool_res.structuredContent.get("result", text_content)
            return text_content
        else:
            return f"Unknown tool: {fun_name}"

async def check_ollama_connection(llm_client: AsyncClient) -> bool:
    """Return True if the Ollama server is reachable, False otherwise."""
    try:
        await llm_client.list()
        return True
    except ConnectionError as e:
        return False


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


async def add_mcp_server(agent_context: AgentContext, key: str, client: MpcClient) -> bool:
    if key in agent_context.mcp_servers:
        print(f"Already connected to {key}.")
        return True
    try:
        await client.__aenter__()
    except Exception as e:
        print(f"Failed to connect to {key}: {e}")
        return False
    try:
        tools = await get_mcp_tools(client)
    except Exception as e:
        await client.__aexit__(None, None, None)
        print(f"Failed to load tools from {key}: {e}")
        return False
    agent_context.mcp_servers[key] = client
    agent_context.server_tools[key] = tools
    for tool_name in tools:
        agent_context.tool_to_server[tool_name] = key
    tool_list = ", ".join(tools.keys()) if tools else "none"
    print(f"Connected to {key}. {len(tools)} tools loaded: {tool_list}")
    return True


async def remove_mcp_server(agent_context: AgentContext, url: str) -> bool:
    if url not in agent_context.mcp_servers:
        print(f"Not connected to {url}.")
        return False
    client = agent_context.mcp_servers.pop(url)
    tools = agent_context.server_tools.pop(url, {})
    for tool_name in tools:
        agent_context.tool_to_server.pop(tool_name, None)
    try:
        await client.__aexit__(None, None, None)
    except Exception:
        pass
    print(f"Disconnected from {url}. {len(tools)} tools removed.")
    return True

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
        return False

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

async def consume_command_config_mcp(agent_context: AgentContext, sub_cmd: str) -> bool:
    if sub_cmd != "mcp":
        return False

    while True:
        if agent_context.mcp_servers:
            print("Connected MCP servers:")
            for i, url in enumerate(agent_context.mcp_servers, 1):
                tools = agent_context.server_tools.get(url, {})
                tool_list = ", ".join(tools.keys()) if tools else "none"
                print(f"  {i}. {url}  ({len(tools)} tools: {tool_list})")
        else:
            print("No MCP servers connected.")

        print("\n[a]dd  [r]emove  [q]uit")
        choice = input("Choice: ").strip().lower()

        if choice in ("q", "quit", ""):
            break
        elif choice in ("a", "add"):
            stype = input("Server type - [h]ttp or [s]tdio: ").strip().lower()
            if stype in ("h", "http"):
                url = input("Enter HTTP server URL: ").strip()
                if url:
                    await add_mcp_server(agent_context, url, MpcClient(url))
            elif stype in ("s", "stdio"):
                cmd_str = input("Enter command (e.g. python server.py  or  uvx mcp-server-time): ").strip()
                if cmd_str:
                    try:
                        parts = shlex.split(cmd_str)
                    except ValueError as e:
                        print(f"Invalid command: {e}")
                        continue
                    transport = StdioTransport(command=parts[0], args=parts[1:])
                    key = f"stdio:{cmd_str}"
                    await add_mcp_server(agent_context, key, MpcClient(transport))
            else:
                print("Unknown type.")
        elif choice in ("r", "remove"):
            servers = list(agent_context.mcp_servers)
            if not servers:
                print("No servers to remove.")
                continue
            for i, url in enumerate(servers, 1):
                print(f"  {i}. {url}")
            sel = input("Select server number (or Enter to cancel): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(servers):
                await remove_mcp_server(agent_context, servers[int(sel) - 1])
            elif sel:
                print("Invalid selection.")
        else:
            print("Unknown option.")

    return True


async def consume_command_config_connection(agent_context: AgentContext, sub_cmd: str) -> bool:
    if sub_cmd != "connection":
        return False

    print(f"Current LLM host: {agent_context.llm_config.llm_host}")
    new_host = input("Enter new host URL (or press Enter to cancel): ").strip()
    if not new_host:
        print("Connection unchanged.")
        return True

    if not (new_host.startswith("http://") or new_host.startswith("https://")):
        print("Invalid URL. Must start with http:// or https://")
        return True

    agent_context.llm_config.llm_host = new_host
    agent_context.llm_client = AsyncClient(host=new_host)

    print(f"Testing connection to {new_host} ...")
    if await check_ollama_connection(agent_context.llm_client):
        agent_context.is_connected = True
        print(f"Connected. LLM host set to: {new_host}")
        await agent_context.load_model_capabilities()
    else:
        agent_context.is_connected = False
        print(f"Warning: could not reach {new_host}. Host updated but connection failed.")
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

    if await consume_command_config_mcp(agent_context, sub_cmd):
        return True
    if await consume_command_config_connection(agent_context, sub_cmd):
        return True
    if consume_command_config_streaming(agent_context, sub_cmd, value, len_parts):
        return True
    elif consume_command_config_thinking(agent_context, sub_cmd, value, len_parts):
        return True
    print("Unknown /config command. Available: /config [model], /config streaming [on|off], /config thinking [on|off], /config connection, /config mcp")
    return True

async def consume_command(agent_context: AgentContext, cmd: str) -> bool:
    if await consume_command_config(agent_context, cmd):
        return True
    if cmd == "/clear":
        agent_context.messages = []
        print("Context cleared:")
        return True
    return False

async def llm_call(
        agent_context: AgentContext, interrupt_event: asyncio.Event):
    """Call the LLM, respecting interrupt events.

    If ``interrupt_event`` is set during streaming, the function aborts and
    raises ``asyncio.CancelledError`` so that the caller can clean up.
    """
    print(f"Calling llm (streaming={agent_context.llm_config.isStreaming}):")
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
            if interrupt_event.is_set():
                raise asyncio.CancelledError()
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

async def llm_interaction(agent_context: AgentContext, interrupt_event: asyncio.Event) -> None:
    """Run a single round of the chat, handling streaming responses.

    The function streams the model's reply, prints thinking/content to the
    console, and processes any tool calls. After handling tool calls it recurses
    to continue the conversation. It respects ``interrupt_event`` so that a
    user‑initiated cancel (Ctrl‑C) aborts the current interaction and returns to
    the input loop.
    """
    all_tools = agent_context.get_all_tools()

    llm_response = await llm_call(agent_context, interrupt_event)
    agent_context.messages.append(llm_response)

    # handle tool calling
    for call in llm_response['tool_calls']:
        if interrupt_event.is_set():
                raise asyncio.CancelledError()
        result: str = ""
        fun_name = call.function.name
        fun_args = call.function.arguments or {}
        result = await agent_context.call_tool(fun_name, fun_args)
        print(f"Tool result [{fun_name}]: {result}")
        agent_context.messages.append(
            {"role": "tool", "tool_name": fun_name, "content": result})

    # If any tools were invoked we call llm again with tool result on context
    if llm_response['tool_calls']:
        await llm_interaction(agent_context, interrupt_event)

async def main() -> None:
    """Initialise clients, discover tools, and start the chat loop with signal handling."""
    llm_config = DEFAULT_CONFIG
    # Event to signal an interrupt
    interrupt_event = asyncio.Event()

    def signal_handler():
        # Set the event; the running interaction will notice and cancel
        interrupt_event.set()
        print("\n[Interrupted] Cancelling current interaction...")
    llm_client = AsyncClient(host=llm_config.llm_host)
    native_tools: Dict[str, Callable] = get_native_tools()
    agent_context = AgentContext(
        llm_client,
        llm_config=llm_config,
        native_tools=native_tools,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    agent_context.is_connected = await check_ollama_connection(agent_context.llm_client)
    if agent_context.is_connected:
        await agent_context.load_model_capabilities()
    else:
        print(
            f"[Warning] Cannot connect to LLM server at {llm_config.llm_host}. "
            "Use /config connection to set a different host."
        )

    while True:
        interrupt_event.clear()
        print("You:")
        try:
            user_input: str = read_multiline()
        except KeyboardInterrupt:
            print("\n[Interrupted] Input cancelled. Returning to prompt.")
            continue
        if interrupt_event.is_set():
            continue

        cmd: str = user_input.strip().lower()
        if cmd in ("/bye", "/exit", "/quit"):
            for url in list(agent_context.mcp_servers):
                await remove_mcp_server(agent_context, url)
            print("Goodbye!")
            break
        if await consume_command(agent_context, cmd):
            continue
        prompt: str = user_input
        agent_context.messages.append({"role": "user", "content": prompt})
        interrupt_event.clear()
        if not agent_context.is_connected:
            print(
                f"[Error] Not connected to LLM server at {agent_context.llm_config.llm_host}. "
                "Use /config connection to set a different host."
            )
            continue
        try:
            await llm_interaction(agent_context, interrupt_event)
        except asyncio.CancelledError:
            print("Interaction cancelled by user.")
            continue
        except KeyboardInterrupt:
            print("Interaction cancelled by user (KeyboardInterrupt).")
            continue
        except Exception as e:
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ("connect", "refused", "unreachable", "timeout")):
                agent_context.is_connected = False
                print(
                    f"\n[Error] Lost connection to the LLM server at {agent_context.llm_config.llm_host}.\n"
                    "Use /config connection to update the host.\n"
                )
            else:
                print(f"\n[Error] Unexpected error during LLM interaction: {e}\n")
                


# ---------------------------------------------------------------------------
# Run the script when executed directly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
