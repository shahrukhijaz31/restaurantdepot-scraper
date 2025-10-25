"""
Product Page Scraper - Syncs detailed product information

This script reads product URLs from the database, scrapes each product page
for detailed information, and updates the database with all product data.
It includes caching to avoid re-fetching unchanged pages.

Requirements:
    - Playwright
    - MySQL database with products table
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

# Cache expiration in hours (products older than this will be re-scraped)
CACHE_EXPIRATION_HOURS = 24


# ===========================
# Product Page Scraper Class
# ===========================

class ProductPageScraper:
    """
    Scraper for individual product pages with caching support.
    """

    def __init__(self):
        """Initialize the scraper."""
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        # MySQL connection
        self.conn = None
        self.cursor = None

        # Statistics
        self.total_products = 0
        self.scraped_count = 0
        self.updated_count = 0
        self.inserted_count = 0
        self.failed_count = 0
        self.skipped_count = 0  # Products that were up-to-date (not re-scraped)

    def initialize_browser(self):
        """Initialize Playwright and browser."""
        print("Initializing Playwright and browser...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        self.context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.page = self.context.new_page()
        print("Browser initialized successfully.")

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

    def check_session_expired(self):
        """Check if the session has expired."""
        try:
            sleep(2)
            current_url = self.page.url
            if "login.restaurantdepot.com" in current_url:
                return True

            oauth_indicators = ["oauth2", "/authorize", "sso/auth", "b2c_1a_verifymember"]
            if any(indicator in current_url.lower() for indicator in oauth_indicators):
                return True

            page_content = self.page.content(timeout=5000)
            sign_in_texts = ["sign in with your email", "sign in to your account", "enter your email"]
            if any(text in page_content.lower() for text in sign_in_texts):
                return True

            return False
        except Exception:
            return False

    def perform_login(self):
        """Perform login."""
        print("Performing login...")
        try:
            self.page.goto(
                'https://member.restaurantdepot.com/rest/sso/auth/restaurantdepot/init?'
                'return_to=https%3A%2F%2Fwww.restaurantdepot.com%2F'
            )
            self.page.wait_for_load_state('networkidle', timeout=60000)
            self.page.locator('input#email').fill(LOGIN_EMAIL)
            sleep(1)
            self.page.locator('input#password').fill(LOGIN_PASSWORD)
            sleep(2)
            self.page.locator('button[type="submit"]').click()

            # Wait for OAuth redirect to complete
            self.page.wait_for_url(
                lambda url: "restaurantdepot.com" in url and "login.restaurantdepot.com" not in url,
                timeout=60000
            )
            sleep(2)

            print("Login successful.")
            return True
        except Exception as e:
            print(f"Login failed: {e}")
            return False


    def scrape_product(self, url, category_name):
        """Scrape a single product page."""
        print(f"Scraping: {url}")

        try:
            
            # Navigate to product page
            self.page.goto(url, timeout=60000)
            sleep(2)

            # Check if session expired
            if self.check_session_expired():
                print("  Session expired, re-logging in...")
                if not self.perform_login():
                    print(f"  Login failed, skipping product")
                    return None
                self.page.goto(url, timeout=60000)
                sleep(2)

            # Extract product data
            title_el = self.page.locator("div#item_details h1 span").first
            title = title_el.text_content(timeout=5000).strip() if title_el.count() > 0 else None

            if not title:
                print(f"  Could not find title for {url}, skipping.")
                return None

            # Extract brand name from JSON-LD structured data
            brand_name = None
            try:
                json_ld_text = self.page.evaluate('''
                    () => {
                        const script = document.querySelector('script[type="application/ld+json"]');
                        return script ? script.textContent : null;
                    }
                ''')

                if json_ld_text:
                    # Parse the JSON string
                    import json as json_lib
                    data = json_lib.loads(json_ld_text)

                    brand_name = data.get("@graph", "")[0].get("brand", "").get("name", "")
                    availability =  data.get("@graph", "")[0].get("offers", "").get("availability", "")
                    if "InStock" in availability:
                        availability = 1
                    else:
                        availability = 0
                        
                    print(f"Brand name extracted: {brand_name}")
                    
                else:
                    print("  Could not find JSON-LD script tag")
            except Exception as e:
                print(f"  Error extracting brand from JSON-LD: {e}")
                # Fallback: extract from title
                brand_name = title.split("-", 1)[0].strip() if title and "-" in title else None

            def get_text_after_colon(label):
                try:
                    # Use XPath to find text containing the label
                    xpath = f"//*[contains(text(), '{label}:')]"
                    result = self.page.evaluate(f'''
                        () => {{
                            const element = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            return element ? element.textContent : null;
                        }}
                    ''')

                    if result and f"{label}:" in result:
                        # Split by the label and get the part after it
                        parts = result.split(f"{label}:")
                        if len(parts) > 1:
                            return parts[1].strip()
                    return None
                except Exception as e:
                    print(f"  Error extracting {label}: {e}")
                    return None

            item_code = get_text_after_colon("Item")
            upc_code = get_text_after_colon("UPC")

            # Extract bin_code (e.g., "Bin - 7044" -> "7044")
            bin_code = None
            try:
                # Use XPath to find text containing "Bin -"
                xpath = "//*[contains(text(), 'Bin -')]"
                bin_text = self.page.evaluate(f'''
                    () => {{
                        const element = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        return element ? element.textContent : null;
                    }}
                ''')

                if bin_text and "Bin -" in bin_text:
                    # Split by "Bin -" and get the part after it, then strip
                    parts = bin_text.split("Bin -")
                    if len(parts) > 1:
                        bin_code = parts[1].strip()
                        print(f"  Bin code extracted: {bin_code}")
            except Exception as e:
                print(f"  Error extracting bin code: {e}")

            # Extract unit_price (Single price) using XPath
            single_price = None
            try:
                # Use XPath to find text containing "Current price:"
                xpath = "//*[contains(text(), 'Current price:')]"
                price_text = self.page.evaluate(f'''
                    () => {{
                        const element = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        return element ? element.textContent : null;
                    }}
                ''')

                if price_text and "Current price:" in price_text:
                    # Split by "Current price:" and get [1], then strip
                    parts = price_text.split("Current price:")
                    if len(parts) > 1:
                        single_price = parts[1].strip()
                        print(f"  Single price extracted: {single_price}")
            except Exception as e:
                print(f"  Error extracting single price: {e}")
            # Extract case_price, discounted_case_price and case info using XPath
            case_price = None
            discounted_case_price = None
            case_unit = None
            case_size = None

            try:
                # Use JavaScript to find the parent div containing "Case of" and extract sibling spans
                case_data = self.page.evaluate('''
                    () => {
                        // Find all divs that contain "Case of" text
                        const divs = Array.from(document.querySelectorAll('div'));
                        const caseDiv = divs.find(div =>
                            div.textContent.trim().startsWith('Case of') &&
                            div.children.length === 0
                        );

                        if (!caseDiv) return null;

                        // Extract the "Case of X" text to get the size number
                        const caseText = caseDiv.textContent.trim();

                        // Get the parent div
                        const parentDiv = caseDiv.parentElement;
                        if (!parentDiv) return null;

                        // Extract all span elements that are direct children of the parent
                        const spans = Array.from(parentDiv.querySelectorAll('span'));

                        return {
                            caseText: caseText,
                            firstSpan: spans[0] ? spans[0].textContent.trim() : null,
                            secondSpan: spans[1] ? spans[1].textContent.trim() : null,
                            totalSpans: spans.length
                        };
                    }
                ''')

                if case_data:
                    case_text = case_data.get('caseText', '')

                    # Extract case size from "Case of X" text (extract just the number)
                    if "Case of" in case_text:
                        # Split by "Case of" and get the number part
                        parts = case_text.replace("Case of", "").strip()
                        case_size = parts
                        case_unit = parts  # Same value
                        print(f"  Case size extracted: {case_size}")

                    # First span is current case price
                    if case_data.get('firstSpan'):
                        case_price = case_data['firstSpan']
                        print(f"  Case price extracted: {case_price}")

                    # Second span is discounted case price
                    if case_data.get('secondSpan'):
                        discounted_case_price = case_data['secondSpan']
                        print(f"  Discounted case price extracted: {discounted_case_price}")

                    print(f"  Total spans found: {case_data.get('totalSpans', 0)}")

            except Exception as e:
                print(f"  Error extracting case info: {e}")

            # Extract availability
            # availability = None
            # try:
            #     # Check if product is in stock
            #     stock_el = self.page.locator("button:has-text('Add to Cart'), button:has-text('Add')").first
            #     if stock_el.count() > 0:
            #         availability = "In Stock"
            #     else:
            #         availability = "Out of Stock"
            # except:
            #     availability = "Unknown"

            # Extract offer_info / sale_flag / product_percentage
            offer_info = None
            sale_flag = 0
            product_percentage = None
            try:
                # Look for sale/offer indicators
                sale_el = self.page.locator("div:has-text('Sale'), span:has-text('Save'), div:has-text('%')").first
                if sale_el.count() > 0:
                    sale_flag = 1
                    offer_info = sale_el.text_content(timeout=1000).strip()
                    # Try to extract percentage if present
                    if "%" in offer_info:
                        import re
                        percentage_match = re.search(r'(\d+)%', offer_info)
                        if percentage_match:
                            product_percentage = percentage_match.group(1)
            except:
                pass

            # Extract image URL
            img_url = None
            img_name = None
            try:
                img_el = self.page.locator("div#item_details img, img[alt*='product'], img.product-image").first
                if img_el.count() > 0:
                    img_url = img_el.get_attribute("src")
                    if img_url:
                        # Extract image filename from URL
                        img_name = img_url.split("/")[-1].split("?")[0]
            except:
                pass

            product_data = {
                'url': url,
                'category': category_name,
                'product_name': title,
                'brand_name': brand_name,
                'product_code': item_code,
                'upc_code': upc_code,
                'bin_code': bin_code,
                'unit_price': single_price,
                'case_price': case_price,
                'discounted_case_price': discounted_case_price,
                'unit_size': case_unit,
                'case_size': case_size,
                'availability': availability,
                'offer_info': offer_info,
                'sale_flag': sale_flag,
                'product_percentage': product_percentage,
                'img_name': img_name,
                'img_url': img_url
            }

            return product_data

        except Exception as e:
            print(f"  Failed to scrape product {url}. Error: {e}")
            return None

    def update_product_in_database(self, product_data):
        """
        Check if product exists in database by URL:
        - If EXISTS: UPDATE all product data (name, brand, prices, etc.)
        - If NOT EXISTS: INSERT new product with all data
        """
        if not self.conn or not self.cursor:
            print("  DB: No database connection available")
            return False

        try:
            # Step 1: Check if product URL already exists in database
            check_sql = "SELECT id, product_name FROM products WHERE url = %s"
            self.cursor.execute(check_sql, (product_data['url'],))
            existing_record = self.cursor.fetchone()

            if existing_record:
                # Product EXISTS in database - UPDATE all fields with new data
                print(f"  DB: Product exists (ID: {existing_record['id']}) - Updating all fields...")

                update_sql = """
                    UPDATE products
                    SET product_name = %s, category = %s, brand_name = %s,
                        product_code = %s, upc_code = %s, bin_code = %s,
                        unit_price = %s, case_price = %s, discounted_case_price = %s,
                        unit_size = %s, case_size = %s, availability = %s, offer_info = %s,
                        sale_flag = %s, product_percentage = %s, img_name = %s,
                        img_url = %s
                    WHERE url = %s
                """
                values = (
                    product_data['product_name'],
                    product_data['category'],
                    product_data['brand_name'],
                    product_data['product_code'],
                    product_data['upc_code'],
                    product_data['bin_code'],
                    product_data['unit_price'],
                    product_data['case_price'],
                    product_data['discounted_case_price'],
                    product_data['unit_size'],
                    product_data['case_size'],
                    product_data['availability'],
                    product_data['offer_info'],
                    product_data['sale_flag'],
                    product_data['product_percentage'],
                    product_data['img_name'],
                    product_data['img_url'],
                    product_data['url']
                )
                self.cursor.execute(update_sql, values)
                self.updated_count += 1
                print(f"  DB: [OK] Updated existing product with all data")

            else:
                # Product NOT EXISTS in database - INSERT new record with all data
                print(f"  DB: Product not found - Inserting new product with all data...")

                insert_sql = """
                    INSERT INTO products (
                        product_name, category, brand_name, product_code, upc_code,
                        bin_code, unit_price, case_price, discounted_case_price, unit_size, case_size,
                        availability, offer_info, sale_flag, product_percentage,
                        img_name, img_url, url
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                values = (
                    product_data['product_name'],
                    product_data['category'],
                    product_data['brand_name'],
                    product_data['product_code'],
                    product_data['upc_code'],
                    product_data['bin_code'],
                    product_data['unit_price'],
                    product_data['case_price'],
                    product_data['discounted_case_price'],
                    product_data['unit_size'],
                    product_data['case_size'],
                    product_data['availability'],
                    product_data['offer_info'],
                    product_data['sale_flag'],
                    product_data['product_percentage'],
                    product_data['img_name'],
                    product_data['img_url'],
                    product_data['url']
                )
                self.cursor.execute(insert_sql, values)
                self.inserted_count += 1
                print(f"  DB: [OK] Inserted new product with all data")

            # Commit the transaction
            self.conn.commit()
            return True

        except pymysql.MySQLError as e:
            print(f"  DB Error: {e}")
            self.conn.rollback()
            return False
        except Exception as e:
            print(f"  Error during DB operation: {e}")
            self.conn.rollback()
            return False

    def get_products_from_database(self):
        """Get all product URLs from database that need to be scraped or updated."""
        if not self.conn or not self.cursor:
            return []

        try:
            # First, check which columns exist in the products table
            self.cursor.execute("SHOW COLUMNS FROM products")
            columns = [col['Field'] for col in self.cursor.fetchall()]
            has_updated_at = 'updated_at' in columns
            has_product_name = 'product_name' in columns

            # Build query based on available columns
            if has_product_name:
                if has_updated_at:
                    select_sql = "SELECT url, category, product_name, updated_at FROM products WHERE url IS NOT NULL"
                else:
                    select_sql = "SELECT url, category, product_name FROM products WHERE url IS NOT NULL"
            else:
                select_sql = "SELECT url, category FROM products WHERE url IS NOT NULL"

            self.cursor.execute(select_sql)
            all_products = self.cursor.fetchall()

            print(f"\nDatabase Check:")
            print(f"  Total products in database: {len(all_products)}")

            # Filter products that need scraping
            products_to_scrape = []

            if has_product_name:
                for product in all_products:
                    # If no product_name, it needs scraping
                    if not product.get('product_name'):
                        products_to_scrape.append(product)
                    # If has updated_at column and it's old (>24 hours), needs refresh
                    elif has_updated_at and product.get('updated_at'):
                        updated_time = product['updated_at']
                        if isinstance(updated_time, str):
                            updated_time = datetime.strptime(updated_time, "%Y-%m-%d %H:%M:%S")
                        age_hours = (datetime.now() - updated_time).total_seconds() / 3600
                        if age_hours > CACHE_EXPIRATION_HOURS:
                            products_to_scrape.append(product)
                    elif not has_updated_at:
                        # No updated_at column, assume it needs refresh if it has been scraped
                        # But if it has product_name, we'll scrape it anyway to be safe
                        products_to_scrape.append(product)
            else:
                # No product_name column, scrape everything
                products_to_scrape = all_products

            print(f"  Products needing scrape/update: {len(products_to_scrape)}")
            print(f"  Products up-to-date: {len(all_products) - len(products_to_scrape)}")

            if not has_updated_at:
                print(f"  [INFO] Run database_schema.sql to add 'updated_at' column for automatic refresh tracking")

            return products_to_scrape
        except Exception as e:
            print(f"Error fetching products from database: {e}")
            import traceback
            traceback.print_exc()
            return []

    def scrape_all_products(self):
        """Main method to scrape all products from database."""
        print("\n" + "=" * 70)
        print("Product Page Scraper - Starting")
        print("=" * 70)
        print("\nHow this works:")
        print("1. Reads product URLs from database")
        print("2. Scrapes each product page for detailed information")
        print("3. For each product:")
        print("   - If URL EXISTS in DB → UPDATE all data (prices, name, etc.)")
        print("   - If URL NOT EXISTS → INSERT new product with all data")
        print("=" * 70)

        # Get products from database
        products = self.get_products_from_database()
        self.total_products = len(products)

        if self.total_products == 0:
            print("\n[WARNING] No products found in database to scrape.")
            print("Run 'python restaurant_depot_scraper.py' first to collect URLs.")
            return

        print(f"\n[SUCCESS] Found {self.total_products} products to process")
        print("Starting product scraping...")

        # Login first
        if not self.perform_login():
            print("Failed to login. Aborting.")
            return

        # Scrape each product
        for idx, product in enumerate(products, 1):
            url = product['url']
            category = product.get('category', 'Unknown')

            print(f"\n[{idx}/{self.total_products}] Category: {category}")

            product_data = self.scrape_product(url, category)

            if product_data:
                if self.update_product_in_database(product_data):
                    self.scraped_count += 1
                else:
                    self.failed_count += 1
            else:
                self.failed_count += 1

        # Print summary
        print("\n" + "=" * 70)
        print("Scraping Complete - Summary")
        print("=" * 70)
        print(f"Total products processed: {self.total_products}")
        print(f"Successfully scraped: {self.scraped_count}")
        print(f"  - Updated existing: {self.updated_count}")
        print(f"  - Inserted new: {self.inserted_count}")
        print(f"Failed: {self.failed_count}")
        print("=" * 70)

    def cleanup(self):
        """Close all connections and resources."""
        print("\n--- Cleaning up resources ---")
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("MySQL connection closed.")

        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        print("Browser closed.")

    def run(self):
        """Main execution method."""
        try:
            self.initialize_browser()
            self.initialize_database()
            self.scrape_all_products()
        except Exception as e:
            print(f"\n!!! A critical error occurred: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()


# ===========================
# Main Entry Point
# ===========================

if __name__ == "__main__":
    scraper = ProductPageScraper()
    scraper.run()
