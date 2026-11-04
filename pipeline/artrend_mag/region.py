"""Edition-region mapping (UN M49 geographic regions, version REGION_VERSION).

KR -> KR, JP -> JP, UN M49 Americas -> AMERICAS, UN M49 Europe -> EUROPE,
everything else (Hong Kong, China, Middle East, Turkey, Cyprus, Caucasus,
Africa, Oceania, ...) -> OTHER. Nothing is forced into the four editions.
"""
from __future__ import annotations

import re
import unicodedata

REGION_VERSION = "UN-M49-2026-10-27"

EUROPE = {
    "AD": "Andorra", "AL": "Albania", "AT": "Austria", "AX": "Åland Islands", "BA": "Bosnia and Herzegovina",
    "BE": "Belgium", "BG": "Bulgaria", "BY": "Belarus", "CH": "Switzerland", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FO": "Faroe Islands", "FR": "France",
    "GB": "United Kingdom", "GG": "Guernsey", "GI": "Gibraltar", "GR": "Greece", "HR": "Croatia", "HU": "Hungary",
    "IE": "Ireland", "IM": "Isle of Man", "IS": "Iceland", "IT": "Italy", "JE": "Jersey", "LI": "Liechtenstein",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro",
    "MK": "North Macedonia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway", "PL": "Poland", "PT": "Portugal",
    "RO": "Romania", "RS": "Serbia", "RU": "Russian Federation", "SE": "Sweden", "SI": "Slovenia",
    "SJ": "Svalbard and Jan Mayen", "SK": "Slovakia", "SM": "San Marino", "UA": "Ukraine", "VA": "Holy See",
}
AMERICAS = {
    "AG": "Antigua and Barbuda", "AI": "Anguilla", "AR": "Argentina", "AW": "Aruba", "BB": "Barbados",
    "BL": "Saint Barthélemy", "BM": "Bermuda", "BO": "Bolivia", "BQ": "Bonaire, Sint Eustatius and Saba",
    "BR": "Brazil", "BS": "Bahamas", "BZ": "Belize", "CA": "Canada", "CL": "Chile", "CO": "Colombia",
    "CR": "Costa Rica", "CU": "Cuba", "CW": "Curaçao", "DM": "Dominica", "DO": "Dominican Republic",
    "EC": "Ecuador", "FK": "Falkland Islands", "GD": "Grenada", "GF": "French Guiana", "GL": "Greenland",
    "GP": "Guadeloupe", "GT": "Guatemala", "GY": "Guyana", "HN": "Honduras", "HT": "Haiti", "JM": "Jamaica",
    "KN": "Saint Kitts and Nevis", "KY": "Cayman Islands", "LC": "Saint Lucia", "MF": "Saint Martin",
    "MQ": "Martinique", "MS": "Montserrat", "MX": "Mexico", "NI": "Nicaragua", "PA": "Panama", "PE": "Peru",
    "PM": "Saint Pierre and Miquelon", "PR": "Puerto Rico", "PY": "Paraguay", "SR": "Suriname", "SV": "El Salvador",
    "SX": "Sint Maarten", "TC": "Turks and Caicos Islands", "TT": "Trinidad and Tobago", "US": "United States",
    "UY": "Uruguay", "VC": "Saint Vincent and the Grenadines", "VE": "Venezuela", "VG": "British Virgin Islands",
    "VI": "U.S. Virgin Islands",
}
ASIA_OTHER = {
    "KR": "Republic of Korea", "JP": "Japan", "CN": "China", "HK": "Hong Kong SAR", "MO": "Macao SAR",
    "TW": "Taiwan", "SG": "Singapore", "TH": "Thailand", "ID": "Indonesia", "PH": "Philippines", "VN": "Viet Nam",
    "MY": "Malaysia", "IN": "India", "AE": "United Arab Emirates", "QA": "Qatar", "SA": "Saudi Arabia",
    "IL": "Israel", "TR": "Türkiye", "CY": "Cyprus", "GE": "Georgia", "AM": "Armenia", "AZ": "Azerbaijan",
    "LB": "Lebanon", "KZ": "Kazakhstan", "UZ": "Uzbekistan", "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka",
    "MN": "Mongolia", "KH": "Cambodia", "MM": "Myanmar", "IR": "Iran", "IQ": "Iraq", "JO": "Jordan", "KW": "Kuwait",
    "BH": "Bahrain", "OM": "Oman", "NP": "Nepal",
}
AFRICA_OCEANIA = {
    "ZA": "South Africa", "NG": "Nigeria", "KE": "Kenya", "GH": "Ghana", "SN": "Senegal", "MA": "Morocco",
    "EG": "Egypt", "TN": "Tunisia", "ET": "Ethiopia", "AU": "Australia", "NZ": "New Zealand",
}


