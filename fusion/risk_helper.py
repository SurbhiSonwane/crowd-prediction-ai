def get_risk(crowd, capacity):
    ratio = crowd / capacity if capacity > 0 else 0
    if ratio < 0.60: return "SAFE",     ratio
    if ratio < 0.85: return "MODERATE", ratio
    return              "HIGH",     ratio

def get_suggested_action(risk_level, location_name):
    actions = {
        "HIGH": {
            "Siddhivinayak Temple": "Open Gate B. Deploy 2 extra staff at queue. Activate mezzanine floor.",
            "Dadar Bus Depot":      "Open platform 2. Add extra buses on route 340 and 351.",
        },
        "MODERATE": {
            "Siddhivinayak Temple": "Monitor queue length. Alert security at entry gate.",
            "Dadar Bus Depot":      "Monitor platform crowd. Prepare extra bus if needed.",
        },
        "SAFE": {
            "Siddhivinayak Temple": "Normal operations.",
            "Dadar Bus Depot":      "Normal operations.",
        }
    }
    return actions.get(risk_level, {}).get(location_name, "Monitor situation.")

def best_time_advice(risk, hour):
    if risk == "SAFE":
        return "Good time to visit."
    if risk == "MODERATE":
        return f"Manageable crowd. Go early or after {(hour+2)%24}:00."
    return f"Very crowded. Try before {max(hour-3,6)}:00 or after {(hour+3)%24}:00."

def user_risk(crowd):
    if crowd < 200: return "SAFE"
    if crowd < 500: return "MODERATE"
    return              "HIGH"