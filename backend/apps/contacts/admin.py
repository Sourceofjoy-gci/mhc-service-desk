from django.contrib import admin

from .models import Contact, ContactMethod, Organisation, VerificationToken

admin.site.register(Contact)
admin.site.register(ContactMethod)
admin.site.register(Organisation)
admin.site.register(VerificationToken)
