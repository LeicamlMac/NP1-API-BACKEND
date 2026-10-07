from django.contrib import admin

from .models import Defeito, Equipamento, ManutencaoPreventiva, OrdemServico, PecaSubstituida


class PecaInline(admin.TabularInline):
    model = PecaSubstituida
    extra = 0


@admin.register(Equipamento)
class EquipamentoAdmin(admin.ModelAdmin):
    list_display = ['id', 'nome', 'modelo', 'fabricante', 'data_instalacao', 'status']
    list_filter = ['status', 'fabricante']


@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipamento', 'tipo', 'status', 'data_abertura', 'data_conclusao', 'responsavel']
    list_filter = ['status', 'tipo']
    inlines = [PecaInline]


@admin.register(Defeito)
class DefeitoAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipamento', 'severidade', 'data_registro']
    list_filter = ['severidade']


@admin.register(ManutencaoPreventiva)
class ManutencaoPreventivaAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipamento', 'descricao', 'periodicidade_dias', 'ultima_manutencao', 'proxima_manutencao']


@admin.register(PecaSubstituida)
class PecaSubstituidaAdmin(admin.ModelAdmin):
    list_display = ['id', 'codigo', 'nome', 'quantidade', 'custo_unitario', 'ordem_servico']
    search_fields = ['codigo', 'nome']
