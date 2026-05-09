from django.urls import path, include
from rest_framework.routers import DefaultRouter
from modulos.comunicacion_control_inteligencia.viewsets.ia_viewsets import IAViewSet

router = DefaultRouter()
router.register(r'ia', IAViewSet, basename='ia-assistant')

urlpatterns = [
    path('', include(router.urls)),
]
