from django.http import JsonResponse
from django.views import View
from sample_project.models import Book, Author, Review
from sample_project.utils import calculate_discount, slugify_title


def book_list(request):
    books = Book.objects.all()
    return JsonResponse({'count': books.count()})


def book_detail(request, book_id):
    book = Book.objects.get(pk=book_id)
    price = _get_book_price(book)
    final_price = calculate_discount(price, 10)
    return JsonResponse({'title': book.title, 'price': final_price, 'slug': slugify_title(book.title)})


def _get_book_price(book):
    return 19.99 if book.is_recent() else 9.99


def author_reviews(request, author_id):
    author = Author.objects.get(pk=author_id)
    return JsonResponse({'author': author.full_profile()})


class ReviewListView(View):
    def get(self, request):
        reviews = Review.objects.all()
        return JsonResponse({'count': reviews.count()})


# Not wired up in urls.py and not called anywhere -> dead code candidate
def deprecated_export_view(request):
    return JsonResponse({'status': 'deprecated'})
