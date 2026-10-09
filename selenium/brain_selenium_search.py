import random
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

uc.Chrome.__del__ = lambda self: None

def main():
    options = uc.ChromeOptions()
    
    options.add_argument("--lang=uk-UA")

    driver = uc.Chrome(options=options)

    driver.maximize_window()

    wait = WebDriverWait(driver, 25)

    try:
        driver.get("https://brain.com.ua/")

        search_query = "Apple iPhone 15 128GB Black"
        
        input_xpath = '//input[@type="search" and contains(@class, "quick-search-input")]'
        
        wait.until(EC.presence_of_element_located((By.XPATH, input_xpath)))
        inputs = driver.find_elements(By.XPATH, input_xpath)
        
        search_input = None
        for candidate in inputs:
            if candidate.is_displayed():
                search_input = candidate
                break

        if not search_input:
            raise Exception("Видиме поле пошуку не знайдено на сторінці")

        search_input.clear()
        search_input.send_keys(search_query)
        time.sleep(random.uniform(0.5, 1.5))

        search_input.send_keys(Keys.ENTER)

        product_container_xpath = '//div[contains(@class, "product-wrapper")]'
        wait.until(EC.presence_of_element_located((By.XPATH, product_container_xpath)))

        product_link_xpath = '//div[contains(@class, "product-wrapper")]//a[contains(@href, "-p") and contains(@href, ".html")]'
        wait.until(EC.presence_of_element_located((By.XPATH, product_link_xpath)))
        
        product_links = driver.find_elements(By.XPATH, product_link_xpath)

        first_visible_link = None
        for link in product_links:
            if link.is_displayed():
                first_visible_link = link
                break

        if not first_visible_link:
            raise Exception("Видиме посилання на товар не знайдено в результатах пошуку")

        time.sleep(random.uniform(0.5, 1.0))
        first_visible_link.click()
        
        time.sleep(3)
        print(f"{driver.title}")

    except Exception as e:
        print(f"{e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()