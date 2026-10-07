from decimal import Decimal

import django_filters
from django.db.models import Case, IntegerField, Sum, Value, When
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .exceptions import Conflito, IdInvalido
from .models import Defeito, Equipamento, ManutencaoPreventiva, OrdemServico, PecaSubstituida
from .serializers import (
    DefeitoSerializer,
    EquipamentoSerializer,
    FinalizarOrdemSerializer,
    ManutencaoPreventivaSerializer,
    OrdemServicoSerializer,
    PecaSubstituidaSerializer,
)

ERRO = inline_serializer('Erro', {
    'erro': serializers.CharField(),
    'status': serializers.IntegerField(),
    'detalhes': serializers.DictField(required=False),
})
RESPOSTAS_ERRO = {
    400: OpenApiResponse(ERRO, description='ID inválido ou dados inválidos'),
    404: OpenApiResponse(ERRO, description='Recurso não encontrado'),
}


class BaseViewSet(viewsets.ModelViewSet):
    """CRUD padrão com tratamento de 'ID inválido' (400) e 'não encontrado' (404)."""

    def get_object(self):
        pk = str(self.kwargs.get(self.lookup_url_kwarg or self.lookup_field))
        if not pk.isdigit() or int(pk) == 0:
            raise IdInvalido(f'ID inválido: "{pk}". O ID deve ser um número inteiro positivo.')
        try:
            return super().get_object()
        except Http404:
            nome = self.queryset.model._meta.verbose_name
            raise NotFound(f'{nome[0].upper() + nome[1:]} com id {pk} não encontrado(a).')


# --------------------------------------------------------------------------- Equipamentos

@extend_schema_view(
    list=extend_schema(summary='Listar equipamentos', description='Filtros: `?status=EM_MANUTENCAO`, `?fabricante=`, `?search=`.'),
    retrieve=extend_schema(summary='Detalhar equipamento', responses={200: EquipamentoSerializer, **RESPOSTAS_ERRO}),
    create=extend_schema(summary='Cadastrar equipamento'),
    update=extend_schema(summary='Atualizar equipamento (completo)', description='Problema 1: corrigir cadastro incorreto.'),
    partial_update=extend_schema(summary='Atualizar equipamento (parcial)'),
    destroy=extend_schema(summary='Excluir equipamento',
                          description='Problema 6: retorna **409** se houver OS ou defeitos vinculados.',
                          responses={204: None, 409: OpenApiResponse(ERRO, description='Possui vínculos'), **RESPOSTAS_ERRO}),
)
class EquipamentoViewSet(BaseViewSet):
    queryset = Equipamento.objects.all()
    serializer_class = EquipamentoSerializer
    filterset_fields = ['status', 'fabricante']
    search_fields = ['nome', 'modelo', 'fabricante']
    ordering_fields = ['id', 'nome', 'data_instalacao', 'status']

    def destroy(self, request, *args, **kwargs):
        equipamento = self.get_object()
        qtd_os = equipamento.ordens_servico.count()
        qtd_defeitos = equipamento.defeitos.count()
        if qtd_os or qtd_defeitos:
            raise Conflito(
                f'Não é possível excluir o equipamento "{equipamento.nome}": possui {qtd_os} ordem(ns) de '
                f'serviço e {qtd_defeitos} defeito(s) vinculados. Para preservar o histórico, altere o '
                f'status para INATIVO (PUT/PATCH).')
        equipamento.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary='Equipamentos em manutenção (Problema 7)', responses=EquipamentoSerializer(many=True))
    @action(detail=False, methods=['get'], url_path='em-manutencao')
    def em_manutencao(self, request):
        qs = self.get_queryset().filter(status=Equipamento.Status.EM_MANUTENCAO)
        return Response(self.get_serializer(qs, many=True).data)

    @extend_schema(summary='Histórico completo do equipamento',
                   description='Ordens de serviço, defeitos e planos preventivos do equipamento.')
    @action(detail=True, methods=['get'])
    def historico(self, request, pk=None):
        equipamento = self.get_object()
        return Response({
            'equipamento': EquipamentoSerializer(equipamento).data,
            'ordens_servico': OrdemServicoSerializer(equipamento.ordens_servico.all(), many=True).data,
            'defeitos': DefeitoSerializer(equipamento.defeitos.all(), many=True).data,
            'manutencoes_preventivas': ManutencaoPreventivaSerializer(equipamento.preventivas.all(), many=True).data,
        })


# --------------------------------------------------------------------------- Ordens de serviço

