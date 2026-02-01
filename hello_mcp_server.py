from fastmcp import FastMCP

mcp = FastMCP("DocExampleMcpSever")

@mcp.tool
def greet(name: str) -> str:
    """greet(name) returns a greeting including name passed as parameter"""
    return f"Hello from MCP Server to {name}!"

if __name__ == "__main__":
    mcp.run(transport="http", port=8042)




"""
{ "jsonrpc": "2.0", "id": 1, "method": ""} 
{ "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2.0", "capabilities": {}, "clientInfo": {"name": "myself", "version": "1.0"}}}
{ "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"name": "greet", "arguments": {}}}
{ "jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "greet", "arguments": {"name": "MBR"}}}
{ "jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "greet", "arguments": {"name": "MR. YES"}}}
"""
