"""
Restaurant Depot URL Collector - Playwright Version

This script logs into Restaurant Depot and collects product URLs from various categories.
It uses a headless browser by default and switches to a persistent headed browser when
headless fails. All product URLs are stored in a MySQL database.

For scraping detailed product information, use sync_products_page.py after running this script.

Requirements:
    - Playwright
    - MySQL database
    - Python packages: playwright, pymysql, python-dotenv
"""

import os
from datetime import datetime
from time import sleep

import pymysql
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load environment variables from .env file
load_dotenv()

# ===========================
# Configuration
# ===========================

# Login credentials from environment variables
LOGIN_EMAIL = os.getenv('RD_EMAIL')
LOGIN_PASSWORD = os.getenv('RD_PASSWORD')

# MySQL configuration from environment variables
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))


# ===========================
# Helper Functions
# ===========================

def scroll_to_load_by_pause(page, max_scrolls=60, scroll_pause_time=10.0):
    """
    Scrolls down the page repeatedly, relying on a pause to trigger product loading.
    Also checks for and clicks "Load More" button if found.
    """
    last_height = page.evaluate("document.body.scrollHeight")
    scroll_count = 0
    load_more_clicks = 0

    while scroll_count < max_scrolls:
        # Scroll to bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        sleep(scroll_pause_time)

        # Check for "Load More" button
        try:
            load_more_button = page.locator('button:has-text("Load More")').first
            if load_more_button.is_visible(timeout=2000):
                print(f"  Found 'Load More' button - clicking (click #{load_more_clicks + 1})...")
                load_more_button.click()
                load_more_clicks += 1
                sleep(3)
                # After clicking Load More, continue scrolling
                continue
        except Exception:
            pass  # No Load More button found, continue scrolling

        new_height = page.evaluate("document.body.scrollHeight")

        if new_height == last_height:
            # Check one more time for Load More button before finishing
            try:
                load_more_button = page.locator('button:has-text("Load More")').first
                if load_more_button.is_visible(timeout=2000):
                    print(f"  Found 'Load More' button at end - clicking (click #{load_more_clicks + 1})...")
                    load_more_button.click()
                    load_more_clicks += 1
                    sleep(3)
                    last_height = page.evaluate("document.body.scrollHeight")
                    continue
            except Exception:
                pass

            print(f"Scrolling complete ({scroll_count} scrolls, {load_more_clicks} Load More clicks)")
            break

        last_height = new_height
        scroll_count += 1

    return True


def get_product_hrefs(page):
    """
    Finds and extracts all 'href' attributes from product links using a specific selector.
    """
    product_link_selector = 'div[aria-label="Product"] a'
    product_hrefs = []

    try:
        product_elements = page.locator(product_link_selector).all()

        if not product_elements:
            return []

        for element in product_elements:
            try:
                href = element.get_attribute("href")
                if href:
                    product_hrefs.append(href)
            except:
                continue

        print(f"Found {len(product_hrefs)} product URLs on the current page.")
        return product_hrefs

    except Exception as e:
        print(f"Error extracting links: {e}")
        return []


# ===========================
# Main Scraper Class
# ===========================

