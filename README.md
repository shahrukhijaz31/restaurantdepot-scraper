# Restaurant Depot Scraper - Playwright Edition

A two-stage web scraper for Restaurant Depot that collects product URLs and detailed product information using Playwright and stores data in MySQL.

## Overview

This scraper works in two stages:

1. **Stage 1 - URL Collection** (`restaurant_depot_scraper.py`): Logs in, navigates through all product categories, and collects product URLs
2. **Stage 2 - Product Details** (`sync_products_page.py`): Scrapes detailed information from each product page

## Features

- Dual-browser approach (headless + headed) for maximum reliability
- Automatic session management and re-login on expiration
- Page caching to avoid re-scraping unchanged products
- MySQL database storage with automatic URL deduplication
- Support for 60+ product categories
- Handles dynamic content loading (infinite scroll, "Load More" buttons)
- Extracts comprehensive product data (prices, codes, images, availability, etc.)

## Requirements

- Python 3.8+
- MySQL database
- Playwright
- Chrome/Chromium browser

## Installation

### 1. Clone or download this project

```bash
cd playwright_script
```

### 2. Create and activate virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

## Database Setup

### 1. Create MySQL database

```sql
CREATE DATABASE restaurant_depot;
```

### 2. Create products table

Run the SQL schema from `database_schema.sql`:

```bash
mysql -u your_username -p restaurant_depot < database_schema.sql
```

Or manually execute:

```sql
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_name VARCHAR(500),
    category VARCHAR(255),
    brand_name VARCHAR(255),
    product_code VARCHAR(100),
    upc_code VARCHAR(100),
    bin_code VARCHAR(50),
    unit_price VARCHAR(50),
    case_price VARCHAR(50),
    discounted_case_price VARCHAR(50),
    unit_size VARCHAR(100),
    case_size VARCHAR(100),
    availability TINYINT(1) DEFAULT 1,
    offer_info TEXT,
    sale_flag TINYINT(1) DEFAULT 0,
    product_percentage VARCHAR(10),
    img_name VARCHAR(255),
    img_url TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_product_code (product_code),
    INDEX idx_category (category),
    INDEX idx_brand (brand_name)
);
```

## Configuration

### 1. Create environment file

Copy `.env.example` to `.env`:

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

### 2. Update `.env` with your credentials

Open `.env` and configure your Restaurant Depot and MySQL credentials:

```bash
# Restaurant Depot Login Credentials
RD_EMAIL=your_email@example.com
RD_PASSWORD=your_password_here

# MySQL Database Configuration
MYSQL_HOST=localhost
MYSQL_USER=your_mysql_username
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=restaurant_depot
MYSQL_PORT=3306
```

**⚠️ Security Note**: Never commit the `.env` file to version control. It's already included in `.gitignore` to prevent accidental commits.

## Usage

### Step 1: Collect Product URLs

Run the URL collector script:

```bash
python restaurant_depot_scraper.py
```

This will:
- Log into Restaurant Depot
- Navigate through 60+ product categories
- Collect all product URLs
- Store URLs in the database
- Save a backup to `product_urls.json`

**Estimated time**: 2-4 hours depending on network speed and number of products

### Step 2: Scrape Product Details

After collecting URLs, run the product details scraper:

```bash
python sync_products_page.py
```

This will:
- Read product URLs from the database
- Scrape detailed information for each product
- Update the database with product data
- Skip products that were recently updated (24-hour cache)

**Estimated time**: 4-8 hours depending on number of products

## How It Works

### Stage 1: URL Collection (`restaurant_depot_scraper.py`)

1. **Browser Strategy**:
   - Starts with headless browser for efficiency
   - Automatically switches to headed browser if headless fails
   - Maintains persistent headed browser session to avoid re-login

2. **Category Processing**:
   - Iterates through 60+ predefined category URLs
   - Handles "Confirm" popups and location modals
   - Scrolls page until all products load
   - Clicks "Load More" buttons when present

3. **Data Storage**:
   - Inserts URLs into MySQL `products` table
   - Skips duplicate URLs
   - Saves JSON backup after each category

### Stage 2: Product Details (`sync_products_page.py`)

1. **Smart Caching**:
   - Checks `updated_at` timestamp in database
   - Skips products updated within last 24 hours
   - Only scrapes new products or stale data

2. **Data Extraction**:
   - Product name and brand
   - Product code, UPC code, bin code
   - Unit price and case price
   - Discounted prices (if on sale)
   - Case size and unit size
   - Availability status (from JSON-LD)
   - Product images

3. **Database Updates**:
   - INSERT for new products
   - UPDATE for existing products
   - Automatic timestamp management

## Project Structure

```
playwright_script/
├── restaurant_depot_scraper.py   # Stage 1: URL collector
├── sync_products_page.py          # Stage 2: Product details scraper
├── .env                           # Environment variables (gitignored)
├── .env.example                   # Environment template
├── .gitignore                     # Git ignore rules
├── requirements.txt               # Python dependencies
├── database_schema.sql            # Database schema
├── README.md                      # This file
├── product_urls.json              # Backup of collected URLs
├── PAGE_CACHE/                    # Cached page data (optional)
└── venv/                          # Virtual environment (gitignored)
```

