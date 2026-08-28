#!/usr/bin/env python3
"""
AEGIS Continuous Event Simulator
Runs inside a Docker container, generating a realistic stream of water supply
operations events.  ~65% of events are routine/good (SEV-0) and ~35% are
anomalous (SEV 2-4) covering every event type (Access, SensorReading,
Maintenance, SystemStatus, QualityCheck).  Every 60-90s a coordinated threat
scenario (SEV 3-5) is injected.  This mix feeds the inference engine's 8
pattern detectors with realistic data.

Environment variables:
    API_BASE               – AEGIS API base URL  (default: http://api:8080/api)
    INTERVAL               – seconds between routine events (default: 1.0)
    SCENARIO_INTERVAL_MIN  – min seconds between threat scenarios (default: 60)
    SCENARIO_INTERVAL_MAX  – max seconds between threat scenarios (default: 90)
"""

import os
import random
import signal
import sys
import time
from datetime import datetime
from typing import Optional

import requests

# ── Configuration ──

API_BASE = os.environ.get("API_BASE", "http://api:8080/api")
INTERVAL = float(os.environ.get("INTERVAL", "1.0"))
SCENARIO_MIN = int(os.environ.get("SCENARIO_INTERVAL_MIN", "60"))
SCENARIO_MAX = int(os.environ.get("SCENARIO_INTERVAL_MAX", "90"))

# ── Reference data (must match seed.cypher / generate_data.py) ──

FACILITIES = [
    # Water Treatment Plants (ETAPs) – CRITICAL/HIGH
    {"id": "FAC-001", "name": "ETAP Norte"},
    {"id": "FAC-002", "name": "ETAP Torrejón"},
    {"id": "FAC-003", "name": "ETAP Colmenar Viejo"},
    {"id": "FAC-004", "name": "ETAP Móstoles"},
    # Pump Stations
    {"id": "FAC-005", "name": "Estación Bombeo Sur"},
    {"id": "FAC-006", "name": "Estación Bombeo Móstoles"},
    {"id": "FAC-007", "name": "Estación Bombeo Majadahonda"},
    {"id": "FAC-008", "name": "Estación Bombeo Fuenlabrada"},
    {"id": "FAC-009", "name": "Estación Bombeo Las Rozas"},
    # Reservoirs / Depósitos
    {"id": "FAC-010", "name": "Depósito Alcalá"},
    {"id": "FAC-011", "name": "Depósito Getafe"},
    {"id": "FAC-012", "name": "Depósito Leganés"},
    {"id": "FAC-013", "name": "Depósito Tres Cantos"},
    {"id": "FAC-014", "name": "Depósito Pozuelo"},
    # Distribution Nodes
    {"id": "FAC-015", "name": "Nodo Distribución Getafe"},
    {"id": "FAC-016", "name": "Nodo Distribución Alcorcón"},
    {"id": "FAC-017", "name": "Nodo Distribución Parla"},
    {"id": "FAC-018", "name": "Nodo Distribución S.S. Reyes"},
    {"id": "FAC-019", "name": "Nodo Distribución Rivas"},
    {"id": "FAC-020", "name": "Nodo Distribución Valdemoro"},
]

# Critical facilities (ETAPs + key reservoirs) – used in sabotage scenarios
CRITICAL_FACILITIES = [f for f in FACILITIES if f["id"] in
    ("FAC-001", "FAC-002", "FAC-003", "FAC-004", "FAC-005", "FAC-010", "FAC-013")]