def edition_region(cc: str | None) -> str | None:
    if not cc:
        return None
    cc = cc.upper()
    if cc == "KR":
        return "KR"
    if cc == "JP":
        return "JP"
    if cc in AMERICAS:
        return "AMERICAS"
    if cc in EUROPE:
        return "EUROPE"
    return "OTHER"


def m49_region(cc: str) -> str:
    if cc in EUROPE:
        return "Europe"
    if cc in AMERICAS:
        return "Americas"
    if cc in ASIA_OTHER:
        return "Asia"
    if cc in {"AU", "NZ"}:
        return "Oceania"
    return "Africa"


def all_rows():
    for table in (EUROPE, AMERICAS, ASIA_OTHER, AFRICA_OCEANIA):
        for cc, name in table.items():
            yield cc, name, m49_region(cc), edition_region(cc), REGION_VERSION


# Name -> ISO code for parsing free-text venue lines (lower-case NFC keys).
_NAME_MAP = {
    "korea": "KR", "south korea": "KR", "republic of korea": "KR", "seoul": "KR", "busan": "KR", "gwangju": "KR",
    "대한민국": "KR", "한국": "KR", "서울": "KR", "부산": "KR", "광주": "KR", "과천": "KR", "청주": "KR", "대구": "KR",
    "japan": "JP", "tokyo": "JP", "osaka": "JP", "kyoto": "JP", "yokohama": "JP", "日本": "JP", "東京": "JP",
    "united states": "US", "usa": "US", "u.s.": "US", "new york": "US", "los angeles": "US", "chicago": "US",
    "san francisco": "US", "miami": "US", "canada": "CA", "toronto": "CA", "ottawa": "CA", "mexico": "MX",
    "mexico city": "MX", "ciudad de méxico": "MX", "brazil": "BR", "são paulo": "BR", "sao paulo": "BR",
    "argentina": "AR", "buenos aires": "AR", "chile": "CL", "colombia": "CO", "peru": "PE",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB", "london": "GB", "liverpool": "GB",
    "st ives": "GB", "france": "FR", "paris": "FR", "metz": "FR", "germany": "DE", "berlin": "DE",
    "italy": "IT", "venice": "IT", "venezia": "IT", "milan": "IT", "spain": "ES", "madrid": "ES",
    "netherlands": "NL", "amsterdam": "NL", "switzerland": "CH", "basel": "CH", "zurich": "CH", "zürich": "CH",
    "geneva": "CH", "belgium": "BE", "brussels": "BE", "austria": "AT", "vienna": "AT", "monaco": "MC",
    "hong kong": "HK", "china": "CN", "shanghai": "CN", "beijing": "CN", "taiwan": "TW", "taipei": "TW",
    "singapore": "SG", "abu dhabi": "AE", "dubai": "AE", "united arab emirates": "AE", "qatar": "QA",
    "doha": "QA", "saudi arabia": "SA", "riyadh": "SA", "australia": "AU", "sydney": "AU",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").strip().lower())


def country_from_text(text: str | None) -> str | None:
    if not text:
        return None
    t = norm(text)
    if t in _NAME_MAP:
        return _NAME_MAP[t]
    # last comma-separated token is usually the country or city
    for part in reversed([p.strip() for p in t.split(",")]):
        if part in _NAME_MAP:
            return _NAME_MAP[part]
    return None
