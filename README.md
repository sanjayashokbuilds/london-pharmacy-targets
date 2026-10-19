# London Pharmacy Targets

Ranks London's independent pharmacy owners by how much they dispense, using free NHS data, and matches each owner to Companies House.

Built in a day as a sales target list for pharmacy software companies that sell to independents and small groups.

## What it does

1. Downloads the last 3 months of NHSBSA *Pharmacy and appliance contractor dispensing data* (items dispensed by every community pharmacy in England).
2. Keeps pharmacies in Greater London (by ICB, falling back to borough or postcode).
3. Groups branches by owner, so a five-branch group is one target, not five.
4. Drops large multiples (50+ branches in England), flags companies already shown as customers on stockrx.uk, and flags single branches dispensing over 25,000 items a month (about 3x a typical London branch) as likely online or hub pharmacies.
5. Ranks owners by average monthly items across their London branches.
6. Looks up the top 100 on Companies House: company number, status, incorporation date and current directors.

Output: `output/london_pharmacy_targets.csv`.

## Why this method

- **Items dispensed is a proxy for stock spend.** More items means more stock moving, so more value from better stock control.
- **Owner, not branch, is the buyer.** The decision is made once per owner, and savings scale with branches.
- **Averaging 3 months** smooths out one-off busy or quiet months.

## Assumptions and where it breaks

- **Owner = contractor name in the NHS file.** If a group runs branches under different company names, they show up as separate owners.
- **Name tidying is simple.** "Smith Chemists Ltd", "Smith Chemists Limited", "Smith's Chemists" and "Smiths Chemists" merge; genuinely different spellings don't.
- **Items are not revenue.** A branch with many cheap items can rank above one with fewer expensive items.
- **The NHS file gives trading names, not company names**, so many owners get no Companies House match. Matching is deliberately strict (active companies only; exact name, a unique "starts with" match, or 92%+ similar) so a gap is more likely than a wrong match.
- **NHS data is three months behind** and excludes private prescriptions.
- **The savings column is StockRx's own "up to £1,000 per branch per month" claim** times branches, not an estimate of mine.

## How I validated it

- Unit tests on fake data (`pytest`), covering column detection, owner grouping, London filtering and averaging.
- First real run (June 2026 data) found 1,377 London pharmacies outside the big chains, with a median of about 7,500 items per branch per month, in line with the England average. It also exposed three problems, now fixed: the same group split by spacing ("Greenlight" vs "Green Light"), dissolved companies matched by name, and online pharmacies mixed in with high-street ones.
- Spot-check: look up the top 10 owners on the NHS "Find a pharmacy" service and Google Maps to confirm they're real London independents.

## Run it (Mac)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your Companies House REST key into .env
python -m targets
```

The NHS file has one row per measure per pharmacy; the tool uses the "Items" measure (Prescription Count).

Options: `--months 6`, `--top 200`, `--no-ch` (skip Companies House). If the NHS changes its column names, the tool stops and tells you which `--…-col` option to use.

## Data sources

- NHSBSA Open Data Portal: Pharmacy and appliance contractor dispensing data (Open Government Licence).
- Companies House REST API.

The output contains directors' names from the public register. It's kept out of git (`output/` is in `.gitignore`).
