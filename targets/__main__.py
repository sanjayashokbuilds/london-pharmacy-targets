"""Run with: python -m targets"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .build import build
from .columns import ColumnError
from .download import download_latest


def main():
    p = argparse.ArgumentParser(description="Rank London independent pharmacy owners by NHS dispensing volume.")
    p.add_argument("--months", type=int, default=3, help="how many recent months to average (default 3)")
    p.add_argument("--top", type=int, default=100, help="how many owners to look up on Companies House (default 100)")
    p.add_argument("--no-ch", action="store_true", help="skip Companies House lookups")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="output")
    for field in ("code", "name", "items", "postcode", "icb", "hwb"):
        p.add_argument(f"--{field}-col", help=f"force the CSV column used for {field}")
    p.add_argument("--items-content", help="in the long-format file, the CONTENT label that holds total items")
    a = p.parse_args()

    overrides = {f: getattr(a, f"{f}_col") for f in ("code", "name", "items", "postcode", "icb", "hwb")}
    month_paths = download_latest(a.months, a.data_dir)

    try:
        owners, pharmacies, cols = build(month_paths, overrides, a.items_content)
    except ColumnError as e:
        print(e)
        raise SystemExit(1)

    print("\nColumns used:", {k: v for k, v in cols.items() if v and k != "long"})
    london = pharmacies["is_london"].sum()
    print(f"Pharmacies in England: {len(pharmacies):,}  |  in London: {london:,}")
    print("London owners by size:", owners["segment"].value_counts().to_dict())

    targets = owners[owners["segment"] != "large multiple"].copy()
    print(f"Flagged as likely online or hub pharmacies: {int(targets['likely_online_or_hub'].sum())}")
    if not a.no_ch:
        load_dotenv()
        key = os.getenv("COMPANIES_HOUSE_API_KEY")
        if not key:
            print("No COMPANIES_HOUSE_API_KEY in .env, so skipping Companies House lookups.")
        else:
            from .companies_house import enrich
            targets = enrich(targets, key, a.top)

    targets.insert(0, "rank", range(1, len(targets) + 1))
    out = Path(a.out_dir)
    out.mkdir(exist_ok=True)
    targets.to_csv(out / "london_pharmacy_targets.csv", index=False)
    print(f"\nSaved {len(targets):,} owners to {out / 'london_pharmacy_targets.csv'}")
    print("\nTop 10:")
    print(targets.head(10)[["rank", "owner_name", "segment", "london_branches", "london_avg_monthly_items"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