@extend_schema_view(
    list=extend_schema(summary='Listar ordens de serviço', description='Filtros: `?status=`, `?tipo=`, `?equipamento=`.'),
    retrieve=extend_schema(summary='Detalhar ordem de serviço (inclui peças e custo total)'),
    create=extend_schema(summary='Abrir ordem de serviço',
                         description='Problema 2: retorna **400** se o equipamento não existir. '
                                     'O equipamento passa automaticamente para EM_MANUTENCAO.'),
    update=extend_schema(summary='Atualizar ordem de serviço', description='Retorna **409** se a OS já estiver finalizada.'),
    partial_update=extend_schema(summary='Atualizar ordem de serviço (parcial)', description='Retorna **409** se a OS já estiver finalizada.'),
    destroy=extend_schema(summary='Excluir ordem de serviço', description='Retorna **409** se a OS já estiver finalizada.'),
)
class OrdemServicoViewSet(BaseViewSet):
    queryset = OrdemServico.objects.select_related('equipamento').prefetch_related('pecas')
    serializer_class = OrdemServicoSerializer
    filterset_fields = ['status', 'tipo', 'equipamento', 'responsavel']
    search_fields = ['responsavel', 'descricao', 'equipamento__nome']
    ordering_fields = ['id', 'data_abertura', 'data_conclusao', 'status']

    @staticmethod
    def _bloquear_se_finalizada(ordem, acao):
        if ordem.finalizada:
            raise Conflito(f'A ordem de serviço #{ordem.pk} já está finalizada e não pode ser {acao}.')

    def perform_create(self, serializer):
        ordem = serializer.save()
        services.aplicar_efeitos_da_finalizacao(ordem)

    def update(self, request, *args, **kwargs):
        self._bloquear_se_finalizada(self.get_object(), 'alterada')
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        equipamento_anterior = serializer.instance.equipamento
        ordem = serializer.save()
        services.aplicar_efeitos_da_finalizacao(ordem)
        if equipamento_anterior.pk != ordem.equipamento_id:
            services.sincronizar_status_equipamento(equipamento_anterior)

    def destroy(self, request, *args, **kwargs):
        ordem = self.get_object()
        self._bloquear_se_finalizada(ordem, 'excluída')
        equipamento = ordem.equipamento
        ordem.delete()
        services.sincronizar_status_equipamento(equipamento)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary='Finalizar ordem de serviço', request=FinalizarOrdemSerializer,
                   responses={200: OrdemServicoSerializer, 409: OpenApiResponse(ERRO, description='OS já finalizada')})
    @action(detail=True, methods=['post'])
    def finalizar(self, request, pk=None):
        ordem = self.get_object()
        self._bloquear_se_finalizada(ordem, 'finalizada novamente')
        entrada = FinalizarOrdemSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        data = entrada.validated_data.get('data_conclusao')
        if data and data < ordem.data_abertura:
            raise ValidationError({'data_conclusao': 'A data de conclusão não pode ser anterior à data de abertura.'})
        services.finalizar_ordem(ordem, data)
        return Response(self.get_serializer(ordem).data)

    @extend_schema(summary='Custo total de peças da OS (Problema 8)', responses=inline_serializer('CustoTotal', {
        'ordem_servico': serializers.IntegerField(),
        'equipamento': serializers.CharField(),
        'quantidade_itens': serializers.IntegerField(),
        'quantidade_pecas': serializers.IntegerField(),
        'custo_total': serializers.DecimalField(max_digits=14, decimal_places=2),
        'itens': PecaSubstituidaSerializer(many=True),
    }))
    @action(detail=True, methods=['get'], url_path='custo-total')
    def custo_total(self, request, pk=None):
        ordem = self.get_object()
        pecas = ordem.pecas.all()
        return Response({
            'ordem_servico': ordem.pk,
            'equipamento': ordem.equipamento.nome,
            'quantidade_itens': len(pecas),
            'quantidade_pecas': sum(p.quantidade for p in pecas),
            'custo_total': str(ordem.custo_total_pecas),
            'itens': PecaSubstituidaSerializer(pecas, many=True).data,
        })


# --------------------------------------------------------------------------- Defeitos

PESO_PRIORIDADE = Case(
    *[When(severidade=sev, then=Value(peso)) for sev, peso in Defeito.PRIORIDADE.items()],
    output_field=IntegerField(),
)


