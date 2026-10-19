"""Turn monthly NHS dispensing files into a ranked list of London pharmacy owners."""
import re

import pandas as pd

from .classify import london_mask, norm_name, owners_table
from .columns import ColumnError, detect_columns


def read_csv(path):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Couldn't read {path}")


SKIP = re.compile(r"%|\b(PER|PERCENT|PERCENTAGE|AVERAGE|COST|COSTS|FEE|FEES|PAYMENT|PAYMENTS|RATE)\b")


def pick_items_rows(raw, long_cols, items_content=None):
    """In the long-format file, keep only the rows that hold the total items count.

    Picks the CONTENT label automatically when exactly one label looks like a
    total items count; otherwise stops and lists the options with their England
    totals so the right one can be chosen with --items-content.
    """
    content, group, value = long_cols["content"], long_cols["group"], long_cols["value"]
    labels = raw[content].fillna("").str.strip()

    if items_content:
        chosen = items_content
    else:
        candidates = sorted(
            l for l in labels.unique()
            if "ITEM" in l.upper() and not SKIP.search(l.upper())
        )
        totals = [c for c in candidates if "TOTAL" in c.upper()]
        plain = [c for c in candidates if c.upper() in ("ITEMS", "NUMBER OF ITEMS", "TOTAL ITEMS")]
        if len(plain) == 1:
            chosen = plain[0]  # the real NHS file uses "Items" (Prescription Count group)
        elif len(candidates) == 1:
            chosen = candidates[0]
        elif len(totals) == 1:
            chosen = totals[0]
        else:
            vals = pd.to_numeric(raw[value].astype(str).str.replace(",", ""), errors="coerce")
            summary = (raw.assign(_v=vals, _l=labels)
                       .groupby(([group] if group else []) + ["_l"])["_v"].sum().reset_index())
            lines = "\n  ".join(
                (f"[{r[group]}] " if group else "") + f"{r['_l']}: {r['_v']:,.0f}"
                for _, r in summary.iterrows()
            )
            raise ColumnError(
                "The file has one row per measure, and I couldn't tell which measure is total items.\n"
                f"Measures in the file, with England totals:\n  {lines}\n\n"
                "Paste this message into Claude and it will tell you which --items-content to use."
            )
    picked = raw[labels == chosen]
    if picked.empty:
        raise ColumnError(f"No rows have CONTENT = '{chosen}'. Check the spelling.")
    print(f"Using measure: {chosen}")
    return picked


def standardise(raw, month, overrides=None, items_content=None):
    """Rename one month's columns to our own names and keep only what we need."""
    cols = detect_columns(list(raw.columns), overrides)

    if cols.get("account_type"):
        appliance = raw[cols["account_type"]].fillna("").str.upper().str.contains("APPLIANCE")
        raw = raw[~appliance]  # appliance contractors supply stoma/catheter kit, not pharmacies

    if cols.get("long"):
        raw = pick_items_rows(raw, cols["long"], items_content)
        items_col = cols["long"]["value"]
    else:
        items_col = cols["items"]

    out = pd.DataFrame({
        "month": month,
        "code": raw[cols["code"]].str.strip(),
        "name": raw[cols["name"]].str.strip(),
        "items": pd.to_numeric(raw[items_col].astype(str).str.replace(",", ""), errors="coerce").fillna(0),
    })
    for key in ("postcode", "icb", "hwb"):
        out[key] = raw[cols[key]].str.strip() if cols.get(key) else None
    out["address"] = (
        raw[cols["address"]].fillna("").agg(", ".join, axis=1).str.replace(r"(, )+", ", ", regex=True).str.strip(", ")
        if cols["address"] else ""
    )
    return out, cols


def pharmacies_table(monthly):
    """One row per pharmacy: latest details plus average monthly items."""
    monthly = monthly.copy()
    monthly["is_london"] = london_mask(monthly)
    per_month = monthly.groupby(["code", "month"], as_index=False).agg(
        items=("items", "sum"), name=("name", "first"), postcode=("postcode", "first"),
        address=("address", "first"), is_london=("is_london", "max"),
    )
    latest = per_month.sort_values("month").groupby("code").tail(1).set_index("code")
    avg = per_month.groupby("code")["items"].mean().rename("avg_monthly_items")
    ph = latest.drop(columns=["items", "month"]).join(avg).reset_index()
    ph["name_norm"] = ph["name"].apply(norm_name)
    return ph[ph["name_norm"] != ""]


def build(month_paths, overrides=None, items_content=None):
    frames, used = [], None
    for month, path in month_paths:
        df, cols = standardise(read_csv(path), month, overrides, items_content)
        frames.append(df)
        used = used or cols
    monthly = pd.concat(frames, ignore_index=True)
    pharmacies = pharmacies_table(monthly)
    owners = owners_table(pharmacies)
    return owners, pharmacies, used
