import asyncio
from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult

client: MpcClient = MpcClient("http://localhost:8081/mcp")

async def list_tools() -> ListToolsResult :
    

async def call_tool(name: str):
    async with client:
        call_result: CallToolResult = await client.call_tool("greet", {"name": name})
        #help(call_result)
        tools : ListToolsResult = await client.list_tools_mcp()
        #print(tools)
        #help(tools)
        
asyncio.run(call_tool("Ford"))