class RestaurantDepotScraper:
    """
    Main scraper class for Restaurant Depot products using Playwright.
    """

    def __init__(self):
        """Initialize the scraper with configuration and resources."""
        # Single Playwright instance
        self.playwright = None

        # Headless Playwright instances (for main scraping)
        self.browser = None
        self.context = None
        self.page = None

        # Headed (Visible) Playwright instances (for categories with 48+ products)
        self.headed_browser = None
        self.headed_context = None
        self.headed_page = None
        self.headed_browser_initialized = False

        # Product URL Collection
        self.product_list = []
        self.product_url_to_category = {}

        # Note: Product page scraping has been moved to sync_products_page.py
        # This scraper only collects product URLs and stores them in the database

        # MySQL connection
        self.conn = None
        self.cursor = None

        # Category URL Mapping
        self.category_url_map = {
            "/store/jetro-restaurant-depot/collections/n-soft-drinks-34220": "Soft Drinks",
            "/store/jetro-restaurant-depot/collections/n-sports-drinks-2483": "Sports Drinks",
            "/store/jetro-restaurant-depot/collections/n-coffee-65890": "Coffee",
            "/store/jetro-restaurant-depot/collections/n-water-sparkling-water-75265": "Water & Sparkling Water",
            "/store/jetro-restaurant-depot/collections/n-energy-drinks-53326": "Energy Drinks",
            "/store/jetro-restaurant-depot/collections/n-juice-70697": "Juice",
            "/store/jetro-restaurant-depot/collections/n-milk-88610": "Milk (Beverages)",
            "/store/jetro-restaurant-depot/collections/n-mixers-non-alcoholic-drinks-50769": "Mixers & Non-Alcoholic Drinks",
            "/store/jetro-restaurant-depot/collections/n-tea-23516": "Tea",
            "/store/jetro-restaurant-depot/collections/n-drink-mixes-56668": "Drink Mixes",
            "/store/jetro-restaurant-depot/collections/n-crackers-68019": "Crackers",
            "/store/jetro-restaurant-depot/collections/n-pudding-gelatin-95393": "Pudding & Gelatin",
            "/store/jetro-restaurant-depot/collections/n-cookies-sweet-treats-23040": "Cookies & Sweet Treats",
            "/store/jetro-restaurant-depot/collections/n-chocolate-candy-75864": "Chocolate & Candy",
            "/store/jetro-restaurant-depot/collections/n-nuts-trail-mix-1652": "Nuts & Trail Mix",
            "/store/jetro-restaurant-depot/collections/n-dried-fruit-fruit-snacks-59736": "Dried Fruit & Fruit Snacks",
            "/store/jetro-restaurant-depot/collections/n-chips-84745": "Chips",
            "/store/jetro-restaurant-depot/collections/n-dips-48565": "Dips",
            "/store/jetro-restaurant-depot/collections/n-more-snacks-18223": "More Snacks",
            "/store/jetro-restaurant-depot/collections/n-fruit-cups-applesauce-1152": "Fruit Cups & Applesauce",
            "/store/jetro-restaurant-depot/collections/n-popcorn-pretzels-76579": "Popcorn & Pretzels",
            "/store/jetro-restaurant-depot/collections/n-gum-mints-67920": "Gum & Mints",
            "/store/jetro-restaurant-depot/collections/rc-perishables": "Perishables",
            "/store/jetro-restaurant-depot/collections/n-milk-cream-39826": "Milk & Cream",
            "/store/jetro-restaurant-depot/collections/n-yogurt-88556": "Yogurt",
            "/store/jetro-restaurant-depot/collections/n-cheese-473": "Cheese",
            "/store/jetro-restaurant-depot/collections/n-eggs-23005": "Eggs",
            "/store/jetro-restaurant-depot/collections/n-butter-33226": "Butter",
            "/store/jetro-restaurant-depot/collections/rc-deli-beef": "Deli Beef",
            "/store/jetro-restaurant-depot/collections/rc-deli-ham": "Deli Ham",
            "/store/jetro-restaurant-depot/collections/rc-deli-chicken": "Deli Chicken",
            "/store/jetro-restaurant-depot/collections/rc-other-deli-meats": "Other Deli Meats",
            "/store/jetro-restaurant-depot/collections/rc-dry-groceries": "Dry Groceries (Main)",
            "/store/jetro-restaurant-depot/collections/n-pasta-grains-dried-goods-75634": "Pasta, Grains, & Dried Goods",
            "/store/jetro-restaurant-depot/collections/n-baking-cooking-20184": "Baking & Cooking",
            "/store/jetro-restaurant-depot/collections/n-canned-goods-soups-70578": "Canned Goods & Soups",
            "/store/jetro-restaurant-depot/collections/n-sauces-condiments-48162": "Sauces & Condiments",
            "/store/jetro-restaurant-depot/collections/n-nut-butters-spreads-63843": "Nut Butters & Spreads",
            "/store/jetro-restaurant-depot/collections/rc-smallwares": "Smallwares",
            "/store/jetro-restaurant-depot/collections/rc-sir-lawrence": "Sir Lawrence®",
            "/store/jetro-restaurant-depot/collections/rc-commercial-cooking-equipment": "Commercial Cooking Equipment",
            "/store/jetro-restaurant-depot/collections/rc-clothing-apparel": "Clothing & Apparel",
            "/store/jetro-restaurant-depot/collections/n-chicken-4162": "Chicken",
            "/store/jetro-restaurant-depot/collections/n-beef-37022": "Beef",
            "/store/jetro-restaurant-depot/collections/n-pork-99187": "Pork",
            "/store/jetro-restaurant-depot/collections/n-turkey-83100": "Turkey",
            "/store/jetro-restaurant-depot/collections/n-hot-dogs-sausages-86387": "Hot Dogs & Sausages",
            "/store/jetro-restaurant-depot/collections/n-lamb-80604": "Lamb",
            "/store/jetro-restaurant-depot/collections/n-specialty-meats-21251": "Specialty Meats",
            "/store/jetro-restaurant-depot/collections/n-plant-based-meat-32040": "Plant-Based Meat",
            "/store/jetro-restaurant-depot/collections/n-deli-meats-37573": "Deli Meats (Fresh/Frozen)",
            "/store/jetro-restaurant-depot/collections/n-frozen-meats-43319": "Frozen Meats",
            "/store/jetro-restaurant-depot/collections/rc-fresh-seafood": "Fresh Seafood",
            "/store/jetro-restaurant-depot/collections/rc-frozen-seafood": "Frozen Seafood",
            "/store/jetro-restaurant-depot/collections/n-fresh-fruits-3590": "Fresh Fruits",
            "/store/jetro-restaurant-depot/collections/n-fresh-vegetables-38110": "Fresh Vegetables",
            "/store/jetro-restaurant-depot/collections/n-herbs-39976": "Herbs",
            "/store/jetro-restaurant-depot/collections/rc-frozen-foods": "Frozen Foods (Main)",
            "/store/jetro-restaurant-depot/collections/n-frozen-breads-doughs-90378": "Frozen Breads & Doughs",
            "/store/jetro-restaurant-depot/collections/rc-frozen-fruits": "Frozen Fruits",
            "/store/jetro-restaurant-depot/collections/n-frozen-vegetables-39040": "Frozen Vegetables",
            "/store/jetro-restaurant-depot/collections/n-frozen-desserts-52243": "Ice Cream & Frozen Desserts",
            "/store/jetro-restaurant-depot/collections/n-frozen-appetizers-and-sides-44862": "Frozen Appetizers and Sides",
            "/store/jetro-restaurant-depot/collections/rc-ice": "Ice",
            "/store/jetro-restaurant-depot/collections/n-cleaning-solutions-60665": "Cleaning Solutions",
            "/store/jetro-restaurant-depot/collections/n-laundry-90915": "Laundry",
            "/store/jetro-restaurant-depot/collections/n-trash-bins-bags-64005": "Trash Bins & Bags",
            "/store/jetro-restaurant-depot/collections/n-candles-air-fresheners-83426": "Candles & Air Fresheners",
            "/store/jetro-restaurant-depot/collections/n-cleaning-tools-36366": "Cleaning Tools",
            "/store/jetro-restaurant-depot/collections/n-housewares-75967": "Housewares",
            "/store/jetro-restaurant-depot/collections/n-pest-control-91748": "Pest Control",
            "/store/jetro-restaurant-depot/collections/n-paper-goods-97220": "Paper Goods",
            "/store/jetro-restaurant-depot/collections/n-disposables-14791": "Disposables",
            "/store/jetro-restaurant-depot/collections/rc-retail-groceries-food": "Retail Groceries (Food)",
            "/store/jetro-restaurant-depot/collections/n-retail-groceries-non-food-70588": "Retail Groceries (Non-Food)"

        }

    def initialize_browser(self):
        """Initialize Playwright and the HEADLESS browser."""
        print("Initializing Playwright and HEADLESS browser...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        self.context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.page = self.context.new_page()
        print("HEADLESS browser initialized successfully.")

    def initialize_headed_browser_and_login(self):
        """
        Initialize the HEADED (visible) browser and log in ONCE.
        This browser stays open to be reused for subsequent categories.
        """
        print("    Initializing HEADED browser for the first time...")
        self.headed_browser = self.playwright.chromium.launch(headless=False, args=['--no-sandbox'])
        self.headed_context = self.headed_browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.headed_page = self.headed_context.new_page()

        try:
            print("    Logging in with HEADED browser...")
            self.headed_page.goto(
                'https://member.restaurantdepot.com/rest/sso/auth/restaurantdepot/init?'
                'return_to=https%3A%2F%2Fwww.restaurantdepot.com%2F'
            )
            
            # 1. Wait for the email field to be ready
            self.headed_page.locator('input#email').wait_for(state='visible', timeout=60000)
            print("    Login page loaded, filling credentials...")
            
            self.headed_page.locator('input#email').fill(LOGIN_EMAIL)
            sleep(1)
            self.headed_page.locator('input#password').fill(LOGIN_PASSWORD)
            sleep(2)
            
            print(" Submitting login...")

            # 2. Click to submit
            self.headed_page.locator('button[type="submit"]').click()

            # 3. Wait for OAuth redirect to complete - must land on restaurantdepot.com (not login.restaurantdepot.com)
            print("Waiting for OAuth redirect to complete...")
            self.headed_page.wait_for_url(lambda url: "restaurantdepot.com" in url and "login.restaurantdepot.com" not in url, timeout=60000)
            sleep(3)

            print(f"    Logged in successfully, current URL: {self.headed_page.url}")

            # 4. Dismiss any promotional popups that appear after login
            print("Checking for post-login popups...")
            self.dismiss_post_login_popup(self.headed_page)

            self.headed_browser_initialized = True
            print("SUCCESS: HEADED browser is now logged in and ready for use.")

        except Exception as e:
            print(f"ERROR: Could not initialize or log in with headed browser: {e}")
            self.headed_browser_initialized = False
            
    def dismiss_post_login_popup(self, page_to_use):
        """
        Dismiss any promotional popups that appear after login.
        Looks for "Get Started" button or close buttons.
        """
        try:
            # Try to find "Get Started" button
            get_started_button = page_to_use.locator('button:has-text("Get Started")').first
            if get_started_button.is_visible(timeout=3000):
                print("    Found 'Get Started' popup, clicking to dismiss...")
                get_started_button.click(timeout=3000)
                sleep(2)
                return
        except Exception:
            pass

        try:
            # Try to find generic close button
            close_button = page_to_use.locator('button[aria-label*="close"], button[aria-label*="Close"]').first
            if close_button.is_visible(timeout=2000):
                print("    Found close button, clicking to dismiss popup...")
                close_button.click(timeout=3000)
                sleep(2)
                return
        except Exception:
            pass

        print("    No popup found or already dismissed.")

    def get_links_from_headed_browser(self, category_url, category_name):
        """Use the persistent headed browser to get a complete list of product links."""
        print("    Executing scrape with HEADED browser...")
        if not self.headed_browser_initialized:
            self.initialize_headed_browser_and_login()
            if not self.headed_browser_initialized:
                print("    FATAL: Headed browser could not be initialized. Skipping category.")
                return

        try:
            # Navigate to the category URL
            print(f"    Navigating to category: {category_url}")
            try:
                self.headed_page.goto(category_url, timeout=60000, wait_until="load")
                sleep(4)
            except Exception as e:
                print(f"    Headed navigation failed: {e}")
                print("    Attempting to re-navigate...")
                # The browser is already logged in, so just retry the navigation
                self.headed_page.goto(category_url, timeout=60000, wait_until="load")
                sleep(4)

            # This is the rest of the logic you wanted
            print("    Looking for 'Confirm' button...")
            self.click_confirm_button_if_present(self.headed_page)
            
            print("    Starting scroll logic...")
            if scroll_to_load_by_pause(self.headed_page):
                print("    Scrolling complete. Getting product links...")
                product_hrefs = get_product_hrefs(self.headed_page)
                self.product_list.extend(product_hrefs)
                for href in product_hrefs:
                    self.product_url_to_category[href] = category_name
        except Exception as e:
            print(f"    An error occurred during headed browser scrape: {e}")
    
    def add_urls_to_database(self, urls, category_name):
        """Add product URLs to database after collecting them from a category."""
        if not self.conn or not self.cursor:
            return

        added_count = 0
        skipped_count = 0
        base_url = "https://member.restaurantdepot.com"

        for url in urls:
            try:
                # Ensure URL is complete (prepend base URL if needed)
                if url.startswith('/'):
                    full_url = base_url + url
                elif not url.startswith('http'):
                    full_url = base_url + '/' + url
                else:
                    full_url = url

                # Check if URL already exists
                check_sql = "SELECT id FROM products WHERE url = %s"
                self.cursor.execute(check_sql, (full_url,))
                existing = self.cursor.fetchone()

                if not existing:
                    # URL doesn't exist - insert with minimal info
                    insert_sql = """
                        INSERT INTO products (url, category)
                        VALUES (%s, %s)
                    """
                    self.cursor.execute(insert_sql, (full_url, category_name))
                    added_count += 1
                else:
                    skipped_count += 1

            except Exception as e:
                print(f"  Error adding URL to database: {e}")
                continue

        try:
            self.conn.commit()
            print(f"  DB: Added {added_count} new URLs, skipped {skipped_count} existing URLs")
        except Exception as e:
            print(f"  DB: Error committing URLs: {e}")
            self.conn.rollback()

    def initialize_database(self):
        """Initialize MySQL database connection."""
        try:
            print("Connecting to MySQL database...")
            self.conn = pymysql.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                port=MYSQL_PORT,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.cursor = self.conn.cursor()
            print("MySQL connection established successfully.")
        except pymysql.MySQLError as e:
            print(f"Error connecting to MySQL: {e}")
            self.conn, self.cursor = None, None

    def check_session_expired(self, page):
        """Check if the session has expired on a given page."""
        try:
            sleep(2)
            current_url = page.url
            if "login.restaurantdepot.com" in current_url: return True
            oauth_indicators = ["oauth2", "/authorize", "sso/auth", "b2c_1a_verifymember"]
            if any(indicator in current_url.lower() for indicator in oauth_indicators): return True
            
            page_content = page.content(timeout=5000)
            sign_in_texts = ["sign in with your email", "sign in to your account", "enter your email"]
            if any(text in page_content.lower() for text in sign_in_texts): return True
            
            return False
        except Exception:
            return False

    def perform_login(self, page, browser_type="HEADLESS"):
        """Perform login on a given page instance."""
        print(f"Performing login ({browser_type})...")
        try:
            page.goto(
                'https://member.restaurantdepot.com/rest/sso/auth/restaurantdepot/init?'
                'return_to=https%3A%2F%2Fwww.restaurantdepot.com%2F'
            )
            page.wait_for_load_state('networkidle', timeout=60000)
            page.locator('input#email').fill(LOGIN_EMAIL)
            sleep(1)
            page.locator('input#password').fill(LOGIN_PASSWORD)
            sleep(2)
            page.locator('button[type="submit"]').click()

            # Wait for OAuth redirect to complete - same as headed browser
            page.wait_for_url(lambda url: "restaurantdepot.com" in url and "login.restaurantdepot.com" not in url, timeout=60000)
            sleep(2)

            print(f"Login successful ({browser_type}).")
            return True
        except Exception as e:
            print(f"Login failed ({browser_type}): {e}")
            return False


    def click_confirm_button_if_present(self, page_to_use):
        """
        Try to find and click the 'Confirm' button on a given page.
        It tries an XPath selector first, then a text selector.
        """
        try:
            # Try XPath first
            xpath_button = page_to_use.locator('xpath=//button/span[text()="Confirm"]/..').first
            if xpath_button.is_visible(timeout=1500):
                xpath_button.click(timeout=3000)
                print("Confirm button clicked (XPath).")
                sleep(2)
                return  # Success
        except PlaywrightTimeoutError:
            pass  # Not found, try next method
        except Exception as e:
            print(f"Error checking XPath confirm button: {e}")

        try:
            # Try text selector second
            text_button = page_to_use.locator('button:has-text("Confirm")').first
            if text_button.is_visible(timeout=1500):
                text_button.click(timeout=3000)
                print("Confirm button clicked (Text).")
                sleep(2)
                return  # Success
        except PlaywrightTimeoutError:
            pass  # Not found, just continue
        except Exception as e:
            print(f"Error checking Text confirm button: {e}")

    def collect_product_urls(self):
        """Collect all product URLs, switching to headed browser if headless fails."""
        print("Starting product URL collection...")
        self.perform_login(self.page)
        base_url = "https://member.restaurantdepot.com"

        total_categories = len(self.category_url_map)
        current_category = 0

        for url_path, category_name in self.category_url_map.items():
            current_category += 1
            category_url = base_url + url_path
            print(f"\n[{current_category}/{total_categories}] Processing Category: {category_name}")
            print(f"URL: {category_url}")

            headless_success = False

            try:
                # Try with headless browser first
                try:
                    self.page.goto(category_url, timeout=60000)
                    sleep(4)
                except Exception as e:
                    print(f"  Navigation failed for {category_name}: {e}")
                    print("  Attempting re-login and retry...")
                    self.perform_login(self.page)
                    self.page.goto(category_url, timeout=60000)
                    sleep(4)

                if self.check_session_expired(self.page):
                    print("Headless session expired, re-logging in...")
                    self.perform_login(self.page)
                    self.page.goto(category_url, timeout=60000)
                    sleep(4)

                self.click_confirm_button_if_present(self.page)

                if scroll_to_load_by_pause(self.page):
                    product_hrefs = get_product_hrefs(self.page)
                    product_count = len(product_hrefs)
                    print(f"  Headless browser found {product_count} products.")

                    if product_count > 0:
                        # Headless succeeded
                        print(f"  Headless browser succeeded. Keeping results.")
                        self.product_list.extend(product_hrefs)
                        for href in product_hrefs:
                            self.product_url_to_category[href] = category_name

                        # Add URLs to database
                        self.add_urls_to_database(product_hrefs, category_name)

                        headless_success = True
                    else:
                        print(f"  Headless browser found 0 products - considering this a failure.")

            except Exception as e:
                print(f"  Headless browser failed for {category_name}. Error: {e}")
                headless_success = False

            # If headless failed, switch to headed browser and retry this category
            if not headless_success:
                print(f"  Switching to HEADED browser for {category_name}...")
                try:
                    # Store count before headed browser
                    before_count = len(self.product_list)

                    self.get_links_from_headed_browser(category_url, category_name)
                    print(f"  Headed browser completed for {category_name}")

                    # Get newly added URLs and add to database
                    new_urls = self.product_list[before_count:]
                    if new_urls:
                        self.add_urls_to_database(new_urls, category_name)

                except Exception as e:
                    print(f"  Headed browser also failed for {category_name}: {e}")

            print(f"Total unique URLs collected so far: {len(set(self.product_list))}")
            self.save_product_urls()

        print("URL collection complete.")
        self.product_list = list(set(self.product_list)) # Remove duplicates before scraping
        print(f"Total unique product URLs to scrape: {len(self.product_list)}")

    def save_product_urls(self):
        """Save all collected product URLs to a JSON file."""
        product_urls_file = "product_urls.json"
        unique_urls = list(set(self.product_list))
        product_data = {
            "total_products": len(unique_urls),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "products": [{"url": url, "category": self.product_url_to_category.get(url, "Unknown")} for url in unique_urls]
        }
        try:
            with open(product_urls_file, "w", encoding="utf-8") as f:
                json.dump(product_data, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(unique_urls)} product URLs to {product_urls_file}")
        except Exception as e:
            print(f"Error saving product URLs: {e}")

    def cleanup(self):
        """Close database connections and quit ALL browsers."""
        print("--- Cleaning up resources ---")
        if self.cursor: self.cursor.close()
        if self.conn: self.conn.close()
        print("MySQL connection closed.")

        if self.context: self.context.close()
        if self.browser: self.browser.close()
        print("HEADLESS browser closed.")

        if self.headed_context: self.headed_context.close()
        if self.headed_browser: self.headed_browser.close()
        print("HEADED browser closed.")
        
        if self.playwright: self.playwright.stop()
        print("Playwright instance stopped.")


    def run(self):
        """Main execution method - collects product URLs only."""
        try:
            print("=" * 70)
            print("Restaurant Depot URL Collector - Starting")
            print("=" * 70)
            print("NOTE: This script only collects product URLs.")
            print("To scrape product details, run: python sync_products_page.py")
            print("=" * 70)

            self.initialize_browser()
            self.initialize_database()
            self.collect_product_urls()

            print("\n" + "=" * 70)
            print("URL Collection Completed Successfully")
            print(f"Total Product URLs Collected: {len(self.product_list)}")
            print(f"Unique URLs: {len(set(self.product_list))}")
            print("\nNext step: Run 'python sync_products_page.py' to scrape product details")
            print("=" * 70)

        except Exception as e:
            print(f"\n!!! A critical error occurred during execution: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()


# ===========================
# Main Entry Point
# ===========================

if __name__ == "__main__":
    scraper = RestaurantDepotScraper()
    scraper.run()