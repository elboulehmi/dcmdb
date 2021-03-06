from django.conf.urls import patterns, url

from main import views

urlpatterns = patterns('',
    url(r'^$', views.index, name='index'),
    url(r'^about', views.about, name='about'),
    url(r'^explore', views.explore, name='explore'),
    url(r'^dicom', views.dicom, name='dicom'),
    url(r'^tos', views.tos, name='tos'),
     url(r'^transfer_syntax', views.transfer_syntax, name='transfer_syntax'),
    url(r'^privacy', views.privacy, name='privacy'),
    url(r'^search', views.search, name='search'),
)