import json
import requests
from collections import defaultdict

# Load the JSON data from a local file
def load_data():
    with open("data.json", "r") as file:
        return json.load(file)

# Fetch all Bazaar prices in one call and cache them
def fetch_all_bazaar_prices():
    url = 'https://api.hypixel.net/skyblock/bazaar'
    response = requests.get(url).json()
    if "products" not in response:
        raise Exception("Failed to fetch Bazaar data")

    prices = {}
    for item_id, details in response["products"].items():
        quick_status = details.get("quick_status", {})
        buy_price = quick_status.get("buyPrice")
        sell_price = quick_status.get("sellPrice")
        hourly_instabuys = quick_status.get("sellMovingWeek", 0) / 168
        hourly_instasells = quick_status.get("buyMovingWeek", 0) / 168

        if buy_price and sell_price:
            if (buy_price / sell_price < 1.07):
                prices[item_id] = {"price": buy_price, "method": "Instabuy", "hourly_instabuys": hourly_instabuys, "hourly_instasells": hourly_instasells}
            else:
                prices[item_id] = {"price": sell_price, "method": "Buy Order", "hourly_instabuys": hourly_instabuys, "hourly_instasells": hourly_instasells}

    return prices

# Fetch all items and prices from Moulberry's Lowest BIN JSON
def fetch_lbin_prices():
    url = "http://moulberry.codes/lowestbin.json"
    response = requests.get(url).json()
    return response

# Fetch the lowest BIN price for an item
def fetch_lowest_auction_price(item_name, lbin_data):
    return lbin_data.get(item_name.upper(), None)

# Search for itemID by name in the loaded data
def get_item_id(data, item_name):
    for item_id, details in data.items():
        if details.get("name") == item_name:
            return item_id
    return None

# Build recipe tree
def build_recipe_tree(data, item_id, prices, lbin_data, visited=None):
    if visited is None:
        visited = set()  # Ensure `visited` is initialized as a set

    if item_id in visited:
        return {"name": item_id, "count": 1, "note": "cycle detected"}

    if item_id not in data or "recipe" not in data[item_id]:
        price_info = prices.get(item_id, {"price": 0})
        if price_info["price"] == 0:  # If not found in Bazaar, check Auctions
            auction_price = fetch_lowest_auction_price(item_id, lbin_data)
            price_info["price"] = auction_price if auction_price else 0
            note = "base item (from auction)" if auction_price else "base item (no price)"
        else:
            note = "base item"

        return {"name": item_id, "count": 1, "note": note, "cost": price_info["price"]}

    recipe = data[item_id]["recipe"]
    merged_ingredients = defaultdict(int)
    visited.add(item_id)  # Properly add to the set

    for ingredient in recipe.values():
        if isinstance(ingredient, str) and ":" in ingredient:
            name, _, count = ingredient.partition(":")
            count = int(count) if count.isdigit() else 1  # Ensure count is an integer
            merged_ingredients[name] += count

    tree = {"name": item_id, "children": [], "count": 1}
    total_craft_cost = 0
    output_count = int(recipe.get("count", 1))  # Ensure `output_count` is an integer

    for name, count in merged_ingredients.items():

        subitem_price = prices.get(name, {}).get("price", 0)

        aggregated_cost = subitem_price * count
        bazaar_price = prices.get(item_id, {}).get("price", float("inf")) * output_count

        if subitem_price == 0:  # If not found in Bazaar, check Auctions
            subitem_price = fetch_lowest_auction_price(name, lbin_data) or 0

        child = build_recipe_tree(data, name, prices, lbin_data, visited)
        child["count"] = count
        total_craft_cost += child.get("cost", 0) * count
        tree["children"].append(child)

        if count >= 80 and subitem_price <= 1000:
            tree = {"name": item_id, "count": 1, "note": "purchased directly", "cost": prices.get(item_id, {}).get("price", 0)}
            visited.remove(item_id)
            return tree

        if aggregated_cost > bazaar_price:
            tree = {"name": item_id, "count": 1, "note": "purchased directly", "cost": bazaar_price}
            visited.remove(item_id)
            return tree

    # Total price (output_count * bazaar_price) comparison with raw craft cost
    bazaar_price = prices.get(item_id, {}).get("price", 0)
    total_bazaar_price = bazaar_price * output_count  # Calculate total bazaar price

    if total_bazaar_price > 0 and (total_bazaar_price <= total_craft_cost or total_craft_cost == 0):
        tree = {
            "name": item_id,
            "count": output_count,
            "note": "purchased directly",
            "cost": total_bazaar_price / output_count  # Normalize per unit
        }
    else:
        tree["cost"] = total_craft_cost / output_count  # Normalize per unit

    visited.remove(item_id)  # Properly remove from the set after processing
    return tree


