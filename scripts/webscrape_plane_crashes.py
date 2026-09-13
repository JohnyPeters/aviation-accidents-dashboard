import requests
from bs4 import BeautifulSoup
import csv
import time
import random
import re

# Base URL and headers
BASE_URL = "https://www.planecrashinfo.com/"
DATABASE_URL = BASE_URL + "database.htm"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/115.0 Safari/537.36")
}

def get_year_links():
    """
    Accesses the main database page and extracts links for each year.
    The links follow the pattern 'YYYY/YYYY.htm'.
    """
    response = requests.get(DATABASE_URL, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    pattern = re.compile(r'(\d{4})/(\1)\.htm')
    year_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if pattern.search(href):
            # Completes the link if it's relative
            full_url = href if href.startswith("http") else BASE_URL + href
            year = a.get_text(strip=True)
            year_links.append((year, full_url))
    return year_links

def parse_detailed_page(url):
    """
    Accesses the details page of an accident and extracts the specified fields.
    Now, locates the table containing the data (data is organized in rows with
    two cells: field and value) and maps them to the desired structure.
    """
    print(f"Accessing details page: {url}")
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Default fields (unknown values)
    details = {
        "Date": "?",
        "Time": "?",
        "Location": "?",
        "Operator": "?",
        "Flight #": "?",
        "Route": "?",
        "AC Type": "?",
        "Registration": "?",
        "cn / ln": "?",
        "Aboard": "?",
        "Fatalities": "?",
        "Ground": "0",
        "Summary": "?"
    }
    
    # Looks for the first table that likely contains the details
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        # Iterates over table rows (ignores header if necessary)
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                # extracts text, including any line breaks
                raw = cells[0].get_text(separator=" ", strip=True)
                # replaces any whitespace sequence (spaces, tabs, \n...) with a single space
                field_text = " ".join(raw.split())
                if field_text.endswith(":"):
                    field_text = field_text[:-1]
                value_text = cells[1].get_text(separator=" ", strip=True)
                if field_text in details:
                    details[field_text] = value_text
    else:
        # Fallback: if table not found, processes the entire text
        detail_text = soup.get_text(separator="\n")
        for line in detail_text.splitlines():
            if ':' in line:
                parts = line.split(":", 1)
                field = parts[0].strip()
                value = parts[1].strip()
                if field in details:
                    details[field] = value
                    
    return details

def parse_year_page(year, url):
    """
    For a year page, extracts each row from the accident table.
    If the date cell has a link to the details page, it accesses it to collect information.
    """
    print(f"Processing data for year: {year}")
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    accidents = []
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        # Skips the header row
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue

            date_cell = cols[0]
            detail_link_tag = date_cell.find("a")
            if detail_link_tag:
                href = detail_link_tag["href"].strip()
                # If the link doesn't contain the year directory, adds it
                if not href.startswith(f"{year}/"):
                    full_link = BASE_URL + f"{year}/{href}"
                else:
                    full_link = href if href.startswith("http") else BASE_URL + href
                try:
                    record = parse_detailed_page(full_link)
                    #print(f"Data extracted from {full_link}: {record}")
                except Exception as e:
                    print(f"Error accessing details at {full_link}: {e}")
                    record = {}
                # If the "Date" field wasn't extracted, sets it from the listing summary
                if record.get("Date", "?") in ["", "?"]:
                    record["Date"] = f"{date_cell.get_text(strip=True)} {year}"
            else:
                # If there's no details link, extracts the summarized data from the listing
                date_str = date_cell.get_text(strip=True)
                loc_op = cols[1].get_text(separator="\n", strip=True).split("\n")
                location = loc_op[0] if len(loc_op) >= 1 else "?"
                operator = loc_op[1] if len(loc_op) >= 2 else "?"
                ac_reg = cols[2].get_text(separator="\n", strip=True).split("\n")
                ac_type = ac_reg[0] if len(ac_reg) >= 1 else "?"
                registration = ac_reg[1] if len(ac_reg) >= 2 else "?"
                fatalities = cols[3].get_text(strip=True)
                record = {
                    "Date": f"{date_str} {year}",
                    "Time": "?",
                    "Location": location,
                    "Operator": operator,
                    "Flight #": "?",
                    "Route": "?",
                    "AC Type": ac_type,
                    "Registration": registration,
                    "cn / ln": "?",
                    "Aboard": "?",
                    "Fatalities": fatalities,
                    "Ground": "0",
                    "Summary": "?"
                }
            accidents.append(record)
            # Delay to mimic human behavior and reduce the risk of being blocked
            time.sleep(random.uniform(1, 3))
    else:
        print(f"Table not found for year {year}.")
    return accidents

def main():
    all_accidents = []
    
    # Extracts year links
    year_links = get_year_links()
    print(f"Found {len(year_links)} year links.")
    
    # Processes each year
    for year, url in year_links:
        accidents = parse_year_page(year, url)
        all_accidents.extend(accidents)
    
    print(f"Found {len(all_accidents)} accidents in total.")
    # Defines CSV headers according to the required structure
    fieldnames = [
        "Date", "Time", "Location", "Operator", "Flight #", "Route",
        "AC Type", "Registration", "cn / ln", "Aboard", "Fatalities",
        "Ground", "Summary"
    ]
    
    output_csv = "data/crashes_data/plane_crash_data.csv"
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in all_accidents:
            writer.writerow(record)
    
    print(f"Detailed data saved to {output_csv}")

if __name__ == "__main__":
    main()