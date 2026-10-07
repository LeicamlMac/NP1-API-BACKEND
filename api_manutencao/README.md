# API de Controle de Manutenção Industrial — NP1

Projeto NP1 da disciplina **Desenvolvimento Web Back-End** (Engenharia de Software).
API RESTful para gerenciar equipamentos, ordens de serviço, defeitos, manutenções preventivas e peças substituídas.

**Stack:** Python 3.10+ · Django · Django REST Framework · SQLite · drf-spectacular (Swagger/OpenAPI) · Postman

---

## 1. Como executar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py popular_dados --limpar   # dados de exemplo para a apresentação
python manage.py runserver
```

| O quê | Onde |
|---|---|
| Swagger (documentação interativa) | http://localhost:8000/api/docs/ |
| ReDoc | http://localhost:8000/api/redoc/ |
| Schema OpenAPI (YAML) | http://localhost:8000/api/schema/ · arquivo `docs/openapi.yaml` |
| Raiz da API (navegável) | http://localhost:8000/api/ |

Testes automatizados (Django): `python manage.py test` → 19 testes.

Testes no Postman: importe `postman/NP1_API_Manutencao.postman_collection.json` e rode pelo **Collection Runner**
(64 requisições, 123 asserções). Pela linha de comando: `npx newman run postman/NP1_API_Manutencao.postman_collection.json`.

---

## 2. Estrutura do projeto

```
api_manutencao/
├── config/                 # settings, urls (Swagger em /api/docs/)
├── manutencao/
│   ├── models.py           # Equipamento, OrdemServico, Defeito, ManutencaoPreventiva, PecaSubstituida
│   ├── serializers.py      # validação dos dados de entrada e formato de saída
│   ├── views.py            # ViewSets (CRUD) + endpoints extras (@action)
│   ├── services.py         # regras de negócio entre recursos (status do equipamento, finalizar OS)
│   ├── exceptions.py       # formato padrão de erro + 409 Conflict + 400 ID inválido
│   ├── urls.py             # rotas REST (DefaultRouter)
│   ├── tests.py            # testes automatizados
│   └── management/commands/popular_dados.py
├── docs/openapi.yaml       # documentação OpenAPI exportada
├── postman/                # coleção Postman (JSON)
└── requirements.txt
```

**Camadas:** `Model` (persistência/SQLite) → `Serializer` (validação) → `ViewSet` (HTTP) → `Router` (URLs).
Regras que envolvem mais de um recurso ficam em `services.py`.

---

## 3. Modelo de dados

```
Equipamento 1───N OrdemServico 1───N PecaSubstituida
     │                  │
     ├──N Defeito       └──0..1 ManutencaoPreventiva (plano atendido pela OS)
     └──N ManutencaoPreventiva
```

| Recurso | Campos | Enums |
|---|---|---|
| Equipamento | id, nome, modelo, fabricante, data_instalacao, status | `ATIVO`, `EM_MANUTENCAO`, `INATIVO` |
| Ordem de Serviço | id, equipamento, tipo, descricao, data_abertura, data_conclusao, responsavel, status, manutencao_preventiva, *custo_total_pecas*, *pecas* | tipo: `PREVENTIVA`, `CORRETIVA` · status: `ABERTA`, `EM_ANDAMENTO`, `FINALIZADA` |
| Defeito | id, equipamento, descricao, severidade, data_registro, *prioridade*, *critico*, *alerta* | `BAIXO`, `MEDIO`, `ALTO`, `CRITICO` |
| Manutenção Preventiva | id, equipamento, descricao, periodicidade_dias, ultima_manutencao, proxima_manutencao, *vencida*, *dias_em_atraso*, *alerta* | — |
| Peça Substituída | id, ordem_servico, nome, codigo, quantidade, custo_unitario, *subtotal* | — |

*Itálico* = campo calculado (somente leitura).

---

## 4. Endpoints

Base: `http://localhost:8000/api`

### CRUD (todos os recursos)

