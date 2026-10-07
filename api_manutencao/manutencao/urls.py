from django.urls import include, path, re_path
from rest_framework.routers import DefaultRouter

from . import views

# trailing_slash opcional: aceita /api/equipamentos e /api/equipamentos/
router = DefaultRouter(trailing_slash='/?')
router.register('equipamentos', views.EquipamentoViewSet)
router.register('ordens-servico', views.OrdemServicoViewSet)
router.register('defeitos', views.DefeitoViewSet)
router.register('manutencoes-preventivas', views.ManutencaoPreventivaViewSet)
router.register('pecas', views.PecaSubstituidaViewSet)

urlpatterns = [
    re_path(r'^alertas/?$', views.AlertasView.as_view(), name='alertas'),
    path('', include(router.urls)),
]
