from django.urls import path
from studio import views

urlpatterns = [path('', views.index, name='studio'),
               path('api/<str:action>/', views.api, name='api'),
               path('export/', views.export, name='export')]
