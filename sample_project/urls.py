from django.urls import path
from sample_project import views

urlpatterns = [
    path('books/', views.book_list, name='book-list'),
    path('books/<int:book_id>/', views.book_detail, name='book-detail'),
    path('authors/<int:author_id>/reviews/', views.author_reviews, name='author-reviews'),
    path('reviews/', views.ReviewListView.as_view(), name='review-list'),
]
