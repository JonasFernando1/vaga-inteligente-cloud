
import lgpio
from time import sleep

GPIO_SERVO = 18

chip = lgpio.gpiochip_open(0)

try:
    lgpio.gpio_claim_output(chip, GPIO_SERVO, 0)

    print("CALIBRAÇÃO DA CANCELA")
    print("Mantenha a área livre.")
    print("Ctrl+C para interromper.\n")

    while True:
        valor = input(
            "Pulso em microssegundos "
            "(850 a 1600, ou sair): "
        ).strip().lower()

        if valor == "sair":
            break

        try:
            pulso = int(valor)
        except ValueError:
            print("Digite um número válido.")
            continue

        if not 850 <= pulso <= 1550:
            print("Valor fora do intervalo inicial.")
            continue

        lgpio.tx_servo(chip, GPIO_SERVO, pulso, 50)
        sleep(0.8)

        # Interrompe os pulsos após o movimento.
        lgpio.tx_pwm(chip, GPIO_SERVO, 0, 0)

        print(f"Pulso aplicado: {pulso} us\n")

except KeyboardInterrupt:
    print("\nCalibração interrompida.")

finally:
    lgpio.tx_pwm(chip, GPIO_SERVO, 0, 0)
    lgpio.gpiochip_close(chip)
    print("GPIO liberado.")
