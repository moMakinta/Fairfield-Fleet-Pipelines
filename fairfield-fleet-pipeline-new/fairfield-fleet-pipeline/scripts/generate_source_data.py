"""Makes the fake source files for Fairfield Chemical Transportation in data/raw.

Everything is invented. The files are messy on purpose so the C# cleaning
step has something to do.

    python scripts/generate_source_data.py
"""
import csv
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
rng = random.Random(21)
START = date(2025, 1, 1)
CUTOFF = datetime(2025, 12, 31, 23, 59)

# code, name, type, city, lat, lon
LOCATIONS = [
    ("JHB", "City Deep Depot", "Depot", "Johannesburg", -26.23, 28.08),
    ("SAS", "Sasolburg Plant", "Plant", "Sasolburg", -26.81, 27.83),
    ("SEC", "Secunda Plant", "Plant", "Secunda", -26.52, 29.20),
    ("DUR", "Durban Port Terminal", "Port", "Durban", -29.87, 31.03),
    ("RCB", "Richards Bay Terminal", "Port", "Richards Bay", -28.80, 32.05),
    ("CPT", "Cape Town Port Terminal", "Port", "Cape Town", -33.91, 18.43),
    ("GQE", "Ngqura Terminal", "Port", "Gqeberha", -33.77, 25.67),
    ("ELS", "East London Terminal", "Port", "East London", -33.03, 27.91),
    ("MPM", "Maputo Terminal", "Port", "Maputo", -25.97, 32.57),
    ("BFN", "Bloemfontein Depot", "Depot", "Bloemfontein", -29.12, 26.21),
    ("RUS", "Rustenburg Depot", "Depot", "Rustenburg", -25.67, 27.24),
    ("PLK", "Polokwane Depot", "Depot", "Polokwane", -23.90, 29.45),
]

# id, origin, destination, mode, km
ROUTES = [
    ("RD01", "SAS", "JHB", "Road", 85), ("RD02", "SEC", "JHB", "Road", 135),
    ("RD03", "JHB", "DUR", "Road", 570), ("RD04", "SAS", "DUR", "Road", 610),
    ("RD05", "SEC", "RCB", "Road", 520), ("RD06", "JHB", "BFN", "Road", 400),
    ("RD07", "JHB", "RUS", "Road", 120), ("RD08", "JHB", "PLK", "Road", 320),
    ("RD09", "SAS", "BFN", "Road", 330), ("RD10", "DUR", "RCB", "Road", 180),
    ("RD11", "GQE", "ELS", "Road", 290), ("RD12", "CPT", "GQE", "Road", 750),
    ("RL01", "SAS", "DUR", "Rail", 700), ("RL02", "SEC", "RCB", "Rail", 580),
    ("RL03", "JHB", "CPT", "Rail", 1500), ("RL04", "SAS", "GQE", "Rail", 1050),
    ("RL05", "JHB", "MPM", "Rail", 600),
    ("SE01", "DUR", "CPT", "Sea", 1480), ("SE02", "RCB", "CPT", "Sea", 1640),
    ("SE03", "DUR", "GQE", "Sea", 730), ("SE04", "RCB", "MPM", "Sea", 330),
    ("SE05", "DUR", "MPM", "Sea", 560),
]

# code, name, hazard class, surcharge %
PRODUCTS = [
    ("SUL", "Sulphuric acid", "8", 15), ("CAU", "Caustic soda", "8", 12),
    ("AMM", "Ammonia", "2", 25), ("MET", "Methanol", "3", 18),
    ("ETH", "Ethanol", "3", 15), ("CHL", "Chlorine", "2", 30),
    ("HCL", "Hydrochloric acid", "8", 15), ("SOL", "Industrial solvents", "3", 18),
    ("FER", "Liquid fertiliser", "9", 5), ("GLY", "Glycol", "None", 0),
]

# mode, rate per tonne-km, minimum charge, fuel price per litre
RATES = [("Road", 1.85, 8000, 21.50), ("Rail", 0.62, 60000, 21.50), ("Sea", 0.21, 250000, 14.00)]