PERSONS = [
    # ── Canal de Isabel II Employees (ORG-001) ──
    {"id": "PER-001", "name": "Javier Torres Romero",       "type": "Employee"},
    {"id": "PER-002", "name": "Rubén Rodríguez Medina",     "type": "Employee"},
    {"id": "PER-003", "name": "Marta Muñoz Garrido",        "type": "Employee"},
    {"id": "PER-005", "name": "Carlos Ruiz Castro",          "type": "Employee"},
    {"id": "PER-008", "name": "Beatriz Santos Pérez",        "type": "Employee"},
    {"id": "PER-011", "name": "Julia Blanco Ruiz",           "type": "Employee"},
    {"id": "PER-014", "name": "Santiago Muñoz Vázquez",      "type": "Employee"},
    {"id": "PER-020", "name": "Adrián Castillo Moreno",      "type": "Employee"},
    {"id": "PER-030", "name": "Álvaro Gómez Guerrero",       "type": "Employee"},
    {"id": "PER-040", "name": "Marcos Blanco Álvarez",       "type": "Employee"},
    {"id": "PER-050", "name": "Luis Hernández Sánchez",      "type": "Employee"},
    {"id": "PER-054", "name": "Pablo García Marín",          "type": "Employee"},
    # ── AquaServ (ORG-002) contractors ──
    {"id": "PER-059", "name": "Sofía Sánchez",               "type": "Contractor"},
    {"id": "PER-060", "name": "Fernando Ruiz",               "type": "Contractor"},
    {"id": "PER-067", "name": "Youssef Volkov",              "type": "Contractor"},
    {"id": "PER-079", "name": "Dmitri Ivanov",               "type": "Contractor"},
    {"id": "PER-089", "name": "Marta González",              "type": "Contractor"},
    {"id": "PER-091", "name": "Javier Delgado",              "type": "Contractor"},
    # ── HidroTec (ORG-003) contractors ──
    {"id": "PER-063", "name": "Alicia Muñoz",                "type": "Contractor"},
    {"id": "PER-070", "name": "Oleg Ivanov",                 "type": "Contractor"},
    {"id": "PER-087", "name": "Viktor El Fassi",             "type": "Contractor"},
    {"id": "PER-097", "name": "Bogdan Hassan",               "type": "Contractor"},
    # ── TechPipe (ORG-004) contractors ──
    {"id": "PER-056", "name": "Carlos Pérez",                "type": "Contractor"},
    {"id": "PER-057", "name": "Víctor Prieto",               "type": "Contractor"},
    {"id": "PER-074", "name": "Tomás Domínguez",             "type": "Contractor"},
    # ── Ibérica de Bombas (ORG-005) contractors ──
    {"id": "PER-068", "name": "Mario Herrera",               "type": "Contractor"},
    {"id": "PER-073", "name": "Diego Ortega",                "type": "Contractor"},
    {"id": "PER-092", "name": "Andrei El Fassi",             "type": "Contractor"},
    # ── CyberSec (ORG-006) contractors ──
    {"id": "PER-077", "name": "Nuria Cabrera",               "type": "Contractor"},
    {"id": "PER-078", "name": "Nikolai El Fassi",            "type": "Contractor"},
    {"id": "PER-085", "name": "Andrés Iglesias",             "type": "Contractor"},
    # ── SecurIT (ORG-007) contractors ──
    {"id": "PER-071", "name": "Andrei Benali",               "type": "Contractor"},
    {"id": "PER-083", "name": "Sergio Marín",                "type": "Contractor"},
    # ── SmartWater (ORG-008) contractors ──
    {"id": "PER-072", "name": "Patricia Ortega",             "type": "Contractor"},
]

EMPLOYEES = [p for p in PERSONS if p["type"] == "Employee"]
CONTRACTORS = [p for p in PERSONS if p["type"] == "Contractor"]

# ═══════════════════════════════════════════════════════════════
#  ROUTINE (GOOD) EVENT GENERATORS
# ═══════════════════════════════════════════════════════════════

def gen_normal_access() -> dict:
    """Authorized badge entry – routine, severity 0."""
    p = random.choice(EMPLOYEES)
    f = random.choice(FACILITIES)
    point = random.choice(["Main Gate", "Control Room", "Lab", "Office", "Parking"])
    return {
        "eventType": "Access",
        "description": f"Authorized badge entry – {p['name']} at {point}",
        "severity": 0,
        "facilityId": f["id"],
        "personId": p["id"],
        "metadata": {"accessPoint": point, "authorized": True},
    }


def gen_normal_sensor_reading() -> dict:
    """Normal sensor telemetry – within limits, severity 0."""
    f = random.choice(FACILITIES)
    readings = [
        ("pressure_bar", "Pressure reading {v:.1f} bar – within normal range", 3.5, 5.5),
        ("chlorine_mg_l", "Chlorine residual {v:.2f} mg/L – optimal", 0.5, 1.5),
        ("turbidity_ntu", "Turbidity {v:.2f} NTU – excellent clarity", 0.1, 1.0),
        ("ph_level", "pH level {v:.2f} – within acceptable range", 6.8, 8.2),
        ("flow_rate_m3h", "Flow rate {v:.0f} m³/h – stable", 80, 150),
        ("temp_celsius", "Water temperature {v:.1f}°C – nominal", 12.0, 22.0),
    ]
    metric, desc, lo, hi = random.choice(readings)
    v = random.uniform(lo, hi)
    return {
        "eventType": "SensorReading",
        "description": desc.format(v=v),
        "severity": 0,
        "facilityId": f["id"],
        "metadata": {"metric": metric, "value": round(v, 3), "status": "normal"},
    }


