"""
Synthetic Data Generator for KSP Crime Database
Generates realistic Karnataka crime data matching the ER diagram schema
"""
import sqlite3
import random
import json
from datetime import datetime, timedelta

# Karnataka Districts
DISTRICTS = [
    "Bengaluru Urban", "Bengaluru Rural", "Mysuru", "Mangaluru", "Hubballi-Dharwad",
    "Belagavi", "Kalaburagi", "Ballari", "Tumakuru", "Shivamogga",
    "Davanagere", "Vijayapura", "Raichur", "Bidar", "Hassan",
    "Chitradurga", "Udupi", "Chikkamagaluru", "Kodagu", "Gadag"
]

# Police Stations per district (sample)
POLICE_STATIONS = {
    "Bengaluru Urban": ["Cubbon Park", "MG Road", "Koramangala", "Whitefield", "Hebbal",
                         "Yelahanka", "Electronic City", "JP Nagar", "Indiranagar", "HSR Layout"],
    "Bengaluru Rural": ["Ramanagara", "Channapatna", "Kanakapura", "Nelamangala", "Doddaballapur"],
    "Mysuru": ["Nazarbad", "Lakshmipuram", "Saraswathipuram", "Vijayanagar", "Jayalakshmipuram"],
    "Mangaluru": ["Mangaluru North", "Mangaluru South", "Konkanpady", "Bajpe", "Ullal"],
    "Hubballi-Dharwad": ["Hubballi Town", "Dharwad", "Gabbur", "Tarihal", "Navalur"],
    "Belagavi": ["Belagavi Camp", "Belagavi Town", "Tilakwadi", "Udyambag", "Vadgaon"],
    "Kalaburagi": ["Kalaburagi Town", "Aland", "Chittapur", "Sedam", "Yadgir"],
    "Ballari": ["Ballari Town", "Sandur", "Hospet", "Kudligi", "Siruguppa"],
    "Tumakuru": ["Tumakuru Town", "Tiptur", "Chikkanayakanahalli", "Sira", "Pavagada"],
    "Shivamogga": ["Shivamogga Town", "Bhadravati", "Shimoga Rural", "Sagar", "Soraba"],
}
# Fill remaining districts with generic stations
for d in DISTRICTS:
    if d not in POLICE_STATIONS:
        POLICE_STATIONS[d] = [f"{d} Station {i}" for i in range(1, 4)]

CRIME_TYPES = [
    "Murder", "Attempt to Murder", "Robbery", "Dacoity", "Theft",
    "Burglary", "Vehicle Theft", "Kidnapping", "Rape", "Sexual Assault",
    "Dowry Death", "Domestic Violence", "Cheating", "Forgery", "Cybercrime",
    "Drug Trafficking", "Arms Act Violation", "Rioting", "Arson", "Hit and Run"
]

IPC_SECTIONS = {
    "Murder": "302", "Attempt to Murder": "307", "Robbery": "392", "Dacoity": "395",
    "Theft": "379", "Burglary": "457", "Vehicle Theft": "379/411", "Kidnapping": "363",
    "Rape": "376", "Sexual Assault": "354", "Dowry Death": "304B", "Domestic Violence": "498A",
    "Cheating": "420", "Forgery": "468", "Cybercrime": "66C IT Act",
    "Drug Trafficking": "NDPS Act", "Arms Act Violation": "Arms Act", "Rioting": "147",
    "Arson": "435", "Hit and Run": "304A"
}

STATUS_OPTIONS = ["Pending Investigation", "Under Investigation", "Chargesheet Filed",
                   "Trial in Progress", "Convicted", "Acquitted", "Case Closed"]

OCCUPATIONS = ["Student", "Farmer", "Business", "Government Employee", "Private Employee",
                "Labourer", "Unemployed", "Retired", "Self Employed", "Driver"]

MOTIVE_MAP = {
    "Murder": ["Personal Enmity", "Property Dispute", "Family Dispute", "Revenge", "Contract Killing"],
    "Robbery": ["Financial Gain", "Drug Addiction", "Unemployment", "Gang Affiliation"],
    "Theft": ["Financial Gain", "Drug Addiction", "Opportunity Crime"],
    "Rape": ["Sexual Motive", "Known to Victim", "Stranger Attack"],
    "Cybercrime": ["Financial Gain", "Blackmail", "Identity Theft", "Romance Scam"],
    "Drug Trafficking": ["Financial Gain", "Gang Affiliation", "Organized Crime"],
    "Domestic Violence": ["Family Dispute", "Alcohol Abuse", "Dowry Demand"],
    "Cheating": ["Financial Gain", "Fraud"],
}

