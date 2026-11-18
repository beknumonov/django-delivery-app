from django.urls import path

from . import views

# The app owns its routes; config/urls.py mounts them under "api/".
# Full paths: /api/notes/ and /api/notes/export/
# name= lets code use reverse("note-list") instead of hard-coding paths.
urlpatterns = [
    path("notes/", views.note_list, name="note-list"),
    path("notes/export/", views.note_export, name="note-export"),
]
