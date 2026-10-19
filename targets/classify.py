"""Decide which pharmacies are in London and who owns how many branches."""
import re

import pandas as pd

LONDON_BOROUGHS = [
    "BARKING AND DAGENHAM", "BARNET", "BEXLEY", "BRENT", "BROMLEY", "CAMDEN", "CITY OF LONDON",
    "CROYDON", "EALING", "ENFIELD", "GREENWICH", "HACKNEY", "HAMMERSMITH AND FULHAM", "HARINGEY",
    "HARROW", "HAVERING", "HILLINGDON", "HOUNSLOW", "ISLINGTON", "KENSINGTON AND CHELSEA",
    "KINGSTON UPON THAMES", "LAMBETH", "LEWISHAM", "MERTON", "NEWHAM", "REDBRIDGE",
    "RICHMOND UPON THAMES", "SOUTHWARK", "SUTTON", "TOWER HAMLETS", "WALTHAM FOREST",
    "WANDSWORTH", "WESTMINSTER",
]

# Postcode areas that sit entirely inside Greater London. Used only if the file
# has no ICB or HWB column; outer areas like BR or HA also cover places outside
# London, so this fallback misses some outer-London pharmacies.
LONDON_POSTCODE_AREAS = {"E", "EC", "N", "NW", "SE", "SW", "W", "WC"}

# Companies shown as StockRx customers on stockrx.uk (checked 19 Oct 2026).
KNOWN_CUSTOMERS = ["SIGNATURE", "BMP HEALTHCARE", "PHARMACY CARE PLUS", "MEDIPILL", "CLICK SOLUTIONS", "AVICENNA"]

LEGAL_SUFFIXES = r"\b(LIMITED|LTD|PLC|LLP|CO|COMPANY|UK)\b"


def norm_name(name):
    """Make owner names comparable: 'J.R. Smith (Chemists) Limited t/a Smiths' -> 'J R SMITH CHEMISTS'."""
    s = str(name or "").upper()
    s = re.split(r"\bT/A\b|\bT\.A\.|\bTRADING AS\b", s)[0]
    s = s.replace("&", " AND ").replace("'", "").replace("’", "")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(LEGAL_SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def group_key(name_norm):
    """Key for grouping branches by owner: ignores spaces, so 'GREEN LIGHT' == 'GREENLIGHT'."""
    return name_norm.replace(" ", "")


# A typical London branch dispenses ~7,500 items a month. Single branches far
# above that are usually online (distance-selling) or hub pharmacies.
HIGH_VOLUME_SINGLE = 25_000


def segment(branches):
    if branches >= 50:
        return "large multiple"
    if branches >= 6:
        return "mid group"
    if branches >= 2:
        return "small group"
    return "single"


def london_mask(df):
    """True for rows in Greater London. Uses ICB, then HWB, then postcode."""
    if "icb" in df and df["icb"].notna().any():
        return df["icb"].fillna("").str.upper().str.contains("LONDON")
    if "hwb" in df and df["hwb"].notna().any():
        hwb = df["hwb"].fillna("").str.upper().str.replace("&", "AND")
        return hwb.apply(lambda v: any(b in v for b in LONDON_BOROUGHS))
    area = df["postcode"].fillna("").str.upper().str.extract(r"^([A-Z]{1,2})\d", expand=False)
    return area.isin(LONDON_POSTCODE_AREAS)


def is_known_customer(name_norm):
    return any(k in name_norm for k in KNOWN_CUSTOMERS)


def owners_table(pharmacies):
    """One row per owner with at least one London branch.

    `pharmacies` has one row per pharmacy (code) with columns:
    code, name, name_norm, postcode, address, is_london, avg_monthly_items.
    """
    pharmacies = pharmacies.assign(key=pharmacies["name_norm"].apply(group_key))
    national = pharmacies.groupby("key")["code"].nunique().rename("national_branches")
    london = pharmacies[pharmacies["is_london"]]

    owners = london.groupby("key").agg(
        name_norm=("name_norm", lambda s: s.mode().iat[0]),
        owner_name=("name", lambda s: s.mode().iat[0]),
        london_branches=("code", "nunique"),
        london_avg_monthly_items=("avg_monthly_items", "sum"),
        branch_postcodes=("postcode", lambda s: ", ".join(sorted(set(s.dropna().astype(str)))[:10])),
        example_address=("address", "first"),
    ).join(national)

    owners["segment"] = owners["national_branches"].apply(segment)
    owners["possible_existing_customer"] = [is_known_customer(n) for n in owners["name_norm"]]
    owners["likely_online_or_hub"] = (
        (owners["london_branches"] == 1) & (owners["london_avg_monthly_items"] > HIGH_VOLUME_SINGLE)
    ) | owners["owner_name"].str.upper().str.contains(r"WWW\.|\.COM|\.CO\.UK|ONLINE", regex=True)
    owners["stockrx_claimed_max_saving_per_month_gbp"] = owners["national_branches"] * 1000
    owners["london_avg_monthly_items"] = owners["london_avg_monthly_items"].round().astype(int)
    owners = owners.reset_index(drop=True)
    return owners.sort_values("london_avg_monthly_items", ascending=False)