def gen_routine_maintenance() -> dict:
    """Scheduled maintenance – severity 0."""
    p = random.choice(CONTRACTORS + [random.choice(EMPLOYEES)])
    f = random.choice(FACILITIES)
    tasks = [
        "Scheduled pump inspection completed",
        "Routine valve check – all OK",
        "Weekly chlorine dosing calibration – passed",
        "Monthly filter backwash executed",
        "Sensor calibration – within tolerance",
        "SCADA system backup completed",
        "UPS battery test – nominal",
        "Fire suppression system test – passed",
        "Quarterly pipe inspection – no anomalies",
    ]
    return {
        "eventType": "Maintenance",
        "description": random.choice(tasks),
        "severity": 0,
        "facilityId": f["id"],
        "personId": p["id"],
        "metadata": {"workOrderId": f"WO-{random.randint(10000,99999)}", "scheduled": True},
    }


def gen_system_heartbeat() -> dict:
    """System health ping – severity 0."""
    f = random.choice(FACILITIES)
    systems = ["SCADA-Main", "PLC-Primary", "HMI-Station", "Historian-DB",
               "VPN-Gateway", "Firewall-OT"]
    sys_name = random.choice(systems)
    return {
        "eventType": "SystemStatus",
        "description": f"{sys_name} heartbeat OK – uptime {random.randint(1,365)} days",
        "severity": 0,
        "facilityId": f["id"],
        "metadata": {"system": sys_name, "status": "healthy",
                      "cpu_pct": random.randint(5, 40)},
    }


def gen_quality_check() -> dict:
    """Water quality lab result – severity 0."""
    f = random.choice(FACILITIES)
    tests = [
        "Bacteriological sample – negative, compliant",
        "Heavy metals analysis – all below limits",
        "Organic compounds test – no detected contaminants",
        "Legionella test – negative",
        "Nitrate levels – 12 mg/L, well within EU limit of 50 mg/L",
    ]
    return {
        "eventType": "QualityCheck",
        "description": random.choice(tests),
        "severity": 0,
        "facilityId": f["id"],
        "metadata": {"result": "pass", "labId": f"LAB-{random.randint(1000,9999)}"},
    }


def gen_minor_anomaly() -> dict:
    """Small deviation – severity 2, non-critical."""
    f = random.choice(FACILITIES)
    anomalies = [
        ("PhysicalAnomaly",
         "Minor pressure fluctuation to {v:.1f} bar – self-correcting",
         "pressure_bar", 5.5, 6.5, 2),
        ("PhysicalAnomaly",
         "Slight turbidity increase to {v:.2f} NTU – monitoring",
         "turbidity_ntu", 1.5, 3.5, 2),
        ("CitizenReport",
         "Single resident complaint about water pressure – investigating",
         None, 0, 0, 2),
        ("Maintenance",
         "Minor pump vibration detected – scheduling inspection",
         "vibration_mm_s", 2.0, 4.0, 2),
        ("PhysicalAnomaly",
         "Temperature variation to {v:.1f}°C – seasonal adjustment",
         "temp_celsius", 22.0, 26.0, 2),
    ]
    etype, desc, metric, lo, hi, sev = random.choice(anomalies)
    v = random.uniform(lo, hi) if metric else 0
    ev: dict = {
        "eventType": etype,
        "description": desc.format(v=v) if "{v" in desc else desc,
        "severity": sev,
        "facilityId": f["id"],
        "metadata": {},
    }
    if metric:
        ev["metadata"] = {"metric": metric, "value": round(v, 3)}
    return ev


# ═══════════════════════════════════════════════════════════════
#  ANOMALOUS EVENT GENERATORS (mid-severity – feed inference)
# ═══════════════════════════════════════════════════════════════

