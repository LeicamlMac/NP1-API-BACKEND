"""Tratamento centralizado de erros.

Toda resposta de erro da API segue o mesmo formato:

    {
        "erro": "Mensagem principal legível",
        "status": 400,
        "detalhes": {...}   # opcional: erros por campo
    }
"""
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler


class Conflito(APIException):
    """409 - a requisição conflita com o estado atual do recurso."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Operação conflita com o estado atual do recurso.'
    default_code = 'conflito'


class IdInvalido(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'ID inválido. O ID deve ser um número inteiro positivo.'
    default_code = 'id_invalido'


def tratador_de_erros(exc, context):
    # Rede de segurança: exclusão bloqueada pelo PROTECT do banco
    if isinstance(exc, ProtectedError):
        exc = Conflito('Não é possível excluir: existem registros vinculados a este recurso.')

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        corpo = {
            'erro': 'Dados inválidos. Verifique os campos informados.',
            'status': response.status_code,
            'detalhes': response.data,
        }
    else:
        detalhe = response.data.get('detail', response.data) if isinstance(response.data, dict) else response.data
        corpo = {'erro': str(detalhe), 'status': response.status_code}

    response.data = corpo
    return response
