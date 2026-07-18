from django.contrib import admin
from .models import Scan


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ('name', 'source_label', 'created_at', 'total_nodes', 'dead_code_count', 'cycle_count')
    readonly_fields = ('result_json',)
