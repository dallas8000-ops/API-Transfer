from django.http import JsonResponse
from django.urls import path


def health(_request) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "api-transfer"})


urlpatterns = [path("", health, name="health")]
