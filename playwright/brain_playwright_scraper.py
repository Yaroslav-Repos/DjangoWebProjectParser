"""Search, scrape, print, and save one Brain product with async Playwright."""

from __future__ import annotations

import asyncio
import random
import sys
from pprint import pprint
from typing import Any
from urllib.parse import urljoin

from asgiref.sync import sync_to_async
from django.db import DataError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from load_django import *  # noqa: F401,F403 - configures Django for this script
from parser_app.models import Product


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


BASE_URL = "https://brain.com.ua/"
SEARCH_QUERY = "Apple iPhone 15 128GB Black"
WAIT_SECONDS = 25_000

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

CHARACTERISTIC_LABELS = {
    "color": "Колір",
    "memory": "Вбудована пам'ять",
    "manufacturer": "Виробник",
    "screen_diagonal": "Діагональ екрану",
    "display_resolution": "Роздільна здатність екрану",
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def parse_reviews_count(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(char for char in value if char.isdigit())
    return int(digits) if digits else None


def xpath_locator(page_or_locator: Page | Locator, xpath: str) -> Locator:
    return page_or_locator.locator(f"xpath={xpath}")


async def first_visible(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        if await candidate.is_visible():
            return candidate
    return None


async def get_text(page: Page, xpath: str) -> str | None:
    try:
        locator = xpath_locator(page, xpath)
        count = await locator.count()
        for visible_only in (True, False):
            for index in range(count):
                element = locator.nth(index)
                if visible_only and not await element.is_visible():
                    continue
                value = clean_text(await element.text_content())
                if value:
                    return value
    except PlaywrightError:
        return None
    return None


async def get_characteristics(page: Page) -> dict[str, str]:
    characteristics: dict[str, str] = {}
    cells = xpath_locator(page, XPATH["characteristics"])
    for index in range(await cells.count()):
        try:
            cell = cells.nth(index)
            label_locator = xpath_locator(
                cell, ".//span[not(descendant::span) and normalize-space()]"
            )
            if await label_locator.count() == 0:
                continue
            label = clean_text(await label_locator.first.text_content())
            full_text = clean_text(await cell.text_content())
        except PlaywrightError:
            continue
        value = clean_text(full_text.removeprefix(label)) if full_text and label else None
        if label and value:
            characteristics[label] = value
    return characteristics


async def get_photos(page: Page, product_url: str) -> list[str]:
    photos: list[str] = []
    images = xpath_locator(page, XPATH["photos"])
    for index in range(await images.count()):
        try:
            image = images.nth(index)
            image_url = await image.get_attribute("src") or await image.get_attribute(
                "data-src"
            )
        except PlaywrightError:
            continue
        if image_url:
            photos.append(urljoin(product_url, image_url))
    return list(dict.fromkeys(photos))


async def get_prices(page: Page) -> tuple[str | None, str | None]:
    """Treat a lone current price as regular, not as a sale price."""
    old_price = await get_text(page, XPATH["price"])
    current_price = await get_text(page, XPATH["sale_price"])
    return (old_price, current_price) if old_price else (current_price, None)


async def collect_product(page: Page) -> dict[str, Any]:
    characteristics = await get_characteristics(page)
    price, sale_price = await get_prices(page)
    product_url = page.url
    return {
        "name": await get_text(page, XPATH["name"]),
        "color": characteristics.get(CHARACTERISTIC_LABELS["color"]),
        "memory": characteristics.get(CHARACTERISTIC_LABELS["memory"]),
        "manufacturer": characteristics.get(CHARACTERISTIC_LABELS["manufacturer"]),
        "price": price,
        "sale_price": sale_price,
        "photos": await get_photos(page, product_url),
        "product_code": await get_text(page, XPATH["product_code"]),
        "reviews_count": parse_reviews_count(await get_text(page, XPATH["reviews_count"])),
        "screen_diagonal": characteristics.get(CHARACTERISTIC_LABELS["screen_diagonal"]),
        "display_resolution": characteristics.get(
            CHARACTERISTIC_LABELS["display_resolution"]
        ),
        "characteristics": characteristics or None,
        "link": product_url,
    }


async def load_characteristics(page: Page) -> bool:
    try:
        container = xpath_locator(page, "//div[@id='br-characteristics']")
        await container.wait_for(state="attached", timeout=WAIT_SECONDS)
        await container.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.8, 1.5))
        await xpath_locator(page, XPATH["characteristics"]).first.wait_for(
            state="attached", timeout=WAIT_SECONDS
        )
    except PlaywrightTimeout:
        print("Timed out while loading the characteristics section.")
        return False
    except PlaywrightError as error:
        print(f"Unable to load the characteristics section: {error}")
        return False
    return True


@sync_to_async
def save_product(data: dict[str, Any]) -> Product:
    """Run Django's synchronous ORM outside the Playwright event loop."""
    product, _ = Product.objects.get_or_create(
        link=data["link"], defaults={"status": "New"}
    )
    for field, value in data.items():
        setattr(product, field, value)
    product.status = "Done"
    product.save()
    return product


async def open_first_search_result(page: Page) -> bool:
    try:
        await page.goto(BASE_URL, timeout=WAIT_SECONDS, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        print("Timed out while opening the home page.")
        return False
    except PlaywrightError as error:
        print(f"Unable to open the home page: {error}")
        return False

    search_inputs = xpath_locator(page, XPATH["search_input"])
    try:
        await search_inputs.first.wait_for(state="attached", timeout=WAIT_SECONDS)
        search_input = await first_visible(search_inputs)
    except PlaywrightTimeout:
        print("Timed out while locating the search input.")
        return False
    except PlaywrightError as error:
        print(f"Unable to locate the search input: {error}")
        return False
    if search_input is None:
        print("No visible search input found.")
        return False
    try:
        await search_input.fill(SEARCH_QUERY)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await search_input.press("Enter")
    except PlaywrightError as error:
        print(f"Unable to submit the search query: {error}")
        return False

    product_links = xpath_locator(page, XPATH["product_link"])
    try:
        await product_links.first.wait_for(state="attached", timeout=WAIT_SECONDS)
        product_link = await first_visible(product_links)
    except PlaywrightTimeout:
        print("Timed out while locating search results.")
        return False
    except PlaywrightError as error:
        print(f"Unable to locate search results: {error}")
        return False
    if product_link is None:
        print("No visible product link found.")
        return False
    try:
        await product_link.scroll_into_view_if_needed()
        await product_link.click()
        await xpath_locator(page, XPATH["name"]).first.wait_for(
            state="attached", timeout=WAIT_SECONDS
        )
    except PlaywrightTimeout:
        print("Timed out while opening the first product.")
        return False
    except PlaywrightError as error:
        print(f"Unable to open the first product: {error}")
        return False
    return True


async def main() -> None:
    async with async_playwright() as playwright:
        context = None
        try:
            browser = await playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except PlaywrightError as error:
            print(f"Unable to launch browser: {error}")
            return

        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1400, "height": 900},
                locale="uk-UA",
                timezone_id="Europe/Kyiv",
            )
        except PlaywrightError as error:
            print(f"Unable to create the browser context: {error}")
            await browser.close()
            return

        try:
            page = await context.new_page()
        except PlaywrightError as error:
            print(f"Unable to create a page: {error}")
            await context.close()
            await browser.close()
            return

        opened = await open_first_search_result(page)
        if opened:
            await load_characteristics(page)
            data = await collect_product(page)
            pprint(data, sort_dicts=False)
            try:
                product = await save_product(data)
            except DataError as error:
                print(f"Unable to save product data to the database: {error}")
            else:
                print(f"Saved Product #{product.pk}: {product.link}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
