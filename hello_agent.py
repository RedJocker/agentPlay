import asyncio
import os
from ollama import chat, ChatResponse, Message, AsyncClient

from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult


def mcp_tool_to_ollama(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get(
                "parameters",
                {"type": "object", "properties": {}, "required": []},
            ),
        },
    }


llm_port=8080
# llm_port=11434
host="http://localhost:{0}".format(llm_port)
client = AsyncClient(host=host)


def hello_tool(model_name: str) -> str:
    """A tool used for greeting the user including the model name
    after usage use the return value as your response
    Args:
      model_name: The argument for The name of the model.

    Returns:
      A string with a greeting
    """
    return "Hello from hello_tool by " + model_name 


async def make_call(model, mcp_client, tools_mcp_obj, messages):
    native_tools = {
        'hello_tool': hello_tool
    }
    tools = {**native_tools, **tools_mcp_obj}
    
    stream: async_generator = await client.chat(
        model=model,
        messages=messages,
        stream=True,
        tools=tools.values(),
        think=True
    )

    thinking: str = ''
    content: str = ''
    tool_calls = []
    
    chunk: ChatResponse
    async for chunk in stream:
        message : Message = chunk.message
        
        if message.thinking:
            if not thinking:
                print("Thinking:\n")
            print(message.thinking, end='', flush=True)
            thinking += message.thinking
        elif message.content:
            if not content:
                print("\n\nAnswer: \n")
            print(message.content, end='', flush=True)
            content += message.content
        elif message.tool_calls:
            print("\nTool_Call: ", end='')
            print(message.tool_calls)
            tool_calls.extend(message.tool_calls)
    print("\n")
    
    messages.append({
        'role': 'assistant',
        'thinking': thinking,
        'content': content,
        'tool_calls': tool_calls,
    })
    
    
    for call in tool_calls:
        result: str = ''
        if native_tools.get(call.function.name) != None:
            result = native_tools[call.function.name](**call.function.arguments)
        elif tools_mcp_obj.get(call.function.name) != None:
            call_result = (await mcp_client.call_tool_mcp(call.function.name, call.function.arguments))
            if call_result.isError:
                result = f'tool call with name {call.function.name} failed' 
            else:
                result = call_result.structuredContent.get('result')
            
        else:
            result = 'There is no tool named ' + call.function.name
        print(result)
        if result:
            messages.append({
                'role': 'tool',
                'tool_name': call.function.name,
                'content': result,
            })
    if tool_calls:
        await make_call(model, mcp_client, tools_mcp_obj, messages)

async def main():
    client: MpcClient = MpcClient("http://localhost:8081/mcp")
    model = 'qwen3:4b'
    # model = 'qwen3-vl:235b-cloud'   
    # model = 'deepseek-v3.1:671b-cloud'
    # model = 'gpt-oss:120b-cloud'
    #model = 'nemotron-3-nano:30b-cloud'
    messages= [
        {
            'role': 'user',
            'content': 'call both the hello_tool and the greet tool with arg MBR',
        },
    ]

    
    async with client:   
        tools_result: ListToolsResult = await client.list_tools_mcp()
        
        raw_tools = tools_result.model_dump(mode="json")["tools"]
        tools_mcp_lst = [mcp_tool_to_ollama(t) for t in raw_tools]
        tools_mpc_obj = {tool['function']['name']: tool for tool in tools_mcp_lst}
        
        await make_call(model, client, tools_mpc_obj, messages)
    
    
asyncio.run(main())
