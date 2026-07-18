from django.urls import path
from . import views

app_name = 'analyzer'

urlpatterns = [
    path('', views.index, name='index'),
    path('analyze/', views.analyze, name='analyze'),
    path('graph/<int:pk>/', views.graph_detail, name='graph_detail'),
    path('history/', views.history, name='history'),
    path('graph/<int:pk>/delete/', views.delete_scan, name='delete_scan'),
]
