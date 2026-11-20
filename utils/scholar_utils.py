# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import warnings
import os
import requests
import threading
import time
from typing import List, Dict, Union, Optional
from thefuzz import fuzz  # type: ignore
import datetime

from dotenv import load_dotenv  # type: ignore

cur_dir = os.path.dirname(os.path.realpath(__file__))
load_dotenv(os.path.join(cur_dir, "../.env"))
S2_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
print(f"Semantic Scholar API key configured: {'yes' if S2_API_KEY else 'no'}")

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,authors,venue,year,abstract,citationCount,journal,publicationDate"
_s2_lock = threading.Lock()
_s2_last_call = [0.0]


def _s2_throttle():
    """Serialises S2 requests to respect the public rate limit."""
    try:
        from utils.settings import get_setting

        interval = float(get_setting("literature.s2_min_interval_sec", 1.1))
    except Exception:
        interval = 1.1
    with _s2_lock:
        wait = _s2_last_call[0] + interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _s2_last_call[0] = time.time()


def _s2_get(params: Dict, timeout: float = 15, max_retries: int = 4):
    headers = {"X-API-KEY": S2_API_KEY} if S2_API_KEY else {}
    for attempt in range(max_retries):
        _s2_throttle()
        try:
            rsp = requests.get(S2_SEARCH_URL, headers=headers, params=params, timeout=timeout)
        except requests.RequestException as exc:
            print(f"      ⚠️ S2 request error: {exc}")
            time.sleep(2 * (attempt + 1))
            continue
        if rsp.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue
        return rsp
    return None


def s2_keyword_search(
    query: str, limit: int = 20, cutoff_date: Optional[str] = None
) -> List[Dict]:
    """Keyword search on Semantic Scholar, filtered by an optional YYYY-MM cutoff."""
    params = {"query": query[:300], "limit": limit, "fields": S2_FIELDS}
    if cutoff_date:
        try:
            params["year"] = f"-{int(cutoff_date.split('-')[0])}"
        except ValueError:
            pass
    rsp = _s2_get(params)
    if rsp is None or rsp.status_code != 200:
        return []
    return [r for r in rsp.json().get("data", []) or [] if r.get("title")]


# --- SEMANTIC SCHOLAR UTILS ---


def s2_title_search(
    title_query: str, year_hint: int = None, cutoff_date: str = None
) -> Optional[Dict]:
    headers = {"X-API-KEY": S2_API_KEY} if S2_API_KEY else {}

    def is_date_valid(p_date, p_year, cutoff_str):
        if not cutoff_str:
            return True
        try:
            c_year, c_month = map(int, cutoff_str.split("-"))
            cutoff_dt = datetime.datetime(c_year, c_month, 1)
            if p_date:
                try:
                    p_dt = datetime.datetime.strptime(p_date, "%Y-%m-%d")
                    return p_dt < cutoff_dt
                except ValueError:
                    pass
            if p_year:
                if p_year < c_year:
                    return True
                if p_year == c_year and c_month > 1:
                    return True
                return False
            return True
        except Exception:
            return True

    try:
        rsp = _s2_get({"query": title_query, "limit": 3, "fields": S2_FIELDS}, timeout=10)
        if rsp is None or rsp.status_code != 200:
            return None
        results = rsp.json().get("data", [])
        if not results:
            return None

        best_match = None
        highest_ratio = 0

        for r in results:
            if not r.get("title"):
                continue
            if not is_date_valid(r.get("publicationDate"), r.get("year"), cutoff_date):
                continue

            ratio = fuzz.ratio(title_query.lower(), r["title"].lower())
            if year_hint and r.get("year") == year_hint:
                ratio += 10

            if ratio > highest_ratio:
                highest_ratio = ratio
                best_match = r

        if highest_ratio > 70:
            return best_match
        return None
    except Exception as e:
        print(f"      ⚠️ S2 Error for '{title_query}': {e}")
        return None