def gen_abnormal_access() -> dict:
    """Suspicious access events – SEV 2-4."""
    f = random.choice(FACILITIES)
    anomalies = [
        # SEV 2 – minor access oddities
        (2, lambda p, f_: {
            "eventType": "Access",
            "description": f"Badge read error for {p['name']} at Main Gate – retried",
            "severity": 2, "facilityId": f_["id"], "personId": p["id"],
            "metadata": {"accessPoint": "Main Gate", "authorized": True, "retries": random.randint(2, 5)},
        }),
        (2, lambda p, f_: {
            "eventType": "Access",
            "description": f"Tailgating detected – {p['name']} did not badge at {random.choice(['Lab', 'Control Room'])}",
            "severity": 2, "facilityId": f_["id"], "personId": p["id"],
            "metadata": {"accessPoint": "Multiple", "tailgating": True},
        }),
        # SEV 3 – concerning access patterns
        (3, lambda p, f_: {
            "eventType": "Access",
            "description": f"Off-hours access by {p['name']} at {random.choice(['Dosing Room', 'Chemical Storage', 'Server Room'])} ({random.randint(22,23)}:{random.randint(0,59):02d}h)",
            "severity": 3, "facilityId": f_["id"], "personId": p["id"],
            "metadata": {"accessPoint": "Restricted", "offHours": True, "authorized": True},
        }),
        (3, lambda p, f_: {
            "eventType": "Access",
            "description": f"Expired badge attempt by {p['name']} at {f_['name']}",
            "severity": 3, "facilityId": f_["id"], "personId": p["id"],
            "metadata": {"accessPoint": "Main Gate", "authorized": False, "badgeExpired": True},
        }),
        # SEV 4 – unauthorized access
        (4, lambda p, f_: {
            "eventType": "UnauthorizedAccess",
            "description": f"{p['name']} attempted restricted zone access at {random.choice(['Chemical Storage', 'Server Room', 'SCADA Terminal'])}",
            "severity": 4, "facilityId": f_["id"], "personId": p["id"],
            "metadata": {"accessPoint": "Restricted Zone", "authorized": False, "escalated": True},
        }),
    ]
    sev, builder = random.choices(anomalies, weights=[30, 25, 25, 10, 10], k=1)[0]
    p = random.choice(CONTRACTORS) if sev >= 3 else random.choice(PERSONS)
    return builder(p, f)


def gen_abnormal_sensor() -> dict:
    """Out-of-range sensor readings – SEV 2-4."""
    f = random.choice(FACILITIES)
    anomalies = [
        # SEV 2 – slight deviations
        (2, "SensorReading", "Pressure reading {v:.1f} bar – slightly above normal",
         "pressure_bar", 5.8, 7.0),
        (2, "SensorReading", "Turbidity {v:.2f} NTU – elevated, monitoring",
         "turbidity_ntu", 1.5, 4.0),
        (2, "SensorReading", "pH level {v:.2f} – drifting outside optimal range",
         "ph_level", 8.3, 9.0),
        (2, "SensorReading", "Water temperature {v:.1f}°C – above seasonal norm",
         "temp_celsius", 24.0, 30.0),
        # SEV 3 – clearly abnormal
        (3, "SensorReading", "Chlorine residual {v:.2f} mg/L – below minimum threshold",
         "chlorine_mg_l", 0.05, 0.3),
        (3, "SensorReading", "Pressure drop to {v:.1f} bar – possible leak",
         "pressure_bar", 1.5, 2.5),
        (3, "SensorReading", "Turbidity spike to {v:.1f} NTU – source quality concern",
         "turbidity_ntu", 5.0, 12.0),
        (3, "SensorReading", "Flow rate anomaly {v:.0f} m³/h – unexpected surge",
         "flow_rate_m3h", 200, 350),
        # SEV 4 – critical sensor values
        (4, "SensorReading", "Chlorine residual CRITICAL {v:.3f} mg/L – public health risk",
         "chlorine_mg_l", 0.0, 0.05),
        (4, "SensorReading", "Pressure CRITICAL {v:.1f} bar – infrastructure stress",
         "pressure_bar", 8.0, 12.0),
    ]
    sev, etype, desc, metric, lo, hi = random.choices(
        anomalies, weights=[20, 20, 15, 10, 10, 10, 5, 5, 3, 2], k=1
    )[0]
    v = random.uniform(lo, hi)
    return {
        "eventType": etype,
        "description": desc.format(v=v),
        "severity": sev,
        "facilityId": f["id"],
        "metadata": {"metric": metric, "value": round(v, 3), "status": "anomalous"},
    }


