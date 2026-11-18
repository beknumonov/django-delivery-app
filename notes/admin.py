from django.contrib import admin

from .models import Note


# Makes notes browsable at /admin/ — handy for inspecting data during the lab.
@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "created_at")  # columns in the list page
    search_fields = ("title", "body")  # adds a search box
