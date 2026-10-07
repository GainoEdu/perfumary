"""Ponto de integração para um gateway de pagamento (cartão/Pix) no futuro.

Para integrar: crie uma subclasse de PaymentGateway, implemente create_payment()
e retorne-a em get_gateway(). O checkout já chama esta camada.
"""


class PaymentGateway:
    name = "base"

    def create_payment(self, order):
        """Retorna uma URL para redirecionar o cliente (ou None)."""
        raise NotImplementedError


class ManualGateway(PaymentGateway):
    """Sem cobrança online: o pedido fica 'Aguardando pagamento' e a loja combina o pagamento."""
    name = "manual"

    def create_payment(self, order):
        return None


def get_gateway():
    return ManualGateway()
