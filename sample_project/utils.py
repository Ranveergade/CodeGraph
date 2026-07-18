from sample_project.helpers import format_currency


def calculate_discount(price, percent):
    discounted = price - (price * percent / 100)
    return format_currency(discounted)


def slugify_title(title):
    return title.lower().replace(' ', '-')


# Never called by anything -> dead code candidate
def legacy_tax_calculator(price):
    return price * 1.18