MODE_ASSET = {"Road": "Truck", "Rail": "Train", "Sea": "Ship"}
SPEED = {"Road": 60, "Rail": 35, "Sea": 25}             # km/h
FUEL_PER_KM = {"Road": 0.38, "Rail": 5.2, "Sea": 55}    # litres
TURNAROUND_H = {"Road": 3, "Rail": 12, "Sea": 24}
LEAD_DAYS = {"Road": (2, 4), "Rail": (4, 7), "Sea": (6, 11)}
DELAYS = {"Road": ["Breakdown", "Road closure", "Loading delay", "Weather"],
          "Rail": ["Signal failure", "Cable theft", "Loading delay", "Border delay"],
          "Sea": ["Port congestion", "Weather", "Berth not available"]}

PREFIX = ["Highveld", "Karoo", "Umgeni", "Limpopo", "Vaal", "Table Bay", "Drakensberg", "Kalahari",
          "Bushveld", "Tugela", "Algoa", "Overberg", "Magalies", "Zululand", "Namaqua", "Lowveld"]
SUFFIX = [("Agri", "Agriculture"), ("Mining Supplies", "Mining"), ("Paints", "Paints & Coatings"),
          ("Water Treatment", "Water Treatment"), ("Plastics", "Plastics"), ("Pulp & Paper", "Pulp & Paper"),
          ("Fertilisers", "Agriculture"), ("Refining", "Petrochemical"), ("Pharma", "Pharmaceutical")]
SHIP_NAMES = ["MV Fairfield Pioneer", "MV Fairfield Agulhas", "MV Fairfield Mzansi", "MV Fairfield Benguela"]


def mdate(d, with_time=False):
    r = rng.random()
    if with_time:
        return d.strftime("%Y-%m-%d %H:%M") if r < 0.8 else d.strftime("%d/%m/%Y %H:%M")
    if r < 0.75:
        return d.strftime("%Y-%m-%d")
    return d.strftime("%d/%m/%Y") if r < 0.95 else d.strftime("%d-%b-%Y")


def excel_value(value):
    """Dates typed the normal way become real Excel dates. The odd formats stay as text, like they do in Excel."""
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return value


