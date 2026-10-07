from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from manutencao import services
from manutencao.models import Defeito, Equipamento, ManutencaoPreventiva, OrdemServico, PecaSubstituida


class Command(BaseCommand):
    help = 'Popula o banco com dados de exemplo para demonstração da API.'

    def add_arguments(self, parser):
        parser.add_argument('--limpar', action='store_true', help='Apaga os dados existentes antes de popular.')

    @transaction.atomic
    def handle(self, *args, **opcoes):
        if opcoes['limpar']:
            PecaSubstituida.objects.all().delete()
            OrdemServico.objects.all().delete()
            Defeito.objects.all().delete()
            ManutencaoPreventiva.objects.all().delete()
            Equipamento.objects.all().delete()

        hoje = timezone.localdate()
        dias = lambda n: hoje - timedelta(days=n)  # noqa: E731
        ano = hoje.year

        torno = Equipamento.objects.create(nome='Torno CNC 01', modelo='ROMI GL 240', fabricante='ROMI',
                                           data_instalacao=date(2019, 3, 15))
        prensa = Equipamento.objects.create(nome='Prensa Hidráulica 02', modelo='PH-150T', fabricante='Schuler',
                                            data_instalacao=date(2020, 7, 1))
        compressor = Equipamento.objects.create(nome='Compressor de Ar 03', modelo='GA 37', fabricante='Atlas Copco',
                                                data_instalacao=date(2021, 1, 20))
        esteira = Equipamento.objects.create(nome='Esteira Transportadora 04', modelo='ET-500', fabricante='WEG',
                                             data_instalacao=date(2018, 11, 5))
        Equipamento.objects.create(nome='Fresadora 05', modelo='FVF-3000', fabricante='Diplomat',
                                   data_instalacao=date(2015, 5, 10), status=Equipamento.Status.INATIVO)

        # Planos preventivos: um vencido, um em dia
        plano_torno = ManutencaoPreventiva.objects.create(
            equipamento=torno, descricao='Lubrificação e troca de óleo do cabeçote',
            periodicidade_dias=90, ultima_manutencao=dias(120))           # vencida há 30 dias
        ManutencaoPreventiva.objects.create(
            equipamento=compressor, descricao='Troca de filtros e verificação de pressão',
            periodicidade_dias=180, ultima_manutencao=dias(30))           # em dia
        ManutencaoPreventiva.objects.create(
            equipamento=esteira, descricao='Alinhamento e tensionamento da correia',
            periodicidade_dias=30, ultima_manutencao=dias(45))            # vencida há 15 dias

        # Defeitos de todas as severidades
        Defeito.objects.create(equipamento=prensa, descricao='Vazamento de óleo no cilindro principal',
                               severidade=Defeito.Severidade.CRITICO, data_registro=dias(2))
        Defeito.objects.create(equipamento=torno, descricao='Ruído anormal no rolamento do eixo-árvore',
                               severidade=Defeito.Severidade.ALTO, data_registro=dias(10))
        Defeito.objects.create(equipamento=esteira, descricao='Correia com desgaste lateral',
                               severidade=Defeito.Severidade.MEDIO, data_registro=dias(20))
        Defeito.objects.create(equipamento=compressor, descricao='Manômetro com leitura oscilante',
                               severidade=Defeito.Severidade.BAIXO, data_registro=dias(5))

        # OS finalizadas ao longo do ano com o mesmo rolamento (histórico - Problema 4)
        for mes, qtd in [(2, 2), (5, 1), (8, 2)]:
            abertura = date(ano, mes, 10)
            if abertura > hoje:
                abertura = dias(60 * qtd)
            os_ = OrdemServico.objects.create(equipamento=torno, tipo=OrdemServico.Tipo.CORRETIVA,
                                              descricao='Substituição de rolamento do eixo-árvore',
                                              data_abertura=abertura, responsavel='Carlos Souza')
            PecaSubstituida.objects.create(ordem_servico=os_, nome='Rolamento 6205 ZZ', codigo='ROL-6205',
                                           quantidade=qtd, custo_unitario=Decimal('45.90'))
            services.finalizar_ordem(os_, abertura + timedelta(days=1))

        # OS em andamento na prensa (defeito crítico) -> prensa fica EM_MANUTENCAO
        os_prensa = OrdemServico.objects.create(equipamento=prensa, tipo=OrdemServico.Tipo.CORRETIVA,
                                                descricao='Reparo do vazamento no cilindro principal',
                                                data_abertura=dias(1), responsavel='Ana Lima',
                                                status=OrdemServico.Status.EM_ANDAMENTO)
        PecaSubstituida.objects.create(ordem_servico=os_prensa, nome='Kit de vedação do cilindro', codigo='VED-150',
                                       quantidade=1, custo_unitario=Decimal('780.00'))
        PecaSubstituida.objects.create(ordem_servico=os_prensa, nome='Óleo hidráulico ISO 68 (20L)', codigo='OLE-68',
                                       quantidade=3, custo_unitario=Decimal('320.50'))
        services.sincronizar_status_equipamento(prensa)

        # OS preventiva aberta, vinculada ao plano vencido do torno
        OrdemServico.objects.create(equipamento=torno, tipo=OrdemServico.Tipo.PREVENTIVA,
                                    descricao='Execução do plano de lubrificação', responsavel='Carlos Souza',
                                    manutencao_preventiva=plano_torno)
        services.sincronizar_status_equipamento(torno)

        self.stdout.write(self.style.SUCCESS(
            f'Dados criados: {Equipamento.objects.count()} equipamentos, {OrdemServico.objects.count()} OS, '
            f'{Defeito.objects.count()} defeitos, {ManutencaoPreventiva.objects.count()} planos preventivos, '
            f'{PecaSubstituida.objects.count()} peças.'))
