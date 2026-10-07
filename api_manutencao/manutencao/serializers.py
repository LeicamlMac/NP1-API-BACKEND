from django.utils import timezone
from rest_framework import serializers

from .models import Defeito, Equipamento, ManutencaoPreventiva, OrdemServico, PecaSubstituida


def fk(queryset, nome, **kwargs):
    """Campo de chave estrangeira com mensagens de erro em português (Problema 2)."""
    return serializers.PrimaryKeyRelatedField(
        queryset=queryset,
        error_messages={
            'required': f'O campo {nome} é obrigatório.',
            'null': f'O campo {nome} não pode ser nulo.',
            'does_not_exist': f'{nome.capitalize()} com id {{pk_value}} não existe.',
            'incorrect_type': f'ID de {nome} inválido: esperado número inteiro, recebido {{data_type}}.',
        },
        **kwargs,
    )


class EquipamentoSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Equipamento
        fields = ['id', 'nome', 'modelo', 'fabricante', 'data_instalacao', 'status', 'status_display']

    def validate_data_instalacao(self, valor):
        if valor > timezone.localdate():
            raise serializers.ValidationError('A data de instalação não pode estar no futuro.')
        return valor


class PecaSubstituidaSerializer(serializers.ModelSerializer):
    ordem_servico = fk(OrdemServico.objects.all(), 'ordem de serviço')
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = PecaSubstituida
        fields = ['id', 'ordem_servico', 'nome', 'codigo', 'quantidade', 'custo_unitario', 'subtotal']

    def validate_ordem_servico(self, ordem):
        # Não é permitido lançar/alterar peças em OS já finalizada
        if ordem.finalizada:
            raise serializers.ValidationError(
                f'A ordem de serviço #{ordem.pk} já está finalizada e não aceita novas peças.')
        return ordem

    def validate_codigo(self, valor):
        return valor.strip().upper()


class OrdemServicoSerializer(serializers.ModelSerializer):
    equipamento = fk(Equipamento.objects.all(), 'equipamento')
    manutencao_preventiva = fk(ManutencaoPreventiva.objects.all(), 'manutenção preventiva',
                               required=False, allow_null=True)
    equipamento_nome = serializers.CharField(source='equipamento.nome', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    custo_total_pecas = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    pecas = PecaSubstituidaSerializer(many=True, read_only=True)

    class Meta:
        model = OrdemServico
        fields = ['id', 'equipamento', 'equipamento_nome', 'tipo', 'tipo_display', 'descricao',
                  'data_abertura', 'data_conclusao', 'responsavel', 'status', 'status_display',
                  'manutencao_preventiva', 'custo_total_pecas', 'pecas']

    def validate(self, dados):
        atual = self.instance
        get = lambda campo: dados.get(campo, getattr(atual, campo, None))  # noqa: E731

        abertura = get('data_abertura') or timezone.localdate()
        conclusao = get('data_conclusao')
        status = get('status') or OrdemServico.Status.ABERTA

        if status == OrdemServico.Status.FINALIZADA and not conclusao:
            # Finalizou sem informar data: usa a data de hoje
            dados['data_conclusao'] = conclusao = timezone.localdate()
        if status != OrdemServico.Status.FINALIZADA and conclusao:
            raise serializers.ValidationError(
                {'data_conclusao': 'Só é possível informar data de conclusão quando o status é FINALIZADA.'})
        if conclusao and conclusao < abertura:
            raise serializers.ValidationError(
                {'data_conclusao': 'A data de conclusão não pode ser anterior à data de abertura.'})

        plano = get('manutencao_preventiva')
        if plano is not None:
            if get('tipo') != OrdemServico.Tipo.PREVENTIVA:
                raise serializers.ValidationError(
                    {'manutencao_preventiva': 'Somente OS do tipo PREVENTIVA podem ser vinculadas a um plano preventivo.'})
            if plano.equipamento_id != get('equipamento').pk:
                raise serializers.ValidationError(
                    {'manutencao_preventiva': 'O plano preventivo pertence a outro equipamento.'})
        return dados


class FinalizarOrdemSerializer(serializers.Serializer):
    data_conclusao = serializers.DateField(required=False)


class DefeitoSerializer(serializers.ModelSerializer):
    equipamento = fk(Equipamento.objects.all(), 'equipamento')
    equipamento_nome = serializers.CharField(source='equipamento.nome', read_only=True)
    severidade_display = serializers.CharField(source='get_severidade_display', read_only=True)
    prioridade = serializers.IntegerField(read_only=True, help_text='1 = Crítico (mais urgente) ... 4 = Baixo')
    critico = serializers.BooleanField(read_only=True)
    alerta = serializers.SerializerMethodField()

    class Meta:
        model = Defeito
        fields = ['id', 'equipamento', 'equipamento_nome', 'descricao', 'severidade', 'severidade_display',
                  'prioridade', 'critico', 'alerta', 'data_registro']

    def get_alerta(self, obj) -> str | None:
        if obj.critico:
            return (f'ATENÇÃO: defeito CRÍTICO no equipamento "{obj.equipamento.nome}". '
                    'Prioridade máxima de atendimento.')
        return None

    def validate_data_registro(self, valor):
        if valor > timezone.localdate():
            raise serializers.ValidationError('A data de registro não pode estar no futuro.')
        return valor


class ManutencaoPreventivaSerializer(serializers.ModelSerializer):
    equipamento = fk(Equipamento.objects.all(), 'equipamento')
    equipamento_nome = serializers.CharField(source='equipamento.nome', read_only=True)
    proxima_manutencao = serializers.DateField(
        required=False, help_text='Se omitida, é calculada: última manutenção + periodicidade.')
    vencida = serializers.BooleanField(read_only=True)
    dias_em_atraso = serializers.IntegerField(read_only=True)
    alerta = serializers.SerializerMethodField()

    class Meta:
        model = ManutencaoPreventiva
        fields = ['id', 'equipamento', 'equipamento_nome', 'descricao', 'periodicidade_dias',
                  'ultima_manutencao', 'proxima_manutencao', 'vencida', 'dias_em_atraso', 'alerta']

    def get_alerta(self, obj) -> str | None:
        if obj.vencida:
            return (f'MANUTENÇÃO VENCIDA há {obj.dias_em_atraso} dia(s): "{obj.descricao}" '
                    f'no equipamento "{obj.equipamento.nome}".')
        return None

    def validate(self, dados):
        atual = self.instance
        ultima = dados.get('ultima_manutencao', getattr(atual, 'ultima_manutencao', None))
        periodicidade = dados.get('periodicidade_dias', getattr(atual, 'periodicidade_dias', None))
        if 'proxima_manutencao' not in dados and (
                'ultima_manutencao' in dados or 'periodicidade_dias' in dados):
            # Recalcula sempre que a base do cálculo mudar
            dados['proxima_manutencao'] = ManutencaoPreventiva(
                ultima_manutencao=ultima, periodicidade_dias=periodicidade).calcular_proxima()
        proxima = dados.get('proxima_manutencao', getattr(atual, 'proxima_manutencao', None))
        if ultima and proxima and proxima <= ultima:
            raise serializers.ValidationError(
                {'proxima_manutencao': 'A próxima manutenção deve ser posterior à última manutenção.'})
        return dados
