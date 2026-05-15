import requests
from fastmcp import FastMCP

mcp = FastMCP("WeatherStdioServer")

@mcp.tool
def weather(city: str) -> str:
    """Retrieve current weather information for a given city using wttr.in."""
    try:
        response = requests.get(f"https://wttr.in/{city}?format=j2")
        response.raise_for_status()
        data = response.json()
        current_condition = data.get("current_condition", [{}])[0]
        temp_c = current_condition.get("temp_C", "N/A")
        desc = ", ".join(
            d.get("value", "") for d in current_condition.get("weatherDesc", [])
        )
        return f"Weather in {city}: {desc}, {temp_c}°C"
    except Exception as e:
        return f"Failed to retrieve weather: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
