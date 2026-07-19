from django.contrib import admin

from .models import Office, Region, ServiceLocation

admin.site.register(Region)
admin.site.register(Office)
admin.site.register(ServiceLocation)
