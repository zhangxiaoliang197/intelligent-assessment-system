"""
AEGIS – Synthetic Data Generator (Expanded)
Generates realistic water supply sabotage events for the PoC.
Includes 20 facilities, 100 persons, 8 organizations, 6 sabotage scenarios,
~500 noise events + sensor readings + ~200 heterogeneous intel documents.

Based on real Canal de Isabel II infrastructure (Madrid).

Usage:
    python generate_data.py
"""

import json
import csv
import random
import os
import uuid
from datetime import datetime, timedelta

random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'seed')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# LOCATIONS  (real Madrid-area municipalities / zones)
# ═══════════════════════════════════════════════════════════════
LOCATIONS = [
    {"id": "LOC-001", "name": "Madrid Norte",               "lat": 40.4800, "lon": -3.6900},
    {"id": "LOC-002", "name": "Madrid Sur",                 "lat": 40.3800, "lon": -3.7100},
    {"id": "LOC-003", "name": "Alcalá de Henares",          "lat": 40.4818, "lon": -3.3635},
    {"id": "LOC-004", "name": "Getafe",                     "lat": 40.3047, "lon": -3.7311},
    {"id": "LOC-005", "name": "Torrejón de Ardoz",          "lat": 40.4553, "lon": -3.4697},
    {"id": "LOC-006", "name": "Móstoles",                   "lat": 40.3223, "lon": -3.8650},
    {"id": "LOC-007", "name": "Alcorcón",                   "lat": 40.3459, "lon": -3.8248},
    {"id": "LOC-008", "name": "Leganés",                    "lat": 40.3281, "lon": -3.7635},
    {"id": "LOC-009", "name": "Fuenlabrada",                "lat": 40.2841, "lon": -3.7940},
    {"id": "LOC-010", "name": "Majadahonda",                "lat": 40.4726, "lon": -3.8722},
    {"id": "LOC-011", "name": "Pozuelo de Alarcón",         "lat": 40.4356, "lon": -3.8145},
    {"id": "LOC-012", "name": "Las Rozas",                  "lat": 40.4929, "lon": -3.8760},
    {"id": "LOC-013", "name": "Rivas-Vaciamadrid",          "lat": 40.3520, "lon": -3.5243},
    {"id": "LOC-014", "name": "Colmenar Viejo",             "lat": 40.6594, "lon": -3.7666},
    {"id": "LOC-015", "name": "San Sebastián de los Reyes", "lat": 40.5475, "lon": -3.6269},
    {"id": "LOC-016", "name": "Parla",                      "lat": 40.2380, "lon": -3.7676},
    {"id": "LOC-017", "name": "Valdemoro",                  "lat": 40.1907, "lon": -3.6744},
    {"id": "LOC-018", "name": "Aranjuez",                   "lat": 40.0323, "lon": -3.6028},
    {"id": "LOC-019", "name": "Tres Cantos",                "lat": 40.6008, "lon": -3.7074},
    {"id": "LOC-020", "name": "Coslada",                    "lat": 40.4237, "lon": -3.5615},
]

# ═══════════════════════════════════════════════════════════════
# FACILITIES  (20 – based on real Canal de Isabel II infra)
# ═══════════════════════════════════════════════════════════════
FACILITIES = [
    # Water Treatment Plants (ETAPs)
    {"id": "FAC-001", "name": "ETAP Norte",                   "type": "WaterTreatmentPlant", "lat": 40.4800, "lon": -3.6900, "criticality": "CRITICAL", "location": "LOC-001"},
    {"id": "FAC-002", "name": "ETAP Torrejón",                "type": "WaterTreatmentPlant", "lat": 40.4553, "lon": -3.4697, "criticality": "CRITICAL", "location": "LOC-005"},
    {"id": "FAC-003", "name": "ETAP Colmenar Viejo",          "type": "WaterTreatmentPlant", "lat": 40.6594, "lon": -3.7666, "criticality": "HIGH",     "location": "LOC-014"},
    {"id": "FAC-004", "name": "ETAP Móstoles",                "type": "WaterTreatmentPlant", "lat": 40.3223, "lon": -3.8650, "criticality": "HIGH",     "location": "LOC-006"},

    # Pump Stations
    {"id": "FAC-005", "name": "Estación Bombeo Sur",          "type": "PumpStation",         "lat": 40.3800, "lon": -3.7100, "criticality": "HIGH",     "location": "LOC-002"},
    {"id": "FAC-006", "name": "Estación Bombeo Móstoles",     "type": "PumpStation",         "lat": 40.3250, "lon": -3.8680, "criticality": "MEDIUM",   "location": "LOC-006"},
    {"id": "FAC-007", "name": "Estación Bombeo Majadahonda",  "type": "PumpStation",         "lat": 40.4726, "lon": -3.8722, "criticality": "MEDIUM",   "location": "LOC-010"},
    {"id": "FAC-008", "name": "Estación Bombeo Fuenlabrada",  "type": "PumpStation",         "lat": 40.2841, "lon": -3.7940, "criticality": "MEDIUM",   "location": "LOC-009"},
    {"id": "FAC-009", "name": "Estación Bombeo Las Rozas",    "type": "PumpStation",         "lat": 40.4929, "lon": -3.8760, "criticality": "LOW",      "location": "LOC-012"},

    # Reservoirs / Depósitos
    {"id": "FAC-010", "name": "Depósito Alcalá",              "type": "Reservoir",           "lat": 40.4818, "lon": -3.3635, "criticality": "HIGH",     "location": "LOC-003"},
    {"id": "FAC-011", "name": "Depósito Getafe",              "type": "Reservoir",           "lat": 40.3047, "lon": -3.7311, "criticality": "MEDIUM",   "location": "LOC-004"},
    {"id": "FAC-012", "name": "Depósito Leganés",             "type": "Reservoir",           "lat": 40.3281, "lon": -3.7635, "criticality": "MEDIUM",   "location": "LOC-008"},
    {"id": "FAC-013", "name": "Depósito Tres Cantos",         "type": "Reservoir",           "lat": 40.6008, "lon": -3.7074, "criticality": "HIGH",     "location": "LOC-019"},
    {"id": "FAC-014", "name": "Depósito Pozuelo",             "type": "Reservoir",           "lat": 40.4356, "lon": -3.8145, "criticality": "MEDIUM",   "location": "LOC-011"},

    # Distribution Nodes
    {"id": "FAC-015", "name": "Nodo Distribución Getafe",     "type": "DistributionNode",    "lat": 40.3047, "lon": -3.7311, "criticality": "MEDIUM",   "location": "LOC-004"},
    {"id": "FAC-016", "name": "Nodo Distribución Alcorcón",   "type": "DistributionNode",    "lat": 40.3459, "lon": -3.8248, "criticality": "MEDIUM",   "location": "LOC-007"},
    {"id": "FAC-017", "name": "Nodo Distribución Parla",      "type": "DistributionNode",    "lat": 40.2380, "lon": -3.7676, "criticality": "LOW",      "location": "LOC-016"},
    {"id": "FAC-018", "name": "Nodo Distribución S.S. Reyes", "type": "DistributionNode",    "lat": 40.5475, "lon": -3.6269, "criticality": "MEDIUM",   "location": "LOC-015"},
    {"id": "FAC-019", "name": "Nodo Distribución Rivas",      "type": "DistributionNode",    "lat": 40.3520, "lon": -3.5243, "criticality": "LOW",      "location": "LOC-013"},
    {"id": "FAC-020", "name": "Nodo Distribución Valdemoro",  "type": "DistributionNode",    "lat": 40.1907, "lon": -3.6744, "criticality": "LOW",      "location": "LOC-017"},
]

# ═══════════════════════════════════════════════════════════════
# ORGANIZATIONS  (8 – 1 utility, 4 maintenance, 2 security, 1 IT)
# ═══════════════════════════════════════════════════════════════
ORGANIZATIONS = [
    {"id": "ORG-001", "name": "Canal de Isabel II",           "type": "WaterUtility"},
    {"id": "ORG-002", "name": "AquaServ Mantenimiento SL",    "type": "MaintenanceContractor"},
    {"id": "ORG-003", "name": "HidroTec Ingeniería SA",       "type": "MaintenanceContractor"},
    {"id": "ORG-004", "name": "TechPipe Solutions SL",        "type": "MaintenanceContractor"},
    {"id": "ORG-005", "name": "Ibérica de Bombas y Válvulas", "type": "MaintenanceContractor"},
    {"id": "ORG-006", "name": "CyberSec Industrial SA",       "type": "SecurityProvider"},
    {"id": "ORG-007", "name": "SecurIT Consulting",           "type": "SecurityProvider"},
    {"id": "ORG-008", "name": "SmartWater Analytics SL",      "type": "ITConsulting"},
]

# ═══════════════════════════════════════════════════════════════
# PERSONS  (100)
# ═══════════════════════════════════════════════════════════════
_FIRST_NAMES_M = [
    "Carlos", "Javier", "Miguel", "Alejandro", "Pablo", "David", "Daniel", "Sergio",
    "Adrián", "Álvaro", "Andrés", "Antonio", "Diego", "Eduardo", "Enrique",
    "Fernando", "Francisco", "Gonzalo", "Héctor", "Hugo", "Iván", "Jorge",
    "José", "Juan", "Luis", "Manuel", "Marcos", "Mario", "Óscar", "Pedro",
    "Rafael", "Ramón", "Ricardo", "Roberto", "Rubén", "Santiago", "Tomás", "Víctor",
]
_FIRST_NAMES_F = [
    "Ana", "Lucía", "Elena", "María", "Carmen", "Laura", "Marta", "Sofía",
    "Paula", "Patricia", "Raquel", "Sara", "Isabel", "Cristina", "Beatriz",
    "Alicia", "Clara", "Diana", "Eva", "Irene", "Julia", "Nuria", "Pilar",
    "Rosa", "Silvia", "Teresa", "Verónica", "Blanca", "Inés", "Rocío",
]
_LAST_NAMES = [
    "García", "Martínez", "López", "Hernández", "González", "Rodríguez",
    "Sánchez", "Pérez", "Fernández", "Gómez", "Ruiz", "Díaz", "Álvarez",
    "Moreno", "Muñoz", "Romero", "Jiménez", "Torres", "Navarro", "Domínguez",
    "Vázquez", "Serrano", "Ramos", "Blanco", "Molina", "Suárez", "Ortega",
    "Castro", "Rubio", "Marín", "Iglesias", "Cortés", "Garrido", "Guerrero",
    "Santos", "Prieto", "Delgado", "Medina", "Herrera", "Castillo", "Cabrera",
]
_FOREIGN_FIRST = ["Dmitri", "Viktor", "Ahmed", "Nikolai", "Youssef", "Andrei", "Hassan", "Bogdan", "Oleg", "Karim"]
_FOREIGN_LAST  = ["Volkov", "Petrov", "Hassan", "Ivanov", "El Fassi", "Kuznetsov", "Alami", "Stoica", "Kozlov", "Benali"]

_ROLES_EMPLOYEE = [
    "Plant Operator", "SCADA Engineer", "Security Manager", "Water Quality Analyst",
    "Network Administrator", "Shift Supervisor", "Lab Technician", "Process Engineer",
    "Environmental Compliance Officer", "Operations Director", "Control Room Operator",
    "Instrumentation Engineer", "Distribution Manager", "Customer Service Manager",
    "Health & Safety Officer",
]
_ROLES_CONTRACTOR = [
    "Maintenance Technician", "Pump Specialist", "IT Consultant", "Electrical Engineer",
    "Valve Technician", "Pipeline Inspector", "SCADA Integrator", "Telemetry Technician",
    "Civil Works Supervisor", "Chemical Dosing Specialist", "Crane Operator",
    "Welding Specialist", "Diving Inspector", "Calibration Technician",
]


def _generate_persons():
    """Generate 100 persons: ~55 employees + ~45 contractors"""
    persons = []
    used_names = set()

    # Canal de Isabel II employees (55)
    employee_count = 0
    while employee_count < 55:
        is_female = random.random() < 0.45
        first = random.choice(_FIRST_NAMES_F if is_female else _FIRST_NAMES_M)
        last1 = random.choice(_LAST_NAMES)
        last2 = random.choice(_LAST_NAMES)
        name = f"{first} {last1} {last2}"
        if name in used_names:
            continue
        used_names.add(name)
        employee_count += 1
        pid = f"PER-{len(persons)+1:03d}"
        clearance = random.choice(["L1", "L2", "L2", "L3"])
        persons.append({
            "id": pid,
            "name": name,
            "role": random.choice(_ROLES_EMPLOYEE),
            "type": "Employee",
            "clearance": clearance,
            "org": "ORG-001",
        })

    # Contractors (45) – spread across maintenance + security + IT companies
    contractor_orgs = (["ORG-002"] * 12 + ["ORG-003"] * 10 + ["ORG-004"] * 8 +
                       ["ORG-005"] * 6 + ["ORG-006"] * 4 + ["ORG-007"] * 3 + ["ORG-008"] * 2)
    random.shuffle(contractor_orgs)

    contractor_count = 0
    while contractor_count < 45:
        if random.random() < 0.3:
            first = random.choice(_FOREIGN_FIRST)
            last = random.choice(_FOREIGN_LAST)
            name = f"{first} {last}"
        else:
            is_female = random.random() < 0.35
            first = random.choice(_FIRST_NAMES_F if is_female else _FIRST_NAMES_M)
            last = random.choice(_LAST_NAMES)
            name = f"{first} {last}"
        if name in used_names:
            continue
        used_names.add(name)
        pid = f"PER-{len(persons)+1:03d}"
        org = contractor_orgs[contractor_count]
        persons.append({
            "id": pid,
            "name": name,
            "role": random.choice(_ROLES_CONTRACTOR),
            "type": "Contractor",
            "clearance": random.choice(["L1", "L1", "L1", "L2"]),
            "org": org,
        })
        contractor_count += 1

    return persons


