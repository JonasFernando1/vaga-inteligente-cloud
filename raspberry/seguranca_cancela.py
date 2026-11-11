
from sensor_ultrassonico import passagem_livre


def pode_abrir():
    return True


def pode_fechar():
    return passagem_livre()