@extend_schema_view(
    list=extend_schema(summary='Listar defeitos (ordenados por prioridade)',
                       description='Problema 5: por padrão os CRÍTICOS aparecem primeiro. Filtros: `?severidade=`, `?equipamento=`.'),
    retrieve=extend_schema(summary='Detalhar defeito'),
    create=extend_schema(summary='Registrar defeito', description='Defeito CRÍTICO retorna campo `alerta` preenchido.'),
    update=extend_schema(summary='Atualizar defeito'),
    partial_update=extend_schema(summary='Atualizar defeito (parcial)'),
    destroy=extend_schema(summary='Excluir defeito'),
)
class DefeitoViewSet(BaseViewSet):
    queryset = Defeito.objects.select_related('equipamento').annotate(peso_prioridade=PESO_PRIORIDADE) \
        .order_by('peso_prioridade', '-data_registro', '-id')
    serializer_class = DefeitoSerializer
    filterset_fields = ['severidade', 'equipamento']
    search_fields = ['descricao', 'equipamento__nome']
    ordering_fields = ['peso_prioridade', 'data_registro', 'id']

    @extend_schema(summary='Defeitos críticos', responses=DefeitoSerializer(many=True))
    @action(detail=False, methods=['get'])
    def criticos(self, request):
        qs = self.get_queryset().filter(severidade=Defeito.Severidade.CRITICO)
        return Response(self.get_serializer(qs, many=True).data)


# --------------------------------------------------------------------------- Manutenção preventiva

class PreventivaFilter(django_filters.FilterSet):
    vencida = django_filters.BooleanFilter(method='filtrar_vencida', label='Somente vencidas (true/false)')

    class Meta:
        model = ManutencaoPreventiva
        fields = ['equipamento', 'vencida']

    def filtrar_vencida(self, queryset, name, value):
        hoje = timezone.localdate()
        return queryset.filter(proxima_manutencao__lt=hoje) if value else queryset.filter(proxima_manutencao__gte=hoje)


@extend_schema_view(
    list=extend_schema(summary='Listar planos de manutenção preventiva', description='Filtro: `?vencida=true`.'),
    retrieve=extend_schema(summary='Detalhar plano preventivo'),
    create=extend_schema(summary='Cadastrar plano preventivo',
                         description='`proxima_manutencao` é calculada automaticamente se omitida.'),
    update=extend_schema(summary='Atualizar plano preventivo'),
    partial_update=extend_schema(summary='Atualizar plano preventivo (parcial)'),
    destroy=extend_schema(summary='Excluir plano preventivo'),
)
class ManutencaoPreventivaViewSet(BaseViewSet):
    queryset = ManutencaoPreventiva.objects.select_related('equipamento')
    serializer_class = ManutencaoPreventivaSerializer
    filterset_class = PreventivaFilter
    ordering_fields = ['proxima_manutencao', 'ultima_manutencao', 'id']

    @extend_schema(summary='Alertas de manutenções vencidas (Problema 3)', responses=ManutencaoPreventivaSerializer(many=True))
    @action(detail=False, methods=['get'])
    def vencidas(self, request):
        qs = self.get_queryset().filter(proxima_manutencao__lt=timezone.localdate())
        return Response(self.get_serializer(qs, many=True).data)

    @extend_schema(summary='Registrar execução da preventiva',
                   description='Atualiza `ultima_manutencao` (padrão: hoje) e recalcula `proxima_manutencao`.',
                   request=inline_serializer('RegistrarExecucao', {'data': serializers.DateField(required=False)}),
                   responses=ManutencaoPreventivaSerializer)
    @action(detail=True, methods=['post'], url_path='registrar-execucao')
    def registrar_execucao(self, request, pk=None):
        plano = self.get_object()
        campo = serializers.DateField()
        data = campo.run_validation(request.data['data']) if request.data.get('data') else timezone.localdate()
        if data > timezone.localdate():
            raise ValidationError({'data': 'A data de execução não pode estar no futuro.'})
        plano.ultima_manutencao = data
        plano.proxima_manutencao = plano.calcular_proxima()
        plano.save()
        return Response(self.get_serializer(plano).data)


# --------------------------------------------------------------------------- Peças substituídas

class PecaFilter(django_filters.FilterSet):
    codigo = django_filters.CharFilter(lookup_expr='iexact')
    nome = django_filters.CharFilter(lookup_expr='icontains')
    equipamento = django_filters.NumberFilter(field_name='ordem_servico__equipamento')
    ano = django_filters.NumberFilter(field_name='ordem_servico__data_abertura', lookup_expr='year')

    class Meta:
        model = PecaSubstituida
        fields = ['ordem_servico', 'codigo', 'nome', 'equipamento', 'ano']


