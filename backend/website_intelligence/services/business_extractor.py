import re


def extract_business_name(page):
    """
    Try to determine the website/business name
    from the page title.
    """

    title = page.title or ""

    if "|" in title:
        return title.split("|")[-1].strip()

    return title.strip()


def extract_emails(content):
    """
    Extract email addresses from page content.
    """

    pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"

    return list(set(re.findall(pattern, content)))


def extract_phone_numbers(content):
    """
    Extract possible phone numbers.
    """

    pattern = r"(?:\+?\d[\d\s().-]{7,}\d)"

    return list(set(re.findall(pattern, content)))


def extract_business_data(page):
    """
    Extract generic information from a crawled webpage.
    """

    content = page.content or ""

    return {
        "url": page.url,
        "business_name": extract_business_name(page),
        "title": page.title or "",
        "description": page.description or "",
        "headings": page.headings or [],
        "emails": extract_emails(content),
        "phone_numbers": extract_phone_numbers(content),
        "content": content,
    }