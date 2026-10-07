"""Regras de negócio que envolvem mais de um recurso."""
from django.db import transaction
from django.utils import timezone

from .models import Equipamento, OrdemServico


def sincronizar_status_equipamento(equipamento):
    """Mantém o status do equipamento coerente com as OS em aberto.

    - Existe OS aberta/em andamento  -> EM_MANUTENCAO
    - Não existe e estava em manutenção -> volta para ATIVO
    """
    tem_os_aberta = equipamento.ordens_servico.exclude(status=OrdemServico.Status.FINALIZADA).exists()
    if tem_os_aberta and equipamento.status != Equipamento.Status.EM_MANUTENCAO:
        equipamento.status = Equipamento.Status.EM_MANUTENCAO
        equipamento.save(update_fields=['status'])
    elif not tem_os_aberta and equipamento.status == Equipamento.Status.EM_MANUTENCAO:
        equipamento.status = Equipamento.Status.ATIVO
        equipamento.save(update_fields=['status'])


@transaction.atomic
def finalizar_ordem(ordem, data_conclusao=None):
    ordem.status = OrdemServico.Status.FINALIZADA
    ordem.data_conclusao = data_conclusao or ordem.data_conclusao or timezone.localdate()
    ordem.save()
    aplicar_efeitos_da_finalizacao(ordem)
    return ordem


def aplicar_efeitos_da_finalizacao(ordem):
    """Ao finalizar uma OS preventiva vinculada a um plano, reprograma o plano."""
    plano = ordem.manutencao_preventiva
    if ordem.finalizada and plano is not None:
        plano.ultima_manutencao = ordem.data_conclusao
        plano.proxima_manutencao = plano.calcular_proxima()
        plano.save()
    sincronizar_status_equipamento(ordem.equipamento)
