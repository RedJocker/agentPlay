import asyncio
import json

from fastmcp import Client as MpcClient
from fastmcp.client.client import CallToolResult
from mcp.types import ListToolsResult

client: MpcClient = MpcClient("http://localhost:8081/mcp")


async def call_list_leads(status: str):
    async with client:
        call_result: CallToolResult = await client.call_tool("listLeads", {"status": status})
        if (call_result.is_error):
            return None
        result_json_str = call_result.structured_content['result']
        # Parse the JSON string into Python objects
        try:
            leads = json.loads(result_json_str)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON: {e}")
            leads = []
        # Return the parsed leads for further processing
        return leads

asyncio.run(call_list_leads("*"))


def rank_managers_by_budget(leads):
    """Aggregate budgets per manager and return ranking.

    Args:
        leads (list): List of lead dictionaries as returned by the MCP tool.
    Returns:
        list: Sorted list of managers with total_budget in descending order.
    """
    manager_budget = {}
    for lead in leads:
        budget = lead.get('budget')
        if budget is None:
            budget = 0
        for mgr in lead.get('managers', []):
            mgr_id = mgr.get('manager_id')
            if mgr_id is None:
                continue
            # Initialise manager entry if not present
            if mgr_id not in manager_budget:
                manager_budget[mgr_id] = {
                    'manager_id': mgr_id,
                    'name': mgr.get('name'),
                    'email': mgr.get('email'),
                    'total_budget': 0.0,
                }
            manager_budget[mgr_id]['total_budget'] += budget
    # Convert to list and sort by total_budget descending
    ranked = sorted(manager_budget.values(), key=lambda x: x['total_budget'], reverse=True)
    return ranked

async def main():
    leads = await call_list_leads("*")
    if not leads:
        print("No leads retrieved.")
        return
    
    ranking = rank_managers_by_budget(leads)
    print(ranking)
    print("Manager ranking by total budget managed:")
    for idx, mgr in enumerate(ranking, start=1):
        print(f"{idx}. {mgr['name']} ({mgr['email']}): $ {mgr['total_budget']:.2f}")
        
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available")
    else:
        
        
        leads = await call_list_leads("*")
        if not leads:
            print("No leads retrieved.")
            return
        ranking = rank_managers_by_budget(leads)
        # Prepare data for plotting
        names = [m['name'] for m in ranking]
        budgets = [m['total_budget'] for m in ranking]
        # Plot bar chart
        plt.figure(figsize=(10, 6))
        bars = plt.bar(names, budgets, color='steelblue')
        plt.xlabel('Manager')
        plt.ylabel('Total Budget Managed')
        plt.title('Managers Ranked by Total Budget Managed')
        plt.xticks(rotation=45, ha='right')
        # Add value labels on top of bars
        for bar, budget in zip(bars, budgets):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width() / 2, height,
                     f'$ {budget:,.2f}', ha='center', va='bottom')
        plt.tight_layout()
        plt.show()

# Execute the main routine
if __name__ == '__main__':
    # If matplotlib is available, show a bar chart; otherwise just run the async main.
    asyncio.run(main())
        