## Extracted Product Fields

| Field | Description | Example |
|-------|-------------|---------|
| `product_name` | Full product title | "Coca-Cola - Classic Coke 12oz Can" |
| `brand_name` | Brand extracted from title or JSON-LD | "Coca-Cola" |
| `category` | Product category | "Soft Drinks" |
| `product_code` | Item code | "1020070" |
| `upc_code` | Universal Product Code | "049000028911" |
| `bin_code` | Warehouse bin location | "7044" |
| `unit_price` | Single unit price | "$1.25" |
| `case_price` | Case price (regular or discounted) | "$29.99" |
| `discounted_case_price` | Original price if on sale | "$34.99" |
| `unit_size` | Units per case | "24" |
| `case_size` | Same as unit_size | "24" |
| `availability` | In stock (1) or out of stock (0) | 1 |
| `offer_info` | Original price when on sale | "$34.99" |
| `sale_flag` | On sale (1) or regular price (0) | 1 |
| `product_percentage` | Discount percentage | "15" |
| `img_url` | Product image URL | "https://..." |
| `img_name` | Image filename | "1020070" |
| `url` | Product page URL | "https://member.restaurantdepot.com/..." |

## Supported Categories

The scraper covers 60+ categories including:

- **Beverages**: Soft Drinks, Coffee, Tea, Juice, Water, Energy Drinks, etc.
- **Snacks**: Chips, Candy, Nuts, Cookies, Crackers, etc.
- **Dairy**: Milk, Cream, Cheese, Butter, Yogurt, Eggs
- **Meats**: Chicken, Beef, Pork, Turkey, Seafood, Deli Meats
- **Produce**: Fresh Fruits, Vegetables, Herbs
- **Frozen**: Frozen Foods, Ice Cream, Breads, Appetizers
- **Dry Goods**: Pasta, Grains, Baking Supplies, Canned Goods
- **Supplies**: Equipment, Paper Goods, Janitorial, Disposables
- **And more...**

## Troubleshooting

### Issue: Login fails repeatedly
**Solution**: Check credentials in script. Ensure your account is active and not locked.

### Issue: Headless browser finds 0 products
**Solution**: This is expected for some categories. The script automatically switches to headed browser.

### Issue: Session expires during scraping
**Solution**: The script automatically detects and re-logs in. No action needed.

### Issue: MySQL connection error
**Solution**:
- Verify `.env` file has correct credentials
- Ensure MySQL service is running
- Check firewall allows connection to MySQL

### Issue: "Product name not found" errors
**Solution**: Website structure may have changed. Product is skipped, not a critical error.

### Issue: Script crashes mid-run
**Solution**:
- Run Stage 1 again - it will skip already collected URLs
- Run Stage 2 again - it will resume from where it stopped

## Performance Tips

1. **Run during off-peak hours**: Website is faster at night
2. **Use stable internet**: Avoid WiFi if possible
3. **Close unnecessary programs**: Browser uses significant RAM
4. **Monitor first run**: Watch for errors in first few categories
5. **Resume capability**: Both scripts can be safely restarted

## Cache Expiration

Products are considered "stale" after 24 hours. To change cache duration:

Edit `sync_products_page.py`:
```python
CACHE_EXPIRATION_HOURS = 24  # Change to desired hours
```

## Output Files

- **MySQL Database**: Primary storage for all product data
- **product_urls.json**: Backup of collected URLs with metadata
- **PAGE_CACHE/**: Optional cached page responses (helps debugging)

## Security Recommendations

1. **Never commit `.env` file** to version control (already in `.gitignore`)
2. **Keep `.env.example` updated** as a template without real credentials
3. **Use different credentials** for development and production environments
4. **Rotate credentials** periodically
5. **Limit database user permissions** to only what's needed
6. **Set appropriate file permissions** on `.env` file:
   ```bash
   # Linux/Mac
   chmod 600 .env
   ```

## Legal & Ethical Considerations

- Ensure you have permission to scrape this website
- Respect robots.txt and rate limits
- Use scraped data in accordance with website's Terms of Service
- This tool is for educational/business intelligence purposes only

## Support & Maintenance

### Updating Category List

To add/modify categories, edit the `category_url_map` in `restaurant_depot_scraper.py`:

```python
self.category_url_map = {
    "/store/jetro-restaurant-depot/collections/new-category": "New Category Name",
    # ... more categories
}
```

### Debugging

Enable verbose logging by adding print statements or use Python's logging module.

Check PAGE_CACHE directory for cached responses to inspect HTML structure.

## License

This project is provided as-is for educational purposes.

## Contact

For questions or issues, please contact the development team.

---

**Last Updated**: October 2025
**Version**: 2.0 (Playwright Edition)
