"""Service Catalogue and Request Types Django app."""
from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    name = "apps.catalogue"
    label = "catalogue"
    verbose_name = "Service Catalogue and Request Types"
