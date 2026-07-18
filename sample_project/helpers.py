from sample_project.utils import slugify_title


def format_currency(amount):
    return f"${amount:.2f}"


def build_book_url(book_title):
    return f"/books/{slugify_title(book_title)}/"
