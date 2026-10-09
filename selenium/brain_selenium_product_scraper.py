"""Scrape one Brain product with Selenium and save it using the Django ORM.

The script repeats the navigation from ``brain_selenium_scraper.py`` and then
performs task steps 5--7.  Every selector used to read the product page is an
XPath selector.
"""

from __future__ import annotations

import random
import sys
import time
from pprint import pprint
from typing import Any
from urllib.parse import urljoin

import undetected_chromedriver as uc
from django.db import DataError
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from load_django import *  # noqa: F401,F403 - configures Django for this script
from parser_app.models import Product


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


BASE_URL = "https://brain.com.ua/"
SEARCH_QUERY = "Apple iPhone 15 128GB Black"
WAIT_SECONDS = 25

XPATH = {
    "search_input": "//input[@type='search' and contains(@class, 'quick-search-input')]",
    "product_link": (
        "//div[contains(@class, 'product-wrapper')]"
        "//a[contains(@href, '-p') and contains(@href, '.html')]"
    ),
    "name": "//h1[contains(@class, 'main-title')]",
    "price": (
        "//div[contains(@class, 'br-pr-price')]"
        "//div[contains(@class, 'br-pr-op')]"
        "//div[contains(@class, 'price-wrapper')]"
    ),
    "sale_price": (
        "//div[contains(@class, 'br-pr-price')]"
        "//div[contains(@class, 'br-pr-np')]"
        "//div[contains(@class, 'price-wrapper')]"
    ),
    "photos": "//div[contains(@class, 'br-pr-slider')]//img[contains(@class, 'br-main-img')]",
    "product_code": "//div[@id='product_code']//span[contains(@class, 'br-pr-code-val')]",
    "reviews_count": "//a[contains(@class, 'reviews-count')]/span",
    "characteristics": "//div[@id='br-characteristics']//div[contains(@class, 'br-pr-chr-item')]/div/div",
}


# Avoid an undetected-chromedriver cleanup issue on some Windows/Python setups.
uc.Chrome.__del__ = lambda self: None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def get_text(driver: uc.Chrome, xpath: str) -> str | None:
    try:
        elements = driver.find_elements(By.XPATH, xpath)
    except (NoSuchElementException, StaleElementReferenceException):
        return None

    # Brain keeps desktop/mobile copies of some blocks. Prefer the visible copy,
    # then fall back to any copy that has text.
    for visible_only in (True, False):
        for element in elements:
            try:
                if visible_only and not element.is_displayed():
                    continue
                value = clean_text(element.text)
                if value:
                    return value
                value = clean_text(element.get_attribute("textContent"))
                if value:
                    return value
            except StaleElementReferenceException:
                continue
    return None


def get_attribute(driver: uc.Chrome, xpath: str, attribute: str) -> str | None:
    try:
        elements = driver.find_elements(By.XPATH, xpath)
    except (NoSuchElementException, StaleElementReferenceException):
        return None

    for visible_only in (True, False):
        for element in elements:
            if visible_only and not element.is_displayed():
                continue
            value = clean_text(element.get_attribute(attribute))
            if value:
                return value
    return None


