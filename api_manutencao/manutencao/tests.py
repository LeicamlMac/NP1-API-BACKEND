from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Defeito, Equipamento, ManutencaoPreventiva, OrdemServico, PecaSubstituida

HOJE = timezone.localdate()


class BaseTest(APITestCase):
    def setUp(self):
        self.equip = Equipamento.objects.create(nome='Torno', modelo='T1', fabricante='ROMI',
                                                data_instalacao=HOJE - timedelta(days=900))

    def criar_os(self, **extra):
        dados = {'equipamento': self.equip.id, 'tipo': 'CORRETIVA', 'responsavel': 'Ana'}
        dados.update(extra)
        return self.client.post('/api/ordens-servico/', dados, format='json')


class EquipamentoTests(BaseTest):
    def test_crud_completo(self):
        r = self.client.post('/api/equipamentos/', {'nome': 'Prensa', 'modelo': 'P1', 'fabricante': 'X',
                                                    'data_instalacao': '2020-01-01'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['status'], 'ATIVO')
        pk = r.data['id']
        self.assertEqual(self.client.get(f'/api/equipamentos/{pk}/').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/equipamentos/{pk}/').status_code, 204)
        self.assertEqual(self.client.get(f'/api/equipamentos/{pk}/').status_code, 404)

    def test_problema1_atualizar_cadastro_incorreto(self):
        r = self.client.put(f'/api/equipamentos/{self.equip.id}/', {
            'nome': 'Torno CNC', 'modelo': 'GL 240', 'fabricante': 'ROMI', 'data_instalacao': '2019-03-15',
            'status': 'ATIVO'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['modelo'], 'GL 240')
        r = self.client.patch(f'/api/equipamentos/{self.equip.id}/', {'fabricante': 'Romi S.A.'}, format='json')
        self.assertEqual(r.data['fabricante'], 'Romi S.A.')

    def test_campos_obrigatorios_ausentes(self):
        r = self.client.post('/api/equipamentos/', {'nome': 'Sem modelo'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('modelo', r.data['detalhes'])
        self.assertIn('erro', r.data)

    def test_status_invalido(self):
        r = self.client.patch(f'/api/equipamentos/{self.equip.id}/', {'status': 'QUEBRADO'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_id_invalido_e_inexistente(self):
        r = self.client.get('/api/equipamentos/abc/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('ID inválido', r.data['erro'])
        r = self.client.get('/api/equipamentos/9999/')
        self.assertEqual(r.status_code, 404)
        self.assertIn('não encontrado', r.data['erro'])

    def test_problema6_excluir_com_os_vinculada(self):
        self.criar_os()
        r = self.client.delete(f'/api/equipamentos/{self.equip.id}/')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Equipamento.objects.filter(pk=self.equip.id).exists())

    def test_problema7_em_manutencao(self):
        self.criar_os()  # abre OS -> equipamento vai para EM_MANUTENCAO
        r = self.client.get('/api/equipamentos/em-manutencao/')
        self.assertEqual([e['id'] for e in r.data], [self.equip.id])
        r = self.client.get('/api/equipamentos/?status=EM_MANUTENCAO')
        self.assertEqual(len(r.data), 1)


class OrdemServicoTests(BaseTest):
    def test_problema2_equipamento_inexistente(self):
        r = self.criar_os(equipamento=9999)
        self.assertEqual(r.status_code, 400)
        self.assertIn('não existe', str(r.data['detalhes']['equipamento']))
        self.assertEqual(OrdemServico.objects.count(), 0)

    def test_abrir_e_finalizar_sincroniza_status(self):
        r = self.criar_os()
        self.assertEqual(r.status_code, 201)
        self.equip.refresh_from_db()
        self.assertEqual(self.equip.status, 'EM_MANUTENCAO')
        r = self.client.post(f'/api/ordens-servico/{r.data["id"]}/finalizar/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'FINALIZADA')
        self.assertEqual(r.data['data_conclusao'], str(HOJE))
        self.equip.refresh_from_db()
        self.assertEqual(self.equip.status, 'ATIVO')

    def test_os_finalizada_nao_pode_ser_alterada(self):
        pk = self.criar_os(status='FINALIZADA').data['id']
        self.assertEqual(self.client.patch(f'/api/ordens-servico/{pk}/', {'responsavel': 'X'}, format='json').status_code, 409)
        self.assertEqual(self.client.delete(f'/api/ordens-servico/{pk}/').status_code, 409)
        self.assertEqual(self.client.post(f'/api/ordens-servico/{pk}/finalizar/').status_code, 409)
        r = self.client.post('/api/pecas/', {'ordem_servico': pk, 'nome': 'P', 'codigo': 'P1',
                                             'quantidade': 1, 'custo_unitario': '1.00'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_tipo_invalido_e_datas(self):
        self.assertEqual(self.criar_os(tipo='EMERGENCIAL').status_code, 400)
        r = self.criar_os(status='FINALIZADA', data_abertura=str(HOJE), data_conclusao=str(HOJE - timedelta(days=1)))
        self.assertEqual(r.status_code, 400)

    def test_problema8_custo_total(self):
        pk = self.criar_os().data['id']
        for qtd, custo in [(2, '45.90'), (3, '10.00')]:
            self.client.post('/api/pecas/', {'ordem_servico': pk, 'nome': 'Peça', 'codigo': f'C{qtd}',
                                             'quantidade': qtd, 'custo_unitario': custo}, format='json')
        r = self.client.get(f'/api/ordens-servico/{pk}/custo-total/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['custo_total'], '121.80')
        self.assertEqual(r.data['quantidade_pecas'], 5)
        self.assertEqual(self.client.get(f'/api/ordens-servico/{pk}/').data['custo_total_pecas'], '121.80')

    def test_finalizar_preventiva_reprograma_plano(self):
        plano = ManutencaoPreventiva.objects.create(equipamento=self.equip, descricao='Lubrificar',
                                                    periodicidade_dias=30, ultima_manutencao=HOJE - timedelta(days=60))
        self.assertTrue(plano.vencida)
        pk = self.criar_os(tipo='PREVENTIVA', manutencao_preventiva=plano.id).data['id']
        self.client.post(f'/api/ordens-servico/{pk}/finalizar/')
        plano.refresh_from_db()
        self.assertEqual(plano.ultima_manutencao, HOJE)
        self.assertFalse(plano.vencida)

    def test_plano_so_em_os_preventiva(self):
        plano = ManutencaoPreventiva.objects.create(equipamento=self.equip, descricao='L', periodicidade_dias=30,
                                                    ultima_manutencao=HOJE)
        self.assertEqual(self.criar_os(manutencao_preventiva=plano.id).status_code, 400)


class PreventivaTests(BaseTest):
    def test_problema3_vencida(self):
        r = self.client.post('/api/manutencoes-preventivas/', {
            'equipamento': self.equip.id, 'descricao': 'Troca de óleo', 'periodicidade_dias': 30,
            'ultima_manutencao': str(HOJE - timedelta(days=40))}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['proxima_manutencao'], str(HOJE - timedelta(days=10)))
        self.assertTrue(r.data['vencida'])
        self.assertEqual(r.data['dias_em_atraso'], 10)
        self.assertIn('VENCIDA', r.data['alerta'])
        self.assertEqual(len(self.client.get('/api/manutencoes-preventivas/vencidas/').data), 1)
        self.assertEqual(len(self.client.get('/api/manutencoes-preventivas/?vencida=true').data), 1)
        self.assertEqual(self.client.get('/api/alertas/').data['totais']['manutencoes_vencidas'], 1)

        r = self.client.post(f'/api/manutencoes-preventivas/{r.data["id"]}/registrar-execucao/', {}, format='json')
        self.assertFalse(r.data['vencida'])
        self.assertEqual(r.data['proxima_manutencao'], str(HOJE + timedelta(days=30)))


class DefeitoTests(BaseTest):
    def test_problema5_critico_em_destaque(self):
        for sev in ['BAIXO', 'CRITICO', 'MEDIO']:
            r = self.client.post('/api/defeitos/', {'equipamento': self.equip.id, 'descricao': sev,
                                                    'severidade': sev}, format='json')
            self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['alerta'] is None)
        lista = self.client.get('/api/defeitos/').data
        self.assertEqual([d['severidade'] for d in lista], ['CRITICO', 'MEDIO', 'BAIXO'])
        self.assertEqual(lista[0]['prioridade'], 1)
        self.assertIn('CRÍTICO', lista[0]['alerta'])
        self.assertEqual(len(self.client.get('/api/defeitos/criticos/').data), 1)

    def test_severidade_invalida(self):
        r = self.client.post('/api/defeitos/', {'equipamento': self.equip.id, 'descricao': 'x',
                                                'severidade': 'GRAVISSIMO'}, format='json')
        self.assertEqual(r.status_code, 400)


class PecaTests(BaseTest):
    def test_problema4_historico_da_peca(self):
        ano = HOJE.year
        for mes in (1, 4, 7):
            os_ = OrdemServico.objects.create(equipamento=self.equip, tipo='CORRETIVA', responsavel='A',
                                              data_abertura=HOJE.replace(month=mes, day=1))
            PecaSubstituida.objects.create(ordem_servico=os_, nome='Rolamento', codigo='ROL-6205',
                                           quantidade=2, custo_unitario=Decimal('45.90'))
        r = self.client.get(f'/api/pecas/historico/?codigo=rol-6205&ano={ano}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_substituicoes'], 3)
        self.assertEqual(r.data['quantidade_total'], 6)
        self.assertEqual(r.data['custo_total'], '275.40')
        self.assertEqual(self.client.get('/api/pecas/historico/').status_code, 400)
        self.assertEqual(len(self.client.get('/api/pecas/?codigo=ROL-6205').data), 3)

    def test_quantidade_e_custo_validos(self):
        pk = self.criar_os().data['id']
        r = self.client.post('/api/pecas/', {'ordem_servico': pk, 'nome': 'P', 'codigo': 'X',
                                             'quantidade': 0, 'custo_unitario': '-1'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('quantidade', r.data['detalhes'])
        self.assertIn('custo_unitario', r.data['detalhes'])