def gen_abnormal_maintenance() -> dict:
    """Maintenance issues and failures – SEV 2-4."""
    f = random.choice(FACILITIES)
    p = random.choice(CONTRACTORS + EMPLOYEES[:2])
    anomalies = [
        # SEV 2 – minor issues
        (2, f"Unscheduled pump maintenance required at {f['name']}",
         {"scheduled": False, "reason": "vibration_alert"}),
        (2, "Sensor calibration drift detected – recalibration needed",
         {"scheduled": False, "reason": "calibration_drift"}),
        (2, f"Filter backwash pressure higher than expected – {random.uniform(1.2,1.8):.1f}x normal",
         {"scheduled": False, "reason": "backwash_pressure"}),
        # SEV 3 – failures
        (3, f"Pump inspection FAILED – bearing wear detected at {f['name']}",
         {"scheduled": True, "result": "fail", "issue": "bearing_wear"}),
        (3, f"Valve actuator malfunction – manual override required at {f['name']}",
         {"scheduled": False, "result": "fail", "issue": "actuator_failure"}),
        (3, f"Chemical dosing pump error – delivery rate {random.randint(40,70)}% of target",
         {"scheduled": False, "result": "fail", "issue": "dosing_error"}),
        # SEV 4 – critical
        (4, f"SCADA-controlled valve stuck OPEN at {f['name']} – cannot close remotely",
         {"scheduled": False, "result": "critical", "issue": "valve_stuck"}),
        (4, f"Backup generator failed monthly test – no redundancy at {f['name']}",
         {"scheduled": True, "result": "critical", "issue": "generator_failure"}),
    ]
    sev, desc, meta = random.choices(
        anomalies, weights=[20, 20, 15, 15, 10, 10, 5, 5], k=1
    )[0]
    return {
        "eventType": "Maintenance",
        "description": desc,
        "severity": sev,
        "facilityId": f["id"],
        "personId": p["id"],
        "metadata": {**meta, "workOrderId": f"WO-{random.randint(10000,99999)}"},
    }


def gen_abnormal_system() -> dict:
    """System anomalies and failures – SEV 2-4."""
    f = random.choice(FACILITIES)
    systems = ["SCADA-Main", "PLC-Primary", "HMI-Station", "Historian-DB",
               "VPN-Gateway", "Firewall-OT"]
    sys_name = random.choice(systems)
    anomalies = [
        # SEV 2 – warnings
        (2, f"{sys_name} high CPU usage {random.randint(80,95)}% – performance degradation",
         {"system": sys_name, "status": "warning", "cpu_pct": random.randint(80, 95)}),
        (2, f"{sys_name} disk usage {random.randint(85,95)}% – cleanup recommended",
         {"system": sys_name, "status": "warning", "disk_pct": random.randint(85, 95)}),
        (2, f"{sys_name} heartbeat delayed {random.randint(30,120)}s – network congestion",
         {"system": sys_name, "status": "warning", "delay_sec": random.randint(30, 120)}),
        # SEV 3 – errors
        (3, f"{sys_name} connection lost for {random.randint(2,15)} minutes – restored",
         {"system": sys_name, "status": "error", "downtime_min": random.randint(2, 15)}),
        (3, f"{sys_name} unauthorized configuration change detected",
         {"system": sys_name, "status": "error", "configChange": True}),
        (3, f"{sys_name} certificate expiring in {random.randint(1,7)} days – renewal critical",
         {"system": sys_name, "status": "error", "certDaysLeft": random.randint(1, 7)}),
        # SEV 4 – critical failures
        (4, f"{sys_name} OFFLINE – no heartbeat for {random.randint(15,60)} minutes",
         {"system": sys_name, "status": "critical", "downtime_min": random.randint(15, 60)}),
        (4, f"{sys_name} firmware integrity check FAILED – possible tampering",
         {"system": sys_name, "status": "critical", "integrityFail": True}),
    ]
    sev, desc, meta = random.choices(
        anomalies, weights=[20, 15, 15, 15, 10, 10, 8, 7], k=1
    )[0]
    return {
        "eventType": "SystemStatus",
        "description": desc,
        "severity": sev,
        "facilityId": f["id"],
        "metadata": meta,
    }


def gen_abnormal_quality() -> dict:
    """Quality check failures – SEV 2-4."""
    f = random.choice(FACILITIES)
    anomalies = [
        # SEV 2 – borderline
        (2, f"Bacteriological sample – borderline count {random.randint(80,99)} CFU/100mL (limit 100)",
         {"result": "borderline", "cfu_100ml": random.randint(80, 99)}),
        (2, f"Nitrate levels {random.randint(40,49)} mg/L – approaching EU limit of 50 mg/L",
         {"result": "borderline", "nitrate_mg_l": random.randint(40, 49)}),
        (2, f"Slight taste/odor detected in finished water sample",
         {"result": "borderline", "issue": "taste_odor"}),
        # SEV 3 – failures
        (3, f"Bacteriological sample POSITIVE – {random.randint(120,500)} CFU/100mL detected",
         {"result": "fail", "cfu_100ml": random.randint(120, 500)}),
        (3, f"Heavy metals: lead {random.uniform(10,25):.1f} µg/L – exceeds 10 µg/L limit",
         {"result": "fail", "lead_ug_l": round(random.uniform(10, 25), 1)}),
        (3, f"Nitrate levels {random.randint(55,80)} mg/L – EXCEEDS EU limit",
         {"result": "fail", "nitrate_mg_l": random.randint(55, 80)}),
        # SEV 4 – critical contamination
        (4, f"Legionella POSITIVE – {random.randint(1000,5000)} CFU/L – immediate action required",
         {"result": "critical", "legionella_cfu_l": random.randint(1000, 5000)}),
        (4, f"Organic contaminant detected – benzene {random.uniform(1,5):.1f} µg/L (limit 1 µg/L)",
         {"result": "critical", "benzene_ug_l": round(random.uniform(1, 5), 1)}),
    ]
    sev, desc, meta = random.choices(
        anomalies, weights=[20, 20, 15, 15, 10, 10, 5, 5], k=1
    )[0]
    return {
        "eventType": "QualityCheck",
        "description": desc,
        "severity": sev,
        "facilityId": f["id"],
        "metadata": {**meta, "labId": f"LAB-{random.randint(1000,9999)}"},
    }