PERSONS = _generate_persons()

# ═══════════════════════════════════════════════════════════════
# SENSORS  (4-6 per facility ≈ ~100 sensors)
# ═══════════════════════════════════════════════════════════════
METRICS = [
    {"name": "chlorine_mg_l",   "unit": "mg/L",  "min": 0.2,  "max": 2.0},
    {"name": "turbidity_ntu",   "unit": "NTU",   "min": 0.0,  "max": 4.0},
    {"name": "ph",              "unit": "pH",    "min": 6.5,  "max": 8.5},
    {"name": "flow_rate_m3h",   "unit": "m³/h",  "min": 100,  "max": 500},
    {"name": "pressure_bar",    "unit": "bar",   "min": 2.0,  "max": 6.0},
    {"name": "temperature_c",   "unit": "°C",    "min": 5.0,  "max": 25.0},
    {"name": "conductivity_us", "unit": "µS/cm", "min": 200,  "max": 800},
    {"name": "dissolved_o2",    "unit": "mg/L",  "min": 4.0,  "max": 12.0},
]

_SENSOR_NAMES = {
    "chlorine_mg_l":   "Cloro Residual",
    "turbidity_ntu":   "Turbidez",
    "ph":              "pH",
    "flow_rate_m3h":   "Caudal",
    "pressure_bar":    "Presión",
    "temperature_c":   "Temperatura",
    "conductivity_us": "Conductividad",
    "dissolved_o2":    "Oxígeno Disuelto",
}


def _generate_sensors():
    sensors = []
    sid = 0
    for fac in FACILITIES:
        n_sensors = random.randint(4, 6)
        metrics_for_fac = random.sample(METRICS, n_sensors)
        for m in metrics_for_fac:
            sid += 1
            sensors.append({
                "id": f"SEN-{sid:03d}",
                "name": f"{_SENSOR_NAMES[m['name']]} {fac['name'].split()[-1]}",
                "metric": m["name"],
                "unit": m["unit"],
                "normalMin": m["min"],
                "normalMax": m["max"],
                "facilityId": fac["id"],
            })
    return sensors


SENSORS = _generate_sensors()

# ═══════════════════════════════════════════════════════════════
# ASSETS  (3–5 per facility)
# ═══════════════════════════════════════════════════════════════
_ASSET_TEMPLATES = [
    {"type": "PLC",       "label": "PLC",       "models": ["Siemens S7-1500", "Schneider M340", "Allen-Bradley ControlLogix", "ABB AC500"]},
    {"type": "Valve",     "label": "Valve",     "models": ["VAG EKN", "Belgicast BV-05", "AVK Serie 36", "Hawle E2"]},
    {"type": "Pump",      "label": "Pump",      "models": ["Grundfos CR90", "KSB Movitec", "Wilo CronoLine", "Ebara 3M"]},
    {"type": "Camera",    "label": "Camera",    "models": ["Hikvision DS-2CD", "Dahua IPC-HFW", "Axis P3245", "Bosch Flexidome"]},
    {"type": "RTU",       "label": "RTU",       "models": ["Schneider SCADAPack", "ABB RTU560", "GE D400", "Motorola ACE3600"]},
    {"type": "FlowMeter", "label": "FlowMeter", "models": ["Endress+Hauser Promag", "Siemens MAG 8000", "ABB AquaMaster"]},
]


def _generate_assets():
    assets = []
    aid = 0
    for fac in FACILITIES:
        n_assets = random.randint(3, 5)
        templates = random.sample(_ASSET_TEMPLATES, min(n_assets, len(_ASSET_TEMPLATES)))
        for t in templates[:n_assets]:
            aid += 1
            assets.append({
                "id": f"AST-{aid:03d}",
                "name": f"{t['label']}-{fac['id'].split('-')[1]}",
                "type": t["type"],
                "model": random.choice(t["models"]),
                "facilityId": fac["id"],
            })
    return assets


ASSETS = _generate_assets()

