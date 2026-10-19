"""Find the columns we need in the NHSBSA dispensing CSV.

The NHSBSA warns that column headings can change over time, so we don't
hard-code names. We match on keywords instead, and stop with a clear
message if a column is missing or ambiguous. Any column can be forced
with a command-line override (e.g. --items-col "NUMBER_OF_ITEMS").
"""
import re


class ColumnError(Exception):
    pass


def norm(header):
    """'Contractor Name' -> 'CONTRACTOR_NAME'."""
    return re.sub(r"[^A-Z0-9]+", "_", str(header).upper()).strip("_")


# For each field: keyword groups tried in order. A header matches a group
# if its normalised form contains every keyword. "avoid" removes headers
# that contain any of those words. "prefer" breaks ties by exact name.
RULES = {
    "code": {
        "groups": [["CONTRACTOR", "CODE"], ["ACCOUNT", "CODE"], ["ODS", "CODE"], ["PHARMACY", "CODE"]],
        "avoid": ["ICB", "HWB", "LPC", "POST", "REGION", "STP", "CCG"],
        "prefer": ["CONTRACTOR_CODE", "ACCOUNT_CODE"],
    },
    "name": {
        "groups": [["CONTRACTOR", "NAME"], ["ACCOUNT", "NAME"], ["PHARMACY", "NAME"], ["TRADING", "NAME"]],
        "avoid": ["ICB", "HWB", "LPC", "REGION", "STP", "CCG"],
        "prefer": ["CONTRACTOR_NAME", "ACCOUNT_NAME"],
    },
    "postcode": {"groups": [["POST", "CODE"], ["POSTCODE"]], "avoid": [], "prefer": ["POST_CODE", "POSTCODE"]},
    "icb": {"groups": [["ICB", "NAME"]], "avoid": [], "prefer": ["ICB_NAME"]},
    "hwb": {
        "groups": [["HWB", "NAME"], ["HEALTH", "WELLBEING", "NAME"]],
        "avoid": [],
        "prefer": ["HWB_NAME", "HEALTH_AND_WELLBEING_BOARD_NAME"],
    },
    "items": {
        "groups": [["ITEMS"]],
        "avoid": ["PERCENT", "PCT", "PER_"],
        "prefer": ["NUMBER_OF_ITEMS", "TOTAL_ITEMS", "TOTAL_NUMBER_OF_ITEMS", "ITEMS", "NUMBER_OF_ITEMS_DISPENSED"],
    },
    "account_type": {"groups": [["ACCOUNT", "TYPE"]], "avoid": [], "prefer": ["PHARMACY_ACCOUNT_TYPE"]},
}


def long_format_columns(headers):
    """The real NHS file is 'long': one row per pharmacy per measure, with the
    measure's name in CONTENT (grouped by CONTENT_GROUP) and its number in VALUE.
    Returns those column names, or None if the file isn't laid out that way."""
    by_norm = {norm(h): h for h in headers}
    if "CONTENT" in by_norm and "VALUE" in by_norm:
        return {"content": by_norm["CONTENT"], "group": by_norm.get("CONTENT_GROUP"), "value": by_norm["VALUE"]}
    return None

REQUIRED = ["code", "name", "items"]


def _pick(headers, rule):
    """Return (header or None, list of candidates if ambiguous)."""
    for group in rule["groups"]:
        hits = [
            h for h in headers
            if all(k in norm(h) for k in group) and not any(a in norm(h) for a in rule["avoid"])
        ]
        if not hits:
            continue
        if len(hits) == 1:
            return hits[0], []
        for p in rule["prefer"]:
            exact = [h for h in hits if norm(h) == p]
            if len(exact) == 1:
                return exact[0], []
        totals = [h for h in hits if "TOTAL" in norm(h)]
        if len(totals) == 1:
            return totals[0], []
        return None, hits
    return None, []


def detect_columns(headers, overrides=None):
    """Map our field names to the CSV's real headers.

    Returns a dict with keys code, name, items, postcode, icb, hwb
    (location keys may be None) and address (a list, possibly empty).
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    found, problems = {}, []
    found["long"] = long_format_columns(headers) if "items" not in overrides else None

    for field, rule in RULES.items():
        if field in overrides:
            if overrides[field] not in headers:
                problems.append(f"--{field}-col '{overrides[field]}' is not a column in this file")
            found[field] = overrides[field]
            continue
        header, ambiguous = _pick(headers, rule)
        if ambiguous:
            problems.append(f"{field}: several possible columns {ambiguous}; choose one with --{field}-col")
        found[field] = header

    required = [f for f in REQUIRED if not (f == "items" and found["long"])]
    if found["long"]:
        problems = [p for p in problems if not p.startswith("items")]
    for field in required:
        if not found.get(field) and not any(p.startswith(field) for p in problems):
            problems.append(f"{field}: no matching column; set it with --{field}-col")

    if not (found.get("icb") or found.get("hwb") or found.get("postcode")):
        problems.append("location: need an ICB name, HWB name or postcode column to find London pharmacies")

    if problems:
        raise ColumnError(
            "Couldn't work out the columns in the NHS file.\n  - "
            + "\n  - ".join(problems)
            + "\n\nColumns in the file:\n  " + "\n  ".join(map(str, headers))
            + "\n\nPaste this message into Claude and it will tell you which override to use."
        )

    found["address"] = [h for h in headers if "ADDRESS" in norm(h)]
    return found