# ═══════════════════════════════════════════════════════════════
#  THREAT SCENARIO GENERATORS (trigger inference engine)
# ═══════════════════════════════════════════════════════════════

def scenario_sabotage() -> list[dict]:
    """Coordinated sabotage: recon → cyber → physical → cover-up."""
    fac = random.choice(CRITICAL_FACILITIES)
    attacker = random.choice(CONTRACTORS)
    return [
        {"eventType": "CyberAlert", "severity": 3, "facilityId": fac["id"],
         "description": f"Port scan on SCADA network from 10.0.99.{random.randint(1,254)}",
         "metadata": {"alertType": "PortScan", "targetSystem": "SCADA-Network"}},
        {"eventType": "UnauthorizedAccess", "severity": 4,
         "facilityId": fac["id"], "personId": attacker["id"],
         "description": f"After-hours badge swipe by {attacker['name']} at Dosing Room",
         "metadata": {"accessPoint": "Dosing Room", "authorized": False}},
        {"eventType": "CyberAlert", "severity": 5, "facilityId": fac["id"],
         "description": f"Brute force PLC login from 10.0.99.{random.randint(1,254)}",
         "metadata": {"alertType": "BruteForce", "targetSystem": "PLC-Main"}},
        {"eventType": "CyberAlert", "severity": 5, "facilityId": fac["id"],
         "description": "PLC firmware modified – dosing setpoint changed to 0.02 mg/L",
         "metadata": {"alertType": "FirmwareTamper", "targetSystem": "PLC-Main"}},
        {"eventType": "PhysicalAnomaly", "severity": 5, "facilityId": fac["id"],
         "description": "Chlorine residual dropped to 0.02 mg/L – critically dangerous",
         "metadata": {"metric": "chlorine_mg_l", "value": 0.02}},
        {"eventType": "PhysicalAnomaly", "severity": 5, "facilityId": fac["id"],
         "description": f"Turbidity spike to {random.uniform(12,25):.1f} NTU – contamination",
         "metadata": {"metric": "turbidity_ntu",
                       "value": round(random.uniform(12, 25), 1)}},
        {"eventType": "CitizenReport", "severity": 4, "facilityId": fac["id"],
         "description": f"Mass reports of discolored water – {random.randint(10,40)} complaints",
         "metadata": {"reportCount": random.randint(10, 40), "area": "Nearby district"}},
    ]


def scenario_cyber_intrusion() -> list[dict]:
    """Multi-facility cyber attack spreading through SCADA."""
    facs = random.sample(FACILITIES, 3)
    events: list[dict] = []
    for fac in facs:
        events.append({
            "eventType": "CyberAlert", "severity": 4, "facilityId": fac["id"],
            "description": f"Anomalous OT traffic at {fac['name']}",
            "metadata": {"alertType": "AnomalousTraffic",
                          "targetSystem": "OT-Network"}})
        events.append({
            "eventType": "CyberAlert", "severity": 5, "facilityId": fac["id"],
            "description": f"Lateral movement – creds harvested at {fac['name']}",
            "metadata": {"alertType": "LateralMovement",
                          "targetSystem": "SCADA-Main"}})
    events.append({
        "eventType": "PhysicalAnomaly", "severity": 5,
        "facilityId": facs[0]["id"],
        "description": "Simultaneous pressure drops – coordinated attack",
        "metadata": {"metric": "pressure_bar", "value": 1.2}})
    return events


