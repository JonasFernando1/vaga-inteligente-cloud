
from gpiozero import DigitalInputDevice
from time import sleep

# Configuração dos sensores IR
ir1 = DigitalInputDevice(17, pull_up=False)
ir2 = DigitalInputDevice(27, pull_up=False)

print("Teste dos sensores IR iniciado")
print("Coloque e retire objetos da frente dos sensores.\n")

try:
    while True:
        print(
            f"Sensor 1: {ir1.value} | "
            f"Sensor 2: {ir2.value}"
        )
        sleep(0.5)

except KeyboardInterrupt:
    print("\nTeste encerrado.")

finally:
    ir1.close()
    ir2.close()

