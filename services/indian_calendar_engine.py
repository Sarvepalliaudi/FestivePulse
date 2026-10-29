"""
FestivePulse — Indian Festival Calendar Engine (Next 200 Years)
Deterministic mathematical and astronomical calculation of all major Indian festivals
across solar, lunisolar (Hindu/Panchang), Islamic (Hijri Tabular), Christian, Sikh,
Jain, and Buddhist calendars for any year from 2024 to 2230+.

No external APIs or AI required. Pure standard library implementation.
"""

import math
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple, Optional


def jd_to_gregorian(jd: float) -> date:
    """Converts a Julian Day number to a Gregorian date object."""
    z = int(jd + 0.5)
    f = (jd + 0.5) - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - int(alpha / 4)
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e)
    if e < 14:
        month = e - 1
    else:
        month = e - 13
    if month > 2:
        year = c - 4716
    else:
        year = c - 4715
    return date(year, month, int(day))


def gregorian_to_jd(year: int, month: int, day: int) -> float:
    """Converts a Gregorian date to Julian Day number."""
    if month <= 2:
        year -= 1
        month += 12
    a = int(year / 100)
    b = 2 - a + int(a / 4)
    jd = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5
    return jd


def calculate_moon_phase_jd(k: float, is_full_moon: bool = False) -> float:
    """
    Computes Julian Ephemeris Day of New Moon (k integer) or Full Moon (k half-integer)
    using Jean Meeus' Astronomical Algorithms (Ch. 49).
    Accurate to within minutes over multiple centuries.
    """
    t = k / 1236.85
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t

    # Mean phase
    jde = 2451549.5926 + 29.530588853 * k + 0.0001337 * t2 - 0.000000150 * t3 + 0.00000000073 * t4

    # Sun's mean anomaly in radians
    m = math.radians(2.5534 + 29.10535669 * k - 0.0000218 * t2 - 0.00000011 * t3)
    # Moon's mean anomaly in radians
    m_prime = math.radians(201.5643 + 385.81693528 * k + 0.0107438 * t2 + 0.00001239 * t3 - 0.000000058 * t4)
    # Moon's argument of latitude in radians
    f = math.radians(160.7108 + 390.67050274 * k - 0.0016341 * t2 - 0.00000227 * t3 + 0.000000011 * t4)
    # Longitude of ascending node
    omega = math.radians(124.7746 - 1.56375580 * k + 0.0020691 * t2 + 0.00000215 * t3)

    if not is_full_moon:
        # Periodic corrections for New Moon (Amavasya)
        pt = -0.40720 * math.sin(m_prime)
        pt += 0.17241 * math.sin(m)
        pt += 0.01608 * math.sin(2 * m_prime)
        pt += 0.01039 * math.sin(2 * f)
        pt += 0.00739 * math.sin(m_prime - m)
        pt -= 0.00514 * math.sin(m_prime + m)
        pt += 0.00208 * math.sin(2 * m)
        pt -= 0.00111 * math.sin(m_prime - 2 * f)
        pt -= 0.00057 * math.sin(m_prime + 2 * f)
        pt += 0.00056 * math.sin(2 * m_prime + m)
        pt -= 0.00042 * math.sin(3 * m_prime)
        pt += 0.00042 * math.sin(m + 2 * f)
        pt += 0.00038 * math.sin(m - 2 * f)
        pt -= 0.00024 * math.sin(2 * m_prime - m)
        pt -= 0.00017 * math.sin(omega)
    else:
        # Periodic corrections for Full Moon (Purnima)
        pt = -0.40614 * math.sin(m_prime)
        pt += 0.17302 * math.sin(m)
        pt += 0.01614 * math.sin(2 * m_prime)
        pt -= 0.00974 * math.sin(2 * f)
        pt -= 0.00739 * math.sin(m_prime - m)
        pt -= 0.00514 * math.sin(m_prime + m)
        pt += 0.00209 * math.sin(2 * m)
        pt -= 0.00111 * math.sin(m_prime - 2 * f)
        pt -= 0.00057 * math.sin(m_prime + 2 * f)
        pt += 0.00056 * math.sin(2 * m_prime + m)
        pt -= 0.00042 * math.sin(3 * m_prime)
        pt += 0.00042 * math.sin(m + 2 * f)
        pt += 0.00038 * math.sin(m - 2 * f)
        pt -= 0.00024 * math.sin(2 * m_prime - m)
        pt -= 0.00017 * math.sin(omega)

    # Convert to Indian Standard Time (+5.5 hours = +0.229167 day)
    return jde + pt + 0.229167