def scenario_insider_threat() -> list[dict]:
    """Insider contractor doing unauthorized reconnaissance."""
    insider = random.choice(CONTRACTORS)
    fac = random.choice(FACILITIES)
    return [
        {"eventType": "Access", "severity": 1, "facilityId": fac["id"],
         "personId": insider["id"],
         "description": f"Badge entry by {insider['name']} – authorized",
         "metadata": {"accessPoint": "Main Gate", "authorized": True}},
        {"eventType": "UnauthorizedAccess", "severity": 4,
         "facilityId": fac["id"], "personId": insider["id"],
         "description": f"{insider['name']} accessed Chemical Storage without clearance",
         "metadata": {"accessPoint": "Chemical Storage", "authorized": False}},
        {"eventType": "UnauthorizedAccess", "severity": 5,
         "facilityId": fac["id"], "personId": insider["id"],
         "description": f"{insider['name']} accessed Server Room – requires L3",
         "metadata": {"accessPoint": "Server Room", "authorized": False}},
        {"eventType": "CyberAlert", "severity": 5, "facilityId": fac["id"],
         "description": "USB device connected to SCADA terminal – exfiltration risk",
         "metadata": {"alertType": "DataExfil", "targetSystem": "SCADA-Terminal"}},
        {"eventType": "PhysicalAnomaly", "severity": 5, "facilityId": fac["id"],
         "description": f"Chemical dosing values manually overridden at {fac['name']}",
         "metadata": {"metric": "dosing_override", "value": 1}},
    ]


def scenario_environmental_crisis() -> list[dict]:
    """External contamination event affecting multiple facilities."""
    facs = random.sample(FACILITIES, 2)
    return [
        {"eventType": "PhysicalAnomaly", "severity": 4, "facilityId": facs[0]["id"],
         "description": f"Source water contamination – ammonia {random.uniform(2,8):.1f} mg/L",
         "metadata": {"metric": "ammonia_mg_l",
                       "value": round(random.uniform(2, 8), 1)}},
        {"eventType": "PhysicalAnomaly", "severity": 4, "facilityId": facs[0]["id"],
         "description": "Intake turbidity surging – possible upstream spill",
         "metadata": {"metric": "turbidity_ntu",
                       "value": round(random.uniform(30, 100), 1)}},
        {"eventType": "PhysicalAnomaly", "severity": 5, "facilityId": facs[1]["id"],
         "description": "Chemical oxygen demand spike – industrial contaminant",
         "metadata": {"metric": "cod_mg_l",
                       "value": round(random.uniform(50, 200), 1)}},
        {"eventType": "CitizenReport", "severity": 4, "facilityId": facs[0]["id"],
         "description": f"Strong chemical smell reported – {random.randint(15,50)} complaints",
         "metadata": {"reportCount": random.randint(15, 50),
                       "area": "Multiple districts"}},
        {"eventType": "PhysicalAnomaly", "severity": 5, "facilityId": facs[1]["id"],
         "description": "Emergency shutdown – contamination threshold exceeded",
         "metadata": {"metric": "emergency_shutdown", "value": 1}},
    ]


THREAT_SCENARIOS = [
    scenario_sabotage,
    scenario_cyber_intrusion,
    scenario_insider_threat,
    scenario_environmental_crisis,
]

# ── Event distribution (weighted: ~65% good / ~35% anomalous) ──
# Anomalous events appear often enough to feed inference patterns

ROUTINE_GENERATORS = [
    # Normal (SEV-0) – ~65%
    (gen_normal_access,         18),
    (gen_normal_sensor_reading, 16),
    (gen_routine_maintenance,   10),
    (gen_system_heartbeat,      11),
    (gen_quality_check,         10),
    # Anomalous (SEV 2-4) – ~35%
    (gen_abnormal_access,        8),
    (gen_abnormal_sensor,        8),
    (gen_abnormal_maintenance,   6),
    (gen_abnormal_system,        7),
    (gen_abnormal_quality,       6),
]
_routine_funcs = [f for f, _ in ROUTINE_GENERATORS]
_routine_weights = [w for _, w in ROUTINE_GENERATORS]


def generate_routine_event() -> dict:
    gen = random.choices(_routine_funcs, weights=_routine_weights, k=1)[0]
    return gen()


# ═══════════════════════════════════════════════════════════════
#  API COMMUNICATION
# ═══════════════════════════════════════════════════════════════

_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})

_stats = {"sent": 0, "failed": 0, "scenarios": 0}


