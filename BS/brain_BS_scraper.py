import argparse
import re
import time
from pprint import pprint
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from django.db import DataError
from requests.exceptions import ConnectionError, HTTPError, Timeout, TooManyRedirects

from load_django import *
from parser_app.models import Product


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 20
DEFAULT_DELAY = 1.0

SELECTORS = {
    "name": "h1.main-title",
    "characteristics_container": "#br-characteristics",
    "characteristics": ".br-pr-chr-item > div > div",
    "price": ".br-pr-price .br-pr-op .price-wrapper",
    "sale_price": ".br-pr-price .br-pr-np .price-wrapper",
    "photos": ".br-pr-slider img.br-main-img",
    "product_code": "#product_code .br-pr-code-val",
    "reviews_count": "a.reviews-count > span",
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
    return value if value else None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None

    try:
        digits = "".join(char for char in value if char.isdigit())
    except (TypeError, AttributeError):
        return None

    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def get_characteristic_label(cell: Tag) -> str | None:
    """Find the characteristic label without relying on a DOM position."""
    if not isinstance(cell, Tag):
        return None

    for span in cell.find_all("span"):
        span_text = clean_text(span.get_text(" ", strip=True))
        if not span_text:
            continue

        if len(span.find_all("span")) == 0:
            return span_text

    return None


def extract_cell_pair(cell: Tag) -> tuple[str | None, str | None]:
    """Extract a characteristic name and value from one characteristic cell."""
    if not isinstance(cell, Tag):
        return None, None

    label_node = None

    for span in cell.find_all("span"):
        span_text = clean_text(span.get_text(" ", strip=True))
        if span_text and not span.find("span"):
            label_node = span
            break

    if label_node is None:
        label = get_characteristic_label(cell)
        if label is None:
            return None, None
    else:
        label = clean_text(label_node.get_text(" ", strip=True))

    full_text = clean_text(cell.get_text(" ", strip=True))
    if not full_text or not label:
        return label, None

    if full_text == label:
        return label, None

    value = clean_text(full_text.removeprefix(label))
    if value:
        return label, value

    return label, None


def parse_characteristics(characteristics_container: Tag | None) -> dict[str, str]:
    data: dict[str, str] = {}

    if not isinstance(characteristics_container, Tag):
        return data

    try:
        cells = characteristics_container.select(SELECTORS["characteristics"])
    except (AttributeError, TypeError):
        return data

    for cell in cells:
        try:
            key, value = extract_cell_pair(cell)
        except (AttributeError, TypeError):
            continue

        if key and value:
            data[key] = value

    return data


def find_characteristic(
    characteristics_container: Tag | None,
    label: str,
    parsed_characteristics: dict[str, str],
) -> str | None:
    """Find a characteristic by its label, not by its position in the page."""
    try:
        value = parsed_characteristics.get(label)
    except (AttributeError, TypeError):
        value = None

    if value:
        return value

    if not isinstance(characteristics_container, Tag):
        return None

    try:
        cells = characteristics_container.select(SELECTORS["characteristics"])
    except (AttributeError, TypeError):
        return None

    for cell in cells:
        try:
            label_node = None

            for span in cell.find_all("span"):
                span_text = clean_text(span.get_text(" ", strip=True))
                if span_text == label:
                    label_node = span
                    break

            if label_node is None:
                continue

            sibling = label_node.find_next_sibling()
            if isinstance(sibling, Tag):
                sibling_value = clean_text(sibling.get_text(" ", strip=True))
                if sibling_value:
                    return sibling_value

            _, value = extract_cell_pair(cell)
            return value

        except (AttributeError, TypeError):
            continue

    return None


def extract_price(node: Tag | None) -> str | None:
    """Extract one price from the selected Brain price wrapper."""
    if not isinstance(node, Tag):
        return None

    try:
        text = clean_text(node.get_text(" ", strip=True))
    except (AttributeError, TypeError):
        return None

    if not text:
        return None

    try:
        match = re.search(r"\d[\d\s\u00A0.,]*\s*₴", text)
    except TypeError:
        return None

    return clean_text(match.group(0)) if match else None


def get_prices(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Return regular and sale prices without treating every current price as a sale."""
    try:
        old_price = extract_price(
            soup.select_one(SELECTORS["price"])
        )
        current_price = extract_price(
            soup.select_one(SELECTORS["sale_price"])
        )
    except (AttributeError, TypeError):
        return None, None

    if old_price:
        return old_price, current_price

    return current_price, None


def parse_product_page(url: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    try:
        characteristics_container = soup.select_one(
            SELECTORS["characteristics_container"]
        )
    except (AttributeError, TypeError):
        characteristics_container = None

    try:
        characteristics = parse_characteristics(characteristics_container)
    except (AttributeError, TypeError):
        characteristics = {}

    data: dict[str, Any] = {
        "name": None,
        "manufacturer": None,
        "color": None,
        "memory": None,
        "product_code": None,
        "price": None,
        "sale_price": None,
        "screen_diagonal": None,
        "display_resolution": None,
        "reviews_count": None,
        "photos": [],
        "characteristics": characteristics or None,
        "link": url,
    }

    try:
        title = soup.select_one(SELECTORS["name"])
        if title is not None:
            data["name"] = clean_text(title.get_text(" ", strip=True))
    except (AttributeError, TypeError):
        data["name"] = None

    try:
        data["color"] = find_characteristic(
            characteristics_container,
            CHARACTERISTIC_LABELS["color"],
            characteristics,
        )
    except (AttributeError, TypeError):
        data["color"] = None

    try:
        data["memory"] = find_characteristic(
            characteristics_container,
            CHARACTERISTIC_LABELS["memory"],
            characteristics,
        )
    except (AttributeError, TypeError):
        data["memory"] = None

    try:
        data["manufacturer"] = find_characteristic(
            characteristics_container,
            CHARACTERISTIC_LABELS["manufacturer"],
            characteristics,
        )
    except (AttributeError, TypeError):
        data["manufacturer"] = None

    try:
        data["price"], data["sale_price"] = get_prices(soup)
    except (AttributeError, TypeError):
        data["price"] = None
        data["sale_price"] = None

    try:
        product_code = soup.select_one(SELECTORS["product_code"])
        if product_code is not None:
            data["product_code"] = clean_text(
                product_code.get_text(" ", strip=True)
            )
    except (AttributeError, TypeError):
        data["product_code"] = None

    try:
        reviews = soup.select_one(SELECTORS["reviews_count"])
        if reviews is not None:
            data["reviews_count"] = parse_int(
                clean_text(reviews.get_text(" ", strip=True))
            )
    except (AttributeError, TypeError):
        data["reviews_count"] = None

    try:
        image_nodes = soup.select(SELECTORS["photos"])
    except (AttributeError, TypeError):
        image_nodes = []

    photos: list[str] = []

    for image in image_nodes:
        try:
            image_url = image.get("src") or image.get("data-src")
            if image_url:
                photos.append(urljoin(url, image_url))
        except (AttributeError, TypeError):
            continue

    data["photos"] = list(dict.fromkeys(photos))

    try:
        data["screen_diagonal"] = find_characteristic(
            characteristics_container,
            CHARACTERISTIC_LABELS["screen_diagonal"],
            characteristics,
        )
    except (AttributeError, TypeError):
        data["screen_diagonal"] = None

    try:
        data["display_resolution"] = find_characteristic(
            characteristics_container,
            CHARACTERISTIC_LABELS["display_resolution"],
            characteristics,
        )
    except (AttributeError, TypeError):
        data["display_resolution"] = None

    return data


def get_or_create_product(url: str) -> Product:
    """Get a product by its unique link or create it once."""
    product, _ = Product.objects.get_or_create(
        link=url,
        defaults={"status": "New"},
    )
    return product


def save_product_data(product: Product, data: dict[str, Any]) -> None:
    fields = (
        "name",
        "manufacturer",
        "color",
        "memory",
        "product_code",
        "price",
        "sale_price",
        "screen_diagonal",
        "display_resolution",
        "reviews_count",
        "photos",
        "characteristics",
    )

    for field in fields:
        try:
            setattr(product, field, data.get(field))
        except (AttributeError, TypeError):
            continue

    try:
        product.link = data.get("link") or product.link
    except (AttributeError, TypeError):
        pass

    try:
        product.status = "Done"
    except (AttributeError, TypeError):
        pass

    try:
        product.save()
    except DataError as error:
        raise ValueError(f"Database value is too long or invalid: {error}") from error


def mark_failed(product: Product) -> None:
    try:
        product.status = "Failed"
        product.save(update_fields=["status"])
    except (AttributeError, TypeError):
        pass


def process_product(product: Product, session: requests.Session) -> bool:
    try:
        url = product.link
    except AttributeError:
        return False

    if not url:
        mark_failed(product)
        print("Failed: empty product link")
        return False

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except ConnectionError:
        print(f"Connection error: {url}")
        mark_failed(product)
        return False
    except Timeout:
        print(f"Timeout error: {url}")
        mark_failed(product)
        return False
    except TooManyRedirects:
        print(f"Too many redirects: {url}")
        mark_failed(product)
        return False
    except HTTPError as error:
        print(f"HTTP error: {error}")
        mark_failed(product)
        return False

    if response.status_code != 200:
        print(f"HTTP error {response.status_code}: {url}")
        mark_failed(product)
        return False

    try:
        data = parse_product_page(url, response.text)
    except (AttributeError, TypeError, ValueError) as error:
        print(f"Parsing error: {error}")
        mark_failed(product)
        return False

    pprint(data, sort_dicts=False)

    try:
        save_product_data(product, data)
    except (AttributeError, TypeError, ValueError) as error:
        print(f"Database save error: {error}")
        mark_failed(product)
        return False

    print(f"Done: {url}")
    return True


def process_url(url: str, delay: float = DEFAULT_DELAY) -> bool:
    product = get_or_create_product(url)

    with requests.Session() as session:
        success = process_product(product, session)

    if delay > 0:
        time.sleep(delay)

    return success


def process_new_products(
    limit: int | None = None,
    delay: float = DEFAULT_DELAY,
) -> None:
    queryset = Product.objects.filter(status="New").order_by("id")

    if limit is not None:
        queryset = queryset[:limit]

    with requests.Session() as session:
        for product in queryset:
            process_product(product, session)

            if delay > 0:
                time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brain product scraper for Django + PostgreSQL."
    )

    parser.add_argument(
        "url",
        nargs="?",
        help="Product URL to add to DB and scrape.",
    )

    parser.add_argument(
        "--all-new",
        action="store_true",
        help="Process all Product objects with status=New.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of New objects when --all-new is used.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Delay between requests in seconds.",
    )

    args = parser.parse_args()

    if not args.url and not args.all_new:
        parser.error("Provide a URL or --all-new")

    if args.url and args.all_new:
        parser.error("Use either URL or --all-new, not both.")

    if args.url:
        process_url(args.url, delay=args.delay)

    if args.all_new:
        process_new_products(
            limit=args.limit,
            delay=args.delay,
        )


if __name__ == "__main__":
    main()
