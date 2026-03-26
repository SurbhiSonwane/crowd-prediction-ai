def get_risk_level(count):
    if count <= 100:
        return "SAFE"
    elif 100 < count <= 250:
        return "MODERATE"
    return "HIGH"

data = [
    {"location":"juhu","count":180,"hour":6},
    {"location":"gateway","count":100,"hour":18},
    {"location":"cst station","count":380,"hour":17}
]

def analyse(data):
    for i in range(0,2):
        print(data[i]["location"]+"|")
        print(data[i]["count"]+"|")
        print(data[i]["hour"]+"|")
        print("Risk:"+get_risk_level(data[i]["count"]))
          
analyse(data)