| Método | URL | Ação | Sucesso |
|---|---|---|---|
| GET | `/equipamentos/` | listar | 200 |
| POST | `/equipamentos/` | criar | 201 |
| GET | `/equipamentos/{id}/` | detalhar | 200 |
| PUT | `/equipamentos/{id}/` | atualizar completo | 200 |
| PATCH | `/equipamentos/{id}/` | atualizar parcial | 200 |
| DELETE | `/equipamentos/{id}/` | excluir | 204 |

O mesmo padrão vale para `/ordens-servico/`, `/defeitos/`, `/manutencoes-preventivas/` e `/pecas/`.

### Endpoints extras

| Método | URL | Descrição |
|---|---|---|
| GET | `/equipamentos/em-manutencao/` | equipamentos com status EM_MANUTENCAO (Problema 7) |
| GET | `/equipamentos/{id}/historico/` | OS, defeitos e planos preventivos do equipamento |
| POST | `/ordens-servico/{id}/finalizar/` | finaliza a OS (body opcional `{"data_conclusao": "2026-10-08"}`) |
| GET | `/ordens-servico/{id}/custo-total/` | custo total das peças da OS (Problema 8) |
| GET | `/defeitos/criticos/` | somente defeitos críticos (Problema 5) |
| GET | `/manutencoes-preventivas/vencidas/` | planos vencidos (Problema 3) |
| POST | `/manutencoes-preventivas/{id}/registrar-execucao/` | registra execução e recalcula a próxima data |
| GET | `/pecas/historico/?codigo=ROL-6205&ano=2026` | histórico de substituições de uma peça (Problema 4) |
| GET | `/alertas/` | painel: manutenções vencidas, defeitos críticos, equipamentos em manutenção |

### Filtros (query string)

- `/equipamentos/?status=EM_MANUTENCAO&fabricante=ROMI&search=torno&ordering=nome`
- `/ordens-servico/?status=ABERTA&tipo=CORRETIVA&equipamento=1`
- `/defeitos/?severidade=CRITICO&equipamento=2`
- `/manutencoes-preventivas/?vencida=true&equipamento=1`
- `/pecas/?codigo=ROL-6205&ordem_servico=3&equipamento=1&ano=2026`

### Exemplos de body

```jsonc
// POST /equipamentos/
{ "nome": "Torno CNC 01", "modelo": "ROMI GL 240", "fabricante": "ROMI",
  "data_instalacao": "2019-03-15", "status": "ATIVO" }

// POST /ordens-servico/
{ "equipamento": 1, "tipo": "CORRETIVA", "descricao": "Ruído no eixo",
  "responsavel": "Carlos Souza", "status": "ABERTA" }

// POST /defeitos/
{ "equipamento": 1, "descricao": "Vazamento de óleo", "severidade": "CRITICO" }

// POST /manutencoes-preventivas/   (proxima_manutencao é calculada se omitida)
{ "equipamento": 1, "descricao": "Troca de óleo", "periodicidade_dias": 90,
  "ultima_manutencao": "2026-06-01" }

// POST /pecas/
{ "ordem_servico": 1, "nome": "Rolamento 6205 ZZ", "codigo": "ROL-6205",
  "quantidade": 2, "custo_unitario": "45.90" }
```

### Formato padrão de erro

Todas as respostas de erro seguem o mesmo formato:

```json
{
  "erro": "Dados inválidos. Verifique os campos informados.",
  "status": 400,
  "detalhes": { "equipamento": ["Equipamento com id 99 não existe."] }
}
```

| Situação | Código |
|---|---|
| Campos obrigatórios ausentes / valor inválido / enum inválido | 400 |
| ID inválido na URL (ex.: `/equipamentos/abc/`) | 400 |
| Equipamento (ou OS) inexistente referenciado no body | 400 |
| Recurso inexistente na URL (ex.: `/equipamentos/999/`) | 404 |
| Alterar, excluir ou finalizar novamente uma OS já finalizada | 409 |
| Excluir equipamento com OS/defeitos vinculados | 409 |
| Lançar peça em OS finalizada | 400 · alterar/excluir peça de OS finalizada: 409 |

---

