from django.contrib import admin

from .models import Role, User, UserRole, AuditLogin

admin.site.register(User)
admin.site.register(Role)
admin.site.register(UserRole)
admin.site.register(AuditLogin)
