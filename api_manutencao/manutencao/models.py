from datetime import timedelta
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone


class Equipamento(models.Model):
    class Status(models.TextChoices):
        ATIVO = 'ATIVO', 'Ativo'
        EM_MANUTENCAO = 'EM_MANUTENCAO', 'Em manutenção'
        INATIVO = 'INATIVO', 'Inativo'

    nome = models.CharField(max_length=120)
    modelo = models.CharField(max_length=80)
    fabricante = models.CharField(max_length=80)
    data_instalacao = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ATIVO)

    class Meta:
        ordering = ['id']
        verbose_name = 'equipamento'

    def __str__(self):
        return f'{self.nome} ({self.modelo})'


class OrdemServico(models.Model):
    class Tipo(models.TextChoices):
        PREVENTIVA = 'PREVENTIVA', 'Preventiva'
        CORRETIVA = 'CORRETIVA', 'Corretiva'

    class Status(models.TextChoices):
        ABERTA = 'ABERTA', 'Aberta'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        FINALIZADA = 'FINALIZADA', 'Finalizada'

    # PROTECT: o banco também impede excluir equipamento com OS vinculada (Problema 6)
    equipamento = models.ForeignKey(Equipamento, on_delete=models.PROTECT, related_name='ordens_servico')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    descricao = models.TextField(blank=True, default='')
    data_abertura = models.DateField(default=timezone.localdate)
    data_conclusao = models.DateField(null=True, blank=True)
    responsavel = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTA)
    # Opcional: plano preventivo atendido por esta OS. Ao finalizar, o plano é reprogramado.
    manutencao_preventiva = models.ForeignKey('ManutencaoPreventiva', on_delete=models.SET_NULL,
                                              null=True, blank=True, related_name='ordens_servico')

    class Meta:
        ordering = ['-data_abertura', '-id']
        verbose_name = 'ordem de serviço'

    def __str__(self):
        return f'OS #{self.pk} - {self.equipamento.nome}'

    @property
    def finalizada(self):
        return self.status == self.Status.FINALIZADA

    @property
    def custo_total_pecas(self):
        """Problema 8: soma de quantidade x custo unitário das peças da OS."""
        total = self.pecas.aggregate(
            total=Sum(ExpressionWrapper(F('quantidade') * F('custo_unitario'),
                                        output_field=DecimalField(max_digits=14, decimal_places=2)))
        )['total']
        return Decimal(total or 0).quantize(Decimal('0.01'))


class Defeito(models.Model):
    class Severidade(models.TextChoices):
        BAIXO = 'BAIXO', 'Baixo'
        MEDIO = 'MEDIO', 'Médio'
        ALTO = 'ALTO', 'Alto'
        CRITICO = 'CRITICO', 'Crítico'

    # Peso numérico usado para ordenar por prioridade (Problema 5): 1 = mais urgente
    PRIORIDADE = {'CRITICO': 1, 'ALTO': 2, 'MEDIO': 3, 'BAIXO': 4}

    equipamento = models.ForeignKey(Equipamento, on_delete=models.PROTECT, related_name='defeitos')
    descricao = models.TextField()
    severidade = models.CharField(max_length=10, choices=Severidade.choices)
    data_registro = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ['-data_registro', '-id']
        verbose_name = 'defeito'

    def __str__(self):
        return f'{self.get_severidade_display()} - {self.equipamento.nome}'

    @property
    def prioridade(self):
        return self.PRIORIDADE[self.severidade]

    @property
    def critico(self):
        return self.severidade == self.Severidade.CRITICO


class ManutencaoPreventiva(models.Model):
    equipamento = models.ForeignKey(Equipamento, on_delete=models.CASCADE, related_name='preventivas')
    descricao = models.CharField(max_length=200)
    periodicidade_dias = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    ultima_manutencao = models.DateField()
    proxima_manutencao = models.DateField(blank=True)

    class Meta:
        ordering = ['proxima_manutencao', 'id']
        verbose_name = 'manutenção preventiva'

    def __str__(self):
        return f'{self.descricao} - {self.equipamento.nome}'

    def calcular_proxima(self):
        return self.ultima_manutencao + timedelta(days=self.periodicidade_dias)

    def save(self, *args, **kwargs):
        # Se a próxima data não for informada, calcula pela periodicidade
        if not self.proxima_manutencao:
            self.proxima_manutencao = self.calcular_proxima()
        super().save(*args, **kwargs)

    @property
    def vencida(self):
        """Problema 3: vencida quando a data prevista já passou."""
        return self.proxima_manutencao < timezone.localdate()

    @property
    def dias_em_atraso(self):
        return max((timezone.localdate() - self.proxima_manutencao).days, 0)


class PecaSubstituida(models.Model):
    ordem_servico = models.ForeignKey(OrdemServico, on_delete=models.CASCADE, related_name='pecas')
    nome = models.CharField(max_length=120)
    codigo = models.CharField(max_length=40, db_index=True)
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    custo_unitario = models.DecimalField(max_digits=12, decimal_places=2,
                                         validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        ordering = ['-id']
        verbose_name = 'peça substituída'
        verbose_name_plural = 'peças substituídas'

    def __str__(self):
        return f'{self.codigo} - {self.nome}'

    @property
    def subtotal(self):
        return (self.quantidade * self.custo_unitario).quantize(Decimal('0.01'))
