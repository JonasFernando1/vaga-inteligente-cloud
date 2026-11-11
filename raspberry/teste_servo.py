
from gpiozero import AngularServo
from time import sleep

# Servo SG90 - GPIO 18 (BCM)
servo = AngularServo(
    18,
    min_angle=-90,
    max_angle=90,
    min_pulse_width=0.001,
    max_pulse_width=0.002,
    initial_angle=None
)

try:
    print("Teste do servo SG90")
    print("Movimentos pequenos, sem carga.")

    input("Pressione ENTER para ir a 0 graus...")
    servo.angle = 0
    sleep(1)
    servo.detach()

    input("Pressione ENTER para ir a +20 graus...")
    servo.angle = 20
    sleep(1)
    servo.detach()

    input("Pressione ENTER para voltar a 0 graus...")
    servo.angle = 0
    sleep(1)
    servo.detach()

    print("Teste concluído!")

except KeyboardInterrupt:
    print("\nTeste interrompido.")

finally:
    servo.detach()
    servo.close()

