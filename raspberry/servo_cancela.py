"""Controle do SG90 via lgpio. BCM18; aberto 850us, fechado 1550us.

Nota: fechar_servo() existe apenas para integração futura com segurança validada.
"""

import threading
import time

import lgpio

GPIO_SERVO = 18
PULSO_ABERTO = 850
PULSO_FECHADO = 1550
TEMPO_MOVIMENTO = 1.0

_lock = threading.Lock()
_chip = None


def inicializar_servo():
    global _chip
    with _lock:
        if _chip is not None:
            return
        chip = lgpio.gpiochip_open(0)
        try:
            lgpio.gpio_claim_output(chip, GPIO_SERVO, 0)
        except Exception:
            lgpio.gpiochip_close(chip)
            raise
        _chip = chip


def _mover(pulso):
    with _lock:
        if _chip is None:
            raise RuntimeError("Servo não inicializado")
        try:
            lgpio.tx_servo(_chip, GPIO_SERVO, pulso, 50)
            time.sleep(TEMPO_MOVIMENTO)
        finally:
            # Para os pulsos. Exige que a haste não caia por gravidade.
            lgpio.tx_pwm(_chip, GPIO_SERVO, 0, 0)


def abrir_servo():
    _mover(PULSO_ABERTO)


def fechar_servo():
    # NÃO chamada pelo controlador até validar monitoramento do HC-SR04.
    _mover(PULSO_FECHADO)


def encerrar_servo():
    global _chip
    with _lock:
        if _chip is not None:
            try:
                lgpio.tx_pwm(_chip, GPIO_SERVO, 0, 0)
            finally:
                lgpio.gpiochip_close(_chip)
                _chip = None
