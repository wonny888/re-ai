import os
import agentql
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables from local .env file
load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
AGENTQL_API_KEY = os.getenv("AGENTQL_API_KEY")

PROXY_SERVER = os.getenv("PROXY_SERVER")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

if AGENTQL_API_KEY:
    os.environ["AGENTQL_API_KEY"] = AGENTQL_API_KEY

proxy_settings = None
if PROXY_SERVER and PROXY_USERNAME and PROXY_PASSWORD:
    proxy_settings = {
        "server": PROXY_SERVER,
        "username": PROXY_USERNAME,
        "password": PROXY_PASSWORD,
    }

SEARCH_URL = "https://www.realtor.com/realestateandhomes-search/89052"
LOGIN_URL = "https://www.realtor.com/myaccount"

REALTOR_QUERY = """
{
    realtor_search_results {
        listing_cards {
            listing_price
            listing_address
            listing_url
            listing_image
            listing_description
            listing_bedrooms
            listing_bathrooms
            listing_sqft
        }
    }
}
"""

PAGINATION_QUERY = """
{
    realtor_search_results {
        pagination {
            next_page_btn
        }
    }
}
"""


def login(page):
    email_input_query = """
    {
        login_form {
            email_input
            continue_btn
        }
    }
    """

    password_input_query = """
    {
        login_form {
            password_input
            login_btn
        }
    }
    """

    page.goto(LOGIN_URL)
    response = page.query_elements(email_input_query)

    if EMAIL:
        response.login_form.email_input.fill(EMAIL)

    page.wait_for_timeout(1000)
    response.login_form.continue_btn.click()

    password_response = page.query_elements(password_input_query)

    if PASSWORD:
        password_response.login_form.password_input.fill(PASSWORD)

    page.wait_for_timeout(1000)
    password_response.login_form.login_btn.click()
    page.wait_for_page_ready_state()


def send_to_google_sheet(listings, sheet_name="Sheet1"):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    credentials = Credentials.from_service_account_file(
        "credentials.json",
        scopes=scopes,
    )

    gc = gspread.authorize(credentials)
    sh = gc.open("RE")
    worksheet = sh.worksheet(sheet_name)

    header = [
        "Price",
        "Address",
        "Bedrooms",
        "Bathrooms",
        "Sqft",
        "Description",
    ]

    rows = []

    for listing in listings:
        if isinstance(listing, dict):
            rows.append([
                listing.get("listing_price", ""),
                listing.get("listing_address", ""),
                listing.get("listing_bedrooms", ""),
                listing.get("listing_bathrooms", ""),
                listing.get("listing_sqft", ""),
                listing.get("listing_description", ""),
            ])

    worksheet.clear()
    worksheet.append_row(header)

    if rows:
        worksheet.append_rows(rows)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        if not os.path.exists("realtor_login.json"):
            print("No login found, starting login process")

            if proxy_settings:
                context = browser.new_context(proxy=proxy_settings)
            else:
                context = browser.new_context()

            page = agentql.wrap(context.new_page())
            login(page)
            context.storage_state(path="realtor_login.json")
            context.close()

        if proxy_settings:
            context = browser.new_context(
                storage_state="realtor_login.json",
                proxy=proxy_settings,
            )
        else:
            context = browser.new_context(
                storage_state="realtor_login.json"
            )

        page = agentql.wrap(context.new_page())

        try:
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_page_ready_state()
            print(f"Successfully navigated to: {page.url}")
            page.wait_for_timeout(3000)

            if "realestateandhomes-search" not in page.url:
                print(f"Warning: Unexpected page: {page.url}")
                page.goto(SEARCH_URL, timeout=60000)
                page.wait_for_page_ready_state()

        except Exception as e:
            print(f"Error navigating with proxy: {e}")
            context.close()

            context = browser.new_context(
                storage_state="realtor_login.json"
            )

            page = agentql.wrap(context.new_page())
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_page_ready_state()

        all_listings = []

        while True:
            current_url = page.url
            realtor_response = page.query_elements(REALTOR_QUERY)
            realtor_search_results = realtor_response.realtor_search_results
            data = realtor_search_results.to_data()

            if data and "listing_cards" in data:
                listings = data["listing_cards"]

                if isinstance(listings, dict):
                    listings = [listings]
                elif not isinstance(listings, list):
                    listings = [listings]

                print(f"Found {len(listings)} listings")

                for listing in listings:
                    if isinstance(listing, dict):
                        print(f"Price: {listing.get('listing_price', 'N/A')}")
                        print(f"Address: {listing.get('listing_address', 'N/A')}")
                        print(f"Beds: {listing.get('listing_bedrooms', 'N/A')}")
                        print(f"Baths: {listing.get('listing_bathrooms', 'N/A')}")
                        print(f"Sqft: {listing.get('listing_sqft', 'N/A')}")
                        print("-" * 40)
                        all_listings.append(listing)

            else:
                print("No listings found")

            try:
                pagination = page.query_elements(PAGINATION_QUERY)
                next_page_btn = (
                    pagination.realtor_search_results.pagination.next_page_btn
                )
                next_page_btn.click()
                page.wait_for_page_ready_state()

            except Exception:
                print("No more pages or pagination not found")
                break

            if current_url == page.url:
                break

        page.close()

        try:
            send_to_google_sheet(all_listings)
            print("Data successfully sent to Google Sheets!")

        except FileNotFoundError:
            print("credentials.json not found.")
            print("Listings were collected but not sent to Google Sheets.")

        except Exception as e:
            print(f"Google Sheets error: {e}")

        browser.close()


if __name__ == "__main__":
    main()
