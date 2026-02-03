import requests
from fastmcp import FastMCP

mcp = FastMCP("DocExampleMcpSever")

@mcp.tool
def greet(name: str) -> str:
    """greet(name) returns a greeting including name passed as parameter"""
    return f"Hello from MCP Server to {name}!"

@mcp.tool
def weather(city: str) -> str:
    """Retrieve weather information for a given city and date using wttr.in.
    Note: wttr.in provides current weather; the date parameter is currently ignored.
    """
    try:
        response : Response = requests.get(f"https://wttr.in/{city}?format=j2")
        response.raise_for_status()
        data = response.json()
        current_condition = data.get("current_condition", [{}])[0]
        temp_c = current_condition.get('temp_C', "N\A")
        desc = ", ".join(
            [ d.get('value', '')
              for d in current_condition.get('weatherDesc', {})])

        return f"Weather in {city}: {desc}, {temp_c}°C"
    except Exception as e:
        return f"Failed to retrieve weather: {e}"

if __name__ == "__main__":
    mcp.run(transport="http", port=8042)