def write_xlsx(name, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(list(rows[0]))
    for row in rows:
        ws.append([excel_value(v) for v in row.values()])
    wb.save(RAW / name)


def build_assets():
    assets = []
    for i in range(1, 25):
        assets.append({"AssetID": f"TRK-{i:03d}", "AssetType": "Truck", "AssetName": f"Tanker {rng.choice('ABCDEFGH')}{rng.choice('BCDFGHJK')} {rng.randint(10, 99)} {rng.choice('BCDFGH')}{rng.choice('BCDFGH')} GP",
                       "CapacityTonnes": rng.choice([28, 30, 32, 34]), "YearBuilt": rng.randint(2012, 2024),
                       "HomeLocation": rng.choice(["JHB", "SAS", "SEC", "DUR"]), "Status": "Retired" if i in (7, 19) else "Active"})
    for i in range(1, 7):
        assets.append({"AssetID": f"TRN-{i:02d}", "AssetType": "Train", "AssetName": f"Tank train set {i}",
                       "CapacityTonnes": rng.choice([1200, 1500, 1800, 2000]), "YearBuilt": rng.randint(2005, 2020),
                       "HomeLocation": rng.choice(["SAS", "SEC", "JHB"]), "Status": "Active"})
    for i in range(1, 5):
        assets.append({"AssetID": f"SHP-{i:02d}", "AssetType": "Ship", "AssetName": SHIP_NAMES[i - 1],
                       "CapacityTonnes": [5000, 8000, 10000, 12000][i - 1], "YearBuilt": rng.randint(2003, 2018),
                       "HomeLocation": rng.choice(["DUR", "RCB"]), "Status": "Active"})
    return assets


def build_maintenance(assets):
    rows, windows, n = [], defaultdict(list), 0
    for a in assets:
        if a["Status"] != "Active":
            continue
        for _ in range(rng.randint(2, 4)):
            kind = rng.choices(["Scheduled service", "Inspection", "Breakdown repair"], [5, 3, 3])[0]
            t = a["AssetType"]
            days = {"Scheduled service": {"Truck": (1, 2), "Train": (3, 5), "Ship": (7, 14)},
                    "Inspection": {"Truck": (1, 1), "Train": (1, 2), "Ship": (2, 3)},
                    "Breakdown repair": {"Truck": (1, 4), "Train": (2, 6), "Ship": (3, 10)}}[kind][t]
            length = rng.randint(*days)
            start = START + timedelta(days=rng.randint(5, 350))
            end = start + timedelta(days=length - 1)
            per_day = {"Truck": 9000, "Train": 85000, "Ship": 260000}[t]
            cost = round(length * per_day * rng.uniform(0.6, 1.5) * (1.6 if kind == "Breakdown repair" else 1), 2)
            n += 1
            windows[a["AssetID"]].append((datetime.combine(start, datetime.min.time()),
                                          datetime.combine(end, datetime.max.time())))
            row = {"MaintenanceID": f"MNT{n:04d}", "AssetID": a["AssetID"], "StartDate": mdate(start),
                   "EndDate": mdate(end), "MaintenanceType": kind, "Cost": f"{cost:.2f}"}
            r = rng.random()
            if r < 0.10:
                row["Cost"] = f"R {cost:,.2f}"
            elif r < 0.13:
                row["MaintenanceType"] = kind.upper()
            elif r < 0.15:
                row["StartDate"], row["EndDate"] = row["EndDate"], mdate(start - timedelta(days=3))
            elif r < 0.17:
                row["AssetID"] = "TRK-999"
            rows.append(row)
            if rng.random() < 0.02:
                rows.append(dict(row))
    return rows, windows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "telemetry").mkdir(exist_ok=True)

    write_xlsx("locations.xlsx", [dict(zip(["LocationCode", "LocationName", "LocationType", "City", "Latitude", "Longitude"], l)) for l in LOCATIONS])
    write_xlsx("routes.xlsx", [dict(zip(["RouteID", "OriginCode", "DestinationCode", "Mode", "DistanceKm"], r)) for r in ROUTES])
    write_xlsx("products.xlsx", [dict(zip(["ProductCode", "ProductName", "HazardClass", "HazardSurchargePct"], p)) for p in PRODUCTS])
    write_xlsx("rate_card.xlsx", [dict(zip(["Mode", "RatePerTonneKm", "MinimumCharge", "FuelPricePerLitre"], r)) for r in RATES])

    customers, used = [], set()
    while len(customers) < 60:
        p, (s, industry) = rng.choice(PREFIX), rng.choice(SUFFIX)
        if (p, s) in used:
            continue
        used.add((p, s))
        customers.append({"CustomerID": f"CU{len(customers) + 1:03d}", "CustomerName": f"{p} {s}", "Industry": industry,
                          "City": rng.choice(["Johannesburg", "Durban", "Cape Town", "Gqeberha", "Bloemfontein", "Rustenburg", "Polokwane", "Maputo"]),
                          "CreditTermsDays": rng.choice([30, 30, 30, 45, 60, ""])})
    messy_customers = [dict(c) for c in customers]
    for c in messy_customers:
        if rng.random() < 0.1:
            c["CustomerName"] = f"  {c['CustomerName'].upper()}"
    messy_customers += [dict(c) for c in rng.sample(messy_customers, 3)]
    write_xlsx("customers.xlsx", messy_customers)

    assets = build_assets()
    messy_assets = [dict(a) for a in assets]
    for a in messy_assets:
        if rng.random() < 0.12:
            a["AssetType"] = a["AssetType"].upper()
        if rng.random() < 0.1:
            a["CapacityTonnes"] = f"{a['CapacityTonnes']} t"
    write_xlsx("assets.xlsx", messy_assets)

    maintenance, windows = build_maintenance(assets)
    write_xlsx("maintenance.xlsx", maintenance)

    loc = {l[0]: l for l in LOCATIONS}
    capacity = {a["AssetID"]: a["CapacityTonnes"] for a in assets}
    by_type = defaultdict(list)
    for a in assets:
        if a["Status"] == "Active":
            by_type[a["AssetType"]].append(a["AssetID"])
    next_free = {a["AssetID"]: datetime(2025, 1, 1, 5) for a in assets}
    routes_by_mode = defaultdict(list)
    for r in ROUTES:
        routes_by_mode[r[3]].append(r)

    orders, trips, pings = defaultdict(list), defaultdict(list), defaultdict(list)
    order_no = trip_no = 0
    day = START
    while day <= CUTOFF.date():
        todays = ["Road"] * rng.randint(2, 6)
        if rng.random() < 0.65:
            todays.append("Rail")
        if rng.random() < 0.27:
            todays.append("Sea")
        for mode in todays:
            order_no += 1
            oid = f"SO25{order_no:05d}"
            route = rng.choice(routes_by_mode[mode])
            km = route[4]
            product = rng.choice(PRODUCTS)
            tonnes = {"Road": round(rng.uniform(18, 95), 1), "Rail": float(rng.randint(500, 3200)),
                      "Sea": float(rng.randint(2500, 14000))}[mode]
            requested = day + timedelta(days=rng.randint(*LEAD_DAYS[mode]))
            cancelled = rng.random() < 0.04
            status = "Cancelled"

            if not cancelled:
                remaining, all_arrived = tonnes, True
                target = datetime.combine(day, datetime.min.time()) + timedelta(days=rng.randint(1, 2), hours=rng.randint(5, 14))
                while remaining > 0.4:
                    asset = min(by_type[MODE_ASSET[mode]], key=lambda a: next_free[a])
                    depart = max(target, next_free[asset]).replace(second=0, microsecond=0)
                    for w_start, w_end in sorted(windows[asset]):
                        if w_start <= depart <= w_end:
                            depart = (w_end + timedelta(hours=6)).replace(second=0, microsecond=0)
                    if depart > CUTOFF:
                        all_arrived = False
                        break
                    load = round(min(remaining, capacity[asset] * rng.uniform(0.92, 1.0)), 1)
                    remaining = round(remaining - load, 1)
                    hours = km / SPEED[mode] * rng.uniform(0.92, 1.3) + {"Road": 1, "Rail": 5, "Sea": 10}[mode]
                    reason = ""
                    if rng.random() < 0.09:
                        reason = rng.choice(DELAYS[mode])
                        hours += {"Road": rng.uniform(4, 20), "Rail": rng.uniform(12, 48), "Sea": rng.uniform(24, 96)}[mode]
                    arrive = (depart + timedelta(hours=hours)).replace(second=0, microsecond=0)
                    next_free[asset] = arrive + timedelta(hours=km / SPEED[mode] + TURNAROUND_H[mode])
                    actual_km = round(km * rng.uniform(0.98, 1.06), 1)
                    fuel = round(actual_km * FUEL_PER_KM[mode] * rng.uniform(0.9, 1.15), 1)
                    in_transit = arrive > CUTOFF
                    if in_transit:
                        all_arrived = False

                    trip_no += 1
                    row = {"TripID": f"TP{trip_no:06d}", "OrderID": oid, "AssetID": asset,
                           "DepartureDateTime": mdate(depart, True),
                           "ArrivalDateTime": "" if in_transit else mdate(arrive, True),
                           "LoadedTonnes": load, "DistanceKm": actual_km, "FuelLitres": "" if in_transit else fuel,
                           "TripStatus": "In transit" if in_transit else "Completed", "DelayReason": reason}
                    r = rng.random()
                    if r < 0.04:
                        row["DistanceKm"] = ""
                    elif r < 0.08:
                        row["DistanceKm"] = f"{actual_km} km"
                    elif r < 0.10 and not in_transit:
                        row["FuelLitres"] = ""
                    r = rng.random()
                    if r < 0.003:
                        row["AssetID"] = "TRK-999"
                    elif r < 0.006:
                        row["AssetID"] = rng.choice(by_type["Train" if mode == "Road" else "Truck"])
                    elif r < 0.009 and not in_transit:
                        row["DepartureDateTime"], row["ArrivalDateTime"] = row["ArrivalDateTime"], row["DepartureDateTime"]
                    elif r < 0.012:
                        row["LoadedTonnes"] = round(load * 3, 1)
                    elif r < 0.014 and not in_transit:
                        row["FuelLitres"] = -fuel
                    elif r < 0.016:
                        row["OrderID"] = "SO2599999"
                    elif r < 0.036:
                        row["AssetID"] = f" {asset.lower()} "
                    elif r < 0.05:
                        row["TripStatus"] = row["TripStatus"].upper()
                    f = f"trips_{depart:%Y_%m}.xlsx"
                    trips[f].append(row)
                    if rng.random() < 0.005:
                        trips[f].append(dict(row))

                    # truck GPS pings, one every 10 minutes
                    if mode == "Road":
                        o, d = loc[route[1]], loc[route[2]]
                        end = min(arrive, CUTOFF)
                        total = (arrive - depart).total_seconds()
                        cruise = actual_km / max(hours - 1.5, 1)
                        t, stop_left = depart, 0
                        while t <= end:
                            frac = (t - depart).total_seconds() / total
                            if stop_left == 0 and rng.random() < 0.03:
                                stop_left = rng.randint(2, 4)
                            if stop_left > 0 or frac < 0.02 or frac > 0.98:
                                speed, stop_left = 0.0, max(stop_left - 1, 0)
                            else:
                                speed = max(5.0, rng.gauss(cruise * 1.08, 7))
                            temp = rng.gauss(24, 3)
                            if rng.random() < 0.004:
                                temp = rng.uniform(46, 60)
                            p = {"asset_id": asset, "ping_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                                 "lat": round(o[4] + (d[4] - o[4]) * frac + rng.gauss(0, 0.01), 5),
                                 "lon": round(o[5] + (d[5] - o[5]) * frac + rng.gauss(0, 0.01), 5),
                                 "speed_kmh": round(speed, 1), "tank_temp_c": round(temp, 1)}
                            r = rng.random()
                            if r < 0.005:
                                p["speed_kmh"] = ""
                            elif r < 0.006:
                                p["speed_kmh"] = 999
                            elif r < 0.008:
                                p["lat"], p["lon"] = 0, 0
                            elif r < 0.0085:
                                p["ping_time"] = "ERR"
                            f = f"truck_pings_{t:%Y_%m}.csv"
                            pings[f].append(p)
                            if rng.random() < 0.01:
                                pings[f].append(dict(p))
                            t += timedelta(minutes=10)
                status = "Delivered" if all_arrived else "Booked"

            row = {"OrderID": oid, "OrderDate": mdate(day), "CustomerID": rng.choice(customers)["CustomerID"],
                   "ProductCode": product[0], "RouteID": route[0], "Tonnes": tonnes,
                   "RequestedDeliveryDate": mdate(requested), "OrderStatus": status}
            r = rng.random()
            if r < 0.05:
                row["Tonnes"] = f"{tonnes} t"
            elif r < 0.053:
                row["Tonnes"] = rng.choice([0, -tonnes])
            elif r < 0.056:
                row["CustomerID"] = "CU999"
            elif r < 0.058:
                row["RouteID"] = "RD99"
            elif r < 0.060:
                row["RequestedDeliveryDate"] = mdate(day - timedelta(days=4))
            elif r < 0.062:
                row["OrderDate"] = rng.choice(["", "TBC"])
            elif r < 0.10:
                row["OrderStatus"] = rng.choice([status.upper(), status.lower(), f" {status}"])
            elif r < 0.12:
                row["ProductCode"] = product[0].lower()
            f = f"sales_orders_{day:%Y_%m}.xlsx"
            orders[f].append(row)
            if rng.random() < 0.005:
                orders[f].append(dict(row))
        day += timedelta(days=1)

    for name, rows in orders.items():
        write_xlsx(name, rows)
    for name, rows in trips.items():
        write_xlsx(name, rows)
    n_pings = 0
    for name, rows in pings.items():
        with open(RAW / "telemetry" / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        n_pings += len(rows)
    print(f"{sum(map(len, orders.values()))} order rows, {sum(map(len, trips.values()))} trip rows, "
          f"{len(maintenance)} maintenance rows, {n_pings} telemetry pings -> {RAW}")


if __name__ == "__main__":
    main()
