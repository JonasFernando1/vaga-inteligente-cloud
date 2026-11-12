"""Testes sem hardware (python -m unittest discover -s tests)."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Substitui apenas GPIO no ambiente de teste.
lgpio = types.ModuleType("lgpio")
lgpio.gpiochip_open = lambda *_: 0
lgpio.gpio_claim_output = lambda *_: None
lgpio.gpiochip_close = lambda *_: None
lgpio.tx_servo = lambda *_: None
lgpio.tx_pwm = lambda *_: None
sys.modules.setdefault("lgpio", lgpio)


class IntegracaoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["VAGA_DB_PATH"] = str(Path(cls.temp.name) / "estacionamento.db")
        os.environ.pop("VAGA_FECHAMENTO_TESTE", None)
        os.environ.pop("VAGA_AUTO_SEM_SENSOR_BANCADA", None)
        cls.banco = importlib.import_module("banco")
        cls.controlador = importlib.import_module("controlador")
        cls.banco.inicializar_banco()
        cls.controlador.inicializar_controle()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_transicao_ir_e_historico(self):
        b = self.banco
        self.assertTrue(b.atualizar_vaga(1, True))
        self.assertFalse(b.atualizar_vaga(1, True))
        self.assertTrue(b.atualizar_vaga(1, False))
        self.assertEqual(len(b.listar_permanencias()), 1)

    def test_rfid_cadastrado(self):
        self.banco.cadastrar_cartao("123456", "Cartão teste", True)
        self.assertTrue(self.banco.verificar_cartao("123456"))
        self.banco.cadastrar_cartao("123456", "Cartão teste", False)
        self.assertFalse(self.banco.verificar_cartao("123456"))

    def test_fechamento_auto_sem_sensor_bloqueado_por_padrao(self):
        c = self.controlador
        self.assertFalse(c._auto_permitido())
        self.assertFalse(c.agendar_fechamento_rfid())
        resultado = c.comandar_cancela("fechar")
        self.assertFalse(resultado["sucesso"])

    def test_abertura_funciona_sem_ler_hardware_real(self):
        c = self.controlador
        with patch.object(c, "inicializar_servo"), patch.object(c, "abrir_servo") as abrir:
            c._ultima_posicao_comandada = None
            resultado = c.comandar_cancela("abrir", origem="teste")
            self.assertTrue(resultado["sucesso"])
            abrir.assert_called_once()

    def test_sensor_provisorio_nao_autoriza_fechamento(self):
        sensor = importlib.import_module("sensor_ultrassonico")
        self.assertFalse(sensor.passagem_livre())
        self.assertIsNone(sensor.obter_estado()["obstaculo"])


if __name__ == "__main__":
    unittest.main()
