
import lgpio
from time import sleep

GPIO_SERVO = 18

chip = lgpio.gpiochip_open(0)

try:
    lgpio.gpio_claim_output(chip, GPIO_SERVO, 0)

    print("Teste SG90 com lgpio")

    input("ENTER para posição central...")
    lgpio.tx_servo(chip, GPIO_SERVO, 1500, 50)
    sleep(1)

    input("ENTER para pequeno movimento...")
    lgpio.tx_servo(chip, GPIO_SERVO, 1600, 50)
    sleep(1)

    input("ENTER para retornar ao centro...")
    lgpio.tx_servo(chip, GPIO_SERVO, 1500, 50)
    sleep(1)

    print("Teste concluído!")

except KeyboardInterrupt:
    print("\nTeste interrompido.")

finally:
    # Cancela a transmissão PWM ativa.
    lgpio.tx_pwm(chip, GPIO_SERVO, 0, 0)
    lgpio.gpiochip_close(chip)

    print("GPIO liberado.")