# ═══════════════════════════════════════════════════════════════
# PERSON ↔ PERSON connections (social network)
# ═══════════════════════════════════════════════════════════════
def _generate_person_connections():
    connections = []
    used = set()

    # Same-org colleague links
    orgs = {}
    for p in PERSONS:
        orgs.setdefault(p["org"], []).append(p["id"])

    for org_id, members in orgs.items():
        n_links = min(len(members) * 2, len(members) * (len(members) - 1) // 2)
        for _ in range(n_links):
            a, b = random.sample(members, 2)
            key = tuple(sorted([a, b]))
            if key not in used:
                used.add(key)
                connections.append({
                    "from": a, "to": b,
                    "type": "colleague",
                    "confidence": round(random.uniform(0.7, 1.0), 2)
                })

    # Cross-org links (suspicious / interesting)
    contractor_persons = [p for p in PERSONS if p["type"] == "Contractor"]
    for _ in range(20):
        a, b = random.sample(contractor_persons, 2)
        if a["org"] != b["org"]:
            key = tuple(sorted([a["id"], b["id"]]))
            if key not in used:
                used.add(key)
                connections.append({
                    "from": a["id"], "to": b["id"],
                    "type": random.choice(["former_colleague", "acquaintance"]),
                    "confidence": round(random.uniform(0.3, 0.7), 2)
                })

    return connections


CONNECTIONS = _generate_person_connections()

# ═══════════════════════════════════════════════════════════════
# HETEROGENEOUS INTEL DOCUMENTS  (~200)
# Video transcriptions, PDF reports, lab analyses, SCADA logs,
# maintenance reports, worker profiles, emails, regulatory
# inspections, incident photo analyses, access badge records
# ═══════════════════════════════════════════════════════════════

DOC_COUNTER = 0

def _next_doc_id():
    global DOC_COUNTER
    DOC_COUNTER += 1
    return f"DOC-{DOC_COUNTER:04d}"


def _random_ts(base_year=2025, base_month=10, range_days=180):
    base = datetime(base_year, base_month, 1)
    return (base + timedelta(days=random.uniform(0, range_days),
                             hours=random.uniform(0, 24))).isoformat()


def generate_intel_documents():
    """Generate ~200 heterogeneous intel documents for OpenSearch indexing."""
    docs = []

    # ──────────────────────────────────────────────────
    # 1. VIDEO TRANSCRIPTIONS  (~25 CCTV footage analyses)
    # ──────────────────────────────────────────────────
    _video_templates = [
        ("CCTV footage analysis – perimeter camera {cam}",
         "Transcription of CCTV recording at {fac}. Camera {cam} captured {n} individuals "
         "approaching the {area} at {time}. {detail} No credentials were presented at the checkpoint. "
         "Duration of presence: approximately {dur} minutes. Clothing: {clothes}. Vehicle: {vehicle}. "
         "Quality: {quality}. Operator notes: {notes}"),
        ("Night vision recording – interior camera {cam}",
         "Night recording from camera {cam} inside {fac} control room. At {time}, a figure is seen "
         "accessing the {panel} panel without badge authentication. The individual appeared to "
         "{action}. Timestamp correlation with SCADA logs shows {scada_detail}. "
         "Face partially obscured by {obstruction}. Gait analysis flagged as {gait}."),
        ("Drone surveillance footage – facility exterior",
         "Aerial surveillance over {fac} conducted on {date}. Drone captured thermal imaging of "
         "{area}. Unusual heat signature detected near {heat_loc}. {thermal_detail} "
         "Perimeter integrity: {perimeter}. Suspicious vehicle observed parked at coordinates "
         "{coords} for {dur} hours. License plate: {plate}."),
        ("Vehicle tracking camera – access road",
         "Access road camera at {fac} recorded {n} vehicles between {time_start} and {time_end}. "
         "Vehicle #{veh_num} (plate: {plate}) not registered in authorized supplier database. "
         "Driver appeared to photograph the facility before entering. {detail} "
         "Cross-referencing with contractor database returned no matches."),
    ]
    _areas = ["south perimeter", "chemical storage", "pump hall entrance", "dosing room",
              "control building rear", "transformer substation", "main gate", "emergency exit"]
    _clothes = ["dark coveralls", "orange hi-vis vest over civilian clothes", "maintenance uniform without company logo",
                "black jacket and cap", "blue overalls with unknown company patch"]
    _vehicles = ["white unmarked van", "silver sedan, model Renault Mégane", "dark SUV with tinted windows",
                 "utility truck with no company markings", "motorcycle", "no vehicle observed"]
    _panels = ["PLC control", "SCADA HMI", "chlorine dosing", "pressure regulation", "main breaker", "telemetry"]
    _actions = ["connect a USB device to the HMI terminal", "photograph the control panel screen",
                "manipulate valve control switches", "install a small device behind the terminal",
                "copy data from the operator workstation", "remove a component from the panel"]
    _obstructions = ["a baseball cap", "a surgical mask", "a hood", "reflective material", "glare from overhead lights"]
    _cameras = ["CAM-A01", "CAM-A02", "CAM-B01", "CAM-B02", "CAM-C01", "CAM-D01", "CAM-E01"]

    for _ in range(25):
        fac = random.choice(FACILITIES)
        person = random.choice(PERSONS)
        tpl_title, tpl_content = random.choice(_video_templates)
        cam = random.choice(_cameras)

        content = tpl_content.format(
            fac=fac["name"], cam=cam, n=random.randint(1, 3),
            area=random.choice(_areas), time=f"{random.randint(0,23):02d}:{random.randint(0,59):02d}",
            detail=f"One individual resembles profile of {person['name']} ({person['role']}) based on height and gait pattern.",
            dur=random.randint(3, 45), clothes=random.choice(_clothes), vehicle=random.choice(_vehicles),
            quality=random.choice(["720p clear", "1080p clear", "480p low-light degraded", "IR night vision"]),
            notes=random.choice(["Flagged for supervisor review", "Archived – no action", "Escalated to security manager",
                                 "Cross-referenced with access logs – mismatch found"]),
            panel=random.choice(_panels), action=random.choice(_actions),
            scada_detail=random.choice(["a parameter change at the same timestamp", "no corresponding SCADA event",
                                        "a brief network disconnection", "an anomalous setpoint modification"]),
            obstruction=random.choice(_obstructions),
            gait=random.choice(["consistent with known personnel", "inconsistent – possible unknown individual",
                                "flagged – matches prior incident footage"]),
            date=_random_ts()[:10], heat_loc=random.choice(_areas),
            thermal_detail=random.choice(["Chemical container temperature elevated above normal.",
                                          "No thermal anomalies detected.",
                                          "Warm fluid leak detected near pipeline junction."]),
            perimeter=random.choice(["intact", "breach detected at sector 3", "fence sensor offline"]),
            coords=f"{fac['lat']:.4f}, {fac['lon']:.4f}",
            plate=f"{random.randint(1000,9999)}-{''.join(random.choices('BCDFGHJKLMNPRSTVWXYZ', k=3))}",
            time_start=f"{random.randint(0,12):02d}:00", time_end=f"{random.randint(13,23):02d}:00",
            veh_num=random.randint(1, 8),
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "video_transcription",
            "title": tpl_title.format(cam=cam),
            "content": content,
            "sourceFile": f"CCTV_{cam}_{fac['id']}_{random.randint(20250101,20260301)}.mp4",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": person["id"],
            "personName": person["name"],
            "timestamp": _random_ts(),
            "classification": random.choice(["RESTRICTED", "CONFIDENTIAL", "INTERNAL"]),
        })

    # ──────────────────────────────────────────────────
    # 2. MAINTENANCE REPORTS  (~30 PDF-style documents)
    # ──────────────────────────────────────────────────
    _maint_templates = [
        ("Maintenance Report – {system} at {fac}",
         "## Maintenance Report\n\n"
         "**Work Order:** WO-{wo}\n"
         "**Technician:** {tech}\n"
         "**Company:** {company}\n"
         "**Facility:** {fac}\n"
         "**Date:** {date}\n"
         "**System:** {system}\n\n"
         "### Work Performed\n"
         "{work}\n\n"
         "### Findings\n"
         "{findings}\n\n"
         "### Parts Replaced\n"
         "- {part1}\n- {part2}\n\n"
         "### Anomalies Noted\n"
         "{anomaly}\n\n"
         "### Sign-off\n"
         "Verified by: {supervisor}\n"
         "Supervisor clearance: {clearance}"),
    ]
    _systems = ["Chlorine dosing pump", "Main intake valve", "SCADA HMI terminal",
                "Backup power generator", "pH adjustment system", "Filtration bank A",
                "Flow control valve", "Pressure regulator", "Telemetry antenna",
                "RTU communication module", "Emergency shutdown system"]
    _work_details = [
        "Replaced worn impeller seals. Recalibrated flow rate to 145 m³/h. Tested emergency shutoff.",
        "Firmware updated from v3.2.1 to v4.0.0. Default credentials changed. Backup configuration saved.",
        "Cleaned and replaced chlorine injection nozzles. Verified dosing accuracy with test samples.",
        "Replaced UPS batteries (x4). Load test performed – 15 min at full load. Transfer switch verified.",
        "Rebuilt valve actuator. Replaced corroded bolts. Torque tested to specification.",
        "Calibrated all 6 sensor probes. Two probes showed drift >5% – replaced with new units.",
        "Installed new SCADA patch (CVE-2025-4421 mitigation). Rebooted system. Verified all I/O points.",
        "Repaired cable fault on trunk line. Replaced 45m of damaged conduit. Continuity test passed.",
    ]
    _anomalies_maint = [
        "Found unauthorized USB device connected to HMI terminal. Device was not in any previous inventory. Removed and handed to security.",
        "Noticed signs of physical tampering on valve control panel – scratch marks around lock mechanism. Photographed and reported.",
        "Calibration values had been manually overridden since last visit. Previous technician not documented. Reset to factory defaults.",
        "Found an unregistered SIM card installed in the RTU communication module. Removed and bagged for forensic analysis.",
        "Access log shows entry at 03:15 AM by badge #{badge} – not matching any scheduled work. Reported to facility manager.",
        "Network cable rerouted through an unauthorized switch. Switch had unknown MAC address. Disconnected and reported to IT security.",
        "Chemical storage room showed signs of recent entry – safety seal broken. Inventory check revealed 2L discrepancy in sodium hypochlorite.",
        "No anomalies detected. All systems operating within normal parameters.",
        "No anomalies detected. System fully operational.",
    ]
    _parts = ["O-ring seal kit P/N 45-882", "Impeller assembly P/N IP-200", "Capacitor 470µF 400V",
              "Pressure transducer PT-3000", "Solenoid valve SV-12", "pH probe (Endress+Hauser CPS11D)",
              "Battery pack 12V 100Ah", "Cable gland M25 IP68", "Fuse 10A 500V HRC",
              "Bearing 6205-2RS", "Coupling spider 95 Shore A", "Filter cartridge FC-10µm"]

    for _ in range(30):
        fac = random.choice(FACILITIES)
        contractors = [p for p in PERSONS if p["type"] == "Contractor"]
        tech = random.choice(contractors)
        org = next((o for o in ORGANIZATIONS if o["id"] == tech["org"]), ORGANIZATIONS[1])
        supervisors = [p for p in PERSONS if p["type"] == "Employee" and p["clearance"] in ("L2", "L3")]
        supervisor = random.choice(supervisors)
        system = random.choice(_systems)

        content = _maint_templates[0][1].format(
            wo=f"{random.randint(2025001, 2026999)}",
            tech=tech["name"], company=org["name"], fac=fac["name"],
            date=_random_ts()[:10], system=system,
            work=random.choice(_work_details),
            findings=random.choice(["All components within tolerance.", "Minor wear detected – scheduled for next quarter.",
                                    "Significant corrosion on inlet pipe – needs priority replacement.",
                                    "Electrical connections showed signs of overheating. Tightened and applied thermal paste."]),
            part1=random.choice(_parts), part2=random.choice(_parts),
            anomaly=random.choice(_anomalies_maint).format(badge=random.randint(1000, 9999)),
            supervisor=supervisor["name"], clearance=supervisor["clearance"],
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "maintenance_report",
            "title": _maint_templates[0][0].format(system=system, fac=fac["name"]),
            "content": content,
            "sourceFile": f"MR_{fac['id']}_{random.randint(20250101,20260301)}.pdf",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": tech["id"],
            "personName": tech["name"],
            "timestamp": _random_ts(),
            "classification": "INTERNAL",
        })

    # ──────────────────────────────────────────────────
    # 3. LAB ANALYSIS RESULTS  (~25 water quality reports)
    # ──────────────────────────────────────────────────
    _lab_templates = [
        ("Water Quality Analysis – {fac} – Sample #{sample}",
         "## Laboratory Analysis Report\n\n"
         "**Lab:** Canal de Isabel II – Central Laboratory\n"
         "**Sample ID:** {sample}\n"
         "**Collection Point:** {fac} – {point}\n"
         "**Collected by:** {collector}\n"
         "**Collection Date:** {date}\n"
         "**Analysis Date:** {analysis_date}\n\n"
         "### Parameters Analyzed\n\n"
         "| Parameter | Value | Unit | Limit | Status |\n"
         "|-----------|-------|------|-------|--------|\n"
         "| Free Chlorine | {cl} | mg/L | 0.2-2.0 | {cl_status} |\n"
         "| Turbidity | {turb} | NTU | <1.0 | {turb_status} |\n"
         "| pH | {ph} | - | 6.5-9.5 | {ph_status} |\n"
         "| Conductivity | {cond} | µS/cm | <2500 | {cond_status} |\n"
         "| E.coli | {ecoli} | CFU/100mL | 0 | {ecoli_status} |\n"
         "| Coliform | {coli} | CFU/100mL | 0 | {coli_status} |\n"
         "| Lead | {lead} | µg/L | <10 | {lead_status} |\n"
         "| Arsenic | {arsenic} | µg/L | <10 | {arsenic_status} |\n"
         "| {extra_param} | {extra_val} | {extra_unit} | {extra_limit} | {extra_status} |\n\n"
         "### Observations\n"
         "{observations}\n\n"
         "### Conclusion\n"
         "{conclusion}"),
    ]
    _collection_points = ["Raw water intake", "Post-filtration", "Post-chlorination",
                          "Distribution exit", "Storage tank outlet", "Consumer tap (random sample)"]
    _extra_params = [
        ("Nitrate", lambda: round(random.uniform(1, 60), 1), "mg/L", "<50"),
        ("Fluoride", lambda: round(random.uniform(0.1, 2.0), 2), "mg/L", "<1.5"),
        ("Manganese", lambda: round(random.uniform(0, 100), 0), "µg/L", "<50"),
        ("Iron", lambda: round(random.uniform(0, 300), 0), "µg/L", "<200"),
        ("Trihalomethanes", lambda: round(random.uniform(5, 120), 1), "µg/L", "<100"),
    ]

    for _ in range(25):
        fac = random.choice(FACILITIES)
        lab_techs = [p for p in PERSONS if "Lab" in p["role"] or "Analyst" in p["role"] or "Quality" in p["role"]]
        collector = random.choice(lab_techs) if lab_techs else random.choice(PERSONS[:55])

        cl = round(random.uniform(0.01, 3.5), 2)
        turb = round(random.uniform(0.1, 8.0), 2)
        ph = round(random.uniform(5.5, 9.8), 1)
        cond = round(random.uniform(150, 2800))
        ecoli = random.choices([0, 0, 0, 0, random.randint(1, 15)], weights=[80, 5, 5, 5, 5])[0]
        coli = random.choices([0, 0, 0, random.randint(1, 25)], weights=[70, 10, 10, 10])[0]
        lead = round(random.uniform(0, 15), 1)
        arsenic = round(random.uniform(0, 12), 1)
        extra = random.choice(_extra_params)
        extra_val = extra[1]()

        anomalies = []
        if cl < 0.2 or cl > 2.0: anomalies.append(f"chlorine {'below' if cl < 0.2 else 'above'} acceptable range")
        if turb > 1.0: anomalies.append("turbidity exceeds limit")
        if ecoli > 0: anomalies.append(f"E.coli detected: {ecoli} CFU/100mL – CRITICAL")
        if coli > 0: anomalies.append(f"coliform bacteria detected: {coli} CFU/100mL")
        if lead > 10: anomalies.append("lead exceeds regulatory limit")

        content = _lab_templates[0][1].format(
            fac=fac["name"], sample=f"S-{random.randint(100000,999999)}",
            point=random.choice(_collection_points),
            collector=collector["name"],
            date=_random_ts()[:10],
            analysis_date=_random_ts()[:10],
            cl=cl, cl_status="✅ OK" if 0.2 <= cl <= 2.0 else "⚠️ OUT OF RANGE",
            turb=turb, turb_status="✅ OK" if turb < 1.0 else "⚠️ ELEVATED",
            ph=ph, ph_status="✅ OK" if 6.5 <= ph <= 9.5 else "⚠️ OUT OF RANGE",
            cond=cond, cond_status="✅ OK" if cond < 2500 else "⚠️ HIGH",
            ecoli=ecoli, ecoli_status="✅ OK" if ecoli == 0 else "🔴 FAIL",
            coli=coli, coli_status="✅ OK" if coli == 0 else "🔴 FAIL",
            lead=lead, lead_status="✅ OK" if lead < 10 else "⚠️ ELEVATED",
            arsenic=arsenic, arsenic_status="✅ OK" if arsenic < 10 else "⚠️ ELEVATED",
            extra_param=extra[0], extra_val=extra_val, extra_unit=extra[2], extra_limit=extra[3],
            extra_status="✅ OK" if str(extra_val) < extra[3].replace("<", "").replace(">", "") else "⚠️ CHECK",
            observations="; ".join(anomalies) if anomalies else "All parameters within acceptable ranges.",
            conclusion=("**ALERT: Sample fails quality criteria. Immediate resampling ordered. "
                        "Facility operations notified.**" if ecoli > 0 or lead > 10 else
                        "Sample meets all regulatory requirements. No action required." if not anomalies else
                        "Minor deviations noted. Monitoring frequency increased to daily."),
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "lab_analysis",
            "title": _lab_templates[0][0].format(fac=fac["name"], sample=f"S-{random.randint(100000,999999)}"),
            "content": content,
            "sourceFile": f"LAB_{fac['id']}_{random.randint(20250101,20260301)}.pdf",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": collector["id"],
            "personName": collector["name"],
            "timestamp": _random_ts(),
            "classification": "INTERNAL",
        })

    # ──────────────────────────────────────────────────
    # 4. WORKER PROFILES  (~30 HR/security dossiers)
    # ──────────────────────────────────────────────────
    _profile_flags = [
        "No security flags.", "Clean record. Eligible for clearance upgrade.",
        "Flagged: frequent after-hours access patterns detected in last 90 days.",
        "Flagged: social media posts critical of water utility management. OSINT team monitoring.",
        "Flagged: financial difficulties reported by credit monitoring service. Review recommended.",
        "Flagged: previous employer reported IP theft investigation (inconclusive).",
        "Flagged: travel to high-risk region in past 12 months. Debriefing completed.",
        "Flagged: undisclosed secondary employment at competing utility contractor.",
        "Flagged: badge sharing incident documented on {date}. Verbal warning issued.",
        "Note: currently under internal investigation for unauthorized data access. Restricted from critical systems.",
    ]
    _training_certs = [
        "SCADA Security Awareness (valid until 2026-12)",
        "Chemical Handling & HAZMAT Level 2",
        "Confined Space Entry Certification",
        "First Aid & Emergency Response",
        "ISO 27001 Information Security Basics",
        "Cybersecurity for Industrial Control Systems",
        "Water Quality Sampling Procedures",
        "Heavy Equipment Operation License",
        "Electrical Safety – High Voltage",
    ]

    for i in range(30):
        person = PERSONS[i * 3 % len(PERSONS)]
        org = next((o for o in ORGANIZATIONS if o["id"] == person["org"]), ORGANIZATIONS[0])
        facs_assigned = random.sample(FACILITIES, random.randint(1, 4))
        certs = random.sample(_training_certs, random.randint(2, 5))

        content = (
            f"## Personnel Security Dossier\n\n"
            f"**Employee ID:** {person['id']}\n"
            f"**Full Name:** {person['name']}\n"
            f"**Role:** {person['role']}\n"
            f"**Organization:** {org['name']} ({org['type']})\n"
            f"**Employment Type:** {person['type']}\n"
            f"**Security Clearance:** {person['clearance']}\n"
            f"**Badge Number:** B-{random.randint(10000,99999)}\n\n"
            f"### Assigned Facilities\n"
            + "\n".join(f"- {f['name']} ({f['type']})" for f in facs_assigned) +
            f"\n\n### Training & Certifications\n"
            + "\n".join(f"- {c}" for c in certs) +
            f"\n\n### Background Check\n"
            f"- Last background check: {_random_ts()[:10]}\n"
            f"- Criminal record: {'None' if random.random() < 0.9 else 'Minor traffic violation (2023)'}\n"
            f"- References verified: {random.choice(['Yes – all 3 references confirmed', 'Yes – 2 of 3 confirmed', 'Pending verification'])}\n\n"
            f"### Security Flags\n"
            f"{random.choice(_profile_flags).format(date=_random_ts()[:10])}\n\n"
            f"### Access History Summary\n"
            f"- Total facility entries (last 90 days): {random.randint(15, 250)}\n"
            f"- After-hours entries: {random.randint(0, 25)}\n"
            f"- Denied access attempts: {random.randint(0, 5)}\n"
            f"- Average duration per visit: {random.randint(2, 10)}h {random.randint(0, 59)}m\n\n"
            f"### Photo ID\n"
            f"Photo file: {person['id']}_badge_photo.jpg\n"
            f"Last updated: {_random_ts()[:10]}\n"
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "worker_profile",
            "title": f"Personnel Dossier – {person['name']}",
            "content": content,
            "sourceFile": f"HR_{person['id']}_dossier.pdf",
            "facilityId": facs_assigned[0]["id"],
            "facilityName": facs_assigned[0]["name"],
            "personId": person["id"],
            "personName": person["name"],
            "timestamp": _random_ts(),
            "classification": "CONFIDENTIAL",
        })

    # ──────────────────────────────────────────────────
    # 5. SCADA LOGS  (~25 system log extracts)
    # ──────────────────────────────────────────────────
    _scada_entries = [
        "LOGIN user={user} terminal=HMI-{n} result={result} ip={ip}",
        "SETPOINT_CHANGE param={param} old={old} new={new} user={user} auth={auth}",
        "ALARM {alarm_type} sensor={sensor} value={value} threshold={threshold}",
        "FIRMWARE_UPDATE device={device} from={vold} to={vnew} user={user}",
        "COMMS_FAIL device={device} duration={dur}s retries={retries}",
        "CONFIG_DOWNLOAD device={device} user={user} file_size={size}KB",
        "USB_DETECTED port={port} device_class={dclass} serial={serial}",
        "NETWORK_SCAN detected from={ip} ports_scanned={ports} protocol={proto}",
        "REMOTE_ACCESS vpn_user={user} source_ip={ip} geo={geo} duration={dur}min",
        "EMERGENCY_STOP triggered_by={user} reason={reason}",
    ]

    for _ in range(25):
        fac = random.choice(FACILITIES)
        person = random.choice(PERSONS)
        num_entries = random.randint(15, 40)
        base_ts = datetime(2026, random.randint(1, 2), random.randint(1, 28),
                           random.randint(0, 23), random.randint(0, 59))

        log_lines = []
        for i in range(num_entries):
            ts = (base_ts + timedelta(minutes=random.randint(0, 480))).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            entry = random.choice(_scada_entries).format(
                user=random.choice(PERSONS)["name"].split()[0].lower(),
                n=random.randint(1, 5), result=random.choice(["OK", "OK", "OK", "FAILED", "LOCKED"]),
                ip=f"10.{random.randint(0,2)}.{random.randint(1,254)}.{random.randint(1,254)}",
                param=random.choice(["chlorine_setpoint", "pressure_target", "flow_max", "ph_target", "alarm_threshold"]),
                old=round(random.uniform(0.5, 5), 2), new=round(random.uniform(0.5, 5), 2),
                auth=random.choice(["AUTHORIZED", "AUTHORIZED", "UNAUTHORIZED"]),
                alarm_type=random.choice(["HIGH_HIGH", "HIGH", "LOW", "LOW_LOW", "COMMS"]),
                sensor=f"SEN-{random.randint(1, len(SENSORS)):03d}",
                value=round(random.uniform(0, 10), 2),
                threshold=round(random.uniform(1, 8), 2),
                device=f"PLC-{fac['id'].split('-')[1]}",
                vold=f"v{random.randint(2,4)}.{random.randint(0,9)}.{random.randint(0,9)}",
                vnew=f"v{random.randint(4,6)}.{random.randint(0,9)}.{random.randint(0,9)}",
                dur=random.randint(1, 300), retries=random.randint(0, 5),
                size=random.randint(50, 5000),
                port=f"USB-{random.randint(1,4)}",
                dclass=random.choice(["mass_storage", "HID", "network_adapter", "unknown"]),
                serial=f"{''.join(random.choices('0123456789ABCDEF', k=12))}",
                ports=random.randint(10, 65535),
                proto=random.choice(["TCP", "UDP"]),
                geo=random.choice(["Madrid,ES", "Madrid,ES", "Unknown", "Moscow,RU", "Casablanca,MA", "Bucharest,RO"]),
                reason=random.choice(["manual_override", "safety_interlock", "operator_judgment"]),
            )
            log_lines.append(f"[{ts}] {entry}")

        content = (
            f"## SCADA System Log Extract\n\n"
            f"**Facility:** {fac['name']} ({fac['id']})\n"
            f"**System:** SCADA Gateway\n"
            f"**Period:** {base_ts.strftime('%Y-%m-%d %H:%M')} to "
            f"{(base_ts + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')}\n"
            f"**Exported by:** {person['name']}\n\n"
            f"### Log Entries ({num_entries} records)\n\n"
            f"```\n" + "\n".join(sorted(log_lines)) + "\n```\n\n"
            f"### Automated Analysis\n"
            f"- Failed logins: {sum(1 for l in log_lines if 'FAILED' in l or 'LOCKED' in l)}\n"
            f"- Unauthorized actions: {sum(1 for l in log_lines if 'UNAUTHORIZED' in l)}\n"
            f"- USB events: {sum(1 for l in log_lines if 'USB_DETECTED' in l)}\n"
            f"- Network scans: {sum(1 for l in log_lines if 'NETWORK_SCAN' in l)}\n"
            f"- Remote access: {sum(1 for l in log_lines if 'REMOTE_ACCESS' in l)}\n"
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "scada_log",
            "title": f"SCADA Log – {fac['name']} – {base_ts.strftime('%Y-%m-%d')}",
            "content": content,
            "sourceFile": f"SCADA_{fac['id']}_{base_ts.strftime('%Y%m%d')}.log",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": person["id"],
            "personName": person["name"],
            "timestamp": base_ts.isoformat(),
            "classification": "RESTRICTED",
        })

    # ──────────────────────────────────────────────────
    # 6. EMAIL COMMUNICATIONS  (~20 intercepted/flagged emails)
    # ──────────────────────────────────────────────────
    _email_subjects = [
        "Re: Access schedule change for next week",
        "FW: Urgent – Chemical delivery delayed",
        "Meeting notes – Security review {fac}",
        "CONFIDENTIAL: Vulnerability assessment results",
        "Re: Re: Overtime authorization request",
        "Vendor proposal – SCADA system upgrade",
        "Incident report draft – please review",
        "Out of office: {person}",
        "FW: Contractor badge renewal",
        "Question about PLC configuration at {fac}",
        "Re: Whistleblower report – anonymous",
        "URGENT: Credential reset required",
        "Network diagram – DO NOT FORWARD",
        "Re: Suspicious activity near {fac}",
        "Delivery confirmation – chemical supplies",
    ]

    _email_bodies = [
        "Hi {to},\n\nI need to modify my access schedule for {fac}. Instead of the Monday-Friday 08:00-16:00 window, "
        "I'll need access on Saturday night (22:00-06:00) for the {system} maintenance. The work order is WO-{wo}.\n\n"
        "Can you authorize the badge extension? My ID is {badge}.\n\nThanks,\n{from_name}",

        "Team,\n\nAttached are the results of the penetration test conducted on the {fac} SCADA network. "
        "Key findings:\n\n"
        "1. {n1} critical vulnerabilities in PLC firmware\n"
        "2. Default credentials still active on {n2} HMI terminals\n"
        "3. Unpatched CVE-2025-{cve} on SCADA gateway\n"
        "4. Network segmentation between OT and IT is insufficient\n\n"
        "Full report attached. Please do not forward outside the security team.\n\nRegards,\n{from_name}",

        "Hi {to},\n\nI noticed some unusual readings at {fac} during my shift last night. "
        "The {param} values were fluctuating between {v1} and {v2}, which seems abnormal for this time of year. "
        "I also saw someone I didn't recognize near the {area}. They had a contractor badge but I couldn't read the company name.\n\n"
        "Should I file a formal report?\n\n{from_name}",

        "{to},\n\nThis is to confirm that the chemical delivery for {fac} has been rescheduled to {date}. "
        "The shipment includes:\n- Sodium hypochlorite: {qty1} L\n- Aluminum sulfate: {qty2} kg\n"
        "- Polymer flocculant: {qty3} kg\n\nPlease ensure the storage area is prepared and someone is available to sign.\n\n"
        "Regards,\n{from_name}\n{company}",

        "INTERNAL MEMO\n\nSubject: Personnel concern – {subject_person}\n\n"
        "During routine monitoring, the following concerns were noted regarding {subject_person} ({role}):\n\n"
        "1. {concern1}\n2. {concern2}\n3. {concern3}\n\n"
        "Recommendation: {recommendation}\n\nThis memo is classified CONFIDENTIAL.\n\n{from_name}\nSecurity Division",
    ]

    _concerns = [
        "Accessed restricted area outside scheduled hours on {n} occasions in last month",
        "Downloaded facility schematics to personal USB device",
        "Made {n} calls to unregistered international numbers from facility premises",
        "Attempted to access systems above clearance level (L3 areas with L1 badge)",
        "Financial monitoring flagged sudden large deposits inconsistent with salary",
        "Observed photographing control room displays on personal phone",
        "Social media activity suggests disgruntlement with employer",
        "Association with known industrial espionage suspect detected via OSINT",
    ]

    for _ in range(20):
        fac = random.choice(FACILITIES)
        sender = random.choice(PERSONS)
        receiver = random.choice(PERSONS)
        while receiver["id"] == sender["id"]:
            receiver = random.choice(PERSONS)
        subject_person = random.choice(PERSONS)

        subject = random.choice(_email_subjects).format(fac=fac["name"], person=sender["name"])
        body_tpl = random.choice(_email_bodies)
        body = body_tpl.format(
            to=receiver["name"].split()[0],
            from_name=sender["name"],
            fac=fac["name"],
            system=random.choice(_systems),
            wo=random.randint(2025001, 2026999),
            badge=f"B-{random.randint(10000,99999)}",
            n1=random.randint(2, 8), n2=random.randint(1, 5),
            cve=random.randint(1000, 9999),
            param=random.choice(["chlorine", "turbidity", "pH", "pressure", "flow rate"]),
            v1=round(random.uniform(0, 3), 2), v2=round(random.uniform(3, 8), 2),
            area=random.choice(_areas),
            date=_random_ts()[:10],
            qty1=random.randint(500, 5000), qty2=random.randint(100, 1000), qty3=random.randint(50, 500),
            company=next((o["name"] for o in ORGANIZATIONS if o["id"] == sender["org"]), ""),
            subject_person=subject_person["name"],
            role=subject_person["role"],
            concern1=random.choice(_concerns).format(n=random.randint(3, 12)),
            concern2=random.choice(_concerns).format(n=random.randint(2, 8)),
            concern3=random.choice(_concerns).format(n=random.randint(1, 5)),
            recommendation=random.choice(["Immediate interview recommended", "Continued monitoring",
                                          "Suspend facility access pending investigation",
                                          "Refer to law enforcement", "Clearance downgrade to L1"]),
        )

        content = (
            f"**From:** {sender['name']} <{sender['name'].split()[0].lower()}.{sender['name'].split()[-1].lower()}@"
            f"{'canalisabelii.es' if sender['org'] == 'ORG-001' else org['name'].lower().replace(' ','') + '.com'}>\n"
            f"**To:** {receiver['name']}\n"
            f"**Date:** {_random_ts()[:16].replace('T', ' ')}\n"
            f"**Subject:** {subject}\n\n"
            f"---\n\n{body}"
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "email",
            "title": subject,
            "content": content,
            "sourceFile": f"EMAIL_{sender['id']}_{random.randint(100000,999999)}.eml",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": sender["id"],
            "personName": sender["name"],
            "timestamp": _random_ts(),
            "classification": random.choice(["INTERNAL", "CONFIDENTIAL", "RESTRICTED"]),
        })

    # ──────────────────────────────────────────────────
    # 7. REGULATORY INSPECTIONS  (~15 audit reports)
    # ──────────────────────────────────────────────────
    _inspection_types = [
        "Annual Water Quality Compliance Audit",
        "Physical Security Assessment",
        "Cybersecurity Maturity Assessment (ICS/SCADA)",
        "Environmental Compliance Review",
        "Health & Safety Inspection",
        "Critical Infrastructure Protection Audit",
    ]
    _findings_reg = [
        "Finding: Emergency shutdown procedures not tested in last 6 months. **Non-compliant** with RD 140/2003 Art. 14.",
        "Finding: CCTV coverage gap identified at southern perimeter. Blind spot of approximately 15 meters.",
        "Finding: Operator training records incomplete for {n} of {total} personnel. Evidence of expired certifications.",
        "Finding: Cybersecurity patch management policy not followed. {n} systems running end-of-life software.",
        "Finding: Chemical storage area ventilation system below required capacity. Measured: {cfm} CFM vs required {req_cfm} CFM.",
        "Finding: Access logs show {n} instances of badge sharing in audited period. Violation of security protocol SP-003.",
        "Finding: Backup power system failed automatic transfer test. Manual intervention required.",
        "Finding: No documented incident response plan for coordinated cyber-physical attack scenario.",
        "Finding: Water sampling frequency below regulatory minimum for {param} parameter.",
        "No significant findings. Facility meets or exceeds all regulatory requirements.",
    ]

    for _ in range(15):
        fac = random.choice(FACILITIES)
        inspector_name = random.choice(["María Luisa Fernández", "Antonio García Ruiz",
                                         "Dr. Elena Martín Sánchez", "Comisario Luis Ortega",
                                         "Ing. Roberto Navarro Díaz"])
        insp_type = random.choice(_inspection_types)
        n_findings = random.randint(2, 6)
        findings = random.sample(_findings_reg, min(n_findings, len(_findings_reg)))

        content = (
            f"## {insp_type}\n\n"
            f"**Facility:** {fac['name']} ({fac['id']})\n"
            f"**Inspection Date:** {_random_ts()[:10]}\n"
            f"**Inspector:** {inspector_name}\n"
            f"**Regulatory Authority:** {'Confederación Hidrográfica del Tajo' if 'compliance' in insp_type.lower() else 'CNPIC – Centro Nacional de Protección de Infraestructuras Críticas'}\n"
            f"**Report Classification:** RESTRICTED\n\n"
            f"### Overall Rating: {random.choice(['SATISFACTORY', 'NEEDS IMPROVEMENT', 'DEFICIENT', 'SATISFACTORY'])}\n\n"
            f"### Findings\n\n" +
            "\n\n".join(f"{i+1}. {f.format(n=random.randint(2,12), total=random.randint(15,40), cfm=random.randint(200,400), req_cfm=random.randint(500,800), param=random.choice(['trihalomethanes', 'lead', 'E.coli']))}" for i, f in enumerate(findings)) +
            f"\n\n### Corrective Actions Required\n"
            f"- Deadline for critical findings: 30 days\n"
            f"- Deadline for non-critical findings: 90 days\n"
            f"- Follow-up inspection scheduled: {_random_ts()[:10]}\n\n"
            f"### Inspector Signature\n"
            f"{inspector_name}\nDate: {_random_ts()[:10]}"
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "regulatory_inspection",
            "title": f"{insp_type} – {fac['name']}",
            "content": content,
            "sourceFile": f"INSP_{fac['id']}_{random.randint(20250101,20260301)}.pdf",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": None,
            "personName": inspector_name,
            "timestamp": _random_ts(),
            "classification": "RESTRICTED",
        })

    # ──────────────────────────────────────────────────
    # 8. INCIDENT PHOTO ANALYSES  (~15 forensic image reports)
    # ──────────────────────────────────────────────────
    _photo_subjects = [
        ("Damaged lock on chemical storage door", "Physical evidence of forced entry. Scratch marks consistent with lock picking tools. Deadbolt housing shows lateral stress damage."),
        ("USB device found connected to HMI", "Black USB flash drive (8GB, SanDisk Cruzer) found inserted in USB-3 port of HMI terminal. Device bagged for forensic imaging."),
        ("Graffiti on facility exterior wall", "Spray-painted symbol found on east wall. Pattern matches known activist group 'Water Liberation Front'. Blue paint, approximately 1m x 0.5m."),
        ("Tampered sensor housing", "Chlorine sensor housing shows signs of being opened. Two of four mounting screws replaced with non-standard hardware. Calibration sticker partially removed."),
        ("Unattended backpack near pump hall", "Black backpack found near pump hall entrance at {time}. Bomb disposal team called. Contents: laptop, two phones, USB cables, and printed facility schematics."),
        ("Tire tracks near perimeter fence", "Fresh tire tracks found in soft ground near perimeter breach point. Tread pattern suggests SUV/light truck. Cast impressions taken for forensic comparison."),
        ("Drone wreckage on facility roof", "Small commercial drone (DJI Mavic 3) found crashed on roof of control building. Camera SD card recovered. Analysis shows aerial photos of facility taken from multiple angles."),
        ("Modified valve handle", "Manual override valve handle found with unauthorized modification. Extension bar welded to handle allowing operation from outside restricted zone."),
    ]

    for _ in range(15):
        fac = random.choice(FACILITIES)
        subject, base_desc = random.choice(_photo_subjects)
        photographer = random.choice([p for p in PERSONS if "Security" in p["role"] or "Inspector" in p["role"]] or PERSONS[:10])

        content = (
            f"## Forensic Image Analysis Report\n\n"
            f"**Case Reference:** IMG-{random.randint(10000,99999)}\n"
            f"**Facility:** {fac['name']}\n"
            f"**Location:** {random.choice(_areas)}\n"
            f"**Date/Time:** {_random_ts()[:16].replace('T', ' ')}\n"
            f"**Photographer:** {photographer['name']}\n\n"
            f"### Subject\n{subject}\n\n"
            f"### Description\n"
            f"{base_desc.format(time=f'{random.randint(0,23):02d}:{random.randint(0,59):02d}')}\n\n"
            f"### Image Metadata\n"
            f"- Camera: {random.choice(['Canon EOS R6', 'Nikon Z6 II', 'iPhone 15 Pro', 'Samsung Galaxy S24'])}\n"
            f"- Resolution: {random.choice(['6000x4000', '4032x3024', '4000x3000'])}\n"
            f"- GPS: {fac['lat']:.4f}, {fac['lon']:.4f}\n"
            f"- Files: {random.randint(3, 15)} images\n\n"
            f"### Chain of Custody\n"
            f"1. Captured by {photographer['name']} at scene\n"
            f"2. Transferred to evidence locker – reference EV-{random.randint(1000,9999)}\n"
            f"3. Digital copies uploaded to AEGIS system\n\n"
            f"### Analysis Notes\n"
            f"{random.choice(['Evidence consistent with intentional tampering.', 'Inconclusive – additional analysis required.', 'Confirmed: unauthorized physical access.', 'Possible coincidental damage – weather-related. Low confidence of malicious intent.'])}\n"
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "incident_photo",
            "title": f"Photo Analysis – {subject[:50]}",
            "content": content,
            "sourceFile": f"PHOTO_{fac['id']}_IMG{random.randint(10000,99999)}.jpg",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": photographer["id"],
            "personName": photographer["name"],
            "timestamp": _random_ts(),
            "classification": "RESTRICTED",
        })

    # ──────────────────────────────────────────────────
    # 9. ACCESS BADGE RECORDS  (~20 database exports)
    # ──────────────────────────────────────────────────
    for _ in range(20):
        fac = random.choice(FACILITIES)
        base_date = datetime(2026, random.randint(1, 2), random.randint(1, 28))
        records = []

        for i in range(random.randint(20, 50)):
            person = random.choice(PERSONS)
            entry_hour = random.randint(0, 23)
            entry_min = random.randint(0, 59)
            duration = random.randint(15, 600)
            authorized = random.random() < 0.85
            records.append(
                f"| B-{random.randint(10000,99999)} | {person['name'][:25]:25s} | "
                f"{(base_date + timedelta(days=random.randint(0,6))).strftime('%Y-%m-%d')} | "
                f"{entry_hour:02d}:{entry_min:02d} | "
                f"{(entry_hour + duration // 60) % 24:02d}:{(entry_min + duration % 60) % 60:02d} | "
                f"{'✅' if authorized else '⚠️ DENIED'} | "
                f"{random.choice(['Main Gate', 'Side Entrance', 'Control Room', 'Chemical Storage', 'Pump Hall', 'Server Room', 'Perimeter Gate'])} |"
            )

        denied_count = sum(1 for r in records if 'DENIED' in r)
        after_hours = sum(1 for r in records if any(f"| {h:02d}:" in r for h in [22, 23, 0, 1, 2, 3, 4, 5]))

        content = (
            f"## Access Badge Log Export\n\n"
            f"**Facility:** {fac['name']}\n"
            f"**Period:** {base_date.strftime('%Y-%m-%d')} to {(base_date + timedelta(days=6)).strftime('%Y-%m-%d')}\n"
            f"**Exported:** {_random_ts()[:16].replace('T', ' ')}\n\n"
            f"### Summary\n"
            f"- Total entries: {len(records)}\n"
            f"- Denied access: {denied_count}\n"
            f"- After-hours entries: {after_hours}\n\n"
            f"### Records\n\n"
            f"| Badge ID | Name | Date | Entry | Exit | Status | Access Point |\n"
            f"|----------|------|------|-------|------|--------|-------------|\n"
            + "\n".join(records)
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "access_badge_record",
            "title": f"Access Log – {fac['name']} – {base_date.strftime('%Y-%m-%d')}",
            "content": content,
            "sourceFile": f"ACCESS_{fac['id']}_{base_date.strftime('%Y%m%d')}.csv",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": None,
            "personName": None,
            "timestamp": base_date.isoformat(),
            "classification": "INTERNAL",
        })

    # ──────────────────────────────────────────────────
    # 10. DATABASE EXTRACTS  (~15 cross-system correlation reports)
    # ──────────────────────────────────────────────────
    _db_types = [
        ("HR Database – Employee Movement Report",
         "Cross-referencing HR system with badge access logs for {fac}.\n\n"
         "### Discrepancies Found\n\n"
         "| Employee | HR Schedule | Actual Access | Discrepancy |\n"
         "|----------|-------------|---------------|-------------|\n"
         "{rows}\n\n"
         "### Analysis\n"
         "{n_disc} discrepancies found out of {n_total} records checked. "
         "{highlight}"),
        ("CMMS Extract – Unscheduled Maintenance Activities",
         "Computerized Maintenance Management System (CMMS) report for {fac}.\n\n"
         "### Unscheduled Work Orders (Last 30 Days)\n\n"
         "| WO# | Date | Technician | System | Justification | Approved |\n"
         "|-----|------|-----------|--------|---------------|----------|\n"
         "{rows}\n\n"
         "### Flags\n"
         "- {n_disc} work orders created outside business hours\n"
         "- {n_unapproved} work orders without prior supervisor approval\n"
         "{highlight}"),
        ("Supply Chain – Chemical Procurement Anomalies",
         "Procurement database analysis for chemical supplies delivered to {fac}.\n\n"
         "### Flagged Transactions\n\n"
         "| PO# | Supplier | Chemical | Qty Ordered | Qty Delivered | Variance |\n"
         "|-----|----------|----------|-------------|---------------|----------|\n"
         "{rows}\n\n"
         "### Observations\n"
         "- {n_disc} delivery discrepancies exceeding 5% threshold\n"
         "{highlight}"),
    ]

    for _ in range(15):
        fac = random.choice(FACILITIES)
        db_title, db_template = random.choice(_db_types)
        n_rows = random.randint(5, 12)
        rows = []
        for i in range(n_rows):
            p = random.choice(PERSONS)
            if "Employee" in db_title:
                rows.append(f"| {p['name'][:25]} | Mon-Fri 08-16 | "
                            f"{random.choice(['Match', 'Match', 'MISMATCH: Weekend access', 'MISMATCH: Night access', 'Match'])} | "
                            f"{random.choice(['None', 'None', '8h outside schedule', '3 unrecorded entries'])} |")
            elif "CMMS" in db_title:
                rows.append(f"| WO-{random.randint(2026001,2026999)} | {_random_ts()[:10]} | "
                            f"{p['name'][:20]} | {random.choice(_systems)[:25]} | "
                            f"{random.choice(['Emergency repair', 'Preventive', 'Calibration', 'No justification provided'])} | "
                            f"{random.choice(['Yes', 'Yes', 'No', 'Pending'])} |")
            else:
                rows.append(f"| PO-{random.randint(50000,59999)} | "
                            f"{random.choice(['ChemSupply SA', 'AguaPura SL', 'QuimIndustrial', 'Import Chem Ltd'])} | "
                            f"{random.choice(['NaOCl', 'Al2(SO4)3', 'PAC', 'NaOH', 'HCl'])} | "
                            f"{random.randint(500,5000)}L | {random.randint(400,5200)}L | "
                            f"{random.choice(['+2%', '-3%', '+8% ⚠️', '-12% ⚠️', '0%', '+15% ⚠️'])} |")

        content = (
            f"## {db_title}\n\n"
            f"**Facility:** {fac['name']}\n"
            f"**Generated:** {_random_ts()[:16].replace('T', ' ')}\n"
            f"**Classification:** CONFIDENTIAL\n\n" +
            db_template.format(
                fac=fac["name"],
                rows="\n".join(rows),
                n_disc=random.randint(2, 8),
                n_total=n_rows,
                n_unapproved=random.randint(1, 4),
                highlight=random.choice([
                    "**ALERT:** Pattern of after-hours maintenance by contractor personnel correlates with anomalous sensor readings.",
                    "No actionable intelligence identified. Standard deviation within normal operational variance.",
                    "**NOTE:** Cross-referencing with SCADA logs reveals temporal correlation with unauthorized setpoint changes.",
                    "**FLAG:** Procurement pattern suggests potential diversion of chemical supplies.",
                ]),
            )
        )

        docs.append({
            "docId": _next_doc_id(),
            "docType": "database_extract",
            "title": f"{db_title} – {fac['name']}",
            "content": content,
            "sourceFile": f"DB_EXTRACT_{fac['id']}_{random.randint(20250101,20260301)}.xlsx",
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": None,
            "personName": None,
            "timestamp": _random_ts(),
            "classification": "CONFIDENTIAL",
        })

    return docs