@extend_schema_view(
    list=extend_schema(summary='Listar peças substituídas',
                       description='Filtros: `?codigo=`, `?nome=`, `?ordem_servico=`, `?equipamento=`, `?ano=`.'),
    retrieve=extend_schema(summary='Detalhar peça substituída'),
    create=extend_schema(summary='Registrar peça substituída', description='Retorna **400** se a OS estiver finalizada.'),
    update=extend_schema(summary='Atualizar peça substituída', description='Retorna **409** se a OS estiver finalizada.'),
    partial_update=extend_schema(summary='Atualizar peça substituída (parcial)'),
    destroy=extend_schema(summary='Excluir peça substituída', description='Retorna **409** se a OS estiver finalizada.'),
)
class PecaSubstituidaViewSet(BaseViewSet):
    queryset = PecaSubstituida.objects.select_related('ordem_servico__equipamento')
    serializer_class = PecaSubstituidaSerializer
    filterset_class = PecaFilter
    search_fields = ['nome', 'codigo']
    ordering_fields = ['id', 'codigo', 'custo_unitario', 'quantidade']

    def _bloquear_se_os_finalizada(self, peca):
        if peca.ordem_servico.finalizada:
            raise Conflito(f'A peça pertence à ordem de serviço #{peca.ordem_servico_id}, que já está '
                           'finalizada. O histórico não pode ser alterado.')

    def update(self, request, *args, **kwargs):
        self._bloquear_se_os_finalizada(self.get_object())
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._bloquear_se_os_finalizada(self.get_object())
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        summary='Histórico de substituições de uma peça (Problema 4)',
        parameters=[
            OpenApiParameter('codigo', str, required=True, description='Código da peça (ex.: ROL-6205)'),
            OpenApiParameter('ano', int, description='Ano de referência (padrão: ano atual)'),
        ],
    )
    @action(detail=False, methods=['get'])
    def historico(self, request):
        codigo = request.query_params.get('codigo', '').strip()
        if not codigo:
            raise ValidationError({'codigo': 'Informe o código da peça. Ex.: ?codigo=ROL-6205'})
        ano = request.query_params.get('ano') or str(timezone.localdate().year)
        if not ano.isdigit():
            raise ValidationError({'ano': 'Ano inválido.'})

        qs = PecaSubstituida.objects.select_related('ordem_servico__equipamento').filter(
            codigo__iexact=codigo, ordem_servico__data_abertura__year=int(ano),
        ).order_by('ordem_servico__data_abertura', 'id')

        quantidade_total = qs.aggregate(t=Sum('quantidade'))['t'] or 0
        custo_total = sum((p.subtotal for p in qs), Decimal('0.00'))
        return Response({
            'codigo': codigo.upper(),
            'nome': qs[0].nome if qs else None,
            'ano': int(ano),
            'total_substituicoes': qs.count(),
            'quantidade_total': quantidade_total,
            'custo_total': str(custo_total),
            'registros': [{
                'id': p.id,
                'ordem_servico': p.ordem_servico_id,
                'equipamento': p.ordem_servico.equipamento.nome,
                'data': p.ordem_servico.data_conclusao or p.ordem_servico.data_abertura,
                'quantidade': p.quantidade,
                'custo_unitario': str(p.custo_unitario),
                'subtotal': str(p.subtotal),
            } for p in qs],
        })


# --------------------------------------------------------------------------- Painel de alertas

class AlertasView(APIView):
    @extend_schema(summary='Painel de alertas',
                   description='Resumo: manutenções vencidas, defeitos críticos e equipamentos em manutenção.',
                   responses=inline_serializer('Alertas', {
                       'gerado_em': serializers.DateTimeField(),
                       'totais': serializers.DictField(child=serializers.IntegerField()),
                       'manutencoes_vencidas': ManutencaoPreventivaSerializer(many=True),
                       'defeitos_criticos': DefeitoSerializer(many=True),
                       'equipamentos_em_manutencao': EquipamentoSerializer(many=True),
                   }))
    def get(self, request):
        vencidas = ManutencaoPreventiva.objects.select_related('equipamento') \
            .filter(proxima_manutencao__lt=timezone.localdate())
        criticos = Defeito.objects.select_related('equipamento').filter(severidade=Defeito.Severidade.CRITICO)
        em_manutencao = Equipamento.objects.filter(status=Equipamento.Status.EM_MANUTENCAO)
        return Response({
            'gerado_em': timezone.localtime().isoformat(timespec='seconds'),
            'totais': {
                'manutencoes_vencidas': vencidas.count(),
                'defeitos_criticos': criticos.count(),
                'equipamentos_em_manutencao': em_manutencao.count(),
                'ordens_abertas': OrdemServico.objects.exclude(status=OrdemServico.Status.FINALIZADA).count(),
            },
            'manutencoes_vencidas': ManutencaoPreventivaSerializer(vencidas, many=True).data,
            'defeitos_criticos': DefeitoSerializer(criticos, many=True).data,
            'equipamentos_em_manutencao': EquipamentoSerializer(em_manutencao, many=True).data,
        })