def send_event(event: dict) -> Optional[dict]:
    try:
        resp = _session.post(f"{API_BASE}/events/ingest", json=event, timeout=10)
        if resp.status_code in (200, 201):
            _stats["sent"] += 1
            return resp.json()
        else:
            _stats["failed"] += 1
            print(f"  ⚠ API {resp.status_code}: {resp.text[:120]}", flush=True)
            return None
    except requests.exceptions.ConnectionError:
        _stats["failed"] += 1
        return None
    except Exception as e:
        _stats["failed"] += 1
        print(f"  ✗ {e}", flush=True)
        return None


def wait_for_api(max_retries: int = 120, delay: float = 5.0):
    """Block until the AEGIS API is reachable."""
    print(f"  ⏳ Waiting for API at {API_BASE} …", flush=True)
    for attempt in range(1, max_retries + 1):
        try:
            resp = _session.get(f"{API_BASE}/dashboard/stats", timeout=5)
            if resp.status_code == 200:
                stats = resp.json()
                print(f"  ✓ API ready  (events={stats.get('totalEvents', '?')}, "
                      f"cases={stats.get('openCases', '?')})", flush=True)
                return
        except Exception:
            pass
        if attempt % 6 == 0:
            print(f"    … still waiting (attempt {attempt}/{max_retries})",
                  flush=True)
        time.sleep(delay)
    print("  ✗ API not reachable – starting anyway.", flush=True)


def print_event(i: int, event: dict, result: Optional[dict],
                scenario_tag: str = ""):
    sev = event.get("severity", 0)
    icons = {0: "✅", 1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}
    icon = icons.get(sev, "⬜")
    etype = event["eventType"]
    fac = event.get("facilityId", "?")
    tag = f" [{scenario_tag}]" if scenario_tag else ""
    eid = result.get("eventId", "?") if result else "FAIL"
    status = "✓" if result else "✗"
    print(f"  {icon} [{i:5d}] {eid:<28s} SEV-{sev} "
          f"{etype:<22s} {fac}{tag} {status}", flush=True)


def print_stats():
    now = datetime.utcnow().strftime("%H:%M:%S")
    print(f"\n  ─── [{now}] sent={_stats['sent']}  failed={_stats['failed']}  "
          f"scenarios={_stats['scenarios']} ───\n", flush=True)


# ═══════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════

_running = True


def _shutdown(sig, frame):
    global _running
    print(f"\n  🛑 Received signal {sig}, shutting down…", flush=True)
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def main():
    global _running

    print(flush=True)
    print("╔══════════════════════════════════════════════════════╗", flush=True)
    print("║  🛰️  AEGIS Continuous Event Simulator                ║", flush=True)
    print("║  Water Supply Intelligence Platform                  ║", flush=True)
    print("╠══════════════════════════════════════════════════════╣", flush=True)
    print(f"║  API       : {API_BASE:<39s} ║", flush=True)
    print(f"║  Interval  : {INTERVAL:<5.1f}s routine events"
          f"                    ║", flush=True)
    print(f"║  Scenarios : every {SCENARIO_MIN}-{SCENARIO_MAX}s"
          f"                              ║", flush=True)
    print("╚══════════════════════════════════════════════════════╝", flush=True)
    print(flush=True)

    wait_for_api()

    event_counter = 0
    next_scenario_at = time.time() + random.randint(SCENARIO_MIN, SCENARIO_MAX)
    last_stats_at = time.time()

    print(f"\n  ▶ Streaming events …\n", flush=True)

    while _running:
        now = time.time()

        # ── Threat scenario? ──
        if now >= next_scenario_at:
            scenario_fn = random.choice(THREAT_SCENARIOS)
            scenario_name = scenario_fn.__name__.replace("scenario_", "").upper()
            _stats["scenarios"] += 1
            events = scenario_fn()

            print(f"\n  🚨 SCENARIO: {scenario_name} ({len(events)} events)",
                  flush=True)
            for ev in events:
                event_counter += 1
                result = send_event(ev)
                print_event(event_counter, ev, result, scenario_tag=scenario_name)
                time.sleep(max(0.3, INTERVAL * 0.5))
                if not _running:
                    break

            next_scenario_at = now + random.randint(SCENARIO_MIN, SCENARIO_MAX)
            print(f"  🔮 Next scenario in ~{int(next_scenario_at - time.time())}s\n",
                  flush=True)
        else:
            # ── Routine event ──
            event_counter += 1
            ev = generate_routine_event()
            result = send_event(ev)
            print_event(event_counter, ev, result)
            time.sleep(INTERVAL)

        # ── Periodic stats ──
        if now - last_stats_at > 60:
            print_stats()
            last_stats_at = now

    # ── Shutdown ──
    print_stats()
    print("  ✓ Simulator stopped.\n", flush=True)


if __name__ == "__main__":
    main()
