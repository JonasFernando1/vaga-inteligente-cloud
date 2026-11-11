"""Contrato para integracao FUTURA do HC-SR04.

A leitura ainda nao existe. Falha sempre de forma fechada: nunca autoriza
fechamento automatico. Ao implementar leituras reais, so forneca os campos
abaixo apos testar, calibrar e confirmar o monitoramento continuo.

Importante: sensor ultrassonico unico NAO e dispositivo de seguranca
anti-esmagamento para uma cancela de verdade.
"""

SENSOR_VALIDADO = False


def obter_estado():
    return {
        "validado": False,         # Testado e validado fisicamente
        "funcionando": False,      # Leitura de distancia atual confiavel
        "obstaculo": None,         # True = presente; False = area livre
        "distancia_cm": None,
        "idade_leitura_s": None,   # Tempo desde a ultima leitura valida
    }


def passagem_livre():
    return False
