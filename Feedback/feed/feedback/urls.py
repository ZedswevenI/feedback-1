from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload, name='upload'),
    path('results/<int:batch_id>/', views.results, name='results'),
    path('results/<int:batch_id>/save-remarks/', views.save_remarks, name='save_remarks'),
    path('report/', views.report, name='report'),
]