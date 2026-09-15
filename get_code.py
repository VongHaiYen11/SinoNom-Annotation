import json

with open("./output/tap_1_review.json", "r", encoding="utf-8") as f:
    data = json.load(f)

vnchn_numbers = [
    ky_hieu
    for obj in data
    for ky_hieu in obj.get("ky_hieu_vnchn", [])
]

with open("./output/vnchn_numbers.json", "w", encoding="utf-8") as f:
    json.dump(vnchn_numbers, f, ensure_ascii=False, indent=2)