INTEL_DOCUMENTS = generate_intel_documents()

# ═══════════════════════════════════════════════════════════════
# EVENT GENERATION
# ═══════════════════════════════════════════════════════════════
EVENT_COUNTER = 100


def next_event_id():
    global EVENT_COUNTER
    EVENT_COUNTER += 1
    return f"EVT-{EVENT_COUNTER:04d}"


def random_timestamp(base: datetime, hours_range: int = 24) -> str:
    delta = timedelta(hours=random.uniform(0, hours_range))
    return (base + delta).isoformat()


def generate_noise_events(count: int = 500):
    """Generate random noise events across all facilities"""
    events = []
    base_date = datetime(2025, 10, 1)

    _maintenance_descs = [
        "Routine filter inspection", "Quarterly pump maintenance", "Sensor calibration",
        "Valve testing", "Pipeline inspection", "Chlorine dosing pump servicing",
        "Pressure gauge replacement", "SCADA terminal update", "Flow meter calibration",
        "Electrical panel inspection", "Backup generator test", "Water sampling for lab",
        "Pipe joint sealing", "Motor bearing replacement", "Tank cleaning completed",
        "Telemetry antenna alignment", "UPS battery replacement", "Fire suppression check",
    ]
    _access_descs_authorized = [
        "Badge access – scheduled shift",
        "Contractor entry – pre-approved maintenance window",
        "Shift change – operator rotation",
        "Lab technician entry for water sampling",
        "Security patrol checkpoint",
        "Delivery personnel – verified credentials",
    ]
    _citizen_descs = [
        "Low pressure report – single household",
        "Color change report – investigated, within limits",
        "Taste complaint – no anomaly detected",
        "Odor complaint – chlorine smell, normal range",
        "Leaking hydrant report – dispatched crew",
        "Report of milky water – air in pipes, resolved",
    ]

    for _ in range(count):
        event_type = random.choices(
            ["Maintenance", "Access", "CitizenReport"],
            weights=[45, 35, 20]
        )[0]
        fac = random.choice(FACILITIES)
        person = random.choice(PERSONS)
        ts = random_timestamp(base_date, hours_range=150 * 24)

        evt = {
            "eventId": next_event_id(),
            "eventType": event_type,
            "severity": random.choices([1, 2, 3], weights=[60, 30, 10])[0],
            "timestamp": ts,
            "facilityId": fac["id"],
            "facilityName": fac["name"],
            "personId": person["id"],
            "personName": person["name"],
        }

        if event_type == "Maintenance":
            evt["description"] = random.choice(_maintenance_descs)
        elif event_type == "Access":
            evt["description"] = random.choice(_access_descs_authorized)
            evt["authorized"] = True
        elif event_type == "CitizenReport":
            evt["description"] = random.choice(_citizen_descs)
            evt["reportCount"] = random.randint(1, 3)

        events.append(evt)

    return events