## 5. Soluções para os problemas propostos

**Problema 1 — Máquina cadastrada incorretamente.**
`PUT /equipamentos/{id}/` (substitui todos os campos) ou `PATCH /equipamentos/{id}/` (só os campos errados).
O serializer revalida tudo (ex.: status precisa ser um dos enums, data de instalação não pode ser futura).

**Problema 2 — OS aberta para equipamento inexistente.**
O campo `equipamento` é uma chave estrangeira validada no serializer (`PrimaryKeyRelatedField`).
Se o id não existir, a API responde **400** com `"Equipamento com id 99 não existe."` e nada é gravado.
No banco, a FK garante a integridade referencial.

**Problema 3 — Manutenção preventiva vencida.**
Cada plano tem `periodicidade_dias` e `ultima_manutencao`; `proxima_manutencao = última + periodicidade`
(calculada automaticamente). O plano está **vencido** quando `proxima_manutencao < hoje`.
A resposta traz `vencida`, `dias_em_atraso` e `alerta`. Consultas: `/manutencoes-preventivas/vencidas/`,
`?vencida=true` e o painel `/alertas/`. Ao finalizar uma OS preventiva vinculada ao plano, a data é reprogramada sozinha.

**Problema 4 — Peça substituída várias vezes no ano.**
`GET /pecas/historico/?codigo=ROL-6205&ano=2026` devolve todas as substituições (OS, equipamento, data,
quantidade, subtotal) e os totais (`total_substituicoes`, `quantidade_total`, `custo_total`).
Também é possível filtrar a listagem: `/pecas/?codigo=ROL-6205&ano=2026`.

**Problema 5 — Defeito crítico.**
Cada defeito recebe `prioridade` (1 = crítico … 4 = baixo), `critico: true/false` e um `alerta` textual quando crítico.
A listagem `/defeitos/` é ordenada por prioridade (críticos sempre primeiro), há o endpoint `/defeitos/criticos/`
e o total aparece no painel `/alertas/`.

**Problema 6 — Excluir equipamento com OS vinculadas.**
A exclusão é bloqueada com **409 Conflict** e mensagem explicando quantas OS/defeitos existem, sugerindo marcar o
equipamento como `INATIVO`. Assim o histórico de manutenção é preservado. Além da checagem na view,
a FK usa `on_delete=PROTECT`, então o próprio banco impede a exclusão.

**Problema 7 — Equipamentos em manutenção.**
`GET /equipamentos/em-manutencao/` ou `GET /equipamentos/?status=EM_MANUTENCAO`.
O status é mantido automaticamente: abrir uma OS coloca o equipamento em `EM_MANUTENCAO`;
finalizar a última OS aberta o devolve para `ATIVO`.

**Problema 8 — Custo total de peças de uma OS.**
`custo_total = Σ (quantidade × custo_unitario)`, calculado no banco com `Sum(F('quantidade') * F('custo_unitario'))`.
Disponível em `GET /ordens-servico/{id}/custo-total/` (com a lista de itens) e no campo `custo_total_pecas` de cada OS.

---

## 6. Decisões técnicas

- **Django REST Framework + ViewSets/Router:** geram o CRUD REST padronizado com poucas linhas; endpoints extras via `@action`.
- **SQLite:** banco em arquivo, sem instalação, suficiente para o escopo. Trocar por PostgreSQL é só mudar `DATABASES`.
- **Enums com `TextChoices`:** o banco só aceita valores válidos e o Swagger mostra as opções.
- **Campos calculados** (`custo_total_pecas`, `vencida`, `prioridade`, `subtotal`) não são armazenados: sempre refletem os dados atuais.
- **409 Conflict** para regras de estado (OS finalizada, exclusão com vínculos), **400** para dados inválidos, **404** para recurso inexistente.
- **OS finalizada é imutável:** preserva o histórico e o custo apurado.
- **Tratador de erros único** (`exceptions.py`) para que o cliente sempre receba o mesmo formato.
- **Documentação gerada a partir do código** (drf-spectacular), então nunca fica desatualizada.
