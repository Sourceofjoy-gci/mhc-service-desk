from django.contrib import admin

from .models import KnowledgeArticle, KnowledgeUsageLog

admin.site.register(KnowledgeArticle)
admin.site.register(KnowledgeUsageLog)