def generate_sensor_readings(count: int = 1000):
    """Generate normal sensor readings (with a few borderline anomalies)"""
    readings = []
    base_date = datetime(2025, 10, 1)

    for _ in range(count):
        sensor = random.choice(SENSORS)
        metric_info = next(m for m in METRICS if m["name"] == sensor["metric"])
        if random.random() < 0.05:
            if random.random() < 0.5:
                value = round(metric_info["min"] - random.uniform(0.1, 0.5), 2)
            else:
                value = round(metric_info["max"] + random.uniform(0.1, 0.5), 2)
            anomaly = True
        else:
            value = round(random.uniform(metric_info["min"], metric_info["max"]), 2)
            anomaly = False

        readings.append({
            "sensorId": sensor["id"],
            "facilityId": sensor["facilityId"],
            "metric": sensor["metric"],
            "value": value,
            "unit": sensor["unit"],
            "timestamp": random_timestamp(base_date, hours_range=150 * 24),
            "anomaly": anomaly,
        })

    return readings


# ═══════════════════════════════════════════════════════════════
# CYPHER GENERATOR
# ═══════════════════════════════════════════════════════════════

def _ce(s: str) -> str:
    """Cypher-escape a string for single-quoted values."""
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _var(prefix: str, raw_id: str) -> str:
    """Turn 'FAC-001' into 'f_FAC_001'."""
    return f"{prefix}_{raw_id.replace('-', '_')}"