def parse_reviews_count(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(char for char in value if char.isdigit())
    return int(digits) if digits else None


def first_visible(elements: list[Any]) -> Any | None:
    for element in elements:
        try:
            if element.is_displayed():
                return element
        except StaleElementReferenceException:
            continue
    return None


def get_characteristics(driver: uc.Chrome) -> dict[str, str]:
    characteristics: dict[str, str] = {}

    try:
        cells = driver.find_elements(By.XPATH, XPATH["characteristics"])
    except NoSuchElementException:
        return characteristics

    for cell in cells:
        try:
            label_element = cell.find_element(By.XPATH, ".//span[not(descendant::span) and normalize-space()]")
            label = clean_text(label_element.get_attribute("textContent"))
        except (NoSuchElementException, StaleElementReferenceException):
            continue

        try:
            full_text = clean_text(cell.get_attribute("textContent"))
        except StaleElementReferenceException:
            continue
        value = clean_text(full_text.removeprefix(label)) if full_text and label else None
        if label and value:
            characteristics[label] = value

    return characteristics


def get_photos(driver: uc.Chrome, product_url: str) -> list[str]:
    photos: list[str] = []
    try:
        images = driver.find_elements(By.XPATH, XPATH["photos"])
    except NoSuchElementException:
        return photos

    for image in images:
        try:
            image_url = image.get_attribute("src") or image.get_attribute("data-src")
        except StaleElementReferenceException:
            continue
        if image_url:
            photos.append(urljoin(product_url, image_url))

    return list(dict.fromkeys(photos))


def get_prices(driver: uc.Chrome) -> tuple[str | None, str | None]:
    """Return regular and sale prices without treating every current price as a sale."""
    old_price = get_text(driver, XPATH["price"])
    current_price = get_text(driver, XPATH["sale_price"])

    if old_price:
        return old_price, current_price

    return current_price, None


def collect_product(driver: uc.Chrome) -> dict[str, Any]:
    product_url = driver.current_url
    characteristics = get_characteristics(driver)
    price, sale_price = get_prices(driver)
    data = {
        "name": get_text(driver, XPATH["name"]),
        "color": characteristics.get("Колір"),
        "memory": characteristics.get("Вбудована пам'ять"),
        "manufacturer": characteristics.get("Виробник"),
        "price": price,
        "sale_price": sale_price,
        "photos": get_photos(driver, product_url),
        "product_code": get_text(driver, XPATH["product_code"]),
        "reviews_count": parse_reviews_count(get_text(driver, XPATH["reviews_count"])),
        "screen_diagonal": characteristics.get("Діагональ екрану"),
        "display_resolution": characteristics.get("Роздільна здатність екрану"),
        "characteristics": characteristics or None,
        "link": product_url,
    }
    return data


def load_characteristics(driver: uc.Chrome, wait: WebDriverWait) -> None:
    """Scroll to the section because Brain can load its full content lazily."""
    try:
        container = wait.until(
            EC.presence_of_element_located((By.XPATH, "//div[@id='br-characteristics']"))
        )
    except TimeoutException:
        return

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
    time.sleep(random.uniform(0.8, 1.5))
    wait.until(
        EC.presence_of_all_elements_located((By.XPATH, XPATH["characteristics"]))
    )


def save_product(data: dict[str, Any]) -> Product:
    product, _ = Product.objects.get_or_create(
        link=data["link"], defaults={"status": "New"}
    )
    for field, value in data.items():
        setattr(product, field, value)
    product.status = "Done"
    product.save()
    return product


def open_first_search_result(driver: uc.Chrome, wait: WebDriverWait) -> bool:
    try:
        driver.get(BASE_URL)
    except WebDriverException as error:
        print(f"Unable to open the home page: {error}")
        return False

    search_inputs = wait.until(
        EC.presence_of_all_elements_located((By.XPATH, XPATH["search_input"]))
    )
    search_input = first_visible(search_inputs)
    if search_input is None:
        print("No visible search input found.")
        return False
    try:
        search_input.clear()
        search_input.send_keys(SEARCH_QUERY)
    except (StaleElementReferenceException, WebDriverException) as error:
        print(f"Unable to fill the search input: {error}")
        return False
    time.sleep(random.uniform(0.5, 1.5))
    try:
        search_input.send_keys(Keys.ENTER)
    except (StaleElementReferenceException, WebDriverException) as error:
        print(f"Unable to submit the search query: {error}")
        return False

    product_links = wait.until(
        EC.presence_of_all_elements_located((By.XPATH, XPATH["product_link"]))
    )
    product_link = first_visible(product_links)
    if product_link is None:
        print("No visible product link found.")
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", product_link)
        wait.until(lambda _: product_link.is_enabled())
        product_link.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", product_link)
    except (StaleElementReferenceException, WebDriverException) as error:
        print(f"Unable to open the first product: {error}")
        return False

    wait.until(EC.presence_of_element_located((By.XPATH, XPATH["name"])))
    return True


def main() -> None:
    options = uc.ChromeOptions()
    options.add_argument("--lang=uk-UA")
    driver = uc.Chrome(options=options)
    driver.maximize_window()
    wait = WebDriverWait(driver, WAIT_SECONDS)

    try:
        opened = open_first_search_result(driver, wait)
    except TimeoutException as error:
        print(f"Timed out while locating a required navigation element: {error}")
        opened = False

    if opened:
        time.sleep(random.uniform(1.0, 2.0))
        load_characteristics(driver, wait)
        data = collect_product(driver)
        pprint(data, sort_dicts=False)
        try:
            product = save_product(data)
        except DataError as error:
            print(f"Unable to save product data to the database: {error}")
        else:
            print(f"Saved Product #{product.pk}: {product.link}")

    driver.quit()


if __name__ == "__main__":
    main()