# Print the recipe tree with multipliers, prices, and formatting
def print_recipe_tree(tree, prices, level=0, multiplier=1):
    indent = "  " * level
    note = f" ({tree['note']})" if "note" in tree else ""
    total_count = tree["count"] * multiplier

    price_info = prices.get(tree["name"], {})
    price = price_info.get("price", 1)
    method = price_info.get("method", None)

    if price > 0:
        unit_price = f"{price:,.2f} per unit"
        total_price = price * total_count
        price_info = f" ({total_count:,.2f} @ {total_price:,.2f} - {method})"
    else:
        unit_price = "No price"
        price_info = ""

    print(f"{indent}- {tree['name']} x{total_count:,.2f}{note} {unit_price}{price_info}")

    for child in tree.get("children", []):
        print_recipe_tree(child, prices, level + 1, total_count)

# Collect raw items recursively
def collect_raw_items(tree, multiplier=1, raw_items=None):
    if raw_items is None:
        raw_items = defaultdict(float)

    total_count = tree["count"] * multiplier

    if "children" not in tree or not tree["children"] or tree.get("note") == "purchased directly":
        raw_items[tree["name"]] += total_count
        return raw_items

    for child in tree.get("children", []):
        collect_raw_items(child, total_count, raw_items)

    return raw_items

def calculate_profit(data, prices, lbin_data):
    profits = []
    for item_id in data.keys():
        tree = build_recipe_tree(data, item_id, prices, lbin_data)
        crafting_cost = tree.get("cost", float("inf"))

        bazaar_price = prices.get(item_id, {}).get("price", 0)
        auction_price = fetch_lowest_auction_price(item_id, lbin_data) or 0

        if bazaar_price > 50000 and crafting_cost < bazaar_price:
            profit = bazaar_price - crafting_cost
            profit_percent = int((bazaar_price - crafting_cost) / crafting_cost * 100)
            profits.append({"item_id": item_id, "profit": profit, "profit percent": profit_percent, "crafting_cost": crafting_cost, "sell_price": bazaar_price})

    return sorted(profits, key=lambda x: x["profit percent"], reverse=True)[:20]

# Main execution
try:
    data = load_data()
    prices = fetch_all_bazaar_prices()
    lbin_data = fetch_lbin_prices()

    top_crafts = calculate_profit(data, prices, lbin_data)

    print("Top 20 Most Profitable Crafts:")
    for craft in top_crafts:
        print(f"- {craft['item_id']}:\n  Profit = {craft['profit']:,.2f}\n  Profit Percent Increase = {craft['profit percent']:,.2f}\n  Crafting Cost = {craft['crafting_cost']:,.2f}\n  Sell Price = {craft['sell_price']:,.2f}\n")


    while True:
        item_name = input("\nEnter the item name to view its recipe tree and raw craft cost (or type 'exit' to quit): ")
        if item_name.lower() == "exit":
            break
        item_id = get_item_id(data, item_name)
        if item_id:
            print(f"\nItem ID for '{item_name}': {item_id}\n")
            recipe_tree = build_recipe_tree(data, item_id, prices, lbin_data)
            print("Recipe Tree:")
            print_recipe_tree(recipe_tree, prices)

            raw_items = collect_raw_items(recipe_tree)
            total_price = 0

            print("\n--- Raw Items Needed ---")
            for item, quantity in raw_items.items():

                recipe = data[item_id]["recipe"]
                output_count = int(recipe.get("count", 1))
                price_info = prices.get(item, {})
                price = price_info.get("price", 0)
                if price == 0:  # Check Auctions if Bazaar price is not found
                    price = fetch_lowest_auction_price(item, lbin_data) or 0

                if price > 0:
                    total_price += price * quantity
                    print(f"- {item}: {quantity:,.2f} @ {price:,.2f} each = {price * quantity:,.2f}")
                else:
                    print(f"- {item}: {quantity:,.2f} (No price available)")
                final = total_price / output_count

            print(f"\nTotal cost of raw items: {final:,.2f}\n")
        else:
            print(f"Item '{item_name}' not found in the data.")
except Exception as e:
    print(f"An error occurred: {e}")