def generate_cypher():
    """Generate the complete seed.cypher file"""
    L = []  # lines accumulator
    L.append("// " + "=" * 60)
    L.append("// AEGIS – Neo4j Initialization Script (Expanded)")
    L.append("// Water Supply Sabotage Detection – Seed Data")
    L.append("// 20 Facilities · 100 Persons · 8 Organizations")
    L.append("// 6 Sabotage Scenarios + Noise Events")
    L.append("// " + "=" * 60)
    L.append("")

    # ── Constraints & Indexes ──
    L.append("// --- Constraints & Indexes ---")
    for label, prop in [
        ("Facility", "facilityId"), ("Person", "personId"), ("Event", "eventId"),
        ("Sensor", "sensorId"), ("Asset", "assetId"), ("Organization", "orgId"),
        ("RiskCase", "caseId"), ("Location", "locationId"), ("Document", "docId"),
    ]:
        L.append(f"CREATE CONSTRAINT {label.lower()}_{prop.lower()} IF NOT EXISTS "
                 f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE;")
    L.append("CREATE INDEX event_timestamp IF NOT EXISTS FOR (e:Event) ON (e.timestamp);")
    L.append("CREATE INDEX event_type IF NOT EXISTS FOR (e:Event) ON (e.eventType);")
    L.append("CREATE INDEX facility_name IF NOT EXISTS FOR (f:Facility) ON (f.name);")
    L.append("CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name);")
    L.append("")

    # ── Locations ──
    L.append("// --- Locations ---")
    for loc in LOCATIONS:
        v = _var("loc", loc["id"])
        L.append(f"CREATE ({v}:Location {{locationId: '{loc['id']}', "
                 f"name: '{_ce(loc['name'])}', latitude: {loc['lat']}, longitude: {loc['lon']}}})")
    L.append("")

    # ── Facilities ──
    L.append("// --- Facilities (20) ---")
    for fac in FACILITIES:
        v = _var("f", fac["id"])
        L.append(f"CREATE ({v}:Facility:{fac['type']} {{facilityId: '{fac['id']}', "
                 f"name: '{_ce(fac['name'])}', type: '{fac['type']}', status: 'Operational', "
                 f"criticality: '{fac['criticality']}', latitude: {fac['lat']}, longitude: {fac['lon']}}})")
    L.append("")

    # ── Organizations ──
    L.append("// --- Organizations (8) ---")
    for org in ORGANIZATIONS:
        v = _var("org", org["id"])
        L.append(f"CREATE ({v}:Organization {{orgId: '{org['id']}', "
                 f"name: '{_ce(org['name'])}', type: '{org['type']}' }})")
    L.append("")

    # ── Persons ──
    L.append("// --- Persons (100) ---")
    for p in PERSONS:
        v = _var("p", p["id"])
        sub = "Employee" if p["type"] == "Employee" else "Contractor"
        L.append(f"CREATE ({v}:Person:{sub} {{personId: '{p['id']}', "
                 f"name: '{_ce(p['name'])}', role: '{_ce(p['role'])}', "
                 f"clearance: '{p['clearance']}', personType: '{p['type']}' }})")
    L.append("")

    # ── Assets ──
    L.append(f"// --- Assets ({len(ASSETS)}) ---")
    for a in ASSETS:
        v = _var("a", a["id"])
        fw = f", firmware: 'v{random.randint(1,5)}.{random.randint(0,9)}.{random.randint(0,9)}'" if a["type"] in ("PLC", "RTU") else ""
        L.append(f"CREATE ({v}:Asset:{a['type']} {{assetId: '{a['id']}', "
                 f"name: '{_ce(a['name'])}', type: '{a['type']}', model: '{_ce(a['model'])}'{fw} }})")
    L.append("")

    # ── Sensors ──
    L.append(f"// --- Sensors ({len(SENSORS)}) ---")
    for s in SENSORS:
        v = _var("s", s["id"])
        L.append(f"CREATE ({v}:Sensor {{sensorId: '{s['id']}', name: '{_ce(s['name'])}', "
                 f"metric: '{s['metric']}', unit: '{s['unit']}', "
                 f"normalMin: {s['normalMin']}, normalMax: {s['normalMax']}}})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # RELATIONSHIPS
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// RELATIONSHIPS")
    L.append("// " + "=" * 60)
    L.append("")

    L.append("// --- Facility → Location ---")
    for fac in FACILITIES:
        L.append(f"CREATE ({_var('f', fac['id'])})-[:LOCATED_AT]->({_var('loc', fac['location'])})")
    L.append("")

    L.append("// --- Facility → Sensor ---")
    for s in SENSORS:
        L.append(f"CREATE ({_var('f', s['facilityId'])})-[:HAS_SENSOR]->({_var('s', s['id'])})")
    L.append("")

    L.append("// --- Facility → Asset ---")
    for a in ASSETS:
        L.append(f"CREATE ({_var('f', a['facilityId'])})-[:HAS_ASSET]->({_var('a', a['id'])})")
    L.append("")

    L.append("// --- Person → Organization ---")
    for p in PERSONS:
        L.append(f"CREATE ({_var('p', p['id'])})-[:BELONGS_TO]->({_var('org', p['org'])})")
    L.append("")

    L.append("// --- Organization → Location ---")
    for org in ORGANIZATIONS:
        n_locs = random.randint(2, 6)
        locs = random.sample(LOCATIONS, n_locs)
        for loc in locs:
            L.append(f"CREATE ({_var('org', org['id'])})-[:OPERATES_IN]->({_var('loc', loc['id'])})")
    L.append("")

    L.append("// --- Person ↔ Person connections ---")
    for c in CONNECTIONS:
        L.append(f"CREATE ({_var('p', c['from'])})-[:CONNECTED_TO "
                 f"{{type: '{c['type']}', confidence: {c['confidence']}}}]"
                 f"->({_var('p', c['to'])})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # helpers for sabotage scenarios
    # ══════════════════════════════════════════════════════════
    def _contractors_of(org_id):
        return [p for p in PERSONS if p["org"] == org_id and p["type"] == "Contractor"]

    def _assets_of(fac_id):
        return [a for a in ASSETS if a["facilityId"] == fac_id]

    def _asset_of_type(fac_id, atype, fallback_idx=0):
        aa = _assets_of(fac_id)
        return next((a for a in aa if a["type"] == atype), aa[fallback_idx])

    def _emit_event(var, eid, labels, etype, desc, sev, ts, extra):
        L.append(f"CREATE ({var}:{labels} {{eventId: '{eid}', eventType: '{etype}', "
                 f"description: '{_ce(desc)}', severity: {sev}, "
                 f"timestamp: datetime('{ts}'), {extra}}})")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 1 – ETAP Norte – Chlorine manipulation
    # ══════════════════════════════════════════════════════════
    L.append("")
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 1: ETAP Norte – Chlorine manipulation")
    L.append("// Window: 2026-01-15 02:00 - 06:00")
    L.append("// " + "=" * 60)
    s1_sus = _contractors_of("ORG-002")[0]
    s1_plc = _asset_of_type("FAC-001", "PLC")

    _emit_event("ev1", "EVT-001", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "Chlorine residual dropped to 0.05 mg/L – critically low", 5,
                "2026-01-15T03:15:00", "metric: 'chlorine_mg_l', value: 0.05, windowId: 'W-001'")
    _emit_event("ev2", "EVT-002", "Event:AccessEvent", "UnauthorizedAccess",
                "Badge access at dosing room – 02:47 – outside scheduled hours", 4,
                "2026-01-15T02:47:00", "accessPoint: 'Dosing Room Door A', authorized: false, windowId: 'W-001'")
    _emit_event("ev3", "EVT-003", "Event:CyberAlertEvent", "CyberAlert",
                f"Failed PLC login attempt from unknown IP on {s1_plc['name']}", 4,
                "2026-01-15T03:02:00",
                f"sourceIP: '10.0.99.14', targetSystem: '{s1_plc['name']}', alertType: 'BruteForce', windowId: 'W-001'")
    _emit_event("ev4", "EVT-004", "Event:CitizenReportEvent", "CitizenReport",
                "Multiple reports of unusual smell in tap water – Chamartín district", 3,
                "2026-01-15T07:30:00", "reportCount: 12, area: 'Chamartín', windowId: 'W-001'")
    L.append(f"CREATE (ev1)-[:OCCURS_AT]->({_var('f','FAC-001')})")
    L.append(f"CREATE (ev2)-[:OCCURS_AT]->({_var('f','FAC-001')})")
    L.append(f"CREATE (ev2)-[:INVOLVES_PERSON]->({_var('p',s1_sus['id'])})")
    L.append(f"CREATE (ev3)-[:OCCURS_AT]->({_var('f','FAC-001')})")
    L.append(f"CREATE (ev3)-[:INVOLVES_ASSET]->({_var('a',s1_plc['id'])})")
    L.append(f"CREATE (ev4)-[:OCCURS_AT]->({_var('f','FAC-001')})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 2 – Depósito Alcalá – Contamination
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 2: Depósito Alcalá – Contamination attempt")
    L.append("// Window: 2026-01-22 22:00 - 2026-01-23 02:00")
    L.append("// " + "=" * 60)
    s2_sus = _contractors_of("ORG-004")[0]
    s2_plc = _asset_of_type("FAC-010", "PLC")

    _emit_event("ev5", "EVT-005", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "Turbidity spike to 15 NTU – well above 4 NTU threshold", 5,
                "2026-01-22T23:45:00", "metric: 'turbidity_ntu', value: 15.0, windowId: 'W-002'")
    _emit_event("ev6", "EVT-006", "Event:AccessEvent", "UnauthorizedAccess",
                "Perimeter fence sensor triggered – south gate – no badge record", 5,
                "2026-01-22T22:30:00", "accessPoint: 'South Perimeter Gate', authorized: false, windowId: 'W-002'")
    _emit_event("ev7", "EVT-007", "Event:CyberAlertEvent", "CyberAlert",
                f"{s2_plc['name']} firmware mismatch – unexpected configuration change", 5,
                "2026-01-23T00:15:00",
                f"targetSystem: '{s2_plc['name']}', alertType: 'FirmwareTamper', windowId: 'W-002'")
    _emit_event("ev8", "EVT-008", "Event:MaintenanceEvent", "Maintenance",
                "Unscheduled maintenance order created post-incident – suspiciously quick", 2,
                "2026-01-23T01:00:00", "windowId: 'W-002'")
    L.append(f"CREATE (ev5)-[:OCCURS_AT]->({_var('f','FAC-010')})")
    L.append(f"CREATE (ev6)-[:OCCURS_AT]->({_var('f','FAC-010')})")
    L.append(f"CREATE (ev7)-[:OCCURS_AT]->({_var('f','FAC-010')})")
    L.append(f"CREATE (ev7)-[:INVOLVES_ASSET]->({_var('a',s2_plc['id'])})")
    L.append(f"CREATE (ev8)-[:OCCURS_AT]->({_var('f','FAC-010')})")
    L.append(f"CREATE (ev8)-[:INVOLVES_PERSON]->({_var('p',s2_sus['id'])})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 3 – Bombeo Sur – Pressure manipulation
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 3: Estación Bombeo Sur – Pressure manipulation")
    L.append("// Window: 2026-02-05 14:00 - 18:00")
    L.append("// " + "=" * 60)
    s3_sus = _contractors_of("ORG-002")[1] if len(_contractors_of("ORG-002")) > 1 else _contractors_of("ORG-002")[0]
    s3_pump = _asset_of_type("FAC-005", "Pump")

    _emit_event("ev9", "EVT-009", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "Pressure surge to 8.5 bar – exceeding safety limit of 6 bar", 5,
                "2026-02-05T15:30:00", "metric: 'pressure_bar', value: 8.5, windowId: 'W-003'")
    _emit_event("ev10", "EVT-010", "Event:AccessEvent", "UnauthorizedAccess",
                "Contractor badge used during non-authorized shift", 3,
                "2026-02-05T14:15:00", "accessPoint: 'Control Room B', authorized: false, windowId: 'W-003'")
    _emit_event("ev11", "EVT-011", "Event:CyberAlertEvent", "CyberAlert",
                "Remote VPN connection from unusual geolocation – pump control accessed", 4,
                "2026-02-05T14:45:00",
                "sourceIP: '185.43.22.7', targetSystem: 'Pump-Control-Sur', alertType: 'AnomalousVPN', windowId: 'W-003'")
    L.append(f"CREATE (ev9)-[:OCCURS_AT]->({_var('f','FAC-005')})")
    L.append(f"CREATE (ev10)-[:OCCURS_AT]->({_var('f','FAC-005')})")
    L.append(f"CREATE (ev10)-[:INVOLVES_PERSON]->({_var('p',s3_sus['id'])})")
    L.append(f"CREATE (ev11)-[:OCCURS_AT]->({_var('f','FAC-005')})")
    L.append(f"CREATE (ev11)-[:INVOLVES_ASSET]->({_var('a',s3_pump['id'])})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 4 – ETAP Móstoles – Chemical overdose
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 4: ETAP Móstoles – Chemical overdose")
    L.append("// Window: 2026-02-12 01:00 - 05:00")
    L.append("// " + "=" * 60)
    s4_sus = _contractors_of("ORG-003")[0]
    s4_plc = _asset_of_type("FAC-004", "PLC")

    _emit_event("ev12", "EVT-012", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "Chlorine level surged to 5.2 mg/L – dangerous overdose at Móstoles ETAP", 5,
                "2026-02-12T02:30:00", "metric: 'chlorine_mg_l', value: 5.2, windowId: 'W-004'")
    _emit_event("ev13", "EVT-013", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "pH dropped to 5.8 – corrosive level detected in treated water", 4,
                "2026-02-12T02:45:00", "metric: 'ph', value: 5.8, windowId: 'W-004'")
    _emit_event("ev14", "EVT-014", "Event:CyberAlertEvent", "CyberAlert",
                f"PLC setpoint change via local HMI without operator authorization at {s4_plc['name']}", 5,
                "2026-02-12T02:15:00",
                f"targetSystem: '{s4_plc['name']}', alertType: 'UnauthorizedSetpoint', windowId: 'W-004'")
    _emit_event("ev15", "EVT-015", "Event:AccessEvent", "UnauthorizedAccess",
                "After-hours badge access at chemical storage room – Móstoles", 4,
                "2026-02-12T01:50:00",
                "accessPoint: 'Chemical Storage Móstoles', authorized: false, windowId: 'W-004'")
    _emit_event("ev16", "EVT-016", "Event:CitizenReportEvent", "CitizenReport",
                "23 households report strong chlorine taste – Móstoles centro", 3,
                "2026-02-12T08:00:00", "reportCount: 23, area: 'Móstoles Centro', windowId: 'W-004'")
    L.append(f"CREATE (ev12)-[:OCCURS_AT]->({_var('f','FAC-004')})")
    L.append(f"CREATE (ev13)-[:OCCURS_AT]->({_var('f','FAC-004')})")
    L.append(f"CREATE (ev14)-[:OCCURS_AT]->({_var('f','FAC-004')})")
    L.append(f"CREATE (ev14)-[:INVOLVES_ASSET]->({_var('a',s4_plc['id'])})")
    L.append(f"CREATE (ev15)-[:OCCURS_AT]->({_var('f','FAC-004')})")
    L.append(f"CREATE (ev15)-[:INVOLVES_PERSON]->({_var('p',s4_sus['id'])})")
    L.append(f"CREATE (ev16)-[:OCCURS_AT]->({_var('f','FAC-004')})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 5 – Depósito Tres Cantos – SCADA exfiltration
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 5: Depósito Tres Cantos – SCADA data exfiltration")
    L.append("// Window: 2026-02-18 23:00 - 2026-02-19 03:00")
    L.append("// " + "=" * 60)
    s5_sus = _contractors_of("ORG-006")[0] if _contractors_of("ORG-006") else _contractors_of("ORG-007")[0]
    s5_rtu = _asset_of_type("FAC-013", "RTU")

    _emit_event("ev17", "EVT-017", "Event:CyberAlertEvent", "CyberAlert",
                "Large data transfer detected from SCADA network to external IP – 2.3 GB", 5,
                "2026-02-19T00:30:00",
                "sourceIP: '10.1.5.22', targetSystem: 'SCADA-Gateway-TC', alertType: 'DataExfiltration', windowId: 'W-005'")
    _emit_event("ev18", "EVT-018", "Event:CyberAlertEvent", "CyberAlert",
                "SSH tunnel established from RTU to unauthorized cloud endpoint", 5,
                "2026-02-19T00:15:00",
                f"targetSystem: '{s5_rtu['name']}', alertType: 'UnauthorizedTunnel', windowId: 'W-005'")
    _emit_event("ev19", "EVT-019", "Event:AccessEvent", "UnauthorizedAccess",
                "VPN session from contractor credentials – geolocated outside Spain", 4,
                "2026-02-18T23:45:00",
                "accessPoint: 'VPN Gateway', authorized: false, windowId: 'W-005'")
    _emit_event("ev20", "EVT-020", "Event:CyberAlertEvent", "CyberAlert",
                "Firewall rule temporarily disabled on OT/IT boundary", 4,
                "2026-02-19T00:05:00",
                "targetSystem: 'FW-OT-Bridge', alertType: 'FirewallTamper', windowId: 'W-005'")
    L.append(f"CREATE (ev17)-[:OCCURS_AT]->({_var('f','FAC-013')})")
    L.append(f"CREATE (ev18)-[:OCCURS_AT]->({_var('f','FAC-013')})")
    L.append(f"CREATE (ev18)-[:INVOLVES_ASSET]->({_var('a',s5_rtu['id'])})")
    L.append(f"CREATE (ev19)-[:OCCURS_AT]->({_var('f','FAC-013')})")
    L.append(f"CREATE (ev19)-[:INVOLVES_PERSON]->({_var('p',s5_sus['id'])})")
    L.append(f"CREATE (ev20)-[:OCCURS_AT]->({_var('f','FAC-013')})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # SCENARIO 6 – Coordinated multi-facility attack
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// SABOTAGE SCENARIO 6: Coordinated attack – Bombeo Móstoles + Nodo Alcorcón")
    L.append("// Window: 2026-02-25 16:00 - 20:00")
    L.append("// " + "=" * 60)
    s6_sus1 = _contractors_of("ORG-005")[0] if _contractors_of("ORG-005") else _contractors_of("ORG-003")[1]
    s6_sus2 = _contractors_of("ORG-004")[1] if len(_contractors_of("ORG-004")) > 1 else _contractors_of("ORG-004")[0]
    s6_pump = _asset_of_type("FAC-006", "Pump")
    s6_valve = _asset_of_type("FAC-016", "Valve")

    _emit_event("ev21", "EVT-021", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "All pumps at Bombeo Móstoles stopped simultaneously – zero flow", 5,
                "2026-02-25T17:00:00", "metric: 'flow_rate_m3h', value: 0.0, windowId: 'W-006'")
    _emit_event("ev22", "EVT-022", "Event:PhysicalAnomalyEvent", "PhysicalAnomaly",
                "Distribution pressure at Alcorcón dropped to 0.3 bar – service disruption", 5,
                "2026-02-25T17:15:00", "metric: 'pressure_bar', value: 0.3, windowId: 'W-006'")
    _emit_event("ev23", "EVT-023", "Event:AccessEvent", "UnauthorizedAccess",
                "Two contractor badges used simultaneously at different facilities", 4,
                "2026-02-25T16:30:00",
                "accessPoint: 'Pump Hall Móstoles', authorized: false, windowId: 'W-006'")
    _emit_event("ev24", "EVT-024", "Event:CyberAlertEvent", "CyberAlert",
                "SCADA command injection detected – emergency valve closure at Alcorcón", 5,
                "2026-02-25T16:55:00",
                f"targetSystem: '{s6_valve['name']}', alertType: 'CommandInjection', windowId: 'W-006'")
    _emit_event("ev25", "EVT-025", "Event:CitizenReportEvent", "CitizenReport",
                "Mass reports: no water in Móstoles and Alcorcón – 150+ calls in 30 min", 4,
                "2026-02-25T17:45:00",
                "reportCount: 154, area: 'Móstoles-Alcorcón', windowId: 'W-006'")
    L.append(f"CREATE (ev21)-[:OCCURS_AT]->({_var('f','FAC-006')})")
    L.append(f"CREATE (ev22)-[:OCCURS_AT]->({_var('f','FAC-016')})")
    L.append(f"CREATE (ev23)-[:OCCURS_AT]->({_var('f','FAC-006')})")
    L.append(f"CREATE (ev23)-[:INVOLVES_PERSON]->({_var('p',s6_sus1['id'])})")
    L.append(f"CREATE (ev24)-[:OCCURS_AT]->({_var('f','FAC-016')})")
    L.append(f"CREATE (ev24)-[:INVOLVES_ASSET]->({_var('a',s6_valve['id'])})")
    L.append(f"CREATE (ev25)-[:OCCURS_AT]->({_var('f','FAC-006')})")
    L.append(f"CREATE (ev25)-[:INVOLVES_PERSON]->({_var('p',s6_sus2['id'])})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # NOISE / NORMAL EVENTS
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// NOISE / NORMAL EVENTS")
    L.append("// " + "=" * 60)
    noise_data = [
        ("evN01", "EVT-N01", "Maintenance", "MaintenanceEvent", "Routine filter replacement", 1,
         "2026-01-12T09:00:00", "FAC-001", PERSONS[0]["id"], ""),
        ("evN02", "EVT-N02", "Access", "AccessEvent", "Scheduled operator shift change", 1,
         "2026-01-14T08:00:00", "FAC-001", PERSONS[0]["id"], ", authorized: true"),
        ("evN03", "EVT-N03", "Maintenance", "MaintenanceEvent", "Quarterly pump inspection", 1,
         "2026-01-20T10:00:00", "FAC-005", PERSONS[3]["id"], ""),
        ("evN04", "EVT-N04", "CitizenReport", "CitizenReportEvent", "Single report of low pressure – resolved", 1,
         "2026-01-25T16:00:00", "FAC-015", None, ", reportCount: 1"),
        ("evN05", "EVT-N05", "Maintenance", "MaintenanceEvent", "Annual valve servicing at Móstoles", 1,
         "2026-01-28T10:00:00", "FAC-004", PERSONS[5]["id"], ""),
        ("evN06", "EVT-N06", "Access", "AccessEvent", "Night security patrol completed without incidents", 1,
         "2026-02-01T02:00:00", "FAC-010", PERSONS[4]["id"], ", authorized: true"),
        ("evN07", "EVT-N07", "Maintenance", "MaintenanceEvent", "Backup generator load test – passed", 1,
         "2026-02-03T11:00:00", "FAC-003", PERSONS[2]["id"], ""),
        ("evN08", "EVT-N08", "CitizenReport", "CitizenReportEvent", "Water color complaint – flushing resolved issue", 1,
         "2026-02-08T14:00:00", "FAC-016", None, ", reportCount: 1"),
        ("evN09", "EVT-N09", "Maintenance", "MaintenanceEvent", "Sensor recalibration at Tres Cantos", 1,
         "2026-02-10T09:30:00", "FAC-013", PERSONS[6]["id"], ""),
        ("evN10", "EVT-N10", "Access", "AccessEvent", "Contractor entry for scheduled electrical work", 1,
         "2026-02-15T08:00:00", "FAC-008", PERSONS[min(60, len(PERSONS)-1)]["id"], ", authorized: true"),
    ]
    for var, eid, etype, elabel, desc, sev, ts, fac_id, per_id, extra in noise_data:
        L.append(f"CREATE ({var}:Event:{elabel} {{eventId: '{eid}', eventType: '{etype}', "
                 f"description: '{_ce(desc)}', severity: {sev}, "
                 f"timestamp: datetime('{ts}'){extra}}})")
        L.append(f"CREATE ({var})-[:OCCURS_AT]->({_var('f', fac_id)})")
        if per_id:
            L.append(f"CREATE ({var})-[:INVOLVES_PERSON]->({_var('p', per_id)})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # RISK CASES  (6)
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append("// RISK CASES (6)")
    L.append("// " + "=" * 60)

    cases = [
        {"id": "CASE-001", "title": "Suspected Chlorine Manipulation – ETAP Norte",
         "status": "Open", "conf": 0.92, "risk": 9.2, "ts": "2026-01-15T08:00:00",
         "desc": "Correlated events: chlorine drop + unauthorized access + PLC brute force + citizen complaints",
         "events": ["ev1", "ev2", "ev3", "ev4"], "facility": _var("f", "FAC-001"),
         "persons": [_var("p", s1_sus["id"])]},
        {"id": "CASE-002", "title": "Suspected Contamination – Depósito Alcalá",
         "status": "Open", "conf": 0.88, "risk": 8.8, "ts": "2026-01-23T04:00:00",
         "desc": "Correlated events: turbidity spike + perimeter breach + firmware tamper",
         "events": ["ev5", "ev6", "ev7", "ev8"], "facility": _var("f", "FAC-010"),
         "persons": [_var("p", s2_sus["id"])]},
        {"id": "CASE-003", "title": "Suspected Pressure Attack – Bombeo Sur",
         "status": "Investigating", "conf": 0.75, "risk": 7.5, "ts": "2026-02-05T19:00:00",
         "desc": "Correlated events: pressure surge + unauthorized contractor + anomalous VPN",
         "events": ["ev9", "ev10", "ev11"], "facility": _var("f", "FAC-005"),
         "persons": [_var("p", s3_sus["id"])]},
        {"id": "CASE-004", "title": "Chemical Overdose – ETAP Móstoles",
         "status": "Open", "conf": 0.95, "risk": 9.5, "ts": "2026-02-12T06:00:00",
         "desc": "Chlorine overdose + pH anomaly + unauthorized PLC setpoint + after-hours access + mass citizen complaints",
         "events": ["ev12", "ev13", "ev14", "ev15", "ev16"], "facility": _var("f", "FAC-004"),
         "persons": [_var("p", s4_sus["id"])]},
        {"id": "CASE-005", "title": "SCADA Data Exfiltration – Tres Cantos",
         "status": "Escalated", "conf": 0.90, "risk": 8.5, "ts": "2026-02-19T04:00:00",
         "desc": "Data exfiltration via SSH tunnel + VPN from outside Spain + firewall tamper – potential espionage",
         "events": ["ev17", "ev18", "ev19", "ev20"], "facility": _var("f", "FAC-013"),
         "persons": [_var("p", s5_sus["id"])]},
        {"id": "CASE-006", "title": "Coordinated Multi-Facility Attack – Móstoles/Alcorcón",
         "status": "Escalated", "conf": 0.97, "risk": 9.8, "ts": "2026-02-25T18:00:00",
         "desc": "Simultaneous pump shutdown + valve injection + mass service disruption – two suspects at two facilities",
         "events": ["ev21", "ev22", "ev23", "ev24", "ev25"], "facility": _var("f", "FAC-006"),
         "persons": [_var("p", s6_sus1["id"]), _var("p", s6_sus2["id"])]},
    ]

    for c in cases:
        v = _var("rc", c["id"])
        L.append(f"CREATE ({v}:RiskCase:SuspectedSabotage {{caseId: '{c['id']}', "
                 f"title: '{_ce(c['title'])}', status: '{c['status']}', "
                 f"confidence: {c['conf']}, riskScore: {c['risk']}, "
                 f"createdAt: datetime('{c['ts']}'), "
                 f"description: '{_ce(c['desc'])}'}})")
    L.append("")

    L.append("// --- Link cases to events, facilities, persons ---")
    for c in cases:
        v = _var("rc", c["id"])
        for ev in c["events"]:
            L.append(f"CREATE ({v})-[:LINKED_EVENT]->({ev})")
        L.append(f"CREATE ({v})-[:LINKED_FACILITY]->({c['facility']})")
        for pv in c["persons"]:
            L.append(f"CREATE ({v})-[:LINKED_PERSON]->({pv})")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # INTEL DOCUMENTS  (~200 heterogeneous)
    # ══════════════════════════════════════════════════════════
    L.append("// " + "=" * 60)
    L.append(f"// INTEL DOCUMENTS ({len(INTEL_DOCUMENTS)})")
    L.append("// " + "=" * 60)
    L.append("")

    _doc_type_labels = {
        "video_transcription": "VideoTranscription",
        "maintenance_report": "MaintenanceReport",
        "lab_analysis": "LabAnalysis",
        "worker_profile": "WorkerProfile",
        "scada_log": "ScadaLog",
        "email": "EmailCommunication",
        "regulatory_inspection": "RegulatoryInspection",
        "incident_photo": "IncidentPhoto",
        "access_badge_record": "AccessBadgeRecord",
        "database_extract": "DatabaseExtract",
    }

    for doc in INTEL_DOCUMENTS:
        v = _var("doc", doc["docId"])
        sublabel = _doc_type_labels.get(doc["docType"], "IntelDocument")
        # Truncate content for graph (full content goes to OpenSearch)
        short_content = _ce(doc["content"][:500].replace("\n", " "))
        L.append(f"CREATE ({v}:Document:{sublabel} {{docId: '{doc['docId']}', "
                 f"docType: '{doc['docType']}', "
                 f"title: '{_ce(doc['title'])}', "
                 f"sourceFile: '{_ce(doc['sourceFile'])}', "
                 f"classification: '{doc['classification']}', "
                 f"timestamp: datetime('{doc['timestamp']}'), "
                 f"contentPreview: '{short_content}'}})")
    L.append("")

    L.append("// --- Document → Facility relationships ---")
    for doc in INTEL_DOCUMENTS:
        v = _var("doc", doc["docId"])
        if doc["facilityId"]:
            L.append(f"CREATE ({v})-[:REFERENCES_FACILITY]->({_var('f', doc['facilityId'])})")
    L.append("")

    L.append("// --- Document → Person relationships ---")
    for doc in INTEL_DOCUMENTS:
        v = _var("doc", doc["docId"])
        if doc.get("personId"):
            L.append(f"CREATE ({v})-[:REFERENCES_PERSON]->({_var('p', doc['personId'])})")
    L.append("")

    # Add trailing semicolon
    while L and L[-1].strip() == "":
        L.pop()
    L[-1] = L[-1].rstrip() + ";"

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("🛰️  AEGIS Data Generator (Expanded)")
    print("=" * 60)

    noise = generate_noise_events(500)
    print(f"✅ Generated {len(noise)} noise events")

    readings = generate_sensor_readings(1000)
    print(f"✅ Generated {len(readings)} sensor readings")

    print(f"✅ {len(FACILITIES)} facilities")
    print(f"✅ {len(PERSONS)} persons")
    print(f"✅ {len(ORGANIZATIONS)} organizations")
    print(f"✅ {len(SENSORS)} sensors")
    print(f"✅ {len(ASSETS)} assets")
    print(f"✅ {len(CONNECTIONS)} person-to-person connections")
    print(f"✅ {len(INTEL_DOCUMENTS)} intel documents (heterogeneous)")

    # Count by type
    doc_types = {}
    for doc in INTEL_DOCUMENTS:
        doc_types[doc["docType"]] = doc_types.get(doc["docType"], 0) + 1
    for dt, count in sorted(doc_types.items()):
        print(f"   📎 {dt}: {count}")

    # Save JSON/CSV files
    with open(os.path.join(OUTPUT_DIR, 'noise_events.json'), 'w', encoding='utf-8') as f:
        json.dump(noise, f, indent=2, default=str, ensure_ascii=False)
    print("📁 Saved noise_events.json")

    with open(os.path.join(OUTPUT_DIR, 'sensor_readings.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['sensorId', 'facilityId', 'metric', 'value', 'unit', 'timestamp', 'anomaly'])
        writer.writeheader()
        writer.writerows(readings)
    print("📁 Saved sensor_readings.csv")

    with open(os.path.join(OUTPUT_DIR, 'facilities.json'), 'w', encoding='utf-8') as f:
        json.dump(FACILITIES, f, indent=2, ensure_ascii=False)
    print("📁 Saved facilities.json")

    with open(os.path.join(OUTPUT_DIR, 'persons.json'), 'w', encoding='utf-8') as f:
        json.dump(PERSONS, f, indent=2, ensure_ascii=False)
    print("📁 Saved persons.json")

    with open(os.path.join(OUTPUT_DIR, 'organizations.json'), 'w', encoding='utf-8') as f:
        json.dump(ORGANIZATIONS, f, indent=2, ensure_ascii=False)
    print("📁 Saved organizations.json")

    with open(os.path.join(OUTPUT_DIR, 'intel_documents.json'), 'w', encoding='utf-8') as f:
        json.dump(INTEL_DOCUMENTS, f, indent=2, default=str, ensure_ascii=False)
    print(f"📁 Saved intel_documents.json ({len(INTEL_DOCUMENTS)} documents)")

    # Also save intel_documents.json alongside seed.cypher (for Docker mount)
    neo4j_init_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'neo4j-init')
    with open(os.path.join(neo4j_init_dir, 'intel_documents.json'), 'w', encoding='utf-8') as f:
        json.dump(INTEL_DOCUMENTS, f, indent=2, default=str, ensure_ascii=False)
    print("📁 Saved intel_documents.json to neo4j-init/ (Docker mount)")

    # Generate and save Cypher seed
    cypher = generate_cypher()
    cypher_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'neo4j-init', 'seed.cypher')
    with open(cypher_path, 'w', encoding='utf-8') as f:
        f.write(cypher)
    print(f"📁 Saved seed.cypher ({len(cypher.splitlines())} lines)")

    print()
    print("🎯 Sabotage scenarios (6):")
    print("   1. CASE-001: Chlorine manipulation at ETAP Norte")
    print("   2. CASE-002: Contamination attempt at Depósito Alcalá")
    print("   3. CASE-003: Pressure attack at Bombeo Sur")
    print("   4. CASE-004: Chemical overdose at ETAP Móstoles")
    print("   5. CASE-005: SCADA data exfiltration at Tres Cantos")
    print("   6. CASE-006: Coordinated multi-facility attack Móstoles/Alcorcón")
    print()
    print(f"📚 Intel document types: {len(doc_types)}")
    print("   📹 video_transcription, 📄 maintenance_report, 🔬 lab_analysis")
    print("   👤 worker_profile, 🖥️ scada_log, 📧 email")
    print("   📋 regulatory_inspection, 📸 incident_photo")
    print("   🔑 access_badge_record, 🗄️ database_extract")
    print()
    print("🔄 Search reindex interval: 2 minutes (reduced from 5)")
    print()
    print("Done! 🚀")


if __name__ == "__main__":
    main()