FIRST_NAMES = ["Ravi", "Kumar", "Suresh", "Ramesh", "Mahesh", "Ganesh", "Rajesh", "Naresh",
               "Priya", "Kavitha", "Lakshmi", "Meera", "Sunita", "Anitha", "Rekha", "Suma",
               "Mohammad", "Abdul", "Siddiq", "Ibrahim", "Krishnamurthy", "Venkatesh",
               "Shivakumar", "Basavraj", "Ningappa", "Siddappa", "Veerappa", "Channappa"]

LAST_NAMES = ["Gowda", "Reddy", "Nair", "Rao", "Murthy", "Swamy", "Patil", "Naik",
              "Hegde", "Shetty", "Poojary", "Kamath", "Bhat", "Pai", "Khan", "Patel",
              "Lingappa", "Siddaraju", "Venkataramaiah", "Thimmarayappa"]


def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def random_date(start_year=2019, end_year=2025):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    return (start + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")


def random_phone():
    return f"9{random.randint(100000000, 999999999)}"


def random_aadhaar():
    return f"{random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"


def create_database(db_path="ksp_crime.db"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # --- DDL ---
    c.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS districts (
        district_id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_name TEXT NOT NULL,
        division TEXT,
        range_name TEXT
    );

    CREATE TABLE IF NOT EXISTS police_stations (
        station_id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_name TEXT NOT NULL,
        district_id INTEGER REFERENCES districts(district_id),
        station_code TEXT,
        address TEXT,
        contact_number TEXT,
        officer_in_charge TEXT,
        latitude REAL,
        longitude REAL
    );

    CREATE TABLE IF NOT EXISTS fir_cases (
        fir_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_number TEXT UNIQUE NOT NULL,
        station_id INTEGER REFERENCES police_stations(station_id),
        crime_type TEXT NOT NULL,
        ipc_section TEXT,
        date_of_incident TEXT,
        date_of_fir TEXT,
        location_of_crime TEXT,
        latitude REAL,
        longitude REAL,
        description TEXT,
        status TEXT DEFAULT 'Pending Investigation',
        assigned_officer TEXT,
        severity_score INTEGER DEFAULT 5,
        modus_operandi TEXT,
        property_loss_value REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS accused (
        accused_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_id INTEGER REFERENCES fir_cases(fir_id),
        name TEXT NOT NULL,
        alias TEXT,
        age INTEGER,
        gender TEXT,
        address TEXT,
        district_id INTEGER REFERENCES districts(district_id),
        occupation TEXT,
        aadhaar_number TEXT,
        contact_number TEXT,
        criminal_history INTEGER DEFAULT 0,
        gang_affiliation TEXT,
        nationality TEXT DEFAULT 'Indian',
        arrest_date TEXT,
        arrest_status TEXT DEFAULT 'Wanted'
    );

    CREATE TABLE IF NOT EXISTS victims (
        victim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_id INTEGER REFERENCES fir_cases(fir_id),
        name TEXT NOT NULL,
        age INTEGER,
        gender TEXT,
        address TEXT,
        district_id INTEGER REFERENCES districts(district_id),
        occupation TEXT,
        contact_number TEXT,
        injury_type TEXT DEFAULT 'None',
        medical_treatment TEXT DEFAULT 'Not Required'
    );

    CREATE TABLE IF NOT EXISTS witnesses (
        witness_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_id INTEGER REFERENCES fir_cases(fir_id),
        name TEXT NOT NULL,
        age INTEGER,
        address TEXT,
        contact_number TEXT,
        statement_recorded INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS criminal_records (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        accused_id INTEGER REFERENCES accused(accused_id),
        previous_fir_number TEXT,
        crime_type TEXT,
        district TEXT,
        year INTEGER,
        conviction_status TEXT
    );

    CREATE TABLE IF NOT EXISTS officers (
        officer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        badge_number TEXT UNIQUE,
        rank TEXT,
        station_id INTEGER REFERENCES police_stations(station_id),
        contact_number TEXT,
        email TEXT,
        cases_handled INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS case_progress (
        progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_id INTEGER REFERENCES fir_cases(fir_id),
        update_date TEXT,
        update_type TEXT,
        notes TEXT,
        officer_id INTEGER REFERENCES officers(officer_id)
    );

    CREATE TABLE IF NOT EXISTS stolen_property (
        property_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fir_id INTEGER REFERENCES fir_cases(fir_id),
        property_type TEXT,
        description TEXT,
        estimated_value REAL,
        recovered INTEGER DEFAULT 0,
        recovery_date TEXT
    );

    CREATE TABLE IF NOT EXISTS crime_analytics_cache (
        cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash TEXT UNIQUE,
        query_text TEXT,
        result_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Index strategy validated by tests/benchmark_performance.py's
    -- EXPLAIN QUERY PLAN before/after comparison (see
    -- docs/PERFORMANCE_BENCHMARK_REPORT.md): reduces full-table scans on
    -- the app's actual query shapes (build_sql_query() in ai_engine.py)
    -- from 11/11 benchmarked query types down to 4/11, with zero
    -- application-code changes required.
    CREATE INDEX IF NOT EXISTS idx_fir_station ON fir_cases(station_id);
    CREATE INDEX IF NOT EXISTS idx_fir_crime_type ON fir_cases(crime_type);
    CREATE INDEX IF NOT EXISTS idx_fir_date ON fir_cases(date_of_incident);
    CREATE INDEX IF NOT EXISTS idx_fir_severity ON fir_cases(severity_score DESC);
    CREATE INDEX IF NOT EXISTS idx_fir_status ON fir_cases(status);
    CREATE INDEX IF NOT EXISTS idx_stations_district ON police_stations(district_id);
    CREATE INDEX IF NOT EXISTS idx_accused_fir ON accused(fir_id);
    CREATE INDEX IF NOT EXISTS idx_accused_status ON accused(arrest_status);
    CREATE INDEX IF NOT EXISTS idx_accused_gang ON accused(gang_affiliation);
    CREATE INDEX IF NOT EXISTS idx_victims_fir ON victims(fir_id);
    CREATE INDEX IF NOT EXISTS idx_stolen_property_fir ON stolen_property(fir_id);
    """)
    conn.commit()

    # --- Seed Districts ---
    divisions = ["Bengaluru", "Mysuru", "Belagavi", "Kalaburagi"]
    for i, d in enumerate(DISTRICTS):
        c.execute("INSERT OR IGNORE INTO districts (district_name, division, range_name) VALUES (?,?,?)",
                  (d, divisions[i % 4], f"{d} Range"))
    conn.commit()

    # --- Seed Police Stations ---
    c.execute("SELECT district_id, district_name FROM districts")
    dist_map = {row[1]: row[0] for row in c.fetchall()}

    station_id_counter = 1
    station_map = {}  # station_name -> station_id

    OFFICER_RANKS = ["Sub Inspector", "Inspector", "Deputy Superintendent", "Circle Inspector"]
    for district, stations in POLICE_STATIONS.items():
        did = dist_map.get(district, 1)
        for s in stations:
            officer = f"{random_name()} ({random.choice(OFFICER_RANKS)})"
            lat = 12.5 + random.uniform(-2, 5)
            lon = 75.5 + random.uniform(-1, 5)
            c.execute("""INSERT INTO police_stations (station_name, district_id, station_code,
                         address, contact_number, officer_in_charge, latitude, longitude)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (s, did, f"KA{station_id_counter:04d}", f"{s} Road, {district}",
                       random_phone(), officer, lat, lon))
            station_map[s] = c.lastrowid
            station_id_counter += 1
    conn.commit()

    # --- Seed Officers ---
    officer_ids = []
    for _, sid in station_map.items():
        for _ in range(random.randint(3, 6)):
            rank = random.choice(["Constable", "Head Constable", "ASI", "Sub Inspector", "Inspector"])
            badge = f"KA{random.randint(10000, 99999)}"
            c.execute("""INSERT OR IGNORE INTO officers (name, badge_number, rank, station_id,
                         contact_number, email, cases_handled) VALUES (?,?,?,?,?,?,?)""",
                      (random_name(), badge, rank, sid, random_phone(),
                       f"{badge.lower()}@ksp.gov.in", random.randint(5, 120)))
            officer_ids.append(c.lastrowid)
    conn.commit()
    if not officer_ids:
        c.execute("SELECT officer_id FROM officers")
        officer_ids = [r[0] for r in c.fetchall()]

    # --- Seed FIR Cases (1500 records) ---
    all_stations = list(station_map.values())
    dist_ids = list(dist_map.values())
    fir_records = []

    for i in range(1, 1501):
        crime = random.choice(CRIME_TYPES)
        station = random.choice(all_stations)
        year = random.randint(2019, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        inc_date = f"{year}-{month:02d}-{day:02d}"
        fir_date = (datetime(year, month, day) + timedelta(days=random.randint(0, 3))).strftime("%Y-%m-%d")
        severity = {"Murder": 10, "Rape": 9, "Robbery": 7, "Dacoity": 8,
                    "Cybercrime": 5, "Theft": 4, "Drug Trafficking": 8}.get(crime, random.randint(3, 8))
        motives = MOTIVE_MAP.get(crime, ["Unknown"])
        c.execute("""INSERT INTO fir_cases (fir_number, station_id, crime_type, ipc_section,
                     date_of_incident, date_of_fir, location_of_crime, latitude, longitude,
                     description, status, assigned_officer, severity_score, modus_operandi,
                     property_loss_value)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (f"KSP{year}{i:05d}", station, crime, IPC_SECTIONS.get(crime, "IPC"),
                   inc_date, fir_date, f"Location_{i}", 12.5 + random.uniform(-2, 5),
                   75.5 + random.uniform(-1, 5),
                   f"{crime} case registered at station. IPC Section {IPC_SECTIONS.get(crime, 'IPC')}.",
                   random.choice(STATUS_OPTIONS),
                   random_name(),
                   severity,
                   random.choice(motives),
                   round(random.uniform(0, 500000), 2) if crime in ["Theft", "Robbery", "Burglary", "Dacoity"] else 0))
        fir_records.append(c.lastrowid)
    conn.commit()

    # --- Seed Accused (1800+ records) ---
    accused_ids = []
    for fir_id in fir_records:
        num_accused = random.choices([1, 2, 3, 4], weights=[55, 25, 15, 5])[0]
        for _ in range(num_accused):
            age = random.randint(16, 65)
            gang = random.choice([None, None, None, "Rowdy Sheeter", "Organized Gang", "Known Criminal"]) 
            c.execute("""INSERT INTO accused (fir_id, name, alias, age, gender, address,
                         district_id, occupation, aadhaar_number, contact_number,
                         criminal_history, gang_affiliation, arrest_date, arrest_status)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (fir_id, random_name(), random.choice([None, random_name().split()[0]]),
                       age, random.choice(["Male", "Male", "Male", "Female"]),
                       f"Address, {random.choice(DISTRICTS)}",
                       random.choice(dist_ids),
                       random.choice(OCCUPATIONS),
                       random_aadhaar() if random.random() > 0.3 else None,
                       random_phone() if random.random() > 0.4 else None,
                       random.randint(0, 5),
                       gang,
                       random_date(2019, 2025) if random.random() > 0.4 else None,
                       random.choice(["Arrested", "Arrested", "Wanted", "Absconding"])))
            accused_ids.append(c.lastrowid)
    conn.commit()

    # --- Seed Criminal Records for repeat offenders ---
    for acc_id in random.sample(accused_ids, min(300, len(accused_ids))):
        for _ in range(random.randint(1, 3)):
            c.execute("""INSERT INTO criminal_records (accused_id, previous_fir_number, crime_type,
                         district, year, conviction_status) VALUES (?,?,?,?,?,?)""",
                      (acc_id, f"KSP{random.randint(2015, 2018)}{random.randint(1, 9999):05d}",
                       random.choice(CRIME_TYPES), random.choice(DISTRICTS),
                       random.randint(2015, 2020),
                       random.choice(["Convicted", "Acquitted", "Pending"])))
    conn.commit()

    # --- Seed Victims ---
    for fir_id in fir_records:
        c.execute("SELECT crime_type FROM fir_cases WHERE fir_id=?", (fir_id,))
        row = c.fetchone()
        if not row:
            continue
        crime = row[0]
        num_victims = 1 if crime in ["Theft", "Cybercrime", "Cheating"] else random.randint(1, 3)
        for _ in range(num_victims):
            c.execute("""INSERT INTO victims (fir_id, name, age, gender, address,
                         district_id, occupation, contact_number, injury_type, medical_treatment)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (fir_id, random_name(), random.randint(5, 80),
                       random.choice(["Male", "Female", "Female"]),
                       f"Address, {random.choice(DISTRICTS)}",
                       random.choice(dist_ids),
                       random.choice(OCCUPATIONS),
                       random_phone(),
                       random.choice(["None", "Minor Injury", "Grievous Injury", "Fatal"]),
                       random.choice(["Not Required", "Outpatient", "Hospitalized"])))
    conn.commit()

    # --- Seed Stolen Property ---
    property_types = ["Mobile Phone", "Cash", "Jewellery", "Vehicle", "Electronics", "Documents"]
    for fir_id in fir_records:
        c.execute("SELECT crime_type FROM fir_cases WHERE fir_id=?", (fir_id,))
        row = c.fetchone()
        if row and row[0] in ["Theft", "Robbery", "Burglary", "Dacoity", "Vehicle Theft"]:
            for _ in range(random.randint(1, 3)):
                c.execute("""INSERT INTO stolen_property (fir_id, property_type, description,
                             estimated_value, recovered, recovery_date) VALUES (?,?,?,?,?,?)""",
                          (fir_id, random.choice(property_types),
                           f"{random.choice(property_types)} stolen",
                           round(random.uniform(500, 200000), 2),
                           random.choice([0, 0, 1]),
                           random_date(2019, 2025) if random.random() > 0.7 else None))
    conn.commit()

    print(f"[✓] Synthetic database created at {db_path}")
    print(f"    Districts: {len(DISTRICTS)}")
    print(f"    Police Stations: {station_id_counter - 1}")
    print(f"    FIR Cases: 1500")

    conn.close()
    return db_path


if __name__ == "__main__":
    create_database()