def get_year_moon_phases(year: int) -> Tuple[List[date], List[date]]:
    """
    Finds all New Moons and Full Moons occurring in the given calendar year.
    Returns (new_moons, full_moons) sorted chronologically.
    """
    # Base lunation k for Jan 2000 is 0
    k_start = int((year - 2000) * 12.3685) - 2
    k_end = k_start + 18

    new_moons = []
    full_moons = []

    for k in range(k_start, k_end):
        # New Moon
        nm_jd = calculate_moon_phase_jd(float(k), is_full_moon=False)
        nm_date = jd_to_gregorian(nm_jd)
        if nm_date.year == year:
            new_moons.append(nm_date)

        # Full Moon
        fm_jd = calculate_moon_phase_jd(float(k) + 0.5, is_full_moon=True)
        fm_date = jd_to_gregorian(fm_jd)
        if fm_date.year == year:
            full_moons.append(fm_date)

    new_moons.sort()
    full_moons.sort()
    return new_moons, full_moons


def hijri_to_gregorian(h_year: int, h_month: int, h_day: int) -> date:
    """
    Converts Tabular Islamic (Hijri) date to Gregorian date.
    Tabular Kuwaiti / Astronomical algorithm valid across centuries.
    """
    # Days since Hijra epoch (16 July 622 CE)
    days = h_day + math.ceil(29.5 * (h_month - 1)) + (h_year - 1) * 354 + math.floor((3 + 11 * h_year) / 30) - 1
    jd = days + 1948439.5
    return jd_to_gregorian(jd)


def gregorian_to_hijri(g_date: date) -> Tuple[int, int, int]:
    """Converts Gregorian date to Tabular Islamic (Hijri) year, month, day."""
    jd = gregorian_to_jd(g_date.year, g_date.month, g_date.day)
    days = jd - 1948439.5 + 1
    h_year = math.floor((30 * days + 10646) / 10631)
    prior_days = days - (math.floor((11 * h_year + 3) / 30) + 354 * (h_year - 1))
    h_month = math.ceil(prior_days / 29.5)
    if h_month > 12:
        h_month = 12
    h_day = int(prior_days - math.ceil(29.5 * (h_month - 1)))
    return int(h_year), int(h_month), max(1, h_day)


