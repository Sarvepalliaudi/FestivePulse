"""
FestivePulse AI — Configuration, Constants, and Regional Master Data
All business parameters are deterministic and configurable.
"""

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "festivepulse.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
ASSETS_DIR = BASE_DIR / "assets"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Application Meta
APP_NAME = "FestivePulse"
APP_TAGLINE = "Festival Sales & Inventory Command Center for Indian Retailers"
APP_ICON = "🪔"
VERSION = "1.0.0"
APP_VERSION = "1.0.0"

# Currency & Formatting
CURRENCY_SYMBOL = "₹"
DEFAULT_NUMBER_FORMAT = "INR_LAKHS"

# Standard Indian GST Slabs
GST_SLABS = [0.0, 5.0, 12.0, 18.0, 28.0]

# Supported Indian Regions
REGIONS = [
    "Pan-India",
    "North",
    "South",
    "East",
    "West",
    "Central",
    "North-East"
]

# Indian States with official 2-digit GST State Codes
INDIAN_STATES = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "36": "Telangana",
    "37": "Andhra Pradesh"
}

# Master List of Indian Festivals Supported
MASTER_FESTIVALS = [
    {
        "code": "DIWALI",
        "name": "Diwali & Dhanteras",
        "primary_regions": ["Pan-India", "North", "West", "Central"],
        "typical_surge_multiplier": 3.50,
        "preparation_lead_days": 35,
    },
    {
        "code": "DURGA_PUJA",
        "name": "Durga Puja & Navratri",
        "primary_regions": ["East", "West", "Pan-India"],
        "typical_surge_multiplier": 3.00,
        "preparation_lead_days": 30,
    },
    {
        "code": "PONGAL",
        "name": "Pongal & Sankranti",
        "primary_regions": ["South", "Pan-India"],
        "typical_surge_multiplier": 2.80,
        "preparation_lead_days": 25,
    },
    {
        "code": "ONAM",
        "name": "Onam",
        "primary_regions": ["South"],
        "typical_surge_multiplier": 3.00,
        "preparation_lead_days": 25,
    },
    {
        "code": "GANESH_CHATURTHI",
        "name": "Ganesh Chaturthi",
        "primary_regions": ["West", "South", "Central"],
        "typical_surge_multiplier": 2.50,
        "preparation_lead_days": 20,
    },
    {
        "code": "EID_FITR",
        "name": "Eid al-Fitr",
        "primary_regions": ["Pan-India", "North", "South", "West"],
        "typical_surge_multiplier": 3.00,
        "preparation_lead_days": 25,
    },
    {
        "code": "BAKRID",
        "name": "Bakrid / Eid al-Adha",
        "primary_regions": ["Pan-India", "North", "South"],
        "typical_surge_multiplier": 2.60,
        "preparation_lead_days": 20,
    },
    {
        "code": "CHRISTMAS",
        "name": "Christmas & New Year",
        "primary_regions": ["Pan-India", "South", "West", "North-East"],
        "typical_surge_multiplier": 2.50,
        "preparation_lead_days": 25,
    }
]

# Standard Product Categories in Indian Festival Commerce
DEFAULT_CATEGORIES = [
    {
        "name": "Sweets, Dry Fruits & Mithai",
        "gst_rate": 5.0,
        "description": "Perishable traditional sweets, gift boxes, and dry fruits"
    },
    {
        "name": "Ethnic Apparel & Festive Wear",
        "gst_rate": 5.0,
        "description": "Kurtas, sarees, lehengas, festive accessories"
    },
    {
        "name": "Puja Samagri & Diyas",
        "gst_rate": 0.0,
        "description": "Clay diyas, camphor, incense, brass idols, puja kits"
    },
    {
        "name": "Home Decor & Festive Lighting",
        "gst_rate": 18.0,
        "description": "LED string lights, rangoli kits, lanterns, wall hangings"
    },
    {
        "name": "Gift Hampers & Specialty Packs",
        "gst_rate": 12.0,
        "description": "Assorted corporate and festive gift hampers"
    },
    {
        "name": "Electronics & Appliances",
        "gst_rate": 18.0,
        "description": "Kitchen appliances, home entertainment, smart home"
    }
]

# Operating Expense Categories for Festival Tracking
EXPENSE_CATEGORIES = [
    ("RENT", "Rent (Store, Stall, Warehouse)"),
    ("TRANSPORT", "Transport & Freight (Logistics, Delivery)"),
    ("PACKAGING", "Packaging (Boxes, Pouches, Bags, Foils)"),
    ("WAGES", "Wages & Bonuses (Staff Overtime, Temporary Labor)"),
    ("MARKETING", "Marketing & Promotion (Ads, Banners, Social Campaigns)"),
    ("OTHER", "Other Costs (Utilities, Decor, Incidental Overheads)"),
    # Legacy category aliases
    ("TEMPORARY_STALL_RENT", "Temporary Stall / Mela Booth Rent"),
    ("PACKAGING_BOXES", "Special Festive Gift Boxes & Packaging"),
    ("STAFF_BONUS_OVERTIME", "Staff Festival Bonus & Peak Overtime"),
    ("MARKETING_BANNERS_PAMPHLETS", "Local Ads, Pamphlets & WhatsApp Campaigns"),
    ("TRANSPORT_FREIGHT", "Express Inbound Freight & Supplier Rush Fees"),
    ("FESTIVAL_DECORATION", "Store / Stall Festival Decoration"),
    ("UTILITIES_POWER", "Special Lighting, Generator & Power Costs"),
    ("MISCELLANEOUS", "Other Incidental Festival Overheads")
]

# Units of Measure
UNITS_OF_MEASURE = ["pcs", "kg", "grams", "box", "pack", "meter", "set", "kit"]

# Payment Modes
PAYMENT_MODES = ["UPI", "CASH", "CARD", "CREDIT_KHATA", "SPLIT"]
