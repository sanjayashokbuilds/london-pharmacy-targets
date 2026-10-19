"""Match pharmacy owners to Companies House and list their current directors.

Uses the Companies House REST API (same key type as UK Funding Radar).
The limit is 600 requests per 5 minutes, so we wait 0.5 s between calls.
"""
import difflib
import time

import requests

from .classify import norm_name

BASE = "https://api.company-information.service.gov.uk"
LINK = "https://find-and-update.company-information.service.gov.uk/company/{}"


class CompaniesHouse:
    def __init__(self, api_key, pause=0.5):
        self.session = requests.Session()
        self.session.auth = (api_key, "")
        self.pause = pause
        self._last = 0.0

    def _get(self, path, params=None):
        for attempt in range(2):
            wait = self.pause - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            r = self.session.get(BASE + path, params=params, timeout=30)
            if r.status_code == 429 and attempt == 0:
                print("Hit the Companies House rate limit; waiting 60 s...")
                time.sleep(60)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        return None

    def match(self, owner_name):
        """Return (company dict, how it matched) or (None, reason).

        Strict on purpose: a wrong match puts the wrong directors on the list.
        Only active companies count (a dissolved company with the same name is
        usually a different, closed business). In order of preference:
          exact   - same name once tidied ('Smith Chemists Ltd' = 'SMITH CHEMISTS')
          prefix  - the only active company whose name starts with the owner name
                    ('Wellcare Pharmacy' -> 'Wellcare Pharmacy (London) Ltd')
          close   - spelling at least 92% similar
        """
        data = self._get("/search/companies", {"q": owner_name, "items_per_page": 20}) or {}
        target = norm_name(owner_name)
        active = [i for i in data.get("items", []) if i.get("company_status") == "active"]

        for item in active:
            if norm_name(item.get("title", "")) == target:
                return item, "exact"

        prefixed = [i for i in active if norm_name(i.get("title", "")).startswith(target + " ")]
        if len(prefixed) == 1:
            return prefixed[0], "prefix"

        best, best_ratio = None, 0.0
        for item in active:
            ratio = difflib.SequenceMatcher(None, norm_name(item.get("title", "")), target).ratio()
            if ratio > best_ratio:
                best, best_ratio = item, ratio
        if best and best_ratio >= 0.92:
            return best, f"close ({best_ratio:.2f})"
        return None, "no confident match (likely a trading name)"

    def directors(self, number):
        data = self._get(f"/company/{number}/officers", {"items_per_page": 100}) or {}
        return [
            o.get("name", "")
            for o in data.get("items", [])
            if o.get("officer_role") == "director" and not o.get("resigned_on")
        ]


def enrich(owners, api_key, top_n):
    """Add Companies House columns to the first `top_n` owners (skipping known customers)."""
    ch = CompaniesHouse(api_key)
    cols = {"company_number": "", "company_status": "", "incorporated": "", "ch_match": "",
            "directors": "", "companies_house_link": ""}
    for c, v in cols.items():
        owners[c] = v

    todo = owners[~owners["possible_existing_customer"]].head(top_n).index
    for i, idx in enumerate(todo, 1):
        name = owners.at[idx, "owner_name"]
        print(f"[{i}/{len(todo)}] Companies House: {name}")
        company, how = ch.match(name)
        owners.at[idx, "ch_match"] = how
        if not company:
            continue
        number = company.get("company_number", "")
        owners.at[idx, "company_number"] = number
        owners.at[idx, "company_status"] = company.get("company_status", "")
        owners.at[idx, "incorporated"] = company.get("date_of_creation", "")
        owners.at[idx, "companies_house_link"] = LINK.format(number)
        owners.at[idx, "directors"] = "; ".join(ch.directors(number))
    return owners