def compute_easter(year: int) -> date:
    """Computes Easter Sunday using standard Meeus / Butcher Gregorian Computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l_val = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_val) // 451
    month = (h + l_val - 7 * m + 114) // 31
    day = ((h + l_val - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def generate_all_indian_festivals_for_year(year: int) -> List[Dict[str, Any]]:
    """
    Calculates 25+ comprehensive Indian festivals for any given Gregorian year (2024 to 2230+).
    Spans all major communities (Hindu, Muslim, Christian, Sikh, Jain, Buddhist, National/Regional).
    All entries are marked as `is_sample_date=1, is_verified=0` so retailers can verify local traditions.
    """
    festivals = []

    # Get astronomical Moon phases
    new_moons, full_moons = get_year_moon_phases(year)

    def find_nm_near(month: int, day_est: int = 15) -> Optional[date]:
        candidates = [d for d in new_moons if d.month == month or (d.month == month - 1 and d.day >= 20) or (d.month == month + 1 and d.day <= 10)]
        if not candidates:
            return None
        target = date(year, month, min(day_est, 28))
        return min(candidates, key=lambda d: abs((d - target).days))

    def find_fm_near(month: int, day_est: int = 15) -> Optional[date]:
        candidates = [d for d in full_moons if d.month == month or (d.month == month - 1 and d.day >= 20) or (d.month == month + 1 and d.day <= 10)]
        if not candidates:
            return None
        target = date(year, month, min(day_est, 28))
        return min(candidates, key=lambda d: abs((d - target).days))

    # 1. PONGAL & MAKAR SANKRANTI (Solar Ingress - January 14/15)
    # Due to precession of equinoxes, Sankranti slowly shifts 1 day every ~72 years.
    sankranti_day = 14 if year < 2080 else 15
    festivals.append({
        "festival_name": "Pongal & Makar Sankranti",
        "region": "South",
        "category": "Harvest & Regional",
        "start_date": date(year, 1, sankranti_day).strftime("%Y-%m-%d"),
        "end_date": (date(year, 1, sankranti_day) + timedelta(days=3)).strftime("%Y-%m-%d"),
        "planning_window_days": 20,
        "notes": f"4-day harvest celebration (Bhogi, Surya Pongal, Mattu Pongal, Kaanum Pongal). Sample {year} date.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })
    festivals.append({
        "festival_name": "Makar Sankranti & Uttarayan",
        "region": "West",
        "category": "Harvest & Regional",
        "start_date": date(year, 1, sankranti_day).strftime("%Y-%m-%d"),
        "end_date": (date(year, 1, sankranti_day) + timedelta(days=1)).strftime("%Y-%m-%d"),
        "planning_window_days": 18,
        "notes": "International Kite Festival in Gujarat & Tilgul sweets exchange in Maharashtra.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 2. REPUBLIC DAY (Fixed Solar - January 26)
    festivals.append({
        "festival_name": "Republic Day",
        "region": "Pan-India",
        "category": "Cultural & National",
        "start_date": f"{year}-01-26",
        "end_date": f"{year}-01-26",
        "planning_window_days": 10,
        "notes": "National holiday; patriotic promotional retail sales & clearance events.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 3. MAHA SHIVRATRI (Magha/Phalguna Krishna Chaturdashi - 1 day before Feb/Mar New Moon)
    feb_nm = find_nm_near(2, 20) or find_nm_near(3, 1)
    if feb_nm:
        shivratri_dt = feb_nm - timedelta(days=1)
        festivals.append({
            "festival_name": "Maha Shivratri",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": shivratri_dt.strftime("%Y-%m-%d"),
            "end_date": shivratri_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "notes": "Puja samagri, milk offerings, fruits, and fasting foods retail surge.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 4. HOLI & HOLIKA DAHAN (Phalguna Purnima - March Full Moon)
    mar_fm = find_fm_near(3, 15)
    if mar_fm:
        holi_dt = mar_fm
        festivals.append({
            "festival_name": "Holi & Holika Dahan",
            "region": "North",
            "category": "Major Religious",
            "start_date": (holi_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            "end_date": holi_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 20,
            "notes": "High surge for gulal, herbal colors, pichkaris, gujiya sweets, and white apparel.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 5. UGADI & GUDI PADWA (Chaitra Shukla Pratipada - 1 day after late March / early April New Moon)
    chaitra_nm = find_nm_near(3, 28) or find_nm_near(4, 5)
    if chaitra_nm:
        ugadi_dt = chaitra_nm + timedelta(days=1)
        festivals.append({
            "festival_name": "Gudi Padwa & Ugadi",
            "region": "West",
            "category": "New Year & Seasonal",
            "start_date": ugadi_dt.strftime("%Y-%m-%d"),
            "end_date": ugadi_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "notes": "Maharashtrian, Telugu & Kannada New Year. Peak buying for gold, apparel, and sweet shrikhand.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        # 6. RAM NAVAMI (Chaitra Shukla Navami - 9 days after Chaitra New Moon)
        ram_navami_dt = chaitra_nm + timedelta(days=9)
        festivals.append({
            "festival_name": "Ram Navami",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": ram_navami_dt.strftime("%Y-%m-%d"),
            "end_date": ram_navami_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 14,
            "notes": "Concluding day of Chaitra Navratri. Puja samagri, prasad sweets, and flowers.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        # 7. MAHAVIR JAYANTI (Chaitra Shukla Trayodashi - 13 days after Chaitra New Moon)
        mahavir_dt = chaitra_nm + timedelta(days=13)
        festivals.append({
            "festival_name": "Mahavir Jayanti",
            "region": "West",
            "category": "Major Religious",
            "start_date": mahavir_dt.strftime("%Y-%m-%d"),
            "end_date": mahavir_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 10,
            "notes": "Jain community festival; sweets, gifts, and temple charitable provisions.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 8. VAISAKHI / VISHU / PUTHANDU / POHELA BOISHAKH (Solar Ingress - April 14/15)
    baisakhi_day = 14 if year < 2085 else 15
    festivals.append({
        "festival_name": "Baisakhi & Solar New Year",
        "region": "North",
        "category": "Harvest & Regional",
        "start_date": f"{year}-04-{baisakhi_day:02d}",
        "end_date": f"{year}-04-{baisakhi_day:02d}",
        "planning_window_days": 15,
        "notes": "Punjab harvest festival, Vishu in Kerala, Puthandu in Tamil Nadu, and Pohela Boishakh in Bengal.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 9. GOOD FRIDAY & EASTER (Computus Calculation)
    easter_dt = compute_easter(year)
    good_friday_dt = easter_dt - timedelta(days=2)
    festivals.append({
        "festival_name": "Good Friday & Easter",
        "region": "South",
        "category": "Major Religious",
        "start_date": good_friday_dt.strftime("%Y-%m-%d"),
        "end_date": easter_dt.strftime("%Y-%m-%d"),
        "planning_window_days": 15,
        "notes": "Bakery, Easter eggs, gifting, and family gathering sales surge.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 10. BUDDHA PURNIMA (Vaisakha Purnima - May Full Moon)
    may_fm = find_fm_near(5, 12)
    if may_fm:
        festivals.append({
            "festival_name": "Buddha Purnima",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": may_fm.strftime("%Y-%m-%d"),
            "end_date": may_fm.strftime("%Y-%m-%d"),
            "planning_window_days": 10,
            "notes": "Buddhist spiritual celebration; incense, candles, and vegetarian sweets.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 11. ISLAMIC FESTIVALS (Tabular Hijri algorithm across current year)
    # Estimate Hijri years spanning this Gregorian year
    h_curr, _, _ = gregorian_to_hijri(date(year, 6, 1))
    for h_yr in [h_curr - 1, h_curr, h_curr + 1]:
        # Eid al-Fitr (1st Shawwal = month 10, day 1)
        try:
            eid_fitr_dt = hijri_to_gregorian(h_yr, 10, 1)
            if eid_fitr_dt.year == year:
                festivals.append({
                    "festival_name": "Eid al-Fitr",
                    "region": "Pan-India",
                    "category": "Major Religious",
                    "start_date": eid_fitr_dt.strftime("%Y-%m-%d"),
                    "end_date": (eid_fitr_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "planning_window_days": 25,
                    "notes": f"Marks conclusion of Ramadan ({h_yr} AH). Huge demand for vermicelli, dates, dry fruits, ethnic wear, and attar.",
                    "is_sample_date": 1,
                    "is_verified": 0,
                    "year": year
                })
        except Exception:
            pass

        # Bakrid / Eid al-Adha (10th Dhu al-Hijjah = month 12, day 10)
        try:
            bakrid_dt = hijri_to_gregorian(h_yr, 12, 10)
            if bakrid_dt.year == year:
                festivals.append({
                    "festival_name": "Bakrid / Eid al-Adha",
                    "region": "Pan-India",
                    "category": "Major Religious",
                    "start_date": bakrid_dt.strftime("%Y-%m-%d"),
                    "end_date": (bakrid_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "planning_window_days": 20,
                    "notes": f"Feast of the Sacrifice ({h_yr} AH). Peak demand for spices, dry fruits, gift items, and cookware.",
                    "is_sample_date": 1,
                    "is_verified": 0,
                    "year": year
                })
        except Exception:
            pass

        # Muharram (Ashura = month 1, day 10)
        try:
            ashura_dt = hijri_to_gregorian(h_yr, 1, 10)
            if ashura_dt.year == year:
                festivals.append({
                    "festival_name": "Muharram (Ashura)",
                    "region": "Pan-India",
                    "category": "Community & Spiritual",
                    "start_date": ashura_dt.strftime("%Y-%m-%d"),
                    "end_date": ashura_dt.strftime("%Y-%m-%d"),
                    "planning_window_days": 10,
                    "notes": f"Islamic New Year & Ashura remembrance ({h_yr} AH).",
                    "is_sample_date": 1,
                    "is_verified": 0,
                    "year": year
                })
        except Exception:
            pass

    # 12. RATH YATRA (Ashadha Shukla Dwitiya - late June / July)
    jun_jul_nm = find_nm_near(6, 25) or find_nm_near(7, 5)
    if jun_jul_nm:
        rath_dt = jun_jul_nm + timedelta(days=2)
        festivals.append({
            "festival_name": "Jagannath Puri Rath Yatra",
            "region": "East",
            "category": "Major Religious",
            "start_date": rath_dt.strftime("%Y-%m-%d"),
            "end_date": (rath_dt + timedelta(days=9)).strftime("%Y-%m-%d"),
            "planning_window_days": 20,
            "notes": "Grand chariot festival in Odisha and Eastern India; major mela footfall and regional souvenir commerce.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 13. INDEPENDENCE DAY (Fixed Solar - August 15)
    festivals.append({
        "festival_name": "Independence Day",
        "region": "Pan-India",
        "category": "Cultural & National",
        "start_date": f"{year}-08-15",
        "end_date": f"{year}-08-15",
        "planning_window_days": 10,
        "notes": "National holiday; large mid-year retail freedom sales and consumer electronics discounts.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 14. RAKSHA BANDHAN (Shravana Purnima - August Full Moon)
    aug_fm = find_fm_near(8, 15) or find_fm_near(8, 25)
    if aug_fm:
        rakhi_dt = aug_fm
        festivals.append({
            "festival_name": "Raksha Bandhan",
            "region": "North",
            "category": "Major Religious",
            "start_date": rakhi_dt.strftime("%Y-%m-%d"),
            "end_date": rakhi_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 25,
            "notes": "Surge for designer rakhis, premium chocolate/mithai hampers, and gift vouchers.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        # 15. KRISHNA JANMASHTAMI (Bhadrapada Krishna Ashtami - 8 days after Shravana Full Moon)
        janmashtami_dt = rakhi_dt + timedelta(days=8)
        festivals.append({
            "festival_name": "Krishna Janmashtami & Dahi Handi",
            "region": "West",
            "category": "Major Religious",
            "start_date": janmashtami_dt.strftime("%Y-%m-%d"),
            "end_date": (janmashtami_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "notes": "Peak sales for butter/makhan, yellow festive apparel, puja accessories, and Krishna jhulas.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 16. GANESH CHATURTHI (Bhadrapada Shukla Chaturthi - 4 days after late Aug/Sept New Moon)
    bhadra_nm = find_nm_near(8, 28) or find_nm_near(9, 10)
    if bhadra_nm:
        ganesh_dt = bhadra_nm + timedelta(days=4)
        festivals.append({
            "festival_name": "Ganesh Chaturthi",
            "region": "West",
            "category": "Major Religious",
            "start_date": ganesh_dt.strftime("%Y-%m-%d"),
            "end_date": (ganesh_dt + timedelta(days=10)).strftime("%Y-%m-%d"),
            "planning_window_days": 25,
            "notes": "10-day celebration in Maharashtra, Karnataka & Telangana. Surge for modaks, clay murtis, brassware, and decor.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 17. ONAM (Thiruvonam in Chingam - typically late August / early September)
    # Aligns near Bhadrapada Shukla constellation
    if bhadra_nm:
        onam_dt = bhadra_nm - timedelta(days=10) if bhadra_nm.month == 9 else bhadra_nm + timedelta(days=5)
        festivals.append({
            "festival_name": "Onam (Thiruvonam)",
            "region": "South",
            "category": "Harvest & Regional",
            "start_date": onam_dt.strftime("%Y-%m-%d"),
            "end_date": (onam_dt + timedelta(days=3)).strftime("%Y-%m-%d"),
            "planning_window_days": 25,
            "notes": "Kerala's largest harvest celebration. Kasavu sarees, Onasadya grocery essentials, gold, and consumer durables.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 18. GANDHI JAYANTI (Fixed Solar - October 2)
    festivals.append({
        "festival_name": "Gandhi Jayanti",
        "region": "Pan-India",
        "category": "Cultural & National",
        "start_date": f"{year}-10-02",
        "end_date": f"{year}-10-02",
        "planning_window_days": 7,
        "notes": "National holiday; Khadi discounts, cooperative exhibitions, and community drives.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # 19. SHARDIYA NAVRATRI, DURGA PUJA & DUSSEHRA (Ashwin Shukla Pratipada to Dashami - Sept/Oct)
    ashwin_nm = find_nm_near(9, 25) or find_nm_near(10, 10)
    if ashwin_nm:
        navratri_start = ashwin_nm + timedelta(days=1)
        durga_puja_start = navratri_start + timedelta(days=5)  # Shasthi
        dussehra_dt = navratri_start + timedelta(days=9)       # Vijayadashami

        festivals.append({
            "festival_name": "Shardiya Navratri & Garba",
            "region": "West",
            "category": "Major Religious",
            "start_date": navratri_start.strftime("%Y-%m-%d"),
            "end_date": (navratri_start + timedelta(days=9)).strftime("%Y-%m-%d"),
            "planning_window_days": 25,
            "notes": "9 nights of Garba/Dandiya in Gujarat & West. Traditional chaniya choli apparel, fasting ingredients, and sound equipment.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        festivals.append({
            "festival_name": "Durga Puja",
            "region": "East",
            "category": "Major Religious",
            "start_date": durga_puja_start.strftime("%Y-%m-%d"),
            "end_date": dussehra_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 30,
            "notes": "Massive cultural festival in West Bengal, Assam, Tripura. New clothing, gifting, feast groceries, and sponsorship commerce.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        festivals.append({
            "festival_name": "Dussehra (Vijayadashami)",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": dussehra_dt.strftime("%Y-%m-%d"),
            "end_date": dussehra_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 20,
            "notes": "Auspicious day for vehicle deliveries, electronics purchases, gold tokens, and sweets.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 20. KARWA CHAUTH (Kartik Krishna Chaturthi - 4 days after Ashwin Full Moon in Oct/Nov)
    oct_fm = find_fm_near(10, 15) or find_fm_near(10, 28)
    if oct_fm:
        karwa_dt = oct_fm + timedelta(days=4)
        festivals.append({
            "festival_name": "Karwa Chauth",
            "region": "North",
            "category": "Major Religious",
            "start_date": karwa_dt.strftime("%Y-%m-%d"),
            "end_date": karwa_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "notes": "Fasting festival; high demand for ethnic red apparel, cosmetics, sargi dry fruit hampers, mehendi, and jewelry.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 21. DIWALI, DHANTERAS & BHAI DOOJ (Kartik Amavasya - late Oct / mid Nov)
    kartik_nm = find_nm_near(10, 25) or find_nm_near(11, 10)
    if kartik_nm:
        diwali_dt = kartik_nm
        dhanteras_dt = diwali_dt - timedelta(days=2)
        bhai_dooj_dt = diwali_dt + timedelta(days=2)

        festivals.append({
            "festival_name": "Diwali & Dhanteras",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": dhanteras_dt.strftime("%Y-%m-%d"),
            "end_date": bhai_dooj_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 35,
            "notes": f"India's biggest retail peak ({year}). Surge across gold, electronics, apparel, sweets, LED lights, diyas, and corporate gifting.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

        # 22. CHHATH PUJA (Kartik Shukla Shashthi - 6 days after Diwali New Moon)
        chhath_dt = diwali_dt + timedelta(days=6)
        festivals.append({
            "festival_name": "Chhath Puja",
            "region": "East",
            "category": "Major Religious",
            "start_date": (chhath_dt - timedelta(days=2)).strftime("%Y-%m-%d"),
            "end_date": (chhath_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            "planning_window_days": 20,
            "notes": "4-day Sun worship in Bihar, UP, and Eastern India. Heavy demand for soop/bamboo baskets, thekua ingredients, sugarcane, and fruits.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 23. GURU NANAK JAYANTI (Kartik Purnima - November Full Moon)
    nov_fm = find_fm_near(11, 15) or find_fm_near(11, 28)
    if nov_fm:
        gurpurab_dt = nov_fm
        festivals.append({
            "festival_name": "Guru Nanak Jayanti (Gurpurab)",
            "region": "North",
            "category": "Major Religious",
            "start_date": gurpurab_dt.strftime("%Y-%m-%d"),
            "end_date": gurpurab_dt.strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "notes": "Sikh celebration; langar supplies, sweets, festive lighting, and devotional books.",
            "is_sample_date": 1,
            "is_verified": 0,
            "year": year
        })

    # 24. CHRISTMAS & YEAR-END HOLIDAY (Fixed Solar - December 24 to 26)
    festivals.append({
        "festival_name": "Christmas",
        "region": "Pan-India",
        "category": "Major Religious",
        "start_date": f"{year}-12-24",
        "end_date": f"{year}-12-26",
        "planning_window_days": 25,
        "notes": "Plum cakes, wine, Christmas trees, fairy lights, secret santa gift hampers, and winter clearance.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": year
    })

    # Sort all generated festivals chronologically
    festivals.sort(key=lambda x: x["start_date"])
    return festivals


def generate_festivals_for_range(start_year: int, end_year: int) -> List[Dict[str, Any]]:
    """
    Generates all Indian festivals for any span of years up to 200 years into the future.
    Example: 2024 to 2226.
    """
    all_fests = []
    for y in range(start_year, end_year + 1):
        all_fests.extend(generate_all_indian_festivals_for_year(y))
    return all_fests